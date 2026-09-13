"""Milestones patrol: 180/90/30-day warnings and overdue KAUST milestones -> finding beads.

One finding bead per (student, milestone) with the current window as a label; at-risk
(30 days) and overdue findings carry ``needs:robert`` and raise an attention event.
Done milestones close their finding. Playbook: brain/playbooks/milestone-risk.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.milestones import kaust_rules as kr
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, attention_event, prov, register
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import DesiredBead, milestones_for

WINDOWS: tuple[tuple[int, str, int], ...] = ((30, "30d", 1), (90, "90d", 2), (180, "180d", 3))
CHECKLIST_30 = (
    "committee confirmed (3 members for the proposal, 4 including an external for the defense)",
    "room and form status",
    "document to the committee (dissertation 6 weeks before the defense)",
)
NEEDS_ROBERT_WINDOWS = {"overdue", "30d"}


def window_for(days: int) -> str | None:
    if days < 0:
        return "overdue"
    for limit, label, _ in WINDOWS:
        if days <= limit:
            return label
    return None


def priority_for(window: str) -> int:
    for _, label, prio in WINDOWS:
        if label == window:
            return prio
    return 1


def finding_xid(person: Person, m: kr.Milestone) -> str:
    return f"finding:milestone:{person.id}:{m.slug}"


def _closed(person: Person, m: kr.Milestone, reason: str, today: date) -> DesiredBead:
    xid = finding_xid(person, m)
    return DesiredBead(
        xid=xid,
        title=f"Milestone warning: {m.name} for {person.name}",
        kind=WorkKind.finding,
        labels=[f"person:{person.id}", f"milestone:{m.slug}", "src:kaust_rules"],
        header=BeadHeader(xid=xid, provenance=[prov("cube.milestones.kaust_rules", m.rule, today)]),
        closed=True,
        close_reason=reason,
    )


def derive(
    ctx: SourceContext,
) -> tuple[list[DesiredBead], list[Finding], list[dict[str, Any]], dict[str, int]]:
    beads: list[DesiredBead] = []
    notes: list[Finding] = []
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    staff_path = str(ctx.dirs["org"] / "staff.org")
    for p in ctx.people:
        if not p.is_student:
            continue
        staff = ctx.staff_entry(p)
        for m in milestones_for(ctx, p):
            if m.status == "done":
                beads.append(_closed(p, m, f"milestone done on {m.done_on}", ctx.today))
                continue
            if m.status == "unknown" or m.due is None:
                if m.notes:
                    notes.append(
                        Finding(
                            key=f"milestone-verify:{p.id}:{m.slug}",
                            title=f"{p.name}: {m.name} outcome not recorded",
                            severity="warn",
                            detail="; ".join(m.notes),
                            source=staff.locator if staff else staff_path,
                        )
                    )
                continue
            days = m.days(ctx.today)
            if days is None:
                continue
            window = window_for(days)
            if window is None:
                beads.append(
                    _closed(p, m, f"{days} days away; outside the 180-day horizon", ctx.today)
                )
                continue
            counts[window] = counts.get(window, 0) + 1
            xid = finding_xid(p, m)
            needs_robert = window in NEEDS_ROBERT_WINDOWS
            when = (
                f"overdue by {-days} day(s)"
                if window == "overdue"
                else f"due in {days} day(s) on {m.due.isoformat()}"
            )
            body = [
                f"Milestone: {m.name} for {p.name} ({p.program})",
                f"Due: {m.due.isoformat()} ({when})",
                f"Rule: {m.rule}",
                f"Status: {m.status}",
            ]
            if m.estimate:
                body.append(f"staff.org estimate: {m.estimate.isoformat()} ({m.estimate_source})")
            body.extend(m.notes)
            if window in NEEDS_ROBERT_WINDOWS:
                body.append("Checklist (30 days):")
                body.extend(f"- [ ] {item}" for item in CHECKLIST_30)
            elif window == "90d":
                body.append(
                    "90 days: confirm an artefact exists (proposal draft, thesis chapter, "
                    "committee form); the secretary can prepare the forms on request."
                )
            body.append(
                "Robert decides what the student hears; never tell a student they are at risk."
            )
            provenance = [prov("cube.milestones.kaust_rules", m.rule, ctx.today)]
            if staff:
                provenance.append(prov(staff_path, staff.locator, ctx.today))
            labels = [
                f"person:{p.id}",
                f"milestone:{m.slug}",
                f"window:{window}",
                f"status:{m.status}",
                "src:kaust_rules",
                "src:staff.org",
            ]
            if needs_robert:
                labels.append("needs:robert")
            beads.append(
                DesiredBead(
                    xid=xid,
                    title=f"Milestone warning: {m.name} for {p.name} ({when})",
                    kind=WorkKind.finding,
                    labels=labels,
                    parent_xid=f"milestone:{p.id}:{m.slug}",
                    header=BeadHeader(xid=xid, provenance=provenance, deadline=m.due),
                    body="\n".join(body),
                    priority=priority_for(window),
                )
            )
            if needs_robert:
                events.append(
                    attention_event(
                        "milestones",
                        f"Milestone {window}: {m.name} for {p.name} ({when})",
                        body="\n".join(body),
                        xid=xid,
                        data={"person": p.id, "window": window, "days": days},
                    )
                )
    return beads, notes, events, counts


@dataclass
class MilestonesPatrol:
    name: str = "milestones"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=False)
        desired, notes, events, counts = derive(ctx)
        open_beads = [b for b in desired if not b.closed]
        report = PatrolReport(self.name, today, dry_run)
        report.findings = [*desired, *notes]
        report.events = events
        report.warnings = list(ctx.warnings)
        report.data["windows"] = counts
        report.summary = (
            f"{len(open_beads)} milestone warning(s) ("
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            + f"), {len(notes)} to verify"
            if open_beads or notes
            else "no milestone within 180 days"
        )
        return report


register(MilestonesPatrol, "milestones")
