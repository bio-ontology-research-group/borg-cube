"""`cube ready --json`: the unblocked Beads work available to the cockpit."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.config import Settings


def cmd_ready(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """Return the ready Beads in the stable cockpit envelope."""
    beads = helpers.beads(settings, True)
    try:
        items = beads.ready() if beads.available() else []
    except Exception as exc:  # noqa: BLE001 - the read-only dashboard must stay usable
        items = []
        detail = f"bd ready unavailable: {exc}"
    else:
        detail = "no ready beads" if not items else f"{len(items)} ready bead(s)"
    helpers.emit(args, {"beads": items}, detail)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    """Register the top-level read-only ready listing."""
    parser = sub.add_parser("ready", help="ready unblocked Beads work")
    helpers.add_json(parser)
    parser.set_defaults(fn=lambda args, settings: cmd_ready(args, settings, helpers))
