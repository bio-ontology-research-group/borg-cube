"""`cube student <slug> --json`: one student's dossier from artefacts Robert already has."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from cube.commands import Helpers
from cube.commands._common import Ledger, add_today, context, now_iso
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.milestones.kaust_rules import next_open
from cube.sync.derivers import milestones_for

_helpers: Helpers | None = None


def cmd_student(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args)
    p = ctx.index.get(args.slug) or ctx.index.by_first_name(args.slug)
    if p is None:
        print(f"no such person in people.yaml: {args.slug}", file=sys.stderr)
        return 2
    ledger = Ledger(_helpers.beads(settings, True))
    policy = ContactPolicy(settings.root / "contacts.yaml")
    milestones = milestones_for(ctx, p)
    notes = ctx.person_notes(p)
    staff = ctx.staff_entry(p)
    contact = ctx.contact_for(p)
    refs = {p.id} | ({contact.slug} if contact else set())
    kg_hits = []
    for pr in ctx.kg_projects:
        hit = next((m for m in pr.members if m.ref in refs), None)
        if hit is None:
            continue
        kg_hits.append(
            {
                "slug": pr.slug,
                "name": pr.name,
                "status": pr.status,
                "status_as_of": pr.status_as_of.isoformat() if pr.status_as_of else None,
                "role": hit.role,
            }
        )
    deadlines = [
        {
            "date": d.when.isoformat(),
            "text": d.text,
            "status": d.status,
            "id": d.pa_id,
            "line": d.line,
        }
        for d in ctx.deadlines
        if p in ctx.index.mentioned_in(d.text)
    ]
    papers = [
        {
            "slug": pa.slug,
            "title": pa.title,
            "state": pa.state,
            "org_heading": f"papers.org::{pa.outline}",
        }
        for pa in ctx.papers
        if any(ctx.index.by_first_name(n) is p for n in pa.people)
    ]
    rkg_person = ctx.rkg.person(p.id)
    open_beads = ledger.open_with_label(f"person:{p.id}")
    nxt = next_open(milestones)
    final = next(
        (m for m in milestones if m.name in {"dissertation defense", "thesis defense"}), None
    )
    payload: dict[str, Any] = {
        "generated": now_iso(),
        "slug": p.id,
        "name": p.name,
        "role": p.cockpit_role,
        "org_file": f"~/org/{p.org_file}" if p.org_file else None,
        "program": {
            "bead": ledger.id_for(f"program:{p.id}"),
            "title": f"{'PhD' if p.cockpit_role == 'phd' else 'MS'} program: {p.name}",
            "name": p.program,
            "started": p.start.isoformat() if p.start else None,
            "expected_end": final.due.isoformat() if final and final.due else None,
            "source": p.source,
        },
        "milestones": [
            {
                "bead": ledger.id_for(f"milestone:{p.id}:{m.slug}"),
                "name": m.name,
                "due": m.due.isoformat() if m.due else None,
                "state": "done" if m.status == "done" else "open",
                "status": m.status,
                "days": m.days(ctx.today),
                "artefact": None,
                "rule": m.rule,
                "estimate": m.estimate.isoformat() if m.estimate else None,
                "notes": m.notes,
            }
            for m in milestones
        ],
        "next_milestone": {
            "name": nxt.name,
            "due": nxt.due.isoformat() if nxt.due else None,
            "days": nxt.days(ctx.today),
        }
        if nxt
        else None,
        "evidence": {
            "commits_7d": None,
            "repos": [],
            "drafts": [],
            "org_notes_last": notes.last_meeting.isoformat()
            if notes and notes.last_meeting
            else None,
            "org_open_checkboxes": notes.open_checkboxes if notes else None,
            "org_recent_headings": [
                {"date": h.when.isoformat(), "title": h.title, "line": h.line}
                for h in notes.recent(8)
            ]
            if notes
            else [],
            "org_todo_headings": notes.todo_headings[:10] if notes else [],
            "checkins": [],
        },
        "staff_org": {"section": staff.section, "bullets": staff.bullets, "line": staff.line}
        if staff
        else None,
        "kg_projects": kg_hits,
        "deadlines": deadlines,
        "papers": papers,
        "research_kg": (
            {
                "position": rkg_person.position,
                "program": rkg_person.program,
                "start_year": rkg_person.start_year,
                "end_year": rkg_person.end_year,
                "thesis_defense_date": rkg_person.thesis_defense_date.isoformat()
                if rkg_person.thesis_defense_date
                else None,
            }
            if rkg_person
            else None
        ),
        "contact": {
            "mattermost_dm": policy.check(p.id, "mattermost_dm", "*", ctx.today).allowed,
            "email": policy.check(p.id, "email", "*", ctx.today).allowed,
            "dossier_read": policy.check(p.id, "dossier_read", "*", ctx.today).allowed,
        },
        "agenda_draft": [],
        "beads": [str(b.get("id")) for b in open_beads if b.get("id")],
        "advisor_run": None,
        "concerns": [n for m in milestones for n in m.notes if "later than" in n],
        "warnings": ctx.warnings,
    }
    lines = [f"{p.name} ({p.id}) {p.program or ''} start {p.start or '?'}"]
    for m in milestones:
        lines.append(
            f"  {m.status:9} {str(m.due or '-'):10} {m.name}"
            + (f"  [{m.estimate_source}]" if m.estimate_source else "")
        )
    lines.append(
        f"  last org note: {payload['evidence']['org_notes_last'] or '-'}; "
        f"kg projects: {len(kg_hits)}; deadlines: {len(deadlines)}; papers: {len(papers)}"
    )
    _helpers.emit(args, payload, "\n".join(lines))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("student", help="one student's dossier")
    sp.add_argument("slug")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_student)
