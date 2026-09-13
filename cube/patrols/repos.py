"""Repos patrol: GitHub organisation snapshot -> audit candidate beads, capped per week.

``kind:audit`` beads are dispatched to the auditor by the marshal, so the cap is enforced at
creation: at most ``MAX_PER_WEEK`` new audit beads per ISO week (tracked in the cursor);
the remaining candidates are listed as notes for the digest and picked up next week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cube.beads import Beads
from cube.config import Settings
from cube.patrols.base import Finding, PatrolReport, register
from cube.patrols.cursors import load_cursor
from cube.sync.context import SourceContext
from cube.sync.derivers import DesiredBead, derive_github_audits
from cube.sync.reconcile import index_existing

MAX_PER_WEEK = 3


def iso_week(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def select(
    candidates: list[DesiredBead],
    existing: set[str],
    already_this_week: list[str],
    week: str,
    cap: int = MAX_PER_WEEK,
) -> tuple[list[DesiredBead], list[DesiredBead]]:
    """Split candidates into (dispatch now, wait). Known xids pass through unchanged."""
    known = [c for c in candidates if c.xid in existing]
    new = sorted((c for c in candidates if c.xid not in existing), key=lambda c: c.xid)
    room = max(0, cap - len(already_this_week))
    chosen = [
        c.model_copy(update={"labels": [*c.labels, "dispatch:auditor", f"week:{week}"]})
        for c in new[:room]
    ]
    return [*known, *chosen], new[room:]


@dataclass
class ReposPatrol:
    name: str = "repos"
    cap: int = MAX_PER_WEEK
    github_details: bool = True

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=self.github_details)
        report = PatrolReport(self.name, today, dry_run)
        candidates = derive_github_audits(ctx)
        snap = ctx.github
        report.warnings = list(ctx.warnings)
        ledger = beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True)
        existing, warning = index_existing(ledger)
        if warning:
            report.warnings.append(warning)
        week = iso_week(today)
        cursor = load_cursor(settings.state_dir(), self.name)
        dispatched: dict[str, list[str]] = {
            str(k): list(v) for k, v in (cursor.get("dispatched") or {}).items()
        }
        this_week = dispatched.get(week, [])
        chosen, waiting = select(candidates, set(existing), this_week, week, self.cap)
        report.findings = list(chosen)
        for c in waiting:
            report.findings.append(
                Finding(
                    key=f"audit-waiting:{c.xid}",
                    title=f"Audit candidate waiting (weekly cap {self.cap}): {c.title}",
                    severity="info",
                    detail=c.body,
                    source=c.header.provenance[0].source if c.header.provenance else None,
                )
            )
        new_ids = [c.xid for c in chosen if c.xid not in existing]
        dispatched[week] = sorted(set(this_week) | set(new_ids))
        report.data["cursor"] = {"dispatched": dispatched}
        report.data["snapshot"] = {
            "org": snap.org,
            "fetched_at": snap.fetched_at,
            "from_cache": snap.from_cache,
            "repos": len(snap.repos),
        }
        report.data["week"] = week
        report.summary = (
            f"{len(snap.repos)} repos, {len(candidates)} audit candidate(s): "
            f"{len(new_ids)} new this run, {len(waiting)} waiting, "
            f"{len(dispatched[week])}/{self.cap} dispatched in {week}"
        )
        return report


register(ReposPatrol, "repos")
