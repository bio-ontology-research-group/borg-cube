#!/usr/bin/env python3
"""Collect per-student monitoring facts from org files (privacy: local-only).

For every entry in people.yaml with ``role: student`` and an ``org_file``, the
script reads ``<org-dir>/<org_file>`` and finds the most recent dated meeting
heading (``* 3 September 2026, weekly 1:1``, ``** Meeting 16 November 2023``,
``*** Meeting with X <2023-10-26 Thu>``). It reports the date, the days since,
whether a "final-year plan" heading exists, and, when ``--milestones-dir`` holds
``<slug>.json`` files written by the phd-milestones script, the next milestone
and its status.

The output describes people and is local-only: write it under a Robert-only
directory and never post it. Only the paths given are read.

Example:
  students_state.py --org-dir ~/org --people people.yaml --milestones-dir state/milestones \
      --out state/students.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
HEADING_RE = re.compile(r"^(\*+)\s+(.*?)\s*$")
TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(20\d{2})\b")
TEXT_DATE_NOYEAR_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\b")
TIMESTAMP_RE = re.compile(r"[<\[](\d{4}-\d{2}-\d{2})")
MEETING_WORDS = re.compile(
    r"\b(meeting|1:1|one-on-one|check-?in|discussion|practice talk|call|notes)\b", re.IGNORECASE
)
FINAL_YEAR_RE = re.compile(r"final[- ]year plan", re.IGNORECASE)
LOCK_FORMS = ("#{name}#", ".#{name}")


def heading_date(text: str, year_hint: int | None) -> dt.date | None:
    """Date of a heading: an org timestamp, ``16 November 2023`` or ``21 April`` (year from "
    "hint)."""
    m = TIMESTAMP_RE.search(text)
    if m:
        try:
            return dt.date.fromisoformat(m.group(1))
        except ValueError:
            return None
    m = TEXT_DATE_RE.search(text)
    if m and m.group(2).lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    m = TEXT_DATE_NOYEAR_RE.search(text)
    if m and m.group(2).lower() in MONTHS and year_hint:
        try:
            return dt.date(year_hint, MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    return None


def scan_org(text: str, today: dt.date) -> dict[str, Any]:
    """Return meeting dates found in headings plus a few structural facts."""
    meetings: list[dict[str, Any]] = []
    final_year_plan = False
    year_hint: int | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        hm = HEADING_RE.match(raw)
        if not hm:
            continue
        title = hm.group(2)
        if FINAL_YEAR_RE.search(title):
            final_year_plan = True
        date = heading_date(title, year_hint)
        if date is None:
            continue
        if date > today + dt.timedelta(days=366):
            continue
        year_hint = date.year
        is_meeting = bool(MEETING_WORDS.search(title)) or bool(
            TEXT_DATE_RE.search(title)
            or TIMESTAMP_RE.search(title)
            or TEXT_DATE_NOYEAR_RE.match(title)
        )
        if is_meeting:
            meetings.append({"date": date.isoformat(), "heading": title, "line": lineno})
    meetings.sort(key=lambda m: m["date"], reverse=True)
    return {"meetings": meetings, "final_year_plan": final_year_plan}


def locked(path: Path) -> bool:
    return any((path.parent / form.format(name=path.name)).exists() for form in LOCK_FORMS) or any(
        (path.parent / form.format(name=path.name)).is_symlink() for form in LOCK_FORMS
    )


def student_state(
    slug: str, entry: dict[str, Any], org_dir: Path, milestones_dir: Path | None, today: dt.date
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "slug": slug,
        "program": entry.get("program"),
        "start": str(entry["start"]) if entry.get("start") else None,
        "org_file": entry.get("org_file"),
        "privacy": "local-only",
    }
    org_file = entry.get("org_file")
    if org_file:
        path = org_dir / org_file
        if path.exists():
            scan = scan_org(path.read_text(encoding="utf-8"), today)
            last = scan["meetings"][0] if scan["meetings"] else None
            state["last_meeting"] = last["date"] if last else None
            state["last_meeting_source"] = f"{path}:{last['line']}" if last else str(path)
            state["days_since_meeting"] = (
                (today - dt.date.fromisoformat(last["date"])).days if last else None
            )
            state["meeting_entries"] = len(scan["meetings"])
            state["final_year_plan"] = scan["final_year_plan"]
            state["org_locked"] = locked(path)
        else:
            state["error"] = f"org file {path} not found"
    else:
        state["error"] = "no org_file in people.yaml"
    if entry.get("start"):
        start = dt.date.fromisoformat(str(entry["start"]))
        state["days_since_start"] = (today - start).days
        state["new_member"] = (today - start).days < 150
    if milestones_dir:
        mpath = milestones_dir / f"{slug}.json"
        if mpath.exists():
            plan = json.loads(mpath.read_text(encoding="utf-8"))
            pending = [m for m in plan.get("milestones", []) if m.get("status") != "passed"]
            pending.sort(key=lambda m: m["deadline"])
            state["next_milestone"] = pending[0] if pending else None
            state["milestone_flags"] = plan.get("flags", [])
            state["expected_defense"] = next(
                (
                    m["deadline"]
                    for m in plan.get("milestones", [])
                    if m["id"] in ("defense", "thesis-defense")
                ),
                None,
            )
    return state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--org-dir", required=True, type=Path)
    p.add_argument("--people", required=True, type=Path, help="people.yaml")
    p.add_argument(
        "--milestones-dir", type=Path, default=None, help="<slug>.json from milestones.py"
    )
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path in (args.org_dir, args.people):
        if not path.exists():
            print(f"students-state: {path} not found", file=sys.stderr)
            return 1
    with args.people.open(encoding="utf-8") as fh:
        people = (yaml.safe_load(fh) or {}).get("people", {})
    today = args.today or dt.date.today()
    students = [
        student_state(slug, entry, args.org_dir, args.milestones_dir, today)
        for slug, entry in people.items()
        if entry.get("role") == "student"
    ]
    state = {
        "kind": "students",
        "generated": today.isoformat(),
        "privacy": "local-only",
        "students": students,
    }
    text = json.dumps(state, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"students-state: {len(students)} students -> {args.out} (local-only)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
