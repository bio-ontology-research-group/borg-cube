"""`cube conflicts --json`: source disagreements (people.yaml list + rule vs estimate)."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.commands._common import Ledger, add_today, context, now_iso
from cube.config import Settings
from cube.sync.derivers import derive_conflicts, derive_programs

_helpers: Helpers | None = None


def cmd_conflicts(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args)
    ledger = Ledger(_helpers.beads(settings, True))
    rows: list[dict[str, Any]] = []
    for b in derive_conflicts(ctx) + [
        d for d in derive_programs(ctx) if d.kind.value == "conflict"
    ]:
        rows.append(
            {
                "xid": b.xid,
                "bead": ledger.id_for(b.xid),
                "title": b.title,
                "person": next(
                    (lab.split(":", 1)[1] for lab in b.labels if lab.startswith("person:")), None
                ),
                "detail": b.body,
                "provenance": [
                    p.model_dump(mode="json", exclude_none=True) for p in b.header.provenance
                ],
            }
        )
    payload = {"generated": now_iso(), "conflicts": rows, "warnings": ctx.warnings}
    _helpers.emit(
        args, payload, "\n".join(f"{r['xid']:50} {r['title']}" for r in rows) or "no conflicts"
    )
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("conflicts", help="source disagreements that need Robert")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_conflicts)
