"""Private browser fleet explorer, hosted on ws and reached through SSH."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.config import Settings


def run(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from cube.explorer import Explorer
    from cube.explorer_http import ExplorerServer

    if not 1024 <= args.port <= 65535:
        raise ValueError("Explorer port must be between 1024 and 65535.")
    if args.dry_run:
        helpers.emit(
            args,
            {
                "dry_run": True,
                "bind": "127.0.0.1",
                "port": args.port,
                "host": settings.host,
                "root": str(settings.root),
            },
            None,
        )
        return 0
    server = ExplorerServer(Explorer(settings), args.port)
    print(f"BORG explorer: http://127.0.0.1:{args.port} (private; SSH tunnel required)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("explorer", help="private fleet activity, usage, memory and controls")
    parser.add_argument("--port", type=int, default=8765)
    helpers.add_dry(parser)
    helpers.add_json(parser)
    parser.set_defaults(fn=lambda a, s: run(a, s, helpers))
