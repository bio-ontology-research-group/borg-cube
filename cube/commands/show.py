"""Detail views for the cockpit: `cube runs show`, `cube approvals show`, `cube beads show`.

Shapes follow emacs/INTERFACE.md (fixtures run-show.json, approval-show.json, bead-show.json).
Implemented as top-level commands `run-show`, `approval-show`, `bead-show` plus aliases so
`cube runs show <id>` and friends work without touching the other command modules.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cube.approvals import ApprovalError, ApprovalStore
from cube.commands import Helpers
from cube.config import Settings
from cube.engine.run import list_runs

TAIL_LINES = 20


def _read(path: Path, limit: int | None = None) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if limit is None else text[:limit]


def run_show(settings: Settings, run_id: str) -> dict[str, Any] | None:
    for meta in list_runs(settings, limit=10_000):
        if str(meta.get("run_id")) != run_id:
            continue
        run_dir = Path(str(meta.get("path")))
        notes_file = next(
            (p for p in (run_dir / "notes.md", run_dir / "result.md") if p.exists()), None
        )
        log_file = next(
            (
                p
                for p in (run_dir / "stdout.jsonl", run_dir / "stdout.txt", run_dir / "log.jsonl")
                if p.exists()
            ),
            None,
        )
        result = _read(run_dir / "result.json")
        summary = meta.get("summary")
        if not summary and result:
            try:
                summary = json.loads(result).get("summary")
            except (json.JSONDecodeError, AttributeError):
                summary = None
        log_tail: list[str] = []
        if log_file is not None:
            text = _read(log_file) or ""
            log_tail = text.splitlines()[-TAIL_LINES:]
        rel = (
            run_dir.relative_to(settings.root) if run_dir.is_relative_to(settings.root) else run_dir
        )
        out = dict(meta)
        out.update(
            {
                "log": str(rel / log_file.name) if log_file else None,
                "notes_file": str(rel / notes_file.name) if notes_file else None,
                "notes": _read(notes_file) if notes_file else None,
                "summary": summary,
                "log_tail": log_tail,
                "prompt": _read(run_dir / "prompt.md", 4000),
            }
        )
        return out
    return None


def approval_show(settings: Settings, approval_id: str) -> dict[str, Any] | None:
    store = ApprovalStore(settings.state_dir())
    try:
        ap = store.get(approval_id)
    except ApprovalError:
        return None
    data = ap.cockpit()
    body = None
    for candidate in (ap.body_file, ap.diff_file):
        if candidate:
            p = Path(candidate)
            if not p.is_absolute():
                p = settings.root / p
            body = _read(p)
            if body is not None:
                break
    data.update(
        {"body": body, "to": ap.to, "subject": ap.subject, "actions": ["approve", "reject", "edit"]}
    )
    return data


def bead_show(settings: Settings, bead_id: str, helpers: Helpers) -> dict[str, Any] | None:
    beads = helpers.beads(settings, True)
    if not beads.available():
        return None
    data = beads.show(bead_id)
    return data or None


def _emit_or_missing(
    args: argparse.Namespace, helpers: Helpers, data: dict[str, Any] | None, what: str
) -> int:
    if data is None:
        helpers.emit(
            args, {"error": f"{what} not found", "id": args.id}, f"{what} {args.id} not found"
        )
        return 3
    helpers.emit(args, data, json.dumps(data, indent=1, default=str))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("run-show", help="details of one run (INTERFACE.md run-show)")
    sp.add_argument("id")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: _emit_or_missing(a, helpers, run_show(s, a.id), "run"))

    sp = sub.add_parser("approval-show", help="details of one approval, with body")
    sp.add_argument("id")
    helpers.add_json(sp)
    sp.set_defaults(
        fn=lambda a, s: _emit_or_missing(a, helpers, approval_show(s, a.id), "approval")
    )

    sp = sub.add_parser("bead-show", help="one bead as JSON (bd show)")
    sp.add_argument("id")
    helpers.add_json(sp)
    sp.set_defaults(
        fn=lambda a, s: _emit_or_missing(a, helpers, bead_show(s, a.id, helpers), "bead")
    )

    # `cube beads show ID` is the spelling the cockpit uses; same payload as bead-show.
    beads = sub.add_parser("beads", help="bead queries (beads show ID)")
    beads_sub = beads.add_subparsers(dest="beads_cmd", required=True)
    sp = beads_sub.add_parser("show", help="one bead as JSON (alias of bead-show)")
    sp.add_argument("id")
    helpers.add_json(sp)
    sp.set_defaults(
        fn=lambda a, s: _emit_or_missing(a, helpers, bead_show(s, a.id, helpers), "bead")
    )
