"""`cube create`: create a provenance-backed, reviewable work bead."""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from datetime import date, datetime
from typing import Any

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.commands._common import require_person, require_project, require_role
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance

_helpers: Helpers | None = None

# Kinds that are Robert's decisions (doctrine 7a), never dispatched work.
DECISION_KINDS = frozenset({"approval", "proposal"})


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "work"


def _provenance(values: list[str]) -> list[Provenance]:
    out: list[Provenance] = []
    for value in values:
        source, sep, locator = value.partition("::")
        source = source.strip()
        if not source:
            raise ValueError("provenance must name a source path or permalink")
        out.append(
            Provenance(source=source, locator=locator.strip() if sep and locator.strip() else None)
        )
    return out


def _commands(beads: Any) -> list[str]:
    return [shlex.join(command) for command in beads.logged_commands()]


def cmd_create(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    if not args.provenance:
        print("cube create: at least one --provenance PATH::LOCATOR is required", file=sys.stderr)
        return 2
    if not args.acceptance:
        print("cube create: at least one --acceptance TEXT is required", file=sys.stderr)
        return 2
    try:
        require_role(settings, args.role)
        require_person(settings, args.person)
        require_project(settings, args.project)
        deadline = date.fromisoformat(args.deadline) if args.deadline else None
        provenance = _provenance(args.provenance)
    except ValueError as exc:
        print(f"cube create: {exc}", file=sys.stderr)
        return 2

    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    xid = args.xid or f"manual:{_slug(args.title)}:{stamp}"
    header = BeadHeader(
        xid=xid,
        provenance=provenance,
        deadline=deadline,
        privacy=Privacy(args.privacy),
    )
    if args.kind in DECISION_KINDS:
        # Robert, 2026-09-07: an approval or a proposal is a decision for Robert,
        # not work for the marshal; it carries needs:robert and no stage.
        labels = [f"kind:{args.kind}", "needs:robert", f"privacy:{args.privacy}"]
    else:
        labels = [f"kind:{args.kind}", "stage:design", f"privacy:{args.privacy}"]
    for prefix, value in (("role", args.role), ("person", args.person), ("project", args.project)):
        if value:
            labels.append(f"{prefix}:{value}")
    for extra in args.label:
        # e.g. repo:owner/name for an audit; validated as key:value, never a shell string
        if not re.fullmatch(r"[a-z][a-z0-9-]*:[A-Za-z0-9._/@+-]+", extra):
            print(f"cube create: bad label {extra!r} (want key:value)", file=sys.stderr)
            return 2
        if extra not in labels:
            labels.append(extra)
    body = "Acceptance:\n" + "\n".join(f"- {line}" for line in args.acceptance)
    beads = _helpers.beads(settings, args.dry_run)
    try:
        bead_id = beads.create(
            args.title,
            header=header,
            body=body,
            type_="task",
            priority=args.priority,
            labels=labels,
            acceptance="\n".join(args.acceptance),
        )
    except BeadsError as exc:
        print(f"cube create: {exc}", file=sys.stderr)
        return 2
    result = {
        "bead": bead_id,
        "xid": xid,
        "title": args.title,
        "labels": labels,
        "header": header.model_dump(mode="json"),
        "acceptance": args.acceptance,
        "dry_run": args.dry_run,
        "commands": _commands(beads),
    }
    text = "\n".join(result["commands"]) if args.dry_run else f"created {bead_id}"
    _helpers.emit(args, result, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("create", help="create a provenance-backed work bead")
    sp.add_argument("--title", required=True)
    sp.add_argument("--kind", required=True)
    sp.add_argument("--role")
    sp.add_argument("--person")
    sp.add_argument("--project")
    sp.add_argument("--deadline")
    sp.add_argument("--priority", type=int, choices=range(0, 5), default=2)
    sp.add_argument("--privacy", choices=[p.value for p in Privacy], default=Privacy.internal.value)
    sp.add_argument("--acceptance", action="append", default=[])
    sp.add_argument("--provenance", action="append", default=[])
    sp.add_argument("--xid", help="stable external id (otherwise generated)")
    sp.add_argument(
        "--label", action="append", default=[], help="extra key:value label, e.g. repo:owner/name"
    )
    helpers.add_json(sp)
    helpers.add_dry(sp)
    sp.set_defaults(fn=cmd_create)
