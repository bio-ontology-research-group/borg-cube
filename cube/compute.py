"""Bounded Slurm submission through the fleet's orchestration host.

This controls allocations submitted through Cube, not arbitrary programs using
the user's SSH credentials. Research code must remain within its allocation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from cube.resources import (
    JobNeeds,
    finish_job,
    mark_submitted,
    read_usage,
    release_job,
    reserve_job,
)

if TYPE_CHECKING:
    from cube.config import Settings

_TARGETS = {
    "ibex": ("dragon", ("/ibex/scratch/projects/c2014",)),
    "dragon": ("dragon", ("/ibex/scratch/projects/c2014",)),
    "unimatrix01": ("unimatrix01", ("/storage", "/data")),
}
_TERMINAL = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "PREEMPTED",
    "REVOKED",
}
_STAT = """import json, os, pathlib, sys
p = pathlib.Path(sys.argv[1]).resolve(strict=True)
roots = [pathlib.Path(root) for root in sys.argv[2:]]
if not p.is_dir() or not any(p == root or root in p.parents for root in roots):
    raise SystemExit('workdir resolves outside approved research storage')
s = os.statvfs(p)
print(json.dumps(dict(free_bytes=s.f_bavail*s.f_frsize,
                     total_bytes=s.f_blocks*s.f_frsize, free_inodes=s.f_favail)))
"""


def _ssh(target: str, args: list[str]) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        _TARGETS[target][0],
        shlex.join(args),
    ]


def _run(command: list[str], data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=data, capture_output=True, timeout=45, check=False)


def _text(value: bytes | str) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _validate_workdir(target: str, workdir: str) -> None:
    if target not in _TARGETS:
        raise ValueError("target must be ibex, dragon or unimatrix01")
    path = PurePosixPath(workdir)
    if not path.is_absolute() or ".." in path.parts or any(ord(char) < 32 for char in workdir):
        raise ValueError("workdir must be an absolute research storage path without traversal")
    if not any(
        path == PurePosixPath(root) or PurePosixPath(root) in path.parents
        for root in _TARGETS[target][1]
    ):
        raise ValueError("workdir is outside approved research storage")


def submit(
    settings: Settings,
    agent: str,
    target: str,
    script: Path,
    workdir: str,
    needs: dict[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Validate, inspect storage, reserve resources, then submit exact script bytes."""
    _validate_workdir(target, workdir)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", agent):
        raise ValueError("invalid agent name")
    raw = dict(needs)
    expected = raw.pop("expected_output_gib", 0)
    if (
        isinstance(expected, bool)
        or not isinstance(expected, (int, float))
        or not math.isfinite(expected)
        or expected < 0
    ):
        raise ValueError("expected_output_gib must be finite and nonnegative")
    request = JobNeeds.model_validate(raw)
    # Reserve exactly the rounded allocations passed to Slurm.
    if not all(
        math.isfinite(value)
        for value in (
            request.walltime_hours * 3600,
            request.memory_gib * 1024,
            expected * 1024**3,
        )
    ):
        raise ValueError("resource quantities exceed representable units")
    seconds = math.ceil(request.walltime_hours * 3600)
    memory_mib = math.ceil(request.memory_gib * 1024)
    request = JobNeeds.model_validate(
        {**request.model_dump(), "walltime_hours": seconds / 3600, "memory_gib": memory_mib / 1024}
    )
    data = script.read_bytes()
    if not data.startswith(b"#!") or b"\x00" in data or len(data) > 4 * 1024**2:
        raise ValueError("script must be a shebang script without NUL bytes, at most 4 MiB")
    if re.search(rb"(?m)^\s*#SBATCH\b", data):
        raise ValueError("remove #SBATCH directives; resources are controlled centrally")
    stat_command = _ssh(target, ["python3", "-c", _STAT, workdir, *_TARGETS[target][1]])
    days, remaining = divmod(seconds, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, secs = divmod(remaining, 60)
    args = [
        "env",
        "-i",
        "PATH=/usr/bin:/bin",
        "sbatch",
        "--parsable",
        "--export=NONE",
        "--nodes=1",
        "--ntasks=1",
        f"--cpus-per-task={request.cpus}",
        f"--mem={memory_mib}M",
        f"--time={days}-{hours:02}:{minutes:02}:{secs:02}",
        f"--chdir={workdir}",
        f"--job-name=cube-{agent}",
        f"--output={workdir}/cube-%j.out",
        f"--error={workdir}/cube-%j.err",
        "--no-requeue",
    ]
    if target in {"ibex", "dragon"}:
        args.extend(["--account=c2014", "--partition=gpu" if request.gpus else "--partition=batch"])
    else:
        args.extend(["--partition=debug", "--exclude=node005"])
    if request.gpus:
        args.append(f"--gres=gpu:{request.gpus}")
    command = _ssh(target, args)
    report: dict[str, Any] = {
        "agent": agent,
        "target": target,
        "workdir": workdir,
        "needs": request.model_dump(),
        "expected_output_gib": expected,
        "script_sha256": hashlib.sha256(data).hexdigest(),
        "commands": [stat_command, command],
        "dry_run": dry_run,
    }
    if dry_run:
        reserve_job(settings, agent, target, request, 2**62, 2**62, 2**62, dry_run=True)
        return {**report, "status": "dry-run"}
    try:
        inspection = _run(stat_command)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**report, "status": "queued", "reason": f"storage inspection failed: {exc}"}
    if inspection.returncode:
        return {
            **report,
            "status": "queued",
            "reason": "storage inspection failed",
            "stderr": _text(inspection.stderr),
        }
    try:
        from cube.resources import StorageEvidence

        storage = StorageEvidence.model_validate(json.loads(inspection.stdout)).model_dump()
    except (ValueError, TypeError):
        return {**report, "status": "queued", "reason": "invalid storage inspection response"}
    output_bytes = math.ceil(expected * 1024**3)
    free_bytes = storage["free_bytes"] - output_bytes
    if free_bytes < 0:
        return {**report, "status": "queued", "reason": "expected output exceeds available space"}
    try:
        reservation = reserve_job(
            settings,
            agent,
            target,
            request,
            free_bytes,
            storage["total_bytes"],
            storage["free_inodes"],
            dry_run=False,
        )
    except ValueError as exc:
        return {**report, "status": "queued", "reason": str(exc)}
    report["reservation"] = reservation
    try:
        result = _run(command, data)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**report, "status": "uncertain", "reason": str(exc), "retry": False}
    if result.returncode == 255:
        return {
            **report,
            "status": "uncertain",
            "reason": "SSH disconnected during submission",
            "retry": False,
        }
    if result.returncode:
        release_job(settings, reservation, dry_run=False)
        return {**report, "status": "failed", "stderr": _text(result.stderr)}
    match = re.fullmatch(r"([0-9]+)(?:;[a-zA-Z0-9_.-]+)?\s*", _text(result.stdout))
    if not match:
        return {
            **report,
            "status": "uncertain",
            "reason": "unrecognized sbatch response",
            "retry": False,
        }
    job_id = match.group(1)
    mark_submitted(settings, reservation, job_id, dry_run=False)
    return {**report, "status": "submitted", "job_id": job_id}


