"""``cube roster`` source reconciliation and guarded people.yaml sync."""

from __future__ import annotations

import argparse
import difflib
import sys
from datetime import date
from typing import Any

from cube.commands import Helpers
from cube.commands._common import now_iso, today_from
from cube.config import Settings
from cube.roster import (
    build_roster,
    load_people_data,
    load_roster_policy,
    render_people_yaml,
    roster_summary,
)
from cube.sources.org import parse_group_roster
from cube.sources.rkg import load_graph, parse_roster
from cube.sources.website import BASE_URL, WebsiteSource

_helpers: Helpers | None = None


def _read_iso() -> str:
    return now_iso()


def roster_payload(
    settings: Settings, *, offline: bool = False, today: date | None = None
) -> tuple[dict[str, Any], list[Any]]:
    staff_path = settings.dirs["org"] / "staff.org"
    roster_path = settings.dirs["website"] / "people" / "roster.md"
    kg_path = settings.dirs["rkg"] / "projects.jsonld"
    people_path = settings.root / "people.yaml"
    staff = parse_group_roster(staff_path)
    website = WebsiteSource(settings.state_dir() / "website").roster(offline=offline)
    for error in website.errors:
        print(f"cube roster: {error}", file=sys.stderr)
    rows = build_roster(
        staff,
        website.profiles,
        parse_roster(roster_path),
        load_graph(kg_path),
        load_people_data(people_path),
        load_roster_policy(settings.root / "cube.yaml"),
    )
    payload = {
        "generated": now_iso(),
        "sources": {
            "staff_org": {
                "path": str(staff_path),
                "section": staff.section,
                "read": _read_iso(),
            },
            "website": {
                "url": f"{BASE_URL}/{{students,research-scientists,postdoctoral-fellows,"
                "research-staff,principal-investigators}",
                "fetched": website.fetched_at,
                "cached": website.cached,
            },
            "roster_md": {"path": str(roster_path)},
            "kg": {"path": str(kg_path)},
        },
        "authority": load_roster_policy(settings.root / "cube.yaml").authority,
        "people": [row.as_dict() for row in rows],
        "summary": roster_summary(rows),
    }
    return payload, rows


def roster_table(payload: dict[str, Any]) -> str:
    lines = [
        "NAME                         ROLE                PROGRAM      "
        "STAFF WEB ROSTER KG YAML STATUS",
        "---------------------------- ------------------- ------------ "
        "----- --- ------ -- ---- --------",
    ]
    for row in payload["people"]:
        present = row["in"]
        conflicts = ",".join(conflict["field"] for conflict in row["conflicts"])
        status = row["status"] + (f" ({conflicts})" if conflicts else "")
        lines.append(
            f"{row['name'][:28]:28} {row['role'][:19]:19} "
            f"{str(row['program'] or '-')[:12]:12} "
            f"{'yes' if present['staff_org'] else '-':5} "
            f"{'yes' if present['website'] else '-':3} "
            f"{'yes' if present['roster_md'] else '-':6} "
            f"{'yes' if present['kg'] else '-':2} "
            f"{'yes' if present['people_yaml'] else '-':4} {status}"
        )
    return "\n".join(lines)


def cmd_roster(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    payload, _ = roster_payload(settings, offline=args.offline, today=today_from(args))
    _helpers.emit(args, payload, roster_table(payload))
    return 0


def cmd_roster_sync(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    today = today_from(args) or date.today()
    _, rows = roster_payload(settings, offline=args.offline, today=today)
    path = settings.root / "people.yaml"
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = render_people_yaml(rows, noted=today)
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
    )
    applied = not args.dry_run
    if applied:
        path.write_text(after, encoding="utf-8")
    result = {"file": str(path), "diff": diff, "applied": applied}
    text = diff or "people.yaml already matches the agreed roster facts\n"
    if args.dry_run:
        text = "DRY-RUN, nothing written\n" + text
    _helpers.emit(args, result, text.rstrip())
    return 0


def _add_source_options(parser: argparse.ArgumentParser, helpers: Helpers) -> None:
    parser.add_argument("--offline", action="store_true", help="use only cached website pages")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    helpers.add_json(parser)


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    parser = sub.add_parser("roster", help="reconcile staff.org and public roster sources")
    _add_source_options(parser, helpers)
    parser.set_defaults(fn=cmd_roster)
    commands = parser.add_subparsers(dest="roster_cmd")
    sync = commands.add_parser("sync", help="rewrite people.yaml from agreed facts")
    _add_source_options(sync, helpers)
    helpers.add_dry(sync)
    sync.set_defaults(fn=cmd_roster_sync)
