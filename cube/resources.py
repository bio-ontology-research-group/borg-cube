"""Central fleet limits and conservative, locked compute reservations.

Reservations charge their entire requested duration, even after release. This
prevents premature completion reports from refunding a day's compute budget.
The ledger is local to the orchestration host; remote clients must use that host.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from cube.config import Settings


class FleetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    daily_research_runs: int | None = Field(default=48, ge=0)
    per_agent_daily_research_runs: int | None = Field(default=4, ge=0)
    local_inference_concurrency: int = Field(default=2, ge=0, le=64)
    local_workday_concurrency: int = Field(default=1, ge=0, le=2)
    local_run_timeout_minutes: int = Field(default=45, ge=1, le=240)
    local_max_turns: int = Field(default=6, ge=2, le=12)
    concurrent_slurm_jobs: int = Field(default=4, ge=0)
    job_cpus: int = Field(default=8, ge=0)
    job_memory_gib: float = Field(default=32, ge=0)
    job_gpus: int = Field(default=1, ge=0)
    job_walltime_hours: float = Field(default=4, ge=0)
    daily_cpu_hours: float = Field(default=128, ge=0)
    daily_gpu_hours: float = Field(default=8, ge=0)
    min_free_gib: float = Field(default=20, ge=0)
    min_free_percent: float = Field(default=10, ge=0, le=100)
    min_free_inodes: int = Field(default=10000, ge=0)
    daily_cost_usd: float = Field(default=10, ge=0)
    decision_digest_hours: float = Field(default=12, ge=0)
    autonomous_interval_hours: float = Field(default=6, ge=0)

    @field_validator("*", mode="before")
    @classmethod
    def reject_bools(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("limits must be numbers, not booleans")
        return value


class JobNeeds(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    cpus: int = Field(default=1, gt=0)
    memory_gib: float = Field(default=4, gt=0)
    gpus: int = Field(default=0, ge=0)
    walltime_hours: float = Field(default=1, gt=0)

    @field_validator("*", mode="before")
    @classmethod
    def reject_bools(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("job resources must be numbers, not booleans")
        return value


class StorageEvidence(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    free_bytes: int = Field(ge=0, strict=True)
    total_bytes: int = Field(gt=0, strict=True)
    free_inodes: int = Field(ge=0, strict=True)


def _state(settings: Settings) -> Path:
    return settings.paths.resolved(settings.root)["state"]


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _atomic(path: Path, data: Any) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _locked(settings: Settings, dry_run: bool = False) -> Iterator[Path]:
    state = _state(settings)
    if dry_run:
        yield state
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state / "fleet-resources.lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield state
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_limits(settings: Settings) -> FleetLimits:
    configured = getattr(settings, "fleet_limits", FleetLimits())
    base = configured.model_dump() if isinstance(configured, FleetLimits) else configured
    saved = _read(_state(settings) / "fleet-limits.json", {})
    return FleetLimits.model_validate({**base, **saved.get("limits", {})})


class LocalCapacityFull(RuntimeError):  # noqa: N818 - admission outcome, not a run failure
    """The shared local endpoint is full; queue without starting inference."""


def schedule_local_workdays(
    settings: Settings,
    names: list[str],
    *,
    dry_run: bool = True,
) -> list[str]:
    """Offer one bounded wave, rotating across ticks instead of racing for slots.

    Persist offers, not successes: idle, crashing or blocked agents must not
    monopolize the next tick. Deferred agents never enter the run/budget machinery.
    The physical endpoint semaphore still owns final admission across all callers.
    """
    limits = load_limits(settings)
    width = min(limits.local_workday_concurrency, limits.local_inference_concurrency)
    with _locked(settings, dry_run) as state:
        path = state / "local-workday-schedule.json"
        saved = _read(path, {})
        previous = saved.get("last_offered", {})
        ordered = sorted(names, key=lambda name: (previous.get(name, 0), name))
        selected = ordered[:width]
        if selected and not dry_run:
            sequence = int(saved.get("sequence", 0)) + 1
            for name in selected:
                previous[name] = sequence
            _atomic(path, {"sequence": sequence, "last_offered": previous})
    return selected


@contextmanager
def local_inference_slot(settings: Settings, runner: str) -> Iterator[None]:
    """Nonblocking process/thread-safe admission shared by every local tier/harness.

    Locks stay held through the entire session, including its final summary.
    Kernel locks release on process exit; no TTL can expire during a slow run.
    """
    from cube.runners.naming import uses_local

    if not uses_local(runner):
        yield
        return
    limit = load_limits(settings).local_inference_concurrency
    directory = _state(settings) / "local-inference-slots"
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(limit):
        handle = (directory / f"{index}.lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            continue
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        return
    raise LocalCapacityFull(f"local inference capacity full ({limit} sessions); queued")


def update_limits(
    settings: Settings, changes: dict[str, Any], evidence: str, dry_run: bool = True
) -> dict[str, Any]:
    """Apply validated overrides with a durable source and previous/new audit."""
    if not evidence.strip():
        raise ValueError("a source for Robert's instruction is required")
    with _locked(settings, dry_run) as state:
        previous = load_limits(settings).model_dump()
        new = FleetLimits.model_validate({**previous, **changes}).model_dump()
        entry = {
            "at": datetime.now(UTC).isoformat(),
            "evidence": evidence,
            "previous": previous,
            "new": new,
        }
        if not dry_run:
            saved = _read(state / "fleet-limits.json", {})
            _atomic(
                state / "fleet-limits.json",
                {
                    "limits": new,
                    "audit": [*saved.get("audit", []), entry],
                },
            )
        return {**entry, "dry_run": dry_run}


def _usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    today = datetime.now(UTC).date().isoformat()
    active = [r for r in records if r["status"] in {"reserved", "submitted"}]
    # A still-active job remains charged after midnight until it is completed.
    charged = [
        r
        for r in records
        if r["date"] == today or today in r.get("charged_dates", []) or r in active
    ]
    return {
        "date": today,
        "active_jobs": len(active),
        "cpu_hours": sum(r["needs"]["cpus"] * r["needs"]["walltime_hours"] for r in charged),
        "gpu_hours": sum(r["needs"]["gpus"] * r["needs"]["walltime_hours"] for r in charged),
        "reservations": records,
    }


def read_usage(settings: Settings) -> dict[str, Any]:
    usage = _usage(_read(_state(settings) / "fleet-jobs.json", []))
    runs = _read(_state(settings) / "fleet-research.json", [])
    today = [run for run in runs if run["date"] == usage["date"]]
    usage["research_runs"] = len(today)
    usage["research_runs_by_agent"] = {
        agent: sum(run["agent"] == agent for run in today)
        for agent in sorted({run["agent"] for run in today})
    }
    return usage


def reserve_research_run(
    settings: Settings,
    agent: str,
    autonomous: bool = False,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Charge an attempted research run before invoking its runner.

    Reservations are never refunded after failure. Inbox-directed runs bypass
    the autonomous interval, but still consume both daily run ceilings. Cost
    accounting belongs to the router, which records actual billed usage.
    """
    if not agent.strip():
        raise ValueError("agent is required")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must include a timezone")
    instant = instant.astimezone(UTC)
    day = instant.date().isoformat()
    with _locked(settings, dry_run) as state:
        limits = load_limits(settings)
        records = _read(state / "fleet-research.json", [])
        charged = [run for run in records if not run.get("cancelled_before_start")]
        today = [run for run in charged if run["date"] == day]
        if limits.daily_research_runs is not None and len(today) >= limits.daily_research_runs:
            raise ValueError("daily fleet research run limit reached")
        if limits.per_agent_daily_research_runs is not None and (
            sum(run["agent"] == agent for run in today) >= limits.per_agent_daily_research_runs
        ):
            raise ValueError("daily agent research run limit reached")
        previous = [
            datetime.fromisoformat(run["created_at"])
            for run in charged
            if run["agent"] == agent and run["autonomous"]
        ]
        if autonomous and previous:
            elapsed = (instant - max(previous)).total_seconds() / 3600
            if elapsed < limits.autonomous_interval_hours:
                raise ValueError("autonomous research interval has not elapsed")
        reservation = {
            "id": f"research-{uuid4().hex}",
            "agent": agent,
            "date": day,
            "created_at": instant.isoformat(),
            "autonomous": autonomous,
        }
        if not dry_run:
            _atomic(state / "fleet-research.json", [*records, reservation])
        return {**reservation, "dry_run": dry_run}


