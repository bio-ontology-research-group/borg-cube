"""`cube event mattermost --payload-file F | --stdin`: webhook intake, never a poll.

The Hermes Mattermost gateway (or any webhook relay) posts the event payload here;
borg-cube never reaches out to Mattermost on a schedule. The payload is ingested by
the ``mattermost_events`` patrol: granted DMs become check-in reply beads, everything
else becomes an unanswered-DM finding for Robert. Default is a dry-run; ``--apply``
writes the inbox transcript, the beads and the attention events.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today
from cube.commands.patrol import cmd_patrol
from cube.config import Settings


def cmd_event(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    payloads: list[dict[str, Any]] = []
    for path in args.payload_file or ():
        payloads.append(json.loads(Path(path).read_text(encoding="utf-8")))
    if args.stdin:
        raw = sys.stdin.read()
        if raw.strip():
            payloads.append(json.loads(raw))
    if not payloads:
        print("no payloads given (use --payload-file or --stdin)", file=sys.stderr)
        return 2
    args.names = ["mattermost_events"]
    args.all = False
    return cmd_patrol(
        args,
        settings,
        helpers,
        payloads=payloads,
    )


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("event", help="ingest a webhook event payload (default: dry-run)")
    sp.add_argument("kind", choices=["mattermost"], help="event source")
    sp.add_argument("--payload-file", action="append", help="JSON payload file (repeatable)")
    sp.add_argument("--stdin", action="store_true", help="read one JSON payload from stdin")
    sp.add_argument("--apply", action="store_true", help="write inbox/beads (default: dry-run)")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_event(a, s, helpers))
