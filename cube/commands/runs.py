"""`cube runs --json`: recent runs from runs/<date>/<run-id>/meta.json."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine.run import list_runs


def cmd_runs(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    runs = list_runs(settings, limit=args.limit)
    text = (
        "\n".join(
            f"{r.get('run_id')} {r.get('role')} {r.get('bead') or '-'} {r.get('runner')} "
            f"{r.get('state')} {r.get('started')}"
            for r in runs
        )
        or "no runs"
    )
    helpers.emit(args, {"runs": runs}, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("runs", help="recent runs")
    sp.add_argument("--limit", type=int, default=20)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_runs(a, s, helpers))