def cancel_unstarted_research(settings: Settings, reservation_id: str, reason: str) -> None:
    """Admission queued before inference: retain audit but do not charge an attempt."""
    with _locked(settings) as state:
        records = _read(state / "fleet-research.json", [])
        for record in records:
            if record["id"] == reservation_id:
                record["cancelled_before_start"] = reason
        _atomic(state / "fleet-research.json", records)


def reserve_job(
    settings: Settings,
    agent: str,
    target: str,
    needs: dict[str, Any] | JobNeeds,
    free_bytes: int,
    total_bytes: int,
    free_inodes: int,
    dry_run: bool = True,
) -> str:
    """Reserve before submission; caller supplies fresh remote filesystem evidence."""
    if not agent.strip():
        raise ValueError("agent is required")
    if target not in {"ibex", "dragon", "unimatrix01"}:
        raise ValueError("target must be ibex, dragon or unimatrix01")
    request = JobNeeds.model_validate(needs)
    storage = StorageEvidence(
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        free_inodes=free_inodes,
    )
    if storage.free_bytes > storage.total_bytes:
        raise ValueError("free bytes exceed filesystem size")
    with _locked(settings, dry_run) as state:
        limits = load_limits(settings)
        for field, cap in (
            ("cpus", "job_cpus"),
            ("memory_gib", "job_memory_gib"),
            ("gpus", "job_gpus"),
            ("walltime_hours", "job_walltime_hours"),
        ):
            if getattr(request, field) > getattr(limits, cap):
                raise ValueError(f"job exceeds {cap}")
        if free_bytes < limits.min_free_gib * 1024**3:
            raise ValueError("insufficient free GiB")
        if 100 * free_bytes / total_bytes < limits.min_free_percent:
            raise ValueError("insufficient free disk percentage")
        if free_inodes < limits.min_free_inodes:
            raise ValueError("insufficient free inodes")
        records: list[dict[str, Any]] = _read(state / "fleet-jobs.json", [])
        usage = _usage(records)
        if usage["active_jobs"] >= limits.concurrent_slurm_jobs:
            raise ValueError("concurrent Slurm job limit reached")
        if usage["cpu_hours"] + request.cpus * request.walltime_hours > limits.daily_cpu_hours:
            raise ValueError("daily CPU hours exhausted")
        if usage["gpu_hours"] + request.gpus * request.walltime_hours > limits.daily_gpu_hours:
            raise ValueError("daily GPU hours exhausted")
        reservation = f"job-{uuid4().hex}"
        if not dry_run:
            _atomic(
                state / "fleet-jobs.json",
                [
                    *records,
                    {
                        "id": reservation,
                        "agent": agent,
                        "target": "ibex" if target == "dragon" else target,
                        "date": usage["date"],
                        "created_at": datetime.now(UTC).isoformat(),
                        "status": "reserved",
                        "needs": request.model_dump(),
                        "storage": storage.model_dump(),
                    },
                ],
            )
        return reservation


