"""`cube org`: lock-aware edits to the external Org workspace through cube.orgwrite."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.commands._common import people_records
from cube.config import Settings
from cube.orgwrite import OrgWriteError, append_dated, set_property, status, toggle_todo

_helpers: Helpers | None = None


def _target(settings: Settings, value: str, *, person_only: bool = False) -> Path:
    people = people_records(settings.root / "people.yaml")
    if value in people:
        org_file = people[value].get("org_file")
        if not org_file:
            raise OrgWriteError(f"{value} has no org_file in people.yaml")
        return settings.dirs["org"] / str(org_file)
    if person_only:
        raise OrgWriteError(f"no such person in people.yaml: {value}")
    supplied = Path(value).expanduser()
    return supplied if supplied.is_absolute() else settings.dirs["org"] / supplied


def _emit_write(args: argparse.Namespace, result: Any) -> int:
    assert _helpers is not None
    payload = result.as_dict()
    text = payload["diff"] or f"org-write: {payload['action']} made no change"
    _helpers.emit(args, payload, text)
    return 0


def cmd_org(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.org_cmd == "append":
            day = date.fromisoformat(args.date) if args.date else date.today()
            body = ""
            if args.body:
                body = (
                    sys.stdin.read()
                    if args.body == "-"
                    else Path(args.body).read_text(encoding="utf-8")
                )
            return _emit_write(
                args,
                append_dated(
                    _target(settings, args.person_or_file),
                    settings.dirs["org"],
                    heading=args.heading,
                    day=day,
                    items=args.item,
                    body=body,
                    apply=not args.dry_run,
                    state_dir=settings.state_dir(),
                ),
            )
        if args.org_cmd == "todo":
            return _emit_write(
                args,
                toggle_todo(
                    _target(settings, args.file),
                    settings.dirs["org"],
                    heading_match=args.heading_match,
                    item=args.item,
                    done=True if args.done else None,
                    apply=not args.dry_run,
                    state_dir=settings.state_dir(),
                ),
            )
        if args.org_cmd == "property":
            key, separator, value = args.set.partition("=")
            if not separator or not key or not value:
                raise OrgWriteError("--set must be KEY=VALUE")
            return _emit_write(
                args,
                set_property(
                    _target(settings, args.file),
                    settings.dirs["org"],
                    heading_match=args.heading_match,
                    key=key,
                    value=value,
                    apply=not args.dry_run,
                    state_dir=settings.state_dir(),
                ),
            )
        if args.org_cmd == "status":
            payload = status(_target(settings, args.person, person_only=True), settings.dirs["org"])
            payload.update({"diff": "", "applied": False})
            assert _helpers is not None
            _helpers.emit(args, payload, None)
            return 0
    except (OrgWriteError, OSError, ValueError) as exc:
        print(f"cube org: {exc}", file=sys.stderr)
        return 2
    return 2


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("org", help="safe, lock-aware external Org edits")
    org_sub = sp.add_subparsers(dest="org_cmd", required=True)

    append = org_sub.add_parser("append", help="append a dated heading newest first")
    append.add_argument("person_or_file")
    append.add_argument("--heading", required=True)
    append.add_argument("--date")
    append.add_argument("--item", action="append", default=[])
    append.add_argument("--body", help="body file, or - for stdin")
    helpers.add_json(append)
    helpers.add_dry(append)

    todo = org_sub.add_parser("todo", help="toggle one checkbox below an unambiguous heading")
    todo.add_argument("file")
    todo.add_argument("--heading-match", required=True)
    todo.add_argument("--item", required=True)
    todo.add_argument("--done", action="store_true", help="set done rather than toggle")
    helpers.add_json(todo)
    helpers.add_dry(todo)

    prop = org_sub.add_parser("property", help="set one property on an unambiguous heading")
    prop.add_argument("file")
    prop.add_argument("--heading-match", required=True)
    prop.add_argument("--set", required=True)
    helpers.add_json(prop)
    helpers.add_dry(prop)

    stat = org_sub.add_parser("status", help="read one person's Org status")
    stat.add_argument("--person", required=True)
    helpers.add_json(stat)

    sp.set_defaults(fn=cmd_org)
