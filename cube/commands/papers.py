"""`cube papers --json`: papers.org state plus papers referenced by pa KG projects."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.commands._common import Ledger, add_today, context, now_iso
from cube.config import Settings

_helpers: Helpers | None = None


def cmd_papers(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args)
    ledger = Ledger(_helpers.beads(settings, True))
    rows: list[dict[str, Any]] = []
    for pa in ctx.papers:
        if args.open and (pa.state or "") in {"PUBLISHED", "CANCELED"}:
            continue
        leads = [ctx.index.by_first_name(n) for n in pa.people]
        lead = next((p.id for p in leads if p), pa.people[0] if pa.people else None)
        rows.append(
            {
                "id": ledger.id_for(f"paper:{pa.slug}"),
                "slug": pa.slug,
                "title": pa.title,
                "state": pa.state,
                "venue": _venue(pa.bullets),
                "deadline": None,
                "deadline_text": pa.deadline_text,
                "lead": lead,
                "people": pa.people,
                "path": None,
                "org_heading": f"papers.org::{pa.outline}",
                "line": pa.line,
                "last_activity": pa.closed.isoformat() if pa.closed else None,
                "review_bead": None,
                "parent": pa.parent_slug,
                "source": "papers.org",
            }
        )
    kg_papers: list[dict[str, Any]] = []
    for proj in ctx.kg_projects:
        for ref in proj.papers:
            kg_papers.append({"project": proj.slug, "paper": ref, "source": str(proj.path)})
    payload = {
        "generated": now_iso(),
        "papers": rows,
        "kg_papers": kg_papers,
        "warnings": ctx.warnings,
    }
    lines = [f"{(r['state'] or '-'):16} {r['slug']:45} {', '.join(r['people'])}" for r in rows]
    _helpers.emit(args, payload, "\n".join(lines))
    return 0


def _venue(bullets: list[str]) -> str | None:
    for b in bullets:
        low = b.lower()
        if low.startswith(("submit to", "submitted to", "for the", "send to")):
            return b.split(" to ", 1)[-1].rstrip("?") if " to " in b else b
        if "at " in low and ("rejected" in low or "revisions" in low):
            return b.split(" at ", 1)[-1]
    return None


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("papers", help="papers.org state and pa KG paper references")
    sp.add_argument("--open", action="store_true", help="hide PUBLISHED and CANCELED")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_papers)