def _transition(
    settings: Settings,
    reservation: str,
    status: str,
    job_id: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    with _locked(settings, dry_run) as state:
        records = _read(state / "fleet-jobs.json", [])
        record = next((r for r in records if r["id"] == reservation), None)
        if record is None:
            raise ValueError("unknown job reservation")
        if record["status"] not in {"reserved", "submitted"}:
            raise ValueError("reservation already closed")
        if status == "submitted" and record["status"] != "reserved":
            raise ValueError("reservation already submitted")
        record["charged_dates"] = sorted(
            {
                *record.get("charged_dates", []),
                datetime.now(UTC).date().isoformat(),
            }
        )
        record.update(status=status, updated_at=datetime.now(UTC).isoformat())
        if job_id is not None:
            record["job_id"] = job_id
        if not dry_run:
            _atomic(state / "fleet-jobs.json", records)
        return dict(record)


def mark_submitted(
    settings: Settings,
    reservation: str,
    job_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    if not job_id.strip():
        raise ValueError("Slurm job id is required")
    return _transition(settings, reservation, "submitted", job_id, dry_run)


def release_job(settings: Settings, reservation: str, dry_run: bool = True) -> dict[str, Any]:
    return _transition(settings, reservation, "released", None, dry_run)


def finish_job(settings: Settings, reservation: str, dry_run: bool = True) -> dict[str, Any]:
    return _transition(settings, reservation, "finished", None, dry_run)
