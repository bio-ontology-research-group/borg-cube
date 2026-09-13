"""`cube attention --json`: pending approvals, needs:robert, blocked, dead leases, errors.

`cube attention ack ID [--reason TEXT] [--apply]` dismisses one item (an error
event that is already handled, for instance); the id is the `att-...` value.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine.attention import acknowledge, build_attention


def cmd_attention(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, True)
    items = build_attention(settings, beads)
    data = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "items": items}
    text = "\n".join(f"[{i['severity']:6}] {i['kind']:12} {i['title']}" for i in items) or (
        "nothing needs attention"
    )
    helpers.emit(args, data, text)
    return 0


def cmd_ack(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, True)
    items = {item["id"]: item for item in build_attention(settings, beads)}
    item = items.get(args.id)
    if item is None:
        print(f"cube attention ack: no attention item {args.id!r}", file=sys.stderr)
        return 2
    record = (
        acknowledge(settings.state_dir(), args.id, reason=args.reason or "")
        if not args.dry_run
        else {"ts": None, "reason": args.reason or ""}
    )
    data = {"id": args.id, "dry_run": args.dry_run, "title": item["title"], "ack": record}
    helpers.emit(
        args,
        data,
        f"{'DRY-RUN ' if args.dry_run else ''}acknowledged {args.id}: {item['title']}",
    )
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("attention", help="what Robert should look at, loudest first")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_attention(a, s, helpers))
    commands = sp.add_subparsers(dest="attention_cmd")
    ack = commands.add_parser("ack", help="dismiss one attention item by id")
    ack.add_argument("id")
    ack.add_argument("--reason", help="why it needs no further attention")
    helpers.add_json(ack)
    helpers.add_dry(ack)
    ack.set_defaults(fn=lambda a, s: cmd_ack(a, s, helpers))
