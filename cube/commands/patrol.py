"""`cube patrol [--all | name ...] [--apply]`: run deterministic sentinel patrols.

Default is a dry-run (nothing written anywhere); ``--apply`` reconciles finding beads
through ``cube.sync.reconcile``, appends attention events and saves cursors. Useful
names: ``milestones deadlines papers repos calendar student_digest data_pull
infra_hygiene leases``; ``mattermost_events`` is fed by ``cube event`` instead.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, today_from
from cube.config import Settings
from cube.patrols import base

# Event-fed patrols only run when their event arrives; leases is internal to the engine.
DEFAULT_SKIP = {"mattermost_events"}


def cmd_patrol(
    args: argparse.Namespace,
    settings: Settings,
    helpers: Helpers,
    *,
    payloads: list[dict[str, Any]] | None = None,
) -> int:
    today = today_from(args) or date.today()
    all_names = base.names()
    if args.all:
        chosen = list(all_names)
    elif args.names:
        unknown = [n for n in args.names if base.normalise(n) not in all_names]
        if unknown:
            print(
                f"unknown patrol(s): {', '.join(unknown)}; known: {', '.join(all_names)}",
                file=sys.stderr,
            )
            return 2
        chosen = [base.normalise(n) for n in args.names]
    else:
        chosen = [n for n in all_names if n not in DEFAULT_SKIP]
    options: dict[str, dict[str, Any]] = {}
    if payloads is not None:
        options["mattermost_events"] = {"payloads": payloads}
    reports = base.run_many(
        settings,
        chosen,
        today=today,
        dry_run=not args.apply,
        beads=helpers.beads(settings, not args.apply),
        options=options,
    )
    data: dict[str, Any] = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "applied": bool(args.apply),
        "patrols": [r.as_dict() for r in reports],
    }
    text = "\n".join(r.text() for r in reports) or "no patrols selected"
    helpers.emit(args, data, text)
    return 0 if all(not r.paused and not r.failed for r in reports) else 1


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("patrol", help="run deterministic patrols (dry-run unless --apply)")
    sp.add_argument("names", nargs="*", help="patrol name(s); default: every timer patrol")
    sp.add_argument("--all", action="store_true", help="every registered patrol")
    sp.add_argument(
        "--apply", action="store_true", help="write beads/events/cursors (default: dry-run)"
    )
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_patrol(a, s, helpers))
