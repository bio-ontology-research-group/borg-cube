"""Per-student context for the Hermes advisor pre-prompt hook (ADR-0003, ADR-0009).

The JSON holds only what a granted student may see: their own milestone plan (dates and
rules, no risk status, no staff.org estimates or Robert's notes), their own check-in
history, provenanced ``visible:student`` beads and the transparency flag. Anything
local-only and any line matching the grades/HR filter is dropped before rendering.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from yaml import YAMLError

from cube.commands._common import Ledger, now_iso
from cube.contact import ContactPolicy
from cube.engine.context import bead_labels, bead_privacy, privacy_filter
from cube.milestones.kaust_rules import next_open
from cube.model import BeadHeader, Privacy
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import milestones_for
from cube.sync.reconcile import bead_status

BOUNDARIES = (
    "The bot answers only about your own milestone plan and your own earlier check-ins.",
    "It never gives assessments, risk scores, Robert's notes or anything about other students.",
    "It tells you when it will summarise something for Robert; the summary quotes what you said.",
)


def is_granted(policy: ContactPolicy, person: Person, today: date) -> bool:
    return person.id in policy.allowed_users("mattermost_dm", today)


def context_filename(person: Person) -> str:
    return f"{person.mattermost or person.id}.json"


def _clean(text: str) -> str | None:
    """Apply the keyword filter only as a secondary signal after privacy classification."""
    filtered, hits = privacy_filter(text)
    return None if hits else filtered


def _content_privacy(bead: dict[str, Any], labels: list[str]) -> Privacy:
    try:
        header = BeadHeader.parse(str(bead.get("description") or ""))
    except (ValueError, TypeError, YAMLError):
        header = None
    # Enforces CLAUDE.md's "provenance or nothing" and privacy-class rules: a fact with no
    # traceable source cannot be classified safely, so it defaults to local-only.
    if header is None or not header.provenance:
        return Privacy.local_only
    if "privacy:local-only" in labels:
        return Privacy.local_only
    return bead_privacy(bead, labels)


def render_context(
    ctx: SourceContext, person: Person, ledger: Ledger, policy: ContactPolicy
) -> dict[str, Any]:
    today = ctx.today
    milestones = milestones_for(ctx, person)
    plan = [
        {
            "name": m.name,
            "due": m.due.isoformat() if m.due else None,
            "state": "done" if m.status == "done" else "open",
            "rule": m.rule if m.source == "kaust_rules" else "planned date",
        }
        for m in milestones
    ]
    nxt = next_open(milestones)
    person_label = f"person:{person.id}"
    checkins: list[dict[str, Any]] = []
    visible: list[dict[str, Any]] = []
    for bead in ledger.beads:
        labels = bead_labels(bead)
        if person_label not in labels or _content_privacy(bead, labels) == Privacy.local_only:
            continue
        title = _clean(str(bead.get("title") or ""))
        if title is None:
            continue
        if "kind:mentoring" in labels and "src:mattermost" in labels:
            checkins.append(
                {
                    "id": bead.get("id"),
                    "date": str(bead.get("created_at") or bead.get("created") or "")[:10] or None,
                    "status": bead_status(bead),
                }
            )
        if "visible:student" in labels and bead_status(bead) not in {"closed", "done"}:
            visible.append(
                {
                    "id": bead.get("id"),
                    "title": title,
                    "due": bead.get("due") or bead.get("deadline"),
                }
            )
    checkins.sort(key=lambda c: str(c.get("date") or ""), reverse=True)
    grant = policy.grants.get(person.id, {}).get("mattermost_dm") or {}
    return {
        "generated": now_iso(),
        "today": today.isoformat(),
        "student": {
            "id": person.id,
            "name": person.name,
            "program": person.program,
            "start": person.start.isoformat() if person.start else None,
        },
        "milestones": plan,
        "next_milestone": (
            {"name": nxt.name, "due": nxt.due.isoformat() if nxt.due else None}
            if nxt and nxt.due
            else None
        ),
        "checkins": checkins[:12],
        "last_checkin": checkins[0]["date"] if checkins else None,
        "visible_beads": visible,
        "transparency": {
            "granted": is_granted(policy, person, today),
            "granted_on": grant.get("granted"),
            "scope": list(grant.get("scope") or []),
            "expires": grant.get("expires"),
            "note_sent_by": "robert",
            "boundaries": list(BOUNDARIES),
        },
    }


def write_context(payload: dict[str, Any], out_dir: Path, filename: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
