"""`cube assign`: validate and record Robert's work assignment on one bead."""

from __future__ import annotations

import argparse
import shlex
import sys
from datetime import date
from typing import Any

import yaml

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.commands._common import now_iso, require_person, require_project, require_role
from cube.config import Settings

_helpers: Helpers | None = None


def _header_and_body(description: str, bead_id: str) -> tuple[dict[str, Any], str]:
    if not description.startswith("---\n"):
        raise ValueError(f"bead {bead_id} has no YAML header; refusing to invent provenance")
    end = description.find("\n---", 4)
    if end < 0:
        raise ValueError(f"bead {bead_id} has an incomplete YAML header")
    header = yaml.safe_load(description[4:end])
    if not isinstance(header, dict) or not header.get("xid"):
        raise ValueError(f"bead {bead_id} has an invalid YAML header")
    return header, description[end + 4 :].lstrip("\n")


def _render_header(header: dict[str, Any], body: str) -> str:
    rendered = "---\n" + yaml.safe_dump(header, sort_keys=False).rstrip() + "\n---\n"
    return rendered + body if body else rendered


def _commands(beads: Any) -> list[str]:
    return [shlex.join(command) for command in beads.logged_commands()]


def cmd_assign(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    try:
        require_role(settings, args.role)
        require_person(settings, args.person)
        require_project(settings, args.project)
        if args.deadline:
            date.fromisoformat(args.deadline)
    except ValueError as exc:
        print(f"cube assign: {exc}", file=sys.stderr)
        return 2

    beads = _helpers.beads(settings, args.dry_run)
    try:
        bead = beads.show(args.bead)
        if not bead:
            raise BeadsError(f"no such bead: {args.bead}")
        header, body = _header_and_body(str(bead.get("description") or ""), args.bead)
    except (BeadsError, ValueError) as exc:
        print(f"cube assign: {exc}", file=sys.stderr)
        return 2

    assignments = {
        "role": args.role,
        "person": args.person,
        "project": args.project,
    }
    labels = [str(label) for label in bead.get("labels") or []]
    for prefix, value in assignments.items():
        if value is None:
            continue
        stale = [label for label in labels if label.startswith(f"{prefix}:")]
        if stale:
            beads.remove_labels(args.bead, stale)
        beads.add_labels(args.bead, [f"{prefix}:{value}"])
        labels = [label for label in labels if label not in stale] + [f"{prefix}:{value}"]

    if args.deadline is not None:
        header["deadline"] = args.deadline
    provenance = header.setdefault("provenance", [])
    if not isinstance(provenance, list):
        print("cube assign: bead header provenance is not a list", file=sys.stderr)
        return 2
    assignment_provenance: dict[str, str] = {
        "source": "cube assign",
        "by": "robert",
        "at": now_iso(),
    }
    if args.note:
        assignment_provenance["note"] = args.note
    provenance.append(assignment_provenance)
    description = _render_header(header, body)
    beads.update_description(args.bead, description)
    if args.priority is not None:
        beads.set_priority(args.bead, args.priority)

    run_report: dict[str, Any] | None = None
    run_role = args.role or next(
        (label.split(":", 1)[1] for label in labels if label.startswith("role:")), None
    )
    if args.run:
        if not run_role:
            print(
                "cube assign: --run needs --role or an existing role: label",
                file=sys.stderr,
            )
            return 2
        from cube.engine.run import execute

        run_report = execute(settings, run_role, bead=args.bead, dry_run=args.dry_run).as_dict()

    result = {
        "bead": {
            **bead,
            "labels": labels,
            "description": description,
            "priority": args.priority if args.priority is not None else bead.get("priority"),
        },
        "dry_run": args.dry_run,
        "commands": _commands(beads),
        "run": run_report,
    }
    text = "\n".join(result["commands"]) if args.dry_run else f"assigned {args.bead}"
    _helpers.emit(args, result, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("assign", help="assign a bead to a role, person or project")
    sp.add_argument("bead")
    sp.add_argument("--role")
    sp.add_argument("--person")
    sp.add_argument("--project")
    sp.add_argument("--deadline")
    sp.add_argument("--priority", type=int, choices=range(0, 5))
    sp.add_argument("--note")
    sp.add_argument("--run", action="store_true")
    helpers.add_json(sp)
    helpers.add_dry(sp)
    sp.set_defaults(fn=cmd_assign)
