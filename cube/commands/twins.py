"""Create the per-student research agents without copying their dossiers."""

from __future__ import annotations

from typing import Any

from cube.commands import Helpers
from cube.student.twins import push_sources, sync_twins


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("twins", help="student research counterparts")
    actions = parser.add_subparsers(dest="twins_cmd", required=True)
    sync = actions.add_parser("sync", help="derive private local research agents from the roster")
    helpers.add_json(sync)
    helpers.add_dry(sync)

    def run(args: Any, settings: Any) -> int:
        result = sync_twins(settings, dry_run=args.dry_run)
        helpers.emit(
            args, result, f"{result['members']} research twins; {len(result['created'])} new agents"
        )
        return 0

    sync.set_defaults(fn=run)
    push = actions.add_parser(
        "push-sources", help="push current students' curated liaison bundles to ws"
    )
    push.add_argument("--bead", required=True)
    helpers.add_json(push)
    helpers.add_dry(push)

    def push_run(args: Any, settings: Any) -> int:
        result = push_sources(
            settings, helpers.beads(settings, args.dry_run), args.bead, dry_run=args.dry_run
        )
        helpers.emit(args, result, f"{len(result['bundles'])} local-only source bundles")
        return 0

    push.set_defaults(fn=push_run)
