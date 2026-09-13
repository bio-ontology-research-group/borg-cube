"""Goals patrol: tell Robert once when a goal is complete.

Robert, 2026-09-07: the desktop should hear from the cube when a goal is done,
not on every hourly tick. This patrol reads the closed ``kind:goal`` beads that
carry a goal header (bd copies the label onto children, so the header is what
tells a goal from its work items), and emits one ``goal`` event per goal closed
within the last day. The event xid keeps the patrol idempotent; goals closed
before the patrol existed never fire.

Robert, 2026-09-08 (ADR-0027): the same tick writes the goal's report under
``briefings/goals/`` and leaves it in hermes-ws's inbox, so it reaches his
Mattermost DM once, through the outbox cron, as one larger message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from cube.beads import Beads
from cube.config import Settings
from cube.engine.context import bead_labels
from cube.goals import CLOSED, goal_header
from cube.patrols.base import PatrolReport, attention_event, event_xid, register
from cube.patrols.cursors import load_cursor
from cube.reports import write_goal_report

RECENT = timedelta(days=1)
# A goal closed for one of these reasons was not achieved; nothing to celebrate.
NOT_ACHIEVED = ("duplicate", "dropped", "superseded", "abandon", "cancel", "won't", "wont")


def achieved(bead: dict[str, object]) -> bool:
    """Closed for completion, not as a duplicate or a dropped goal."""
    header = goal_header(bead)
    if header is not None and header.status == "dropped":
        return False
    reason = str(bead.get("close_reason") or "").lower()
    return not any(word in reason for word in NOT_ACHIEVED)


def _closed_at(bead: dict[str, object]) -> datetime | None:
    for key in ("closed_at", "updated_at"):
        raw = bead.get(key)
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


def completed_goals(
    issues: list[dict[str, object]], *, now: datetime, recent: timedelta = RECENT
) -> list[dict[str, object]]:
    """Goals (header-bearing kind:goal beads) closed within ``recent`` of ``now``."""
    out: list[dict[str, object]] = []
    for bead in issues:
        labels = bead_labels(bead)
        if "kind:goal" not in labels or any(x.startswith("pipeline-stage:") for x in labels):
            continue
        header = goal_header(bead)
        if header is None:
            continue
        if str(bead.get("status") or "") not in CLOSED and header.status != "done":
            continue
        closed = _closed_at(bead)
        if closed is None or now - closed > recent:
            continue
        if not achieved(bead):
            continue
        out.append(bead)
    return out


@dataclass
class GoalsPatrol:
    name: str = "goals"
    now: datetime | None = None

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        now = self.now or datetime.now(UTC)
        report = PatrolReport(self.name, today, dry_run)
        ledger = beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run)
        issues = ledger.list_issues("--all")
        done = completed_goals(issues, now=now)
        seen = set(load_cursor(settings.state_dir(), self.name).get("xids") or [])
        reports: list[dict[str, object]] = []
        for goal in done:
            goal_id = str(goal.get("id") or "")
            header = goal_header(goal)
            success = "\n".join(f"- {line}" for line in (header.success if header else []))
            event = attention_event(
                self.name,
                f"Goal complete: {goal.get('title') or goal_id}",
                event="goal",
                xid=f"goal:complete:{goal_id}",
                body=(
                    f"{goal_id} closed"
                    + (f": {goal.get('close_reason')}" if goal.get("close_reason") else "")
                    + (f"\n\nSuccess criteria:\n{success}" if success else "")
                ),
                data={"bead": goal_id},
            )
            report.events.append(event)
            if event_xid(event) in seen:
                continue  # reported on an earlier tick; the cursor remembers
            reports.append(write_goal_report(settings, goal, issues, now=now, dry_run=dry_run))
        report.data["reports"] = reports
        posted = sum(1 for row in reports if row.get("posted"))
        report.summary = (
            f"{len(done)} goal(s) completed in the last day; {len(reports)} report(s) written, "
            f"{posted} left for Robert's Mattermost DM"
        )
        return report


register(GoalsPatrol, "goals")
