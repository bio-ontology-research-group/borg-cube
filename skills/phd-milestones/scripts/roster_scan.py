#!/usr/bin/env python3
"""Scan a staff.org roster for milestone dates and report what is missing or late.

The roster (Robert's ~/org/staff.org) lists people as ``** Name`` headings
under top-level sections such as ``* Students`` and ``* Research staff``,
with free-form bullets like ``- start PhD: 1 Jan 2025``, ``- Preproposal:
Jan 2026``, ``- PhD Proposal completed May 2025``, ``- Graduates: Dec 2028``
or ``- contract end date: 30 June 2026``. This script parses those bullets
into dated fields and reports, per person, the dates found, the fields that
are missing, and (with ``--programs`` and a programme) the computed KAUST
deadline for comparison.

Only the path given on the command line is read. Output is a table or JSON;
nothing is written. Names and dates in the roster are internal data: keep the
output in Robert-only locations.

Example:
  roster_scan.py --staff-org ~/org/staff.org --section Students
  roster_scan.py --staff-org ~/org/staff.org --people people.yaml \
      --programs ../assets/programs.yaml --json
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import milestones  # noqa: E402

MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS.update({"sept": 9})
SEASONS = {"spring": 1, "summer": 6, "fall": 8, "autumn": 8, "winter": 12}

FIELD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("start", re.compile(r"\b(start(?:ed|s)?|joined|began)\b", re.IGNORECASE)),
    ("qualifier", re.compile(r"\b(pre-?proposal|qualif\w*)\b", re.IGNORECASE)),
    ("proposal", re.compile(r"\bproposal\b", re.IGNORECASE)),
    ("graduates", re.compile(r"\b(graduat\w*|defen[cs]e|thesis defense)\b", re.IGNORECASE)),
    ("contract_end", re.compile(r"\b(contract\s*end|end date|ends?)\b", re.IGNORECASE)),
    ("transfer", re.compile(r"\b(move to|transfer)\b", re.IGNORECASE)),
]
DATE_RE = re.compile(
    r"(?:(?P<day>\d{1,2})\s+)?(?P<month>[A-Za-z]{3,9})\.?\s+(?P<year>20\d{2})"
    r"|(?P<iso>20\d{2}-\d{2}-\d{2})"
    r"|(?P<season>spring|summer|fall|autumn|winter)\s+(?P<syear>20\d{2})"
)
EXPECTED_FIELDS = {
    "students": ["start", "qualifier", "proposal", "graduates"],
    "research staff": ["contract_end"],
    "staff": ["contract_end"],
}


def parse_date(text: str) -> dt.date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    if m.group("iso"):
        return dt.date.fromisoformat(m.group("iso"))
    if m.group("season"):
        return dt.date(int(m.group("syear")), SEASONS[m.group("season").lower()], 1)
    month = MONTHS.get(m.group("month").lower())
    if not month:
        return None
    day = int(m.group("day")) if m.group("day") else 1
    try:
        return dt.date(int(m.group("year")), month, day)
    except ValueError:
        return None


def classify(bullet: str) -> str | None:
    """Return the field a bullet describes; 'qualifier' wins over 'proposal'."""
    for field, pattern in FIELD_PATTERNS:
        if pattern.search(bullet):
            if field == "proposal" and FIELD_PATTERNS[1][1].search(bullet):
                return "qualifier"
            return field
    return None


def parse_roster(text: str) -> list[dict[str, Any]]:
    """Return one record per ``** Name`` heading with its section and dated fields."""
    people: list[dict[str, Any]] = []
    section = None
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("* "):
            section = line[2:].strip()
            current = None
            continue
        if line.startswith("** "):
            current = {
                "name": line[3:].strip(),
                "section": section,
                "fields": {},
                "notes": [],
                "raw": [],
            }
            people.append(current)
            continue
        if current is None or not line.strip():
            continue
        stripped = line.strip()
        current["raw"].append(stripped)
        if not stripped.startswith("- "):
            continue
        bullet = stripped[2:]
        field = classify(bullet)
        date = parse_date(bullet)
        done = bool(re.search(r"\b(completed|passed|done)\b", bullet, re.IGNORECASE))
        if field and date:
            entry = {"date": date.isoformat(), "text": bullet, "done": done}
            if field == "proposal" and done:
                entry["status"] = "passed"
            current["fields"].setdefault(field, entry)
        elif field:
            current["notes"].append(bullet)
        if re.search(r"\bMSc?\b|master", bullet, re.IGNORECASE):
            current.setdefault("degree_hint", "MS")
        if re.search(r"\bPhD\b", bullet):
            current.setdefault("degree_hint", "PhD")
    for p in people:
        del p["raw"]
    return people


def match_person(name: str, people_yaml: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Match a roster heading to a people.yaml entry by full name, then by first name."""
    entries = people_yaml.get("people", {})
    lowered = name.lower()
    for slug, entry in entries.items():
        if str(entry.get("name", "")).lower() == lowered:
            return slug, entry
    first = lowered.split()[0] if lowered.split() else lowered
    hits = [
        (slug, e)
        for slug, e in entries.items()
        if str(e.get("name", "")).lower().split()[:1] == [first]
    ]
    return hits[0] if len(hits) == 1 else None


