"""`cube drop BEAD FILE`: push one artifact to a peer's drop directory (ADR-0026)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.hosts import drop_file, drop_repository


def cmd_drop(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    target = args.host or next(
        (name for name, entry in settings.hosts.items() if entry.role == "orchestration"),
        settings.host,
    )
    if target not in settings.hosts:
        print(f"cube drop: unknown host {target!r}", file=sys.stderr)
        return 2
    beads = helpers.beads(settings, args.dry_run)
    path = Path(args.file).expanduser().resolve()
    if args.repo:
        result = drop_repository(
            settings, target, args.bead, path, beads=beads, dry_run=args.dry_run
        )
    else:
        result = drop_file(settings, target, args.bead, path, beads=beads, dry_run=args.dry_run)
    data = result.as_dict()
    data["dry_run"] = args.dry_run
    if result.delivered:
        text = f"dropped {result.source} at {target}:{result.remote_path} sha256 {result.sha256}"
    elif args.dry_run and result.remote_path:
        text = f"DRY-RUN would drop {result.source} at {target}:{result.remote_path}"
    else:
        text = f"cube drop: {result.error}"
    helpers.emit(args, data, text)
    return 0 if result.delivered or (args.dry_run and result.remote_path) else 1


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser(
        "drop", help="push one artifact file to a peer's drop directory and point the bead at it"
    )
    parser.add_argument("bead")
    parser.add_argument("file", help="a file, or with --repo a git checkout")
    parser.add_argument(
        "--repo",
        action="store_true",
        help="ship a git checkout: bundle of every ref, uncommitted patch, manifest",
    )
    parser.add_argument("--host", help="receiving host (default: the orchestration host)")
    helpers.add_json(parser)
    helpers.add_dry(parser)
    parser.set_defaults(fn=lambda a, s: cmd_drop(a, s, helpers))