def status(settings: Settings, reservation: str, dry_run: bool = True) -> dict[str, Any]:
    """Poll one known job; absence from the queue never releases its reservation."""
    record = next((r for r in read_usage(settings)["reservations"] if r["id"] == reservation), None)
    if record is None:
        raise ValueError("unknown job reservation")
    job_id = record.get("job_id")
    if not job_id:
        return {"reservation": reservation, "status": record["status"], "reason": "no known job id"}
    if not re.fullmatch(r"[0-9]+", job_id):
        raise ValueError("invalid stored Slurm job id")
    target = record["target"]
    commands = [
        _ssh(target, ["squeue", "--noheader", "--jobs", job_id, "--format=%T"]),
        _ssh(
            target,
            ["sacct", "--noheader", "--parsable2", "--jobs", job_id, "--format=JobIDRaw,State"],
        ),
        _ssh(target, ["scontrol", "show", "job", job_id, "--oneliner"]),
    ]
    report = {"reservation": reservation, "job_id": job_id, "dry_run": dry_run}
    if record["status"] in {"finished", "released"}:
        return {**report, "status": record["status"]}
    if dry_run:
        return {**report, "status": "dry-run", "commands": commands}
    for index, command in enumerate(commands):
        try:
            result = _run(command)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode:
            continue
        output = _text(result.stdout).strip()
        state = None
        if index == 0 and output:
            state = output.splitlines()[0].strip()
        elif index == 1:
            for line in output.splitlines():
                fields = line.split("|")
                if len(fields) >= 2 and fields[0] == job_id:
                    state = fields[1].split()[0].rstrip("+") if fields[1] else None
                    break
        elif index == 2:
            found = re.search(r"\bJobState=([A-Z_]+)\b", output)
            state = found.group(1) if found else None
        if state:
            # A queue response is useful progress but not accounting proof.
            if state in _TERMINAL and index > 0:
                finish_job(settings, reservation, dry_run=False)
            return {**report, "status": state, "source": ("squeue", "sacct", "scontrol")[index]}
    return {**report, "status": "unknown", "reason": "no conclusive scheduler state"}