def analyse(
    people: list[dict[str, Any]],
    people_yaml: dict[str, Any] | None,
    rules: dict[str, Any] | None,
    today: dt.date,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for person in people:
        section = (person.get("section") or "").lower()
        expected = EXPECTED_FIELDS.get(section, [])
        record: dict[str, Any] = {
            "name": person["name"],
            "section": person["section"],
            "fields": person["fields"],
            "missing": [f for f in expected if f not in person["fields"]],
            "flags": [],
        }
        if people_yaml:
            hit = match_person(person["name"], people_yaml)
            if hit:
                slug, entry = hit
                record["slug"] = slug
                record["program"] = entry.get("program")
                if entry.get("start"):
                    record.setdefault("fields", {}).setdefault(
                        "start",
                        {"date": str(entry["start"]), "text": "people.yaml", "done": False},
                    )
        start = record["fields"].get("start", {}).get("date")
        program = record.get("program")
        if rules and start and program and section == "students":
            try:
                computed = milestones.plan(
                    dt.date.fromisoformat(start), program, rules, today=today
                )
            except milestones.MilestoneError as exc:
                record["flags"].append(f"cannot compute deadlines: {exc}")
            else:
                record["computed"] = {m["id"]: m["deadline"] for m in computed["milestones"]}
                grad = record["fields"].get("graduates", {}).get("date")
                degree_deadline = record["computed"].get("defense") or record["computed"].get(
                    "thesis-defense"
                )
                if grad and degree_deadline and grad > degree_deadline:
                    record["flags"].append(
                        f"stated graduation {grad} is after the computed degree deadline "
                        f"{degree_deadline}"
                    )
                for mid in ("qualifier", "proposal"):
                    due = record["computed"].get(mid)
                    stated = record["fields"].get(mid)
                    if due and not stated and due < today.isoformat():
                        record["flags"].append(f"{mid} deadline {due} passed with no roster entry")
        for field, entry in record["fields"].items():
            if field in ("contract_end", "graduates") and entry["date"] < today.isoformat():
                record["flags"].append(f"{field} {entry['date']} is in the past")
        out.append(record)
    return out


def render_table(records: list[dict[str, Any]]) -> str:
    lines = [
        f"{'name':28} {'section':16} {'start':10} {'qualifier':10} {'proposal':10} "
        f"{'graduates':10} flags"
    ]
    for r in records:
        f = r["fields"]

        def d(key: str) -> str:
            return f.get(key, {}).get("date", "-")

        flags = "; ".join(r["flags"]) if r["flags"] else ""
        missing = f"missing {','.join(r['missing'])}" if r["missing"] else ""
        tail = "; ".join(x for x in (missing, flags) if x)
        lines.append(
            f"{r['name'][:28]:28} {(r['section'] or '')[:16]:16} {d('start'):10} "
            f"{d('qualifier'):10} {d('proposal'):10} {d('graduates'):10} {tail}"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--staff-org", required=True, type=Path, help="path to staff.org")
    p.add_argument("--people", type=Path, default=None, help="people.yaml for programme lookup")
    p.add_argument("--programs", type=Path, default=None, help="programs.yaml to compute deadlines")
    p.add_argument("--section", default=None, help="only this top-level section (e.g. Students)")
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.staff_org.exists():
        print(f"roster-scan: {args.staff_org} not found", file=sys.stderr)
        return 1
    people = parse_roster(args.staff_org.read_text(encoding="utf-8"))
    if args.section:
        people = [p for p in people if (p["section"] or "").lower() == args.section.lower()]
    people_yaml = None
    if args.people:
        with args.people.open(encoding="utf-8") as fh:
            people_yaml = yaml.safe_load(fh) or {}
    rules = None
    if args.programs:
        try:
            rules = milestones.load_programs(args.programs)
        except milestones.MilestoneError as exc:
            print(f"roster-scan: {exc}", file=sys.stderr)
            return 1
    records = analyse(people, people_yaml, rules, args.today or dt.date.today())
    if args.json:
        print(json.dumps(records, indent=2))
    else:
        print(render_table(records), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
