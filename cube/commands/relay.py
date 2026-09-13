"""`cube relay HOST CUBE-ARGS...`: bounded immediate delivery between cube hosts."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.hosts import relay


def cmd_relay(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    cube_args = list(args.cube_args)
    if "--json" in cube_args:
        args.json = True
    if args.host not in settings.hosts:
        print(f"cube relay: unknown host {args.host!r}", file=sys.stderr)
        return 2
    if not cube_args:
        print("cube relay: a cube command is required", file=sys.stderr)
        return 2
    result = relay(settings, args.host, cube_args)
    data = result.as_dict()
    text = (
        f"relayed to {args.host}"
        if result.reachable
        else f"{args.host} unreachable; queued for next sync"
    )
    helpers.emit(args, data, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("relay", help="run a cube command on a configured peer over SSH")
    parser.add_argument("host")
    parser.add_argument("cube_args", nargs=argparse.REMAINDER)
    helpers.add_json(parser)
    parser.set_defaults(fn=lambda a, s: cmd_relay(a, s, helpers))
