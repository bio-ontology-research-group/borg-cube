"""Leases patrol: expire dead leases so the marshal can requeue their beads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from cube.beads import Beads
from cube.config import Settings
from cube.engine import lease as leases
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, prov, register
from cube.sync.derivers import DesiredBead

STORM_THRESHOLD = 5


@dataclass
class LeasesPatrol:
    name: str = "leases"
    now: datetime | None = None

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        now = self.now or datetime.now(UTC)
        state = settings.state_dir()
        report = PatrolReport(self.name, today, dry_run)
        dead = leases.dead_leases(state, now) if dry_run else leases.expire_dead(state, now)
        live = leases.live_leases(state, now)
        for lease in dead:
            report.findings.append(
                Finding(
                    key=f"lease:{lease.bead}",
                    title=(
                        f"{'would expire' if dry_run else 'expired'} lease on {lease.bead} "
                        f"({lease.role}, run {lease.run_id}, pid {lease.pid} on {lease.host}, "
                        f"expiry {lease.expires})"
                    ),
                    severity="warn",
                    source=str(leases.lease_path(state, lease.bead)),
                )
            )
        xid = "finding:leases:storm"
        header = BeadHeader(
            xid=xid, provenance=[prov(str(leases.leases_dir(state)), f"{len(dead)} dead", today)]
        )
        if len(dead) >= STORM_THRESHOLD:
            body = "\n".join(
                f"- {x.bead}: {x.role} run {x.run_id} pid {x.pid} expired {x.expires}" for x in dead
            )
            report.findings.append(
                DesiredBead(
                    xid=xid,
                    title=f"Dead lease storm: {len(dead)} leases expired in one pass",
                    kind=WorkKind.finding,
                    labels=["src:leases", "needs:robert"],
                    header=header,
                    body=body,
                    priority=1,
                )
            )
            report.events.append(
                attention_event(self.name, f"{len(dead)} dead leases expired", body=body, xid=xid)
            )
        else:
            report.findings.append(
                DesiredBead(
                    xid=xid,
                    title="Dead lease storm",
                    kind=WorkKind.finding,
                    labels=["src:leases"],
                    header=header,
                    closed=True,
                    close_reason=f"{len(dead)} dead lease(s), below {STORM_THRESHOLD}",
                )
            )
        report.data["dead"] = [x.as_dict() for x in dead]
        report.data["live"] = [x.as_dict() for x in live]
        report.summary = (
            f"{len(dead)} dead lease(s) {'found' if dry_run else 'expired'}, {len(live)} live"
        )
        return report


register(LeasesPatrol, "leases")
