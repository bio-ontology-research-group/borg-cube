"""`cube incidents --json`: open infrastructure incidents and the cockpit banner."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine.attention import incident_data


def cmd_incidents(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    data = incident_data(settings, helpers.beads(settings, True))
    banner = data["banner"]
    text = str(banner["text"]) if banner is not None else "no open incidents"
    helpers.emit(args, data, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("incidents", help="open infrastructure incidents and cockpit banner")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda args, settings: cmd_incidents(args, settings, helpers))
