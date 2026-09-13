"""Exact-command system changes. Decisions must come from Robert's authenticated channel.

The injected executor takes one argv list and returns (returncode, stdout, stderr).
Execution logs deliberately retain exit codes only: system output can contain secrets.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from cube.config import Settings
from cube.disclosure import release_text


class SysopsError(ValueError):
    """Invalid proposal, decision, or execution state."""


Executor = Callable[[list[str]], tuple[int, str, str]]


_FIELDS = {
    "host",
    "commands",
    "rationale",
    "impact",
    "prechecks",
    "postchecks",
    "rollback",
    "evidence",
}
_ID = re.compile(r"sys-[0-9a-f]{64}\Z")
_HOST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\Z")
_DIAGNOSTICS = {
    "uptime": [["uptime"]],
    "disk": [["df", "-h"], ["df", "-i"]],
    "memory": [["free", "-h"]],
    "services": [["systemctl", "--failed", "--no-pager"]],
    "journal": [["journalctl", "-p", "err", "-n", "40", "--no-pager"]],
    "slurm": [["sinfo"], ["squeue"]],
}


def _host(settings: Settings, host: str) -> None:
    if not isinstance(host, str) or not _HOST.fullmatch(host):
        raise SysopsError("invalid host")
    if host not in settings.decisions.systems:
        raise SysopsError("host must be explicitly listed in decisions.systems")


def _validate(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise SysopsError("proposal requires exactly: " + ", ".join(sorted(_FIELDS)))
    _host(settings, payload["host"])
    if len(json.dumps(payload)) > 9000:
        raise SysopsError("bundle exceeds one review message; split into smaller changes")
    if release_text(json.dumps(payload), personal_source=True).startswith("[withheld:"):
        raise SysopsError("bundle contains credentials or private records")
    for field in ("rationale", "impact"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise SysopsError(f"{field} must be nonempty text")
    evidence = payload["evidence"]
    if (
        not isinstance(evidence, list)
        or not evidence
        or any(not isinstance(item, str) or not item.strip() for item in evidence)
    ):
        raise SysopsError("evidence must contain source references")
    for field in ("commands", "prechecks", "postchecks", "rollback"):
        commands = payload[field]
        if not isinstance(commands, list) or not commands:
            raise SysopsError(f"{field} must contain at least one argv")
        for argv in commands:
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
            ):
                raise SysopsError(f"{field} must contain nonempty argv lists")
            # No password automation, interactive elevation, or second-hop commands.
            tokens = {Path(arg).name.lower() for arg in argv}
            if tokens & {"rootsh", "sshpass", "passwd", "chpasswd", "su", "ssh"}:
                raise SysopsError("interactive elevation, passwords, and nested SSH are forbidden")
            if "sudo" in tokens and (
                "-n" not in argv or any(a in argv for a in ("-S", "-i", "-s"))
            ):
                raise SysopsError("sudo requires -n and cannot read passwords or open shells")
            if Path(argv[0]).name in {"sh", "bash", "dash", "zsh", "fish"}:
                raise SysopsError("use explicit executable argv, not shell scripts")
            if payload["host"] == "node005" and tokens & {
                "reboot",
                "shutdown",
                "poweroff",
                "halt",
                "kexec",
            }:
                raise SysopsError("node005 must never be rebooted")
    return cast(dict[str, Any], json.loads(json.dumps(payload)))


def _digest(payload: dict[str, Any]) -> str:
    return (
        "sys-"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _directory(settings: Settings) -> Path:
    path = settings.state_dir() / "sysops"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


@contextmanager
def _locked(settings: Settings) -> Iterator[None]:
    with (_directory(settings) / ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _path(settings: Settings, proposal_id: str) -> Path:
    if not _ID.fullmatch(proposal_id):
        raise SysopsError("invalid proposal id")
    return _directory(settings) / f"{proposal_id}.json"


def _save(settings: Settings, record: dict[str, Any]) -> None:
    path = _path(settings, record["id"])
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def get(settings: Settings, proposal_id: str) -> dict[str, Any]:
    """Read and integrity-check a proposal."""
    try:
        record = json.loads(_path(settings, proposal_id).read_text())
    except FileNotFoundError as error:
        raise SysopsError("unknown proposal") from error
    if record["id"] != proposal_id or _digest(record["payload"]) != proposal_id:
        raise SysopsError("proposal digest mismatch")
    _validate(settings, record["payload"])
    return cast(dict[str, Any], record)


def propose(settings: Settings, payload: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """Deduplicate exact bundles. Revised content always needs a new decision."""
    payload = _validate(settings, payload)
    proposal_id = _digest(payload)
    with _locked(settings):
        if _path(settings, proposal_id).exists():
            return get(settings, proposal_id)
        record = {"id": proposal_id, "payload": payload, "status": "pending", "history": []}
        if not dry_run:
            _save(settings, record)
        return record


def pending(settings: Settings) -> list[dict[str, Any]]:
    """Pending bundles for the single Mattermost decision digest."""
    return [
        record
        for path in sorted(_directory(settings).glob("sys-*.json"))
        if (record := get(settings, path.stem))["status"] == "pending"
    ]


def decide(
    settings: Settings, proposal_id: str, choice: str, note: str = "", *, dry_run: bool = True
) -> dict[str, Any]:
    """Caller authenticates Robert; modify requests a revision, never execution."""
    if choice not in {"approve", "deny", "modify"}:
        raise SysopsError("decision must be approve, deny, or modify")
    if choice == "modify" and not note.strip():
        raise SysopsError("modify requires the requested change")
    with _locked(settings):
        record = get(settings, proposal_id)
        if record["status"] not in {"pending", "approved"}:
            raise SysopsError("proposal is terminal; prepare a revised bundle")
        record["status"] = {
            "approve": "approved",
            "deny": "denied",
            "modify": "modification_requested",
        }[choice]
        record["approval_digest"] = proposal_id if choice == "approve" else None
        record["history"].append({"decision": choice, "note": note})
        if not dry_run:
            _save(settings, record)
        return record


def _argv(settings: Settings, host: str, argv: list[str]) -> list[str]:
    if host == settings.host:
        return list(argv)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "--", host, shlex.join(argv)]


def _exec(argv: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300, check=False
    )
    return result.returncode, result.stdout, result.stderr


def execute(
    settings: Settings, proposal_id: str, *, dry_run: bool = True, exec_fn: Executor | None = None
) -> dict[str, Any]:
    """Execute once under a lock; failures require a fresh human-reviewed bundle."""
    with _locked(settings):
        record = get(settings, proposal_id)
        if record["status"] != "approved" or record.get("approval_digest") != proposal_id:
            raise SysopsError("execution requires approval of this exact bundle")
        if dry_run:
            return {**record, "dry_run": True}
        record["status"] = "executing"
        record["results"] = []
        _save(settings, record)
        payload = record["payload"]
        runner = exec_fn or _exec
        for phase in ("prechecks", "commands", "postchecks"):
            for index, argv in enumerate(payload[phase]):
                try:
                    rc, _stdout, _stderr = runner(_argv(settings, payload["host"], argv))
                except Exception:
                    # Exceptions can embed credentials or captured command output.
                    rc = -1
                record["results"].append({"phase": phase, "index": index, "returncode": rc})
                if rc != 0:
                    record["status"] = "failed"
                    record["rollback_commands"] = payload["rollback"]
                    record["message"] = (
                        "Stopped; inspect locally. Rollback needs a separate approved proposal."
                    )
                    _save(settings, record)
                    return record
        record["status"] = "applied"
        _save(settings, record)
        return record


def diagnose(
    settings: Settings,
    host: str,
    check: str,
    *,
    dry_run: bool = True,
    exec_fn: Executor | None = None,
) -> dict[str, Any]:
    """Fixed diagnostics only, filtered before output crosses the boundary."""
    _host(settings, host)
    if check not in _DIAGNOSTICS:
        raise SysopsError("unknown diagnostic")
    commands = [_argv(settings, host, argv) for argv in _DIAGNOSTICS[check]]
    result: dict[str, Any] = {
        "host": host,
        "check": check,
        "commands": commands,
        "dry_run": dry_run,
        "results": [],
    }
    if not dry_run:
        for argv in commands:
            rc, stdout, _stderr = (exec_fn or _exec)(argv)
            result["results"].append(
                {
                    "returncode": rc,
                    "stdout": release_text(stdout, personal_source=True)[:8192],
                }
            )
    return result


def inspect_host(
    settings: Settings,
    host: str,
    check: str,
    *,
    exec_fn: Executor | None = None,
) -> dict[str, Any]:
    """Run a bounded diagnostic (read-only)."""
    return diagnose(settings, host, check, dry_run=False, exec_fn=exec_fn)
