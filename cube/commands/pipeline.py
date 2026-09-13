"""``cube pipeline`` deterministic research workflow commands."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.commands._common import require_person, require_project
from cube.config import Settings
from cube.model import Provenance, RunResult
from cube.pipeline import (
    advance,
    ask,
    list_pipeline_epics,
    new_pipeline,
    pipeline_status,
    record_plan_artifacts,
    recruit,
)


def _provenance(values: list[str]) -> list[Provenance]:
    result = [Provenance(source="cli", locator="cube pipeline new")]
    for value in values:
        source, separator, locator = value.partition("::")
        if not source.strip():
            raise ValueError("provenance must name a source path or permalink")
        result.append(
            Provenance(
                source=source.strip(),
                locator=locator.strip() if separator and locator.strip() else None,
            )
        )
    return result


def cmd_new(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    if not args.success:
        print("cube pipeline new: at least one --success criterion is required", file=sys.stderr)
        return 2
    try:
        require_project(settings, args.project)
        if args.person:
            require_person(settings, args.person)
        provenance = _provenance(args.provenance)
        question = (
            f"Collect the email I sent about {args.from_mail}: extract the ideas, list the "
            "papers and the code I already have (links, DOIs, local repositories)"
        )
        beads = helpers.beads(settings, args.dry_run)
        data = new_pipeline(
            settings,
            beads,
            title=args.title,
            target=args.target,
            success=args.success,
            question=question,
            person=args.person,
            project=args.project,
            privacy=args.privacy,
            provenance=provenance,
        )
    except (ValueError, BeadsError) as exc:
        print(f"cube pipeline new: {exc}", file=sys.stderr)
        return 2
    data.update({"dry_run": args.dry_run, "commands": beads.logged_commands()})
    helpers.emit(
        args,
        data,
        f"{'DRY-RUN ' if args.dry_run else ''}research pipeline {data['epic']}",
    )
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, True)
    try:
        if args.epic:
            data: dict[str, Any] = pipeline_status(settings, beads, args.epic, today=date.today())
        else:
            epics = list_pipeline_epics(beads)
            data = {
                "pipelines": [
                    pipeline_status(settings, beads, str(item["id"]), today=date.today())
                    for item in epics
                ]
            }
    except (ValueError, BeadsError) as exc:
        print(f"cube pipeline status: {exc}", file=sys.stderr)
        return 2
    helpers.emit(
        args,
        data,
        (
            f"{data['epic']}: {data['status']} at {data['stage']}"
            if args.epic
            else f"{len(data['pipelines'])} research pipeline(s)"
        ),
    )
    return 0


def cmd_record(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """Re-apply a finished run's pipeline artifacts (after a checker fix, no new model run)."""
    from cube.commands.show import run_show  # noqa: PLC0415

    meta = run_show(settings, args.run)
    if meta is None:
        print(f"cube pipeline record: run {args.run} not found", file=sys.stderr)
        return 3
    run_dir = Path(str(meta.get("path") or meta.get("run_dir") or ""))
    result_path = run_dir / "result.json"
    bead_id = str(meta.get("bead") or "")
    if not result_path.exists() or not bead_id:
        print(f"cube pipeline record: {args.run} has no result.json or bead", file=sys.stderr)
        return 3
    beads = helpers.beads(settings, args.dry_run)
    try:
        result = RunResult.model_validate(json.loads(result_path.read_text(encoding="utf-8")))
        bead = beads.show(bead_id)
        report = record_plan_artifacts(
            settings, bead, run_dir, result, beads=beads, today=date.today()
        )
        if report.get("close") and not args.dry_run:
            beads.close(bead_id, "pipeline artifact recorded (cube pipeline record)")
            beads.remove_labels(bead_id, ["needs:robert"])
    except (ValueError, BeadsError, OSError) as exc:
        print(f"cube pipeline record: {exc}", file=sys.stderr)
        return 2
    data = {"run": args.run, "bead": bead_id, "dry_run": args.dry_run, **report}
    helpers.emit(args, data, f"{bead_id}: {report.get('stage')} close={report.get('close')}")
    return 0 if not report.get("errors") else 1


def cmd_advance(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, args.dry_run)
    try:
        data = advance(settings, beads, args.epic, today=date.today(), dry_run=args.dry_run)
    except (ValueError, BeadsError, ImportError, OSError) as exc:
        print(f"cube pipeline advance: {exc}", file=sys.stderr)
        return 2
    data["dry_run"] = args.dry_run
    data["commands"] = beads.logged_commands()
    helpers.emit(args, data, f"pipeline {args.epic}: {data['stage']}")
    return 0


