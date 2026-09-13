"""`cube sync`: derive beads from the sources of record and reconcile with bd."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, context, now_iso
from cube.config import Settings
from cube.sync.derivers import DERIVERS, derive_all
from cube.sync.reconcile import apply, index_existing, plan, summarize

_helpers: Helpers | None = None


def cmd_sync(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args, github_details=not args.no_github_details)
    desired = derive_all(ctx, args.source or None)
    beads = _helpers.beads(settings, args.dry_run)
    existing, warning = index_existing(beads)
    if warning:
        ctx.warn(warning)
    actions = plan(desired, existing)
    results: list[dict[str, Any]] = []
    if not args.dry_run:
        results = apply(actions, desired, beads, existing)
    payload = {
        "generated": now_iso(),
        "today": ctx.today.isoformat(),
        "dry_run": args.dry_run,
        "sources": args.source or list(DERIVERS),
        "desired": len(desired),
        "existing": len(existing),
        "summary": summarize(actions),
        "actions": [a.model_dump() for a in actions if a.op != "noop" or args.verbose],
        "results": results,
        "warnings": ctx.warnings,
    }
    lines = [
        f"{'DRY-RUN ' if args.dry_run else ''}sync plan "
        f"({len(desired)} desired, {len(existing)} in ledger)"
    ]
    for a in actions:
        if a.op == "noop" and not args.verbose:
            continue
        extra = f" +{','.join(a.labels_add)}" if a.op == "update-labels" else ""
        due = f" due {a.deadline}" if a.deadline and a.op == "create" else ""
        lines.append(f"  {a.op:13} {a.kind:12} {a.xid}{due}{extra}  {a.title[:70]}")
    summ = summarize(actions)
    lines.append("")
    lines.append("by op: " + ", ".join(f"{k}={v}" for k, v in sorted(summ["by_op"].items())))
    for kind, ops in sorted(summ["by_kind"].items()):
        lines.append(f"  {kind:12} " + ", ".join(f"{k}={v}" for k, v in sorted(ops.items())))
    if ctx.warnings:
        lines.append("")
        lines.extend(f"warning: {w}" for w in ctx.warnings)
    if results:
        failed = [r for r in results if not r.get("ok")]
        lines.append(f"applied {len(results)} action(s), {len(failed)} failed")
    _helpers.emit(args, payload, "\n".join(lines))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser(
        "sync", help="derive beads from ~/org, ~/pa, KG, GitHub, calendar (dry-run by default)"
    )
    sp.add_argument(
        "--source",
        action="append",
        choices=sorted(DERIVERS),
        help="restrict to one or more sources (repeatable)",
    )
    sp.add_argument("--verbose", action="store_true", help="also list up-to-date beads")
    sp.add_argument(
        "--no-github-details",
        action="store_true",
        help="skip per-repo README/CI/LICENSE checks (faster; uses cache if present)",
    )
    add_today(sp)
    helpers.add_json(sp)
    helpers.add_dry(sp)
    sp.set_defaults(fn=cmd_sync)
