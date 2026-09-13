"""``cube patrol decisions``: answer the decisions Robert would approve anyway.

Most pending decisions are not choices: a resource step inside the declared
allowance, an agent joining a team, an advisory goal review, a reversible write
under ``runs/``. ``decisions.policy`` in ``cube.yaml`` lists the ones that
answer themselves; this patrol, on a 15 minute timer, applies them and leaves
everything else for Robert. The ``never_automatic`` guards (outbound, people,
integrity, conflict, question, deletion, spend over budget) are never answered
here, whatever a rule says.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from cube.beads import Beads
from cube.config import Settings
from cube.decisions import announce_pending, apply_policy
from cube.patrols.base import Finding, PatrolReport, register


class DecisionsPatrol:
    name = "decisions"

    def __init__(self, *, now: datetime | None = None) -> None:
        self.now = now

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(name=self.name, today=today, dry_run=dry_run)
        if settings.fleet_enabled and settings.host == "ws":
            from cube.fleet_github import publish_pending

            report.data["fleet_publications"] = publish_pending(settings, dry_run=dry_run)
            failures = [row for row in report.data["fleet_publications"] if row.get("error")]
            if failures:
                report.warnings.append(
                    f"{len(failures)} GitHub publications pending after failure; "
                    "check GitHub authentication and organization access on ws"
                )
        now = self.now or datetime.now(UTC)
        rows = apply_policy(settings, beads, dry_run=dry_run, now=now)
        answered = [row for row in rows if row.get("answered")]
        waiting = [row for row in rows if not row.get("answered")]
        report.data["answered"] = answered
        report.data["waiting"] = [row["id"] for row in waiting]
        for row in answered:
            report.findings.append(
                Finding(
                    key=f"decision:{row['id']}",
                    title=f"{row['id']} {row.get('answer')}: {row.get('note')}",
                    detail=str(row.get("title") or ""),
                    source=f"cube.yaml decisions.policy[{(row.get('policy') or {}).get('rule')}]",
                )
            )
        for row in rows:
            if row.get("error"):
                report.warnings.append(f"{row['id']}: {row['error']}")
        # Robert, 2026-09-07: what still waits for him goes to his Mattermost DM
        # through hermes-ws's inbox and the outbox cron (ADR-0020), once each.
        announced = announce_pending(settings, beads, dry_run=dry_run, now=now)
        report.data["announced"] = [row["id"] for row in announced]
        for row in announced:
            report.findings.append(
                Finding(
                    key=f"announce:{row['id']}",
                    title=f"{row['id']} announced to Robert's Mattermost DM",
                    detail=str(row["text"])[:120],
                    source="agents/hermes-ws/inbox.jsonl",
                )
            )
        report.summary = (
            f"auto-answered {len(answered)}, {len(waiting)} wait for Robert, "
            f"{len(announced)} announced on Mattermost"
        )
        return report


register(DecisionsPatrol, "decisions")
