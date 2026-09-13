"""``cube patrol deliveries``: send approved messages to people once contact hours open.

Agents work 24/7 but people are contacted only inside ``contact.hours``
(cube.yaml). ``cube deliver`` defers an approved message outside the window;
this patrol, on an hourly timer, delivers every deferred approval whose window
has opened. Nothing is sent that Robert has not approved.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from cube.approvals.deliver import PERSON_KINDS, deliver
from cube.approvals.store import ApprovalError, ApprovalStore
from cube.beads import Beads
from cube.config import Settings
from cube.contact_hours import within_contact_hours
from cube.patrols.base import PatrolReport, register


class DeliveriesPatrol:
    name = "deliveries"

    def __init__(self, *, now: datetime | None = None) -> None:
        self.now = now

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(name=self.name, today=today, dry_run=dry_run)
        now = self.now or datetime.now(UTC)
        store = ApprovalStore(settings.state_dir())
        deferred = [
            item
            for item in store.items("approved")
            if item.kind in PERSON_KINDS
            and isinstance(item.delivery, dict)
            and item.delivery.get("result") == "deferred"
        ]
        report.data["deferred"] = [item.id for item in deferred]
        report.data["delivered"] = []
        if not within_contact_hours(settings.contact.hours, now):
            report.summary = f"{len(deferred)} deferred message(s); outside contact hours"
            return report
        for item in deferred:
            try:
                res = deliver(settings, store, item.id, dry_run=dry_run, now=now)
            except ApprovalError as exc:
                report.warnings.append(f"{item.id}: {exc}")
                continue
            if res.ok:
                report.data["delivered"].append(item.id)
            else:
                report.warnings.append(f"{item.id}: {res.result}: {res.message}")
        report.summary = (
            f"delivered {len(report.data['delivered'])} of {len(deferred)} deferred message(s)"
        )
        return report


register(DeliveriesPatrol, "deliveries")
