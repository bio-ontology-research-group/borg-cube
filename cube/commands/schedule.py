"""Preview or execute one dependency-ready agent allocation."""

from typing import Any

from cube.scheduler import tick


def register(sub: Any, helpers: Any) -> None:
    parser = sub.add_parser("schedule", help=__doc__)
    helpers.add_json(parser)
    helpers.add_dry(parser)

    def run(args: Any, settings: Any) -> int:
        result = tick(settings, helpers.beads(settings, args.dry_run), dry_run=args.dry_run)
        helpers.emit(args, result, None)
        return 0

    parser.set_defaults(fn=run)
