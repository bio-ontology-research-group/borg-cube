"""`cube kg propose`: prepare, but never apply, a research-KG JSON-LD change."""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import shlex
import sys
from datetime import date
from pathlib import Path
from typing import Any

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.commands._common import require_person
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance

_helpers: Helpers | None = None


def _commands(beads: Any) -> list[str]:
    return [shlex.join(command) for command in beads.logged_commands()]


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _project_node(path: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("@graph") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        raise ValueError(f"{path} does not contain a JSON-LD @graph")
    wanted = f"project/{slug}"
    matches = [
        node
        for node in nodes
        if isinstance(node, dict) and str(node.get("@id", "")).endswith(wanted)
    ]
    if not matches:
        raise ValueError(f"no such project in research KG: {slug}")
    if len(matches) != 1:
        raise ValueError(f"project {slug!r} is ambiguous in research KG")
    return data, matches[0]


def _node_diff(path: Path, old: dict[str, Any], new: dict[str, Any]) -> str:
    before = json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    after = json.dumps(new, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path}::{old['@id']}",
            tofile=f"{path}::{old['@id']} (proposed)",
        )
    )


def _write_patch(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"refusing to overwrite existing KG proposal patch: {path}")
    path.write_text(text, encoding="utf-8")


def cmd_kg(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    if args.kg_cmd != "propose":
        return 2
    if not (args.set or args.add_member or args.note):
        print("cube kg propose: give --set, --add-member or --note", file=sys.stderr)
        return 2
    kg_path = settings.dirs["rkg"] / "projects.jsonld"
    try:
        _data, old = _project_node(kg_path, args.project_slug)
        new = copy.deepcopy(old)
        for assignment in args.set:
            field, separator, value = assignment.partition("=")
            if not separator or not field:
                raise ValueError("--set must be field=value")
            if field in {"@id", "@type"}:
                raise ValueError(f"--set may not alter project identity field {field}")
            new[field] = _json_value(value)
        if args.add_member:
            require_person(settings, args.add_member)
            members = new.get("borg:hasMember") or []
            members = members if isinstance(members, list) else [members]
            member_id = f"borg-id:person/{args.add_member}"
            if not any(
                isinstance(member, dict) and member.get("@id") == member_id for member in members
            ):
                members.append({"@id": member_id})
            new["borg:hasMember"] = members
        if args.note:
            previous = new.get("borg:note")
            if previous is None:
                new["borg:note"] = args.note
            elif isinstance(previous, list):
                new["borg:note"] = [*previous, args.note]
            else:
                new["borg:note"] = [previous, args.note]
        diff = _node_diff(kg_path, old, new)
        if not diff:
            raise ValueError("proposal makes no change")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cube kg propose: {exc}", file=sys.stderr)
        return 2

    day = date.today()
    patch = settings.runs_dir() / "kg" / f"{day.isoformat()}-{args.project_slug}.patch"
    relative_patch = (
        str(patch.relative_to(settings.root)) if patch.is_relative_to(settings.root) else str(patch)
    )
    beads = _helpers.beads(settings, args.dry_run)
    bead_id: str | None = None
    if not args.dry_run:
        try:
            _write_patch(patch, diff)
            header = BeadHeader(
                xid=f"kg-propose:{day.isoformat()}:{args.project_slug}",
                provenance=[
                    Provenance(
                        source=str(kg_path),
                        locator=f"@graph[@id={old['@id']}]",
                        seen=day,
                    )
                ],
                privacy=Privacy.public,
            )
            bead_id = beads.create(
                f"Approval: apply KG proposal for {args.project_slug}",
                header=header,
                body=f"Evidence: {relative_patch}\n\n{diff}",
                type_="task",
                priority=1,
                labels=[
                    "kind:outbound",
                    "needs:robert",
                    f"project:{args.project_slug}",
                    "privacy:public",
                ],
                acceptance=(
                    f"Robert reviews and applies {relative_patch} through the approval queue."
                ),
            )
        except (BeadsError, OSError, ValueError) as exc:
            print(f"cube kg propose: {exc}", file=sys.stderr)
            return 2
    else:
        # Dry runs still show exactly the approval-bead call that --apply will make.
        header = BeadHeader(
            xid=f"kg-propose:{day.isoformat()}:{args.project_slug}",
            provenance=[Provenance(source=str(kg_path), locator=f"@graph[@id={old['@id']}]")],
            privacy=Privacy.public,
        )
        beads.create(
            f"Approval: apply KG proposal for {args.project_slug}",
            header=header,
            body=f"Evidence: {relative_patch}\n\n{diff}",
            type_="task",
            priority=1,
            labels=[
                "kind:outbound",
                "needs:robert",
                f"project:{args.project_slug}",
                "privacy:public",
            ],
            acceptance=f"Robert reviews and applies {relative_patch} through the approval queue.",
        )
    result = {
        "project": args.project_slug,
        "patch": relative_patch,
        "diff": diff,
        "bead": bead_id,
        "applied": not args.dry_run,
        "commands": _commands(beads),
    }
    text = (
        "\n".join([diff, *_commands(beads)])
        if args.dry_run
        else f"created {relative_patch}; approval bead {bead_id}"
    )
    _helpers.emit(args, result, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("kg", help="prepare research-KG changes for Robert's approval")
    kg_sub = sp.add_subparsers(dest="kg_cmd", required=True)
    propose = kg_sub.add_parser("propose", help="write a project-node patch and approval bead")
    propose.add_argument("project_slug")
    propose.add_argument("--set", action="append", default=[])
    propose.add_argument("--add-member")
    propose.add_argument("--note")
    helpers.add_json(propose)
    helpers.add_dry(propose)
    sp.set_defaults(fn=cmd_kg)
