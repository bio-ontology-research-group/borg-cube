"""`cube people --json`: roster with milestone status, last meeting, open bead count."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.commands._common import Ledger, add_today, context, now_iso
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.goals import people_work
from cube.milestones.kaust_rules import next_open
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import milestones_for

_helpers: Helpers | None = None


def person_row(
    ctx: SourceContext, p: Person, ledger: Ledger, policy: ContactPolicy
) -> dict[str, Any]:
    milestones = milestones_for(ctx, p) if p.is_student else []
    nxt = next_open(milestones)
    notes = ctx.person_notes(p)
    org_file = f"~/org/{p.org_file}" if p.org_file else None
    open_beads = ledger.open_with_label(f"person:{p.id}")
    goals, owed = people_work(ledger.beads, p.id)
    agenda = [
        f"Raise owed work: {item['title']} (due {item['due'] or 'not set'}; bead {item['bead']})."
        for item in owed
    ]
    if nxt:
        agenda.append(
            f"Review milestone: {nxt.name} (due "
            f"{nxt.due.isoformat() if nxt.due else 'not set'}; {nxt.status})."
        )
    return {
        "slug": p.id,
        "name": p.name,
        "role": p.cockpit_role,
        "org_file": org_file,
        "program": ledger.id_for(f"program:{p.id}"),
        "program_name": p.program,
        "start": p.start.isoformat() if p.start else None,
        "next_milestone": (
            {
                "name": nxt.name,
                "due": nxt.due.isoformat() if nxt.due else None,
                "days": nxt.days(ctx.today),
                "status": nxt.status,
            }
            if nxt
            else None
        ),
        "milestone_status": {m.name: m.status for m in milestones},
        "contact": {
            "mattermost_dm": policy.check(p.id, "mattermost_dm", "*", ctx.today).allowed,
            "email": policy.check(p.id, "email", "*", ctx.today).allowed,
            "dossier_read": policy.check(p.id, "dossier_read", "*", ctx.today).allowed,
        },
        "attention": len([b for b in open_beads if "needs:robert" in (b.get("labels") or [])]),
        "open_beads": len(open_beads),
        "last_meeting": notes.last_meeting.isoformat() if notes and notes.last_meeting else None,
        "open_checkboxes": notes.open_checkboxes if notes else None,
        "source": p.source,
        "goals": goals,
        "owed": owed,
        "next_meeting_agenda": agenda,
    }


def cmd_people(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args)
    ledger = Ledger(_helpers.beads(settings, True))
    policy = ContactPolicy(settings.root / "contacts.yaml")
    rows = [person_row(ctx, p, ledger, policy) for p in ctx.people]
    if args.students:
        rows = [r for r in rows if r["role"] in {"phd", "msc"}]
    payload = {
        "generated": now_iso(),
        "today": ctx.today.isoformat(),
        "people": rows,
        "warnings": ctx.warnings + ([ledger.warning] if ledger.warning else []),
    }
    lines = []
    for r in rows:
        nm = r["next_milestone"]
        nxt = f"{nm['name']} {nm['due']} ({nm['status']})" if nm else "-"
        lines.append(
            f"{r['slug']:28} {r['role']:8} {str(r['program_name'] or ''):11} "
            f"last meeting {r['last_meeting'] or '-':10} next: {nxt}"
        )
    _helpers.emit(args, payload, "\n".join(lines))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("people", help="group roster with milestone status")
    sp.add_argument("--students", action="store_true", help="only PhD and MS students")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_people)
