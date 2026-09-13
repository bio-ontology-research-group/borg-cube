"""Calendar patrol: tomorrow's meetings with group members -> meeting-note prep beads.

Reuses ``derive_meetings`` (one ``kind:meeting-note`` bead per person and day, marshalled
to the scribe) and adds the attendee dossier pointer so the prep brief starts from the
right artefacts (``cube student <slug>``, the org file, the latest student digest).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from cube.beads import Beads
from cube.config import Settings
from cube.patrols.base import PatrolReport, register
from cube.sync.context import SourceContext
from cube.sync.derivers import DesiredBead, derive_meetings


def dossier_pointer(ctx: SourceContext, slug: str, briefings: str) -> str:
    p = ctx.index.get(slug)
    lines = [f"Dossier: cube student {slug} --json"]
    if p and p.org_file:
        lines.append(f"Notes: ~/org/{p.org_file}")
    if p and p.is_student:
        lines.append(f"Latest digest: {briefings}/students/*-{slug}.md (Robert-only)")
        notes = ctx.person_notes(p)
        if notes and notes.last_meeting:
            lines.append(
                f"Last dated org heading: {notes.last_meeting.isoformat()}; "
                f"open checkboxes: {notes.open_checkboxes}"
            )
    c = ctx.contact_for(p) if p else None
    if c:
        lines.append(f"Contact card: {c.path}")
    return "\n".join(lines)


def derive(ctx: SourceContext, briefings: str = "briefings") -> list[DesiredBead]:
    out: list[DesiredBead] = []
    for bead in derive_meetings(ctx):
        slug = next((lab.split(":", 1)[1] for lab in bead.labels if lab.startswith("person:")), "")
        body = bead.body + "\n\n" + dossier_pointer(ctx, slug, briefings) if slug else bead.body
        out.append(bead.model_copy(update={"body": body, "labels": [*bead.labels, "prep"]}))
    return out


@dataclass
class CalendarPatrol:
    name: str = "calendar"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=False)
        desired = derive(ctx, briefings=str(settings.root / "briefings"))
        report = PatrolReport(self.name, today, dry_run)
        report.findings = list(desired)
        report.warnings = list(ctx.warnings)
        tomorrow = (today + timedelta(days=1)).isoformat()
        report.summary = (
            f"{len(desired)} meeting(s) with group members on {tomorrow}"
            if desired
            else f"no meetings with group members on {tomorrow}"
        )
        if not ctx.calendar:
            report.warnings.append(f"no *.cal or *.ics files under {ctx.dirs['org']}")
        return report


register(CalendarPatrol, "calendar")
