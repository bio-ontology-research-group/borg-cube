"""Runner protocol and shared plumbing (injectable subprocess and HTTP for tests)."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from cube.model import RunResult
from cube.roles import Role


@dataclass
class ExecResult:
    """What an executed command returned (subprocess.CompletedProcess without the generics)."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


Exec = Callable[..., ExecResult]
"""Signature: exec_fn(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: float,
stdin_devnull: bool) -> ExecResult"""

HttpPost = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]
"""Signature: http_post(url, headers, body, timeout) -> (status, body_bytes)"""

HttpGet = Callable[[str, Mapping[str, str], float], tuple[int, bytes]]
"""Signature: http_get(url, headers, timeout) -> (status, body_bytes)"""


class RunnerUsage(dict[str, Any]):
    """Usage counters carrying non-serialized runner identity for the budget ledger."""

    def __init__(self, values: Mapping[str, Any] | None = None, runner: str = ""):
        super().__init__(values or {})
        self.runner = runner


def runner_usage(values: Mapping[str, Any] | None, runner: str) -> RunnerUsage:
    return RunnerUsage(values, runner)


def default_exec(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdin_devnull: bool = True,
    stdin_text: str | None = None,
) -> ExecResult:
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=(
                subprocess.PIPE
                if stdin_text is not None
                else (subprocess.DEVNULL if stdin_devnull else None)
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return ExecResult(127, "", f"{cmd[0]}: not found ({exc})")
    try:
        stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # A tool child may inherit stdout and outlive the worker. Killing only
        # the parent can leave inference/tool processes and communicate hanging.
        _signal_group(proc, signal.SIGTERM)
        try:
            proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        finally:
            _signal_group(proc, signal.SIGKILL)
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired as drain:
            # An escaped child may still own a pipe: never wait indefinitely.
            stdout, stderr = _exec_text(drain.stdout), _exec_text(drain.stderr)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
        proc.wait(timeout=1)
        return ExecResult(
            124,
            stdout or _exec_text(exc.stdout),
            f"{stderr.rstrip()}\ntimeout after {timeout:.0f}s".lstrip(),
            timed_out=True,
        )
    except BaseException:
        _signal_group(proc, signal.SIGKILL)
        proc.wait(timeout=1)
        raise
    return ExecResult(proc.returncode, stdout, stderr)


def _signal_group(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _exec_text(value: bytes | str | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")


def default_http_post(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
            return int(resp.status), bytes(resp.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read() or b"")


def default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed hosts
            return int(resp.status), bytes(resp.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read() or b"")


@dataclass
class RunContext:
    run_id: str
    role: Role
    prompt: str
    cwd: Path
    run_dir: Path
    state_dir: Path | None = None
    system_prompt: str | None = None
    model: str | None = None
    profile: str | None = None
    sandbox: str | None = None
    resume_id: str | None = None
    bead: str | None = None
    session: str | None = None
    timeout: float = 1800.0
    schema: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False
    # True only for an open-data run (privacy.open_endpoints_for, ADR-0018): the
    # request may reach an endpoint that logs or trains on prompts.
    open_data: bool = False
    # Robert, 2026-09-08 (ADR-0027): directories a `read_roots: host` role may read;
    # empty for every other role. Honoured by the Claude Code runner's path rules.
    read_roots: list[Path] = field(default_factory=list)
    # Directories that stay closed inside the read roots (symlinked `~/pa`, credential
    # stores); rendered as Claude Code deny rules, which win over allow rules.
    deny_roots: list[Path] = field(default_factory=list)

    def process_env(self) -> dict[str, str]:
        """Child environment. Secrets live here and never on the command line."""
        env = dict(os.environ)
        env.update(self.env)
        env["CUBE_RUN_ID"] = self.run_id
        env["CUBE_SESSION"] = self.session or f"run-{self.run_id}"
        if self.bead:
            env["CUBE_BEAD"] = self.bead
        env["CUBE_ROLE"] = self.role.name
        return env


@dataclass
class RunOutcome:
    raw_text: str
    result: RunResult | None
    session_id: str | None
    usage: dict[str, Any]
    exit_code: int
    stderr: str
    command: list[str] = field(default_factory=list)
    rate_limited: bool = False
    error: str | None = None
    cost_usd: float | None = None
    checkpoint_only: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.result is not None and not self.error


class Runner(Protocol):
    name: str

    def command(self, ctx: RunContext) -> list[str]: ...

    def run(self, ctx: RunContext) -> RunOutcome: ...


RATE_LIMIT_PATTERNS = re.compile(
    r"rate[ _-]?limit|too many requests|\b429\b|usage limit|limit reached|"
    r"quota exceeded|overloaded|capacity|insufficient_quota|resource[_ ]exhausted|"
    r"\bfree\b|no endpoints",
    re.IGNORECASE,
)


def looks_rate_limited(*texts: str | None) -> bool:
    return any(t and RATE_LIMIT_PATTERNS.search(t) for t in texts)


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Find the RunResult object in free text: whole text, fenced block, or the last {...}."""
    text = text.strip()
    if not text:
        return None
    for candidate in (text, *(m.group(1) for m in _FENCE.finditer(text))):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    start = text.find("{")
    end = text.rfind("}")
    while start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        return data if isinstance(data, dict) else None
    return None


def failure_error(
    parse_error: str | None,
    *,
    harness: str,
    timed_out: bool = False,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> str | None:
    """The error to record for a run without a result: the cause, not the symptom.

    Robert, 2026-09-08: "error: no JSON object in output" was the most frequent
    error on ws, and in every case the harness had timed out (20 of 20 hermes@local
    failures on 2026-09-07 and 2026-09-08 carried `timeout after 1800s` in stderr).
    A timeout or an empty stdout says so; the parse error is kept only when there
    was output to parse.
    """
    detail = stderr.strip()
    if timed_out:
        return f"{harness} {detail or 'timed out'}; no result before the deadline"
    if not (stdout or "").strip():
        where = f": {detail[:200]}" if detail else ""
        code = f" (exit {returncode})" if returncode else ""
        return f"{harness} produced no output{code}{where}"
    return parse_error


def parse_result(text: str | dict[str, Any] | None) -> tuple[RunResult | None, str | None]:
    """Validate text or dict into a RunResult; returns (result, error)."""
    if text is None:
        return None, "empty output"
    data = text if isinstance(text, dict) else extract_json_object(text)
    if data is None:
        return None, "no JSON object in output"
    data = wrap_bare_artifact(data)
    try:
        return RunResult.model_validate(data), None
    except ValidationError as exc:
        # Name every failing field: the run is kept on the ledger with the
        # error, and a model that omits a field must see which one (cube-7q24).
        fields = [
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        ]
        detail = "; ".join(fields[:5])
        if len(fields) > 5:
            detail += f"; and {len(fields) - 5} more"
        return None, f"RunResult invalid ({exc.error_count()} error(s)): {detail}"


def wrap_bare_artifact(data: dict[str, Any]) -> dict[str, Any]:
    """A chat model asked for one artifact often returns the artifact itself.

    Robert, 2026-09-07: the literature agent's free-model runs failed three times a
    day with "RunResult invalid: Field required" because the digest JSON came back
    without the RunResult envelope. An object with a string ``kind`` and no
    ``summary`` is that artifact; it becomes a RunResult carrying it inline.
    """
    if "summary" in data or not isinstance(data.get("kind"), str):
        return data
    kind = str(data["kind"])
    entries = data.get("entries")
    count = len(entries) if isinstance(entries, list) else None
    summary = f"{kind} artifact returned bare"
    if count is not None:
        summary += f" with {count} entries"
    return {
        "summary": summary,
        "artifacts": [
            {
                "kind": kind,
                "path": f"{kind}.json",
                "summary": f"{kind} returned inline by a chat model",
                "content": json.dumps(data, ensure_ascii=False),
            }
        ],
    }


def write_schema(ctx: RunContext) -> Path:
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.run_dir / "schema.json"
    if not path.exists():
        path.write_text(json.dumps(ctx.schema, indent=1), encoding="utf-8")
    return path


def write_system_prompt(ctx: RunContext) -> Path | None:
    if not ctx.system_prompt:
        return None
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.run_dir / "system.md"
    if not path.exists():
        path.write_text(ctx.system_prompt, encoding="utf-8")
    return path
