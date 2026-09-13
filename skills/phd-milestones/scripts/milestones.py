#!/usr/bin/env python3
"""Compute KAUST milestone deadlines for one student from start date and programme.

Reads the rules from assets/programs.yaml (every rule carries its manifest
source ids and a verified-on date), chooses the rule set from the start date
(students who started in Fall 2023 or later follow the current rules), and
prints a dated plan: milestones with deadlines, the preparation steps around
each defense, and flags (deadline passed without being marked as passed,
deadline within the artefact window).

Semester ends are approximations from the calendar block of programs.yaml;
the Registrar's academic calendar holds the exact dates.

Examples:
  milestones.py --start 2025-01-01 --program phd-bioeng
  milestones.py --start 2024-08-25 --program ms-cs --track thesis --json
  milestones.py --start 2021-08-22 --program PhD-CS --passed qualifier --passed proposal
  milestones.py --start 2026-06-01 --program phd-cs --org-out ~/org/dan.org --dry-run

This script stands alone; cube/milestones/kaust_rules.py is a separate
implementation for the patrols and must not be imported here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_PROGRAMS = HERE.parent / "assets" / "programs.yaml"
TERMS = ("spring", "summer", "fall")
DUE_SOON_DEFAULT = 60


class MilestoneError(Exception):
    """User-facing failure (bad programme, missing rule)."""


# --------------------------------------------------------------------------- calendar


def _md(value: str) -> tuple[int, int]:
    month, day = value.split("-")
    return int(month), int(day)


def term_of(date: dt.date, cal: dict[str, Any]) -> tuple[int, str]:
    """Return (academic year, term) for a date.

    Dates before the spring start belong to that spring (a January start is a
    Spring start); dates from the fall start onwards belong to fall.
    """
    md = (date.month, date.day)
    if md < _md(cal["summer"]["starts"]):
        return date.year, "spring"
    if md < _md(cal["fall"]["starts"]):
        return date.year, "summer"
    return date.year, "fall"


def term_end(year: int, term: str, cal: dict[str, Any]) -> dt.date:
    month, day = _md(cal[term]["ends"])
    return dt.date(year, month, day)


def next_term(year: int, term: str) -> tuple[int, str]:
    idx = TERMS.index(term)
    if idx == len(TERMS) - 1:
        return year + 1, TERMS[0]
    return year, TERMS[idx + 1]


def add_years(date: dt.date, years: int) -> dt.date:
    try:
        return date.replace(year=date.year + years)
    except ValueError:  # 29 February
        return date.replace(year=date.year + years, day=28)


def resolve_deadline(
    spec: dict[str, Any], start: dt.date, count_summers: bool, cal: dict[str, Any]
) -> dt.date:
    """Turn a deadline spec into a date.

    Keys: one of ``years``, ``terms`` or ``semesters``; optional ``plus_summers``,
    ``at: start`` (the start of the counted term instead of its end) and
    ``offset_days``.
    """
    if "years" in spec:
        due = add_years(start, int(spec["years"]))
        return due + dt.timedelta(days=int(spec.get("offset_days", 0)))
    year, term = term_of(start, cal)
    if "terms" in spec:
        wanted = int(spec["terms"])
        counted = 1
        while counted < wanted:
            year, term = next_term(year, term)
            counted += 1
        due = term_end(year, term, cal)
        return due + dt.timedelta(days=int(spec.get("offset_days", 0)))
    if "semesters" not in spec:
        raise MilestoneError(f"deadline spec needs years, terms or semesters: {spec}")
    wanted = int(spec["semesters"])
    counted = 0
    while True:
        if count_summers or term != "summer":
            counted += 1
            if counted == wanted:
                break
        year, term = next_term(year, term)
    for _ in range(int(spec.get("plus_summers", 0))):
        year, term = next_term(year, term)
        while term != "summer":
            year, term = next_term(year, term)
    if spec.get("at") == "start":
        month, day = _md(cal[term]["starts"])
        due = dt.date(year, month, day)
    else:
        due = term_end(year, term, cal)
    return due + dt.timedelta(days=int(spec.get("offset_days", 0)))


# --------------------------------------------------------------------------- rules


def load_programs(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MilestoneError(f"programs file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "programs" not in data:
        raise MilestoneError(f"{path} lacks a 'programs' mapping")
    return data


def resolve_program(rules: dict[str, Any], name: str) -> tuple[str, dict[str, Any]]:
    aliases = rules.get("aliases", {})
    key = aliases.get(name, name).lower()
    programs = rules["programs"]
    if key not in programs:
        raise MilestoneError(
            f"unknown programme {name!r}; known: {sorted(programs)} and aliases {sorted(aliases)}"
        )
    return key, programs[key]


def rule_set_for(start: dt.date, rules: dict[str, Any], requested: str) -> str:
    if requested != "auto":
        return requested
    boundary = rules.get("rule_set_boundary")
    if isinstance(boundary, str):
        boundary = dt.date.fromisoformat(boundary)
    return "current" if start >= boundary else "pre-fall-2023"


def plan(
    start: dt.date,
    program_name: str,
    rules: dict[str, Any],
    track: str = "thesis",
    rule_set: str = "auto",
    today: dt.date | None = None,
    passed: list[str] | None = None,
    event_dates: dict[str, dt.date] | None = None,
    due_soon_days: int | None = None,
) -> dict[str, Any]:
    """Build the plan as a JSON-ready dict."""
    today = today or dt.date.today()
    passed = passed or []
    event_dates = event_dates or {}
    cal = rules["calendar"]
    key, program = resolve_program(rules, program_name)
    degree = program["degree"]
    chosen = rule_set_for(start, rules, rule_set)
    count_summers = chosen == "pre-fall-2023"
    window = due_soon_days or int(
        rules.get("flags", {}).get("artefact_window_days", DUE_SOON_DEFAULT)
    )
    _, start_term = term_of(start, cal)

    try:
        block = rules["milestones"][degree][chosen]
    except KeyError as exc:
        raise MilestoneError(f"no milestone rules for {degree} under {chosen}") from exc
    specs = block["rules"] if isinstance(block, dict) else block
    consequence = block.get("consequence") if isinstance(block, dict) else None
    milestones: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    for spec in specs:
        if spec.get("track") and spec["track"] != track:
            continue
        deadline_spec = spec["deadline"]
        if start_term == "spring" and "spring_start" in spec:
            deadline_spec = spec["spring_start"]
        due = resolve_deadline(deadline_spec, start, count_summers, cal)
        days_left = (due - today).days
        done = spec["id"] in passed
        if done:
            status = "passed"
        elif days_left < 0:
            status = "overdue"
        elif days_left <= window:
            status = "due-soon"
        else:
            status = "upcoming"
        item = {
            "id": spec["id"],
            "label": spec["label"],
            "deadline": due.isoformat(),
            "days_left": days_left,
            "status": status,
            "sources": spec.get("sources", []),
            "verified_on": spec.get("verified_on"),
            "note": spec.get("note"),
        }
        milestones.append(item)
        if status == "overdue":
            flags.append(
                {
                    "milestone": spec["id"],
                    "kind": "overdue",
                    "message": f"{spec['label']} was due {due.isoformat()} and is not marked "
                    "passed",
                }
            )
        elif status == "due-soon":
            flags.append(
                {
                    "milestone": spec["id"],
                    "kind": "due-soon",
                    "message": (
                        f"{spec['label']} due {due.isoformat()} ({days_left} days): "
                        "an artefact (committee list, draft, form) should exist"
                    ),
                }
            )

    preparation: list[dict[str, Any]] = []
    by_id = {m["id"]: m for m in milestones}
    for event, steps in rules.get("preparation", {}).items():
        if event not in by_id or event in passed:
            continue
        event_date = event_dates.get(event)
        relative_to = "scheduled date" if event_date else "deadline"
        base = event_date or dt.date.fromisoformat(by_id[event]["deadline"])
        for step in steps:
            date = base + dt.timedelta(days=int(step["days"]))
            preparation.append(
                {
                    "event": event,
                    "id": step["id"],
                    "label": step["label"],
                    "date": date.isoformat(),
                    "relative_to": relative_to,
                    "sources": step.get("sources", []),
                    "verified_on": step.get("verified_on"),
                    "note": step.get("note"),
                }
            )

    return {
        "start": start.isoformat(),
        "start_term": start_term,
        "program": key,
        "program_name": program.get("program_name"),
        "degree": degree,
        "track": track if degree == "MS" else None,
        "rule_set": chosen,
        "semester_counting": "fall, spring and summer" if count_summers else "fall and spring",
        "today": today.isoformat(),
        "programs_version": rules.get("version"),
        "program_facts": {
            k: v
            for k, v in program.items()
            if k not in {"degree", "program_name", "sources", "verified_on"}
        },
        "program_sources": program.get("sources", []),
        "milestones": milestones,
        "preparation": preparation,
        "committees": rules.get("committees", {}),
        "consequence": consequence,
        "flags": flags,
        "caveat": (
            "Semester ends are approximations; the Registrar's academic calendar has the exact "
            "deadline. Rules with verified_on null are unverified."
        ),
    }


# --------------------------------------------------------------------------- output


def _mark(item: dict[str, Any]) -> str:
    return "" if item.get("verified_on") else " [unverified]"


def render_text(result: dict[str, Any]) -> str:
    lines = [
        f"Milestone plan: {result['degree']} {result['program_name']} "
        f"({result['program']}), start {result['start']} ({result['start_term']} start)",
        f"Rule set: {result['rule_set']}; semesters counted as {result['semester_counting']}; "
        f"today {result['today']}; programs.yaml {result['programs_version']}",
        "",
        "Milestones",
    ]
    for m in result["milestones"]:
        lines.append(
            f"  {m['deadline']}  {m['status']:9} {m['label']} [{', '.join(m['sources'])}]{_mark(m)}"
        )
        if m.get("note"):
            lines.append(f"              note: {m['note']}")
    if result["preparation"]:
        lines += ["", "Preparation steps (dates relative to the scheduled date or the deadline)"]
        for p in result["preparation"]:
            lines.append(
                f"  {p['date']}  {p['event']}/{p['id']}: {p['label']} "
                f"(relative to {p['relative_to']}) [{', '.join(p['sources'])}]{_mark(p)}"
            )
    if result.get("consequence"):
        lines += ["", f"Consequence of a missed milestone: {result['consequence']}"]
    lines += ["", "Flags" if result["flags"] else "Flags: none"]
    for f in result["flags"]:
        lines.append(f"  {f['kind']:9} {f['message']}")
    lines += ["", result["caveat"]]
    return "\n".join(lines) + "\n"


def render_org(result: dict[str, Any]) -> str:
    today = dt.date.fromisoformat(result["today"])
    heading = (
        f"* Milestones ({result['degree']} {result['program']}, computed "
        f"{today.day} {today.strftime('%B %Y')})"
    )
    lines = [heading, f"- start: {result['start']}, rule set {result['rule_set']}"]
    for m in result["milestones"]:
        d = dt.date.fromisoformat(m["deadline"])
        box = "[X]" if m["status"] == "passed" else "[ ]"
        lines.append(f"- {box} {m['label']} <{d.isoformat()} {d.strftime('%a')}>")
    lines.append(f"- {result['caveat']}")
    return "\n".join(lines) + "\n"


def lock_paths(target: Path) -> list[Path]:
    return [target.parent / f"#{target.name}#", target.parent / f".#{target.name}"]


def write_org(target: Path, text: str, dry_run: bool) -> str:
    locks = [p for p in lock_paths(target) if p.exists() or p.is_symlink()]
    if locks:
        raise MilestoneError(f"{target} is open in Emacs (lock {locks[0].name}); not writing")
    if dry_run:
        return f"dry-run: would append {len(text.splitlines())} lines to {target}\n{text}"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    target.write_text(existing + sep + text, encoding="utf-8")
    return f"appended {len(text.splitlines())} lines to {target}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--start", required=True, type=dt.date.fromisoformat, help="start date (ISO)")
    p.add_argument(
        "--program",
        required=True,
        help="phd-cs, phd-bioeng, ms-cs, ms-bioeng or a people.yaml alias such as PhD-CS",
    )
    p.add_argument("--track", choices=["thesis", "non-thesis"], default="thesis")
    p.add_argument(
        "--rules",
        choices=["auto", "current", "pre-fall-2023"],
        default="auto",
        help="rule set; auto picks from the start date",
    )
    p.add_argument("--programs", type=Path, default=DEFAULT_PROGRAMS, help="programs.yaml")
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    p.add_argument(
        "--passed", action="append", default=[], help="milestone id already passed (repeatable)"
    )
    p.add_argument("--proposal-date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--defense-date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--due-soon-days", type=int, default=None, help="override the artefact window")
    p.add_argument("--org-out", type=Path, default=None, help="append an org snippet to this file")
    p.add_argument("--dry-run", action="store_true", help="with --org-out: print, do not write")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rules = load_programs(args.programs)
        events = {}
        if args.proposal_date:
            events["proposal"] = args.proposal_date
        if args.defense_date:
            events["defense"] = args.defense_date
            events["thesis-defense"] = args.defense_date
        result = plan(
            args.start,
            args.program,
            rules,
            track=args.track,
            rule_set=args.rules,
            today=args.today,
            passed=args.passed,
            event_dates=events,
            due_soon_days=args.due_soon_days,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(render_text(result), end="")
        if args.org_out:
            print(write_org(args.org_out, render_org(result), args.dry_run))
    except MilestoneError as exc:
        print(f"milestones: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
