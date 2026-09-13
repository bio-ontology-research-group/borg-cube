#!/usr/bin/env python3
"""Compare two versions of an individual development plan (IDP) and report what moved.

An IDP written from ``assets/idp-template.md`` has Markdown sections holding
goal checkboxes (``- [ ] goal text (by YYYY-MM-DD)``) and tables whose first
column is a key (a skill or competency) followed by a self-rating. The diff
compares an older and a newer file and lists, per section:

* goals added, dropped, completed (unchecked to checked) and reopened;
* goals whose target date moved, with both dates;
* goals overdue as of ``--today`` (unchecked with a past date) in the newer file;
* table rows whose rating changed, with both values.

Output is text or ``--json``. The script reads only; it never writes an IDP.
Use it before an annual review to see what the student changed since the
last version, and to produce the review agenda.

Example:
  idp_diff.py --old idp-2025-09.md --new idp-2026-09.md --today 2026-09-02
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.*?)\s*$")
DATE_RE = re.compile(r"\(?\s*(?:by|due|target)?\s*:?\s*(\d{4}-\d{2}-\d{2})\s*\)?\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


@dataclass
class Goal:
    section: str
    text: str
    done: bool
    date: str | None
    line: int


@dataclass
class Row:
    section: str
    key: str
    values: list[str]
    line: int


@dataclass
class Idp:
    goals: dict[tuple[str, str], Goal] = field(default_factory=dict)
    rows: dict[tuple[str, str], Row] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip("."))


def split_goal(text: str) -> tuple[str, str | None]:
    """Return (goal text without the date suffix, ISO date or None)."""
    m = DATE_RE.search(text)
    if not m:
        return text.strip(), None
    return text[: m.start()].strip().rstrip("(,;: "), m.group(1)


def parse_idp(text: str) -> Idp:
    idp = Idp()
    section = "(top)"
    in_fence = False
    header_seen: dict[str, bool] = {}
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            section = m.group(2).strip()
            if section not in idp.sections:
                idp.sections.append(section)
            continue
        m = CHECKBOX_RE.match(line)
        if m:
            goal_text, date = split_goal(m.group(2))
            key = (section, normalise(goal_text))
            idp.goals[key] = Goal(section, goal_text, m.group(1).lower() == "x", date, i)
            continue
        m = TABLE_ROW_RE.match(line)
        if m:
            cells = [c.strip() for c in m.group(1).split("|")]
            if not cells or not cells[0]:
                continue
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                header_seen[section] = True
                continue
            if not header_seen.get(section):
                # first row before the separator is the header row
                header_seen[section] = False
                continue
            idp.rows[(section, normalise(cells[0]))] = Row(section, cells[0], cells[1:], i)
    return idp


@dataclass
class Diff:
    added: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    completed: list[dict] = field(default_factory=list)
    reopened: list[dict] = field(default_factory=list)
    rescheduled: list[dict] = field(default_factory=list)
    overdue: list[dict] = field(default_factory=list)
    rating_changes: list[dict] = field(default_factory=list)
    sections_added: list[str] = field(default_factory=list)
    sections_dropped: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(asdict(self).values())


def _g(goal: Goal) -> dict:
    return {"section": goal.section, "goal": goal.text, "date": goal.date, "line": goal.line}


def diff_idps(old: Idp, new: Idp, today: dt.date) -> Diff:
    d = Diff()
    d.sections_added = [s for s in new.sections if s not in old.sections]
    d.sections_dropped = [s for s in old.sections if s not in new.sections]
    for key, goal in new.goals.items():
        prev = old.goals.get(key)
        if prev is None:
            d.added.append(_g(goal))
        else:
            if goal.done and not prev.done:
                d.completed.append(_g(goal))
            elif prev.done and not goal.done:
                d.reopened.append(_g(goal))
            if goal.date != prev.date and (goal.date or prev.date):
                d.rescheduled.append({**_g(goal), "old_date": prev.date, "new_date": goal.date})
        if not goal.done and goal.date:
            try:
                due = dt.date.fromisoformat(goal.date)
            except ValueError:
                continue
            if due < today:
                d.overdue.append({**_g(goal), "days_overdue": (today - due).days})
    for key, goal in old.goals.items():
        if key not in new.goals:
            d.dropped.append(_g(goal))
    for key, row in new.rows.items():
        prev = old.rows.get(key)
        if prev is not None and prev.values != row.values:
            d.rating_changes.append(
                {"section": row.section, "key": row.key, "old": prev.values, "new": row.values}
            )
    return d


def render_text(d: Diff, old_name: str, new_name: str) -> str:
    out = [f"IDP diff: {old_name} -> {new_name}"]
    if d.is_empty():
        out.append("no changes")
        return "\n".join(out)

    def block(title: str, items: list[dict], fmt) -> None:
        if items:
            out.append("")
            out.append(f"{title} ({len(items)})")
            out.extend(f"  - {fmt(i)}" for i in items)

    def goal_fmt(i: dict) -> str:
        date = f" (by {i['date']})" if i.get("date") else ""
        return f"[{i['section']}] {i['goal']}{date}"

    block("Goals completed", d.completed, goal_fmt)
    block("Goals added", d.added, goal_fmt)
    block("Goals dropped", d.dropped, goal_fmt)
    block("Goals reopened", d.reopened, goal_fmt)
    block(
        "Goals rescheduled",
        d.rescheduled,
        lambda i: f"[{i['section']}] {i['goal']}: {i['old_date']} -> {i['new_date']}",
    )
    block(
        "Goals overdue in the new version",
        d.overdue,
        lambda i: f"[{i['section']}] {i['goal']}: due {i['date']}, {i['days_overdue']} days ago",
    )
    block(
        "Ratings changed",
        d.rating_changes,
        lambda i: f"[{i['section']}] {i['key']}: {' | '.join(i['old'])} -> {' | '.join(i['new'])}",
    )
    if d.sections_added:
        out.append("")
        out.append("Sections added: " + ", ".join(d.sections_added))
    if d.sections_dropped:
        out.append("Sections dropped: " + ", ".join(d.sections_dropped))
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--old", type=Path, required=True, help="earlier IDP (Markdown)")
    p.add_argument("--new", type=Path, required=True, help="later IDP (Markdown)")
    p.add_argument(
        "--today", type=dt.date.fromisoformat, default=None, help="date for overdue checks"
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in (args.old, args.new):
        if not path.is_file():
            print(f"idp_diff: file not found: {path}", file=sys.stderr)
            return 2
    today = args.today or dt.date.today()
    d = diff_idps(
        parse_idp(args.old.read_text(encoding="utf-8")),
        parse_idp(args.new.read_text(encoding="utf-8")),
        today,
    )
    if args.json:
        print(json.dumps(asdict(d), indent=2))
    else:
        print(render_text(d, args.old.name, args.new.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
