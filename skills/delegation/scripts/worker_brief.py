#!/usr/bin/env python3
"""Render a scoped worker brief for one bead from assets/worker-brief.md.

The brief carries only what the worker needs: objective, deliverable,
acceptance criteria, the sources it may read, what is out of scope, its
dependencies, provenance, the escalation rules and who reviews. A bead missing
objective, output, acceptance criteria, sources or out_of_scope cannot be
briefed; the script exits 2 and names the field (the lead fixes the plan, not
the brief). Dry run by default: the brief is printed; ``--apply`` writes
``--out``.

Example:
  worker_brief.py --beads runs/7/beads.json --bead audit-deepgo
  worker_brief.py --beads runs/7/beads.json --bead audit-deepgo \
      --out runs/7/briefs/audit-deepgo.md --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "worker-brief.md"
DEFAULT_ESCALATION = HERE.parent / "assets" / "escalation-rules.md"
REQUIRED = ("objective", "output", "acceptance_criteria", "sources", "out_of_scope")


class BriefError(Exception):
    """The bead cannot be briefed as written."""


def bullets(items: list[Any], empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {i['check'] if isinstance(i, dict) else i}" for i in items)


def escalation_summary(path: Path) -> str:
    """The numbered rules from escalation-rules.md, without the prose."""
    if not path.exists():
        return "- see assets/escalation-rules.md"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    rules = [
        line
        for line in lines
        if line[:2].rstrip(".").isdigit()
        or (len(line) > 2 and line[0].isdigit() and line[1] in ".)")
    ]
    return "\n".join(f"- {r}" for r in rules) if rules else "- see assets/escalation-rules.md"


def render(bead: dict[str, Any], plan: dict[str, Any], template: str, escalation: str) -> str:
    missing = [k for k in REQUIRED if not bead.get(k)]
    if missing:
        raise BriefError(f"bead {bead.get('id')} lacks {', '.join(missing)}; fix the plan")
    review_by = bead.get("review_by") or plan.get("review_by") or "group-leader"
    values = {
        "TITLE": bead["title"],
        "ID": bead["id"],
        "KIND": bead.get("kind", "implement"),
        "OWNER": bead.get("owner_role", "?"),
        "PRIVACY": bead.get("privacy", "internal"),
        "EFFORT": bead.get("effort") or "not set; ask the lead before exceeding 20 tool calls",
        "OBJECTIVE": bead["objective"],
        "OUTPUT": bead["output"],
        "ACCEPTANCE": bullets(bead["acceptance_criteria"], "none (invalid bead)"),
        "SOURCES": bullets(bead["sources"], "nothing beyond the brief"),
        "OUT_OF_SCOPE": bead["out_of_scope"],
        "DEPENDS": bullets(bead.get("depends_on") or [], "none"),
        "PROVENANCE": bullets(
            bead.get("provenance") or plan.get("provenance") or [], "none recorded (invalid bead)"
        ),
        "ESCALATION": escalation,
        "REVIEW_BY": review_by,
    }
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", str(val))
    if bead.get("privacy") == "local-only":
        out += (
            "\nPrivacy: this bead is local-only. Run only on the local tier; "
            "never send its content to a cloud model.\n"
        )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--beads", required=True, type=Path, help="beads JSON from beads_from_plan.py")
    p.add_argument("--bead", required=True, help="bead id to brief")
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p.add_argument("--escalation", type=Path, default=DEFAULT_ESCALATION)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--apply", action="store_true", help="write --out (default: print only)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = json.loads(args.beads.read_text(encoding="utf-8"))
        template = args.template.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"worker-brief: {exc}", file=sys.stderr)
        return 1
    beads = plan["beads"] if isinstance(plan, dict) else plan
    bead = next((b for b in beads if b.get("id") == args.bead), None)
    if bead is None:
        print(
            f"worker-brief: no bead {args.bead!r}; known: {[b.get('id') for b in beads]}",
            file=sys.stderr,
        )
        return 1
    try:
        text = render(
            bead,
            plan if isinstance(plan, dict) else {},
            template,
            escalation_summary(args.escalation),
        )
    except BriefError as exc:
        print(f"worker-brief: {exc}", file=sys.stderr)
        return 2
    if args.apply and args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"worker-brief: wrote {args.out}")
    else:
        print(text, end="")
        if args.out:
            print(f"\n[dry-run] rerun with --apply to write {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