def cmd_ask(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, args.dry_run)
    try:
        data = ask(
            settings,
            beads,
            args.epic,
            from_member=args.from_member,
            to_member=args.to_member,
            text=args.text,
            dry_run=args.dry_run,
        )
    except (ValueError, BeadsError, OSError) as exc:
        print(f"cube pipeline ask: {exc}", file=sys.stderr)
        return 2
    data["commands"] = beads.logged_commands()
    helpers.emit(
        args,
        data,
        "delivered" if data["delivered"] else "contact or recruitment approval requested",
    )
    return 0


def cmd_recruit(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    if not args.deny and not args.role:
        print("cube pipeline recruit: --role is required unless --deny is used", file=sys.stderr)
        return 2
    beads = helpers.beads(settings, args.dry_run)
    try:
        data = recruit(
            settings,
            beads,
            args.epic,
            member=args.member,
            role_name=args.role,
            why=args.why,
            deny=args.deny,
            dry_run=args.dry_run,
        )
    except (ValueError, BeadsError, OSError) as exc:
        print(f"cube pipeline recruit: {exc}", file=sys.stderr)
        return 2
    data["commands"] = beads.logged_commands()
    helpers.emit(
        args,
        data,
        f"{'denied' if data['denied'] else 'recruited'} {args.member}",
    )
    return 0


def cmd_rehearse(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from tempfile import TemporaryDirectory

    from cube.pipeline_rehearsal import run_rehearsal

    with TemporaryDirectory(prefix="cube-pipeline-") as directory:
        data = run_rehearsal(settings.root, __import__("pathlib").Path(directory))
    if args.json:
        helpers.emit(args, data, None)
    else:
        helpers.emit(
            args,
            data,
            "\n".join([*data["transitions"], json.dumps(data["status"], sort_keys=True)]),
        )
    return int(data["exit_code"])


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("pipeline", help="create and run a gated research pipeline")
    commands = parser.add_subparsers(dest="pipeline_cmd", required=True)

    new = commands.add_parser("new", help="start a research pipeline from sent mail")
    new.add_argument("--title", required=True)
    new.add_argument("--target", required=True, type=date.fromisoformat)
    new.add_argument("--success", action="append", default=[])
    new.add_argument("--from-mail", required=True)
    new.add_argument("--person")
    new.add_argument("--project")
    new.add_argument("--privacy", choices=["public", "internal", "local-only"], default="internal")
    new.add_argument("--provenance", action="append", default=[])
    helpers.add_json(new)
    helpers.add_dry(new)
    new.set_defaults(fn=lambda args, settings: cmd_new(args, settings, helpers))

    status = commands.add_parser("status", help="show one or all research pipelines")
    status.add_argument("epic", nargs="?")
    helpers.add_json(status)
    status.set_defaults(fn=lambda args, settings: cmd_status(args, settings, helpers))

    rec = commands.add_parser("record", help="re-apply a finished run's pipeline artifacts")

    rec.add_argument("run")

    helpers.add_json(rec)

    helpers.add_dry(rec)

    rec.set_defaults(fn=lambda a, s: cmd_record(a, s, helpers))

    move = commands.add_parser("advance", help="apply one deterministic stage transition")
    move.add_argument("epic")
    helpers.add_json(move)
    helpers.add_dry(move)
    move.set_defaults(fn=lambda args, settings: cmd_advance(args, settings, helpers))

    ask_parser = commands.add_parser("ask", help="ask a pipeline team member for help")
    ask_parser.add_argument("epic")
    ask_parser.add_argument("--from", dest="from_member", required=True)
    ask_parser.add_argument("--to", dest="to_member", required=True)
    ask_parser.add_argument("text")
    helpers.add_json(ask_parser)
    helpers.add_dry(ask_parser)
    ask_parser.set_defaults(fn=lambda args, settings: cmd_ask(args, settings, helpers))

    recruit_parser = commands.add_parser(
        "recruit", help="accept or deny a pipeline recruitment request"
    )
    recruit_parser.add_argument("epic")
    recruit_parser.add_argument("--member", required=True)
    recruit_parser.add_argument("--role")
    recruit_parser.add_argument("--why", required=True)
    recruit_parser.add_argument("--deny", action="store_true")
    helpers.add_json(recruit_parser)
    helpers.add_dry(recruit_parser)
    recruit_parser.set_defaults(fn=lambda args, settings: cmd_recruit(args, settings, helpers))

    rehearse = commands.add_parser("rehearse", help="run the complete offline pipeline fixture")
    helpers.add_json(rehearse)
    rehearse.set_defaults(fn=lambda args, settings: cmd_rehearse(args, settings, helpers))
