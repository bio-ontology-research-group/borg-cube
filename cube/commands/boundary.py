"""Restricted role tools; this command never evaluates arbitrary code."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

from cube.commands import Helpers
from cube.config import Settings


def run(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from cube import boundary, sysops
    from cube.agents.liaison import request_paths
    from cube.decisions import ask
    from cube.disclosure import release_text

    role = os.environ.get("CUBE_ROLE", "")
    op = args.operation
    allowed = {
        "liaison": {"ls", "head", "grep", "mail-search", "mail-show", "request"},
        "sysadmin": {"inspect", "propose", "request"},
    }
    if role not in allowed or op not in allowed[role]:
        print("boundary: operation not granted to this role", file=sys.stderr)
        return 2
    try:
        if op == "request" and release_text(args.value, personal_source=True) != args.value:
            raise ValueError("permission requests must not contain private data or credentials")
        if op in {"ls", "head", "grep"}:
            data = boundary.lookup(
                settings, op, args.value, pattern=args.pattern, beads=helpers.beads(settings, True)
            )
        elif op.startswith("mail-"):
            data = boundary.mail(settings, op.removeprefix("mail-"), args.value)
        elif op == "inspect":
            data = sysops.inspect_host(settings, args.value, args.check)
        elif op == "propose":
            data = sysops.propose(settings, json.loads(args.value), dry_run=args.dry_run)
        elif role == "liaison" and request_paths(args.value):
            data = boundary.request_access(
                settings, helpers.beads(settings, args.dry_run), args.value, dry_run=args.dry_run
            )
        else:
            data = ask(
                settings,
                helpers.beads(settings, args.dry_run),
                sender=f"role:{role}",
                text=args.value,
                bead=os.environ.get("CUBE_BEAD"),
                critical="privacy" if role == "liaison" else "security",
                dry_run=args.dry_run,
            )
        safe = release_text(json.dumps(data, default=str), personal_source=role == "liaison")
        print(safe)
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"boundary: {exc}", file=sys.stderr)
        return 2


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("boundary", help="bounded liaison and sysadmin tools")
    parser.add_argument(
        "operation",
        choices=["ls", "head", "grep", "mail-search", "mail-show", "inspect", "propose", "request"],
    )
    parser.add_argument(
        "value", help="path, mail query, host, proposal JSON, or permission request"
    )
    parser.add_argument("--pattern", default="")
    parser.add_argument("--check", default="disk")
    helpers.add_dry(parser)
    helpers.add_json(parser)
    parser.set_defaults(fn=lambda a, s: run(a, s, helpers))
