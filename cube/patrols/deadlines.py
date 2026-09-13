"""Deadlines patrol: ~/pa/deadlines.md on a 7/30-day horizon plus overdue items.

One finding bead per deadline (parent: the deadline bead ``cube sync`` derives); overdue
and 7-day items carry ``needs:robert`` and raise an attention event. Closed or done
deadlines close their finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, prov, register
from cube.sources.pa_kg import Deadline
from cube.sync.context import SourceContext
from cube.sync.derivers import DesiredBead

NEEDS_ROBERT_WINDOWS = {"overdue", "7d"}
# Robert, 2026-09-07: a deadline overdue this long is bookkeeping in deadlines.md,
# not fifteen decisions. Those items go into one weekly digest bead.
STALE_OVERDUE_DAYS = 14


def digest_xid(today: date) -> str:
    year, week, _ = today.isocalendar()
    return f"finding:deadlines:overdue-digest:{year}-W{week:02d}"


def window_for(days: int) -> str | None:
    if days < 0:
        return "overdue"
    if days <= 7:
        return "7d"
    if days <= 30:
        return "30d"
    return None


def finding_xid(d: Deadline) -> str:
    return f"finding:deadline:{d.xid}"


def derive(
    ctx: SourceContext,
) -> tuple[list[DesiredBead], list[Finding], list[dict[str, Any]], dict[str, int]]:
    beads: list[DesiredBead] = []
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    stale: list[Deadline] = []
    for d in ctx.deadlines:
        xid = finding_xid(d)
        base_labels = ["src:deadlines.md"] + [
            f"person:{p.id}" for p in ctx.index.mentioned_in(d.text)
        ]
        provenance = [prov(str(d.path), d.locator, ctx.today)]
        days = (d.when - ctx.today).days
        window = window_for(days) if d.is_open else None
        if window == "overdue" and -days > STALE_OVERDUE_DAYS:
            stale.append(d)
            counts["stale"] = counts.get("stale", 0) + 1
            beads.append(
                DesiredBead(
                    xid=xid,
                    title=f"Deadline overdue by {-days} day(s): {d.text[:80]}",
                    kind=WorkKind.finding,
                    labels=base_labels,
                    header=BeadHeader(xid=xid, provenance=provenance),
                    closed=True,
                    close_reason=f"overdue {-days} days; listed in the weekly overdue digest",
                )
            )
            continue
        if window is None:
            reason = (
                f"deadlines.md status {d.status}"
                if not d.is_open
                else f"{days} days away; outside the 30-day horizon"
            )
            beads.append(
                DesiredBead(
                    xid=xid,
                    title=f"Deadline warning: {d.text[:80]}",
                    kind=WorkKind.finding,
                    labels=base_labels,
                    header=BeadHeader(xid=xid, provenance=provenance),
                    closed=True,
                    close_reason=reason,
                )
            )
            continue
        counts[window] = counts.get(window, 0) + 1
        when = (
            f"overdue by {-days} day(s)"
            if window == "overdue"
            else f"due in {days} day(s) on {d.when.isoformat()}"
        )
        needs_robert = window in NEEDS_ROBERT_WINDOWS
        labels = [*base_labels, f"window:{window}"]
        if d.section:
            labels.append(f"section:{d.section.lower().replace(' ', '-')[:30]}")
        if needs_robert:
            labels.append("needs:robert")
        title = f"Deadline {when}: {d.text}"
        if len(title) > 120:
            title = title[:117].rstrip() + "..."
        body = [d.text, f"Date: {d.when.isoformat()} ({when})", f"Source: {d.locator}"]
        if d.pa_id:
            body.append(f"pa id: {d.pa_id}")
        beads.append(
            DesiredBead(
                xid=xid,
                title=title,
                kind=WorkKind.finding,
                labels=labels,
                parent_xid=d.xid,
                header=BeadHeader(xid=xid, provenance=provenance, deadline=d.when),
                body="\n".join(body),
                priority=1 if needs_robert else 2,
            )
        )
        if needs_robert:
            events.append(
                attention_event(
                    "deadlines",
                    title,
                    body="\n".join(body),
                    xid=xid,
                    data={"window": window, "days": days},
                )
            )
    if stale:
        beads.append(overdue_digest(stale, ctx.today))
    return beads, [], events, counts


def overdue_digest(stale: list[Deadline], today: date) -> DesiredBead:
    """One bead a week for the deadlines nobody moved: prune or reschedule them."""
    xid = digest_xid(today)
    lines = [
        f"- {d.when.isoformat()} ({(today - d.when).days} days): {d.text} ({d.locator})"
        for d in sorted(stale, key=lambda d: d.when)
    ]
    body = [
        f"{len(stale)} deadline(s) in deadlines.md are more than {STALE_OVERDUE_DAYS} days "
        "overdue. Mark each done, move its date, or delete the line; the individual "
        "findings are closed and this digest is refiled weekly while any remain.",
        "",
        *lines,
    ]
    return DesiredBead(
        xid=xid,
        title=f"Overdue deadlines to prune or reschedule: {len(stale)} item(s) in deadlines.md",
        kind=WorkKind.finding,
        labels=["src:deadlines.md", "needs:robert", "window:stale"],
        header=BeadHeader(
            xid=xid,
            provenance=[prov(str(stale[0].path), "overdue items", today)],
        ),
        body="\n".join(body),
        priority=2,
    )


@dataclass
class DeadlinesPatrol:
    name: str = "deadlines"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=False)
        desired, notes, events, counts = derive(ctx)
        report = PatrolReport(self.name, today, dry_run)
        report.findings = [*desired, *notes]
        report.events = events
        report.warnings = list(ctx.warnings)
        report.data["windows"] = counts
        open_beads = [b for b in desired if not b.closed]
        report.summary = (
            f"{len(open_beads)} deadline warning(s) ("
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            + ")"
            if open_beads
            else "no deadline within 30 days"
        )
        if not ctx.deadlines:
            report.warnings.append(f"no deadlines read from {ctx.dirs['pa'] / 'deadlines.md'}")
        return report


register(DeadlinesPatrol, "deadlines")
