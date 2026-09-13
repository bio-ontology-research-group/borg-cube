"""`cube review <bead>`: run the stronger-tier reviewer, or record Robert's verdict directly."""

from __future__ import annotations

import argparse
from typing import Any

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.config import Settings
from cube.engine import execute, review_gate
from cube.engine.context import bead_labels, label_value
from cube.roles import RoleError, load_role


def cmd_review(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, args.dry_run)
    bead: dict[str, Any] = {}
    if beads.available():
        try:
            bead = beads.show(args.bead)
        except BeadsError as exc:
            helpers.emit(args, {"ok": False, "error": str(exc)}, f"error: {exc}")
            return 1
    labels = bead_labels(bead)
    if args.verdict:
        if not review_gate.is_review_bead(bead) and not args.force:
            msg = f"{args.bead} is not a kind:review bead (use --force to record anyway)"
            helpers.emit(args, {"ok": False, "error": msg}, msg)
            return 3
        out = review_gate.apply_verdict(
            beads,
            args.bead,
            bead,
            verdict=args.verdict,
            summary=args.summary or f"verdict by {args.by}",
            by=args.by,
            run_id="manual",
        )
        out.update({"ok": True, "dry_run": args.dry_run, "commands": beads.log})
        helpers.emit(
            args, out, f"{'DRY-RUN ' if args.dry_run else ''}{args.verdict} on {args.bead}"
        )
        return 0
    reviewer = args.role or label_value(labels, "role:")
    if not reviewer:
        producer = label_value(labels, "producer:") or "programmer"
        try:
            reviewer = load_role(settings.root, producer).review_required_by
        except RoleError:
            reviewer = None
    if not reviewer:
        msg = f"cannot determine reviewer role for {args.bead}; pass --role"
        helpers.emit(args, {"ok": False, "error": msg}, msg)
        return 3
    report = execute(
        settings,
        reviewer,
        bead=args.bead,
        runner_name=args.runner,
        dry_run=args.dry_run,
        prompt_text="Review this bead and return a verdict approve|revise|reject with evidence.",
    )
    data = report.as_dict()
    data.pop("prompt", None)
    helpers.emit(
        args,
        data,
        f"review {args.bead} by {reviewer}: {report.state}"
        + (f" verdict={data['result'].get('verdict')}" if data.get("result") else "")
        + (f" error={report.error}" if report.error else ""),
    )
    return 0 if report.ok else 1


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("review", help="review gate: run the reviewer role or record a verdict")
    sp.add_argument("bead")
    sp.add_argument("--role", help="reviewer role (default: role: label or producer's reviewer)")
    sp.add_argument("--runner", help="force a runner (stub for tests)")
    sp.add_argument("--verdict", choices=review_gate.VERDICTS, help="record a verdict directly")
    sp.add_argument("--summary", help="verdict text (with --verdict)")
    sp.add_argument("--by", default="robert")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--dry-run", dest="dry_run", action="store_true")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_review(a, s, helpers))
