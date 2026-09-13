"""state/leases/<bead>.json: one live run per bead (pid + expiry); dead leases expire."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 2 * 3600


class LeaseHeld(RuntimeError):  # noqa: N818 - domain name
    pass


@dataclass
class Lease:
    bead: str
    run_id: str
    role: str
    pid: int
    host: str
    created: str
    expires: str
    tier: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def expired(self, now: datetime | None = None) -> bool:
        return datetime.fromisoformat(self.expires) <= (now or datetime.now(UTC))

    def pid_alive(self) -> bool:
        if self.host != socket.gethostname():
            return True  # cannot tell from here; trust the expiry
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def live(self, now: datetime | None = None) -> bool:
        return not self.expired(now) and self.pid_alive()


def leases_dir(state_dir: Path) -> Path:
    return state_dir / "leases"


def lease_path(state_dir: Path, bead: str) -> Path:
    return leases_dir(state_dir) / f"{bead}.json"


def load(state_dir: Path, bead: str) -> Lease | None:
    path = lease_path(state_dir, bead)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Lease(**{k: data[k] for k in Lease.__dataclass_fields__ if k in data})
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def acquire(
    state_dir: Path,
    bead: str,
    *,
    run_id: str,
    role: str,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    tier: str | None = None,
    pid: int | None = None,
    now: datetime | None = None,
) -> Lease:
    now = now or datetime.now(UTC)
    existing = load(state_dir, bead)
    if existing and existing.live(now):
        raise LeaseHeld(
            f"bead {bead} is leased by run {existing.run_id} (pid {existing.pid} on "
            f"{existing.host}) until {existing.expires}"
        )
    lease = Lease(
        bead=bead,
        run_id=run_id,
        role=role,
        pid=pid or os.getpid(),
        host=socket.gethostname(),
        created=now.isoformat(timespec="seconds"),
        expires=(now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
        tier=tier,
    )
    path = lease_path(state_dir, bead)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease.as_dict(), indent=1), encoding="utf-8")
    return lease


def release(state_dir: Path, bead: str, run_id: str | None = None) -> bool:
    existing = load(state_dir, bead)
    if existing is None:
        return False
    if run_id and existing.run_id != run_id:
        return False
    lease_path(state_dir, bead).unlink(missing_ok=True)
    return True


def all_leases(state_dir: Path) -> list[Lease]:
    d = leases_dir(state_dir)
    if not d.exists():
        return []
    out: list[Lease] = []
    for path in sorted(d.glob("*.json")):
        lease = load(state_dir, path.stem)
        if lease:
            out.append(lease)
    return out


def live_leases(state_dir: Path, now: datetime | None = None) -> list[Lease]:
    return [x for x in all_leases(state_dir) if x.live(now)]


def dead_leases(state_dir: Path, now: datetime | None = None) -> list[Lease]:
    return [x for x in all_leases(state_dir) if not x.live(now)]


def expire_dead(state_dir: Path, now: datetime | None = None) -> list[Lease]:
    """Remove leases whose process is gone or whose expiry passed; return them."""
    dead = dead_leases(state_dir, now)
    for lease in dead:
        lease_path(state_dir, lease.bead).unlink(missing_ok=True)
    return dead
