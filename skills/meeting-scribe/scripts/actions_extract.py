#!/usr/bin/env python3
"""Extract action items, decisions and open questions from meeting notes into an org entry.

Reads plain text, Markdown or a transcript (``--notes FILE``) and looks for
lines that carry an action (``- [ ]``, ``TODO``, ``Action:``, ``AI:``, ``X will
...``, ``X to ...``, ``by <date>``), a decision (``Decided``, ``Decision:``,
``we agreed``) or an open question (``Open:``, ``?``). For each action it
finds the owner (``(name)``, ``@slug`` or an attendee name at the start of the
sentence) and a deadline (org timestamp, ``10 Sep 2026``, ``2026-09-10``).
Missing owners or dates are marked ``[unclear]`` rather than guessed.

Output is an org entry ``* <D Month YYYY>, <topic>`` with ``- [ ]`` items
carrying ``(owner)`` and ``<YYYY-MM-DD Day>``, or JSON with ``--format json``.
Nothing is written; pipe the org text into org_append.py.

Example:
  actions_extract.py --notes runs/42/notes.txt --date 2026-09-03 --topic "weekly 1:1" \
      --attendees "Alex Example,Robert" --format org > runs/42/entry.org
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

ACTION_PREFIX_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\[ \]|TODO\b|ACTION\b|Action:|AI:|TO ?DO:)\s*", re.IGNORECASE
)
ACTION_VERB_RE = re.compile(r"\b(will|to|should|needs? to|must|going to)\s+\w+", re.IGNORECASE)
DECISION_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:Decided|Decision|Agreed|We agreed)\b[:\s]*", re.IGNORECASE
)
OPEN_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:Open|Question|Q)\b[:\s]+", re.IGNORECASE)
OWNER_PAREN_RE = re.compile(r"\(([A-Z][a-z]+(?:[ .'-]+[A-Z][a-z]+){0,3})\)")
OWNER_AT_RE = re.compile(r"@([a-z][a-z0-9-]+)")
TIMESTAMP_RE = re.compile(r"<(\d{4}-\d{2}-\d{2})[^>]*>|\[(\d{4}-\d{2}-\d{2})[^\]]*\]")
ISO_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
TEXT_DATE_RE = re.compile(
    r"\b(?:by|before|until|on|due)?\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?(?:\s+(20\d{2}))?\b",
    re.IGNORECASE,
)
MONTH_FIRST_RE = re.compile(
    r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b"
)
WEEKDAY_RE = re.compile(
    r"\b(next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)\b",
    re.IGNORECASE,
)


def parse_deadline(text: str, meeting_date: dt.date) -> tuple[str | None, str]:
    """Return (ISO date or None, how it was found)."""
    m = TIMESTAMP_RE.search(text)
    if m:
        return (m.group(1) or m.group(2)), "timestamp"
    m = ISO_RE.search(text)
    if m:
        return m.group(1), "iso"
    m = TEXT_DATE_RE.search(text)
    if m and m.group(2).lower() in MONTHS:
        year = int(m.group(3)) if m.group(3) else meeting_date.year
        try:
            date = dt.date(year, MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None, "unparsable"
        if not m.group(3) and date < meeting_date:
            date = date.replace(year=year + 1)
        return date.isoformat(), "text"
    m = MONTH_FIRST_RE.search(text)
    if m and m.group(1).lower() in MONTHS:
        year = int(m.group(3)) if m.group(3) else meeting_date.year
        try:
            date = dt.date(year, MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None, "unparsable"
        if not m.group(3) and date < meeting_date:
            date = date.replace(year=year + 1)
        return date.isoformat(), "text"
    if WEEKDAY_RE.search(text):
        return None, "relative"
    return None, "none"


def find_owner(text: str, attendees: list[str]) -> tuple[str | None, str]:
    m = OWNER_PAREN_RE.search(text)
    if m:
        return m.group(1).strip(), "parenthesis"
    m = OWNER_AT_RE.search(text)
    if m:
        return m.group(1), "mention"
    lowered = text.lower()
    for name in attendees:
        first = name.split()[0].lower()
        if re.match(rf"^\W*(?:{re.escape(name.lower())}|{re.escape(first)})\b", lowered):
            return name, "sentence-start"
        if re.search(rf"\b{re.escape(first)}\s+(will|to|should|needs? to)\b", lowered):
            return name, "sentence"
    return None, "none"


def clean(text: str) -> str:
    text = OWNER_PAREN_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return text


def extract(text: str, meeting_date: dt.date, attendees: list[str]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    decisions: list[str] = []
    open_items: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if DECISION_RE.match(line):
            decisions.append(clean(DECISION_RE.sub("", line, count=1)))
            continue
        if OPEN_RE.match(line):
            open_items.append(clean(OPEN_RE.sub("", line, count=1)))
            continue
        is_action = bool(ACTION_PREFIX_RE.match(line)) or bool(ACTION_VERB_RE.search(line))
        if not is_action:
            if line.endswith("?"):
                open_items.append(clean(line))
            continue
        body = ACTION_PREFIX_RE.sub("", line, count=1)
        owner, owner_how = find_owner(body, attendees)
        deadline, date_how = parse_deadline(body, meeting_date)
        flags = []
        if owner is None:
            flags.append("owner unclear")
        if deadline is None:
            flags.append("no date" if date_how in ("none",) else f"date {date_how}")
        actions.append(
            {
                "text": clean(TIMESTAMP_RE.sub("", body)),
                "owner": owner,
                "owner_from": owner_how,
                "deadline": deadline,
                "deadline_from": date_how,
                "flags": flags,
                "line": lineno,
            }
        )
    return {
        "date": meeting_date.isoformat(),
        "actions": actions,
        "decisions": decisions,
        "open": open_items,
        "counts": {
            "actions": len(actions),
            "without_owner": sum(1 for a in actions if a["owner"] is None),
            "without_date": sum(1 for a in actions if a["deadline"] is None),
        },
    }


def org_heading_date(date: dt.date) -> str:
    return f"{date.day} {date.strftime('%B %Y')}"


def render_org(result: dict[str, Any], topic: str, source: str | None, level: int = 1) -> str:
    date = dt.date.fromisoformat(result["date"])
    stars = "*" * level
    lines = [f"{stars} {org_heading_date(date)}, {topic}"]
    if source:
        lines.append(f"- source: {source}")
    lines.append("- summary: [unclear]")
    for a in result["actions"]:
        owner = a["owner"] or "[unclear]"
        item = f"- [ ] {a['text']} ({owner})"
        if a["deadline"]:
            d = dt.date.fromisoformat(a["deadline"])
            item += f" <{d.isoformat()} {d.strftime('%a')}>"
        elif a["deadline_from"] == "relative":
            item += " [unclear: relative date in notes]"
        lines.append(item)
    for d in result["decisions"]:
        lines.append(f"- Decided: {d}")
    for o in result["open"]:
        lines.append(f"- Open: {o}")
    return "\n".join(lines) + "\n"


def render_md(result: dict[str, Any], topic: str) -> str:
    lines = [f"Meeting {result['date']}, {topic}", ""]
    if result["actions"]:
        lines.append("Action items")
        for a in result["actions"]:
            tail = " ".join(f"[{f}]" for f in a["flags"])
            lines.append(
                f"- {a['text']} ({a['owner'] or 'owner unclear'}{', ' + a['deadline'] if a['deadline'] else ''}) {tail}".rstrip()
            )
    if result["decisions"]:
        lines += ["", "Decisions"] + [f"- {d}" for d in result["decisions"]]
    if result["open"]:
        lines += ["", "Open questions"] + [f"- {o}" for o in result["open"]]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--notes", required=True, type=Path, help="notes or transcript file")
    p.add_argument(
        "--date", type=dt.date.fromisoformat, default=None, help="meeting date (default today)"
    )
    p.add_argument("--topic", default="meeting", help="topic for the heading")
    p.add_argument("--attendees", default="", help="comma-separated names for owner detection")
    p.add_argument(
        "--people", type=Path, default=None, help="people.yaml; adds all names as attendees"
    )
    p.add_argument("--source", default=None, help="provenance line (path, permalink, Message-ID)")
    p.add_argument("--level", type=int, default=1, help="org heading level")
    p.add_argument("--format", choices=["org", "json", "md"], default="org")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.notes.exists():
        print(f"actions-extract: {args.notes} not found", file=sys.stderr)
        return 1
    attendees = [a.strip() for a in args.attendees.split(",") if a.strip()]
    if args.people and args.people.exists():
        with args.people.open(encoding="utf-8") as fh:
            people = (yaml.safe_load(fh) or {}).get("people", {})
        attendees += [str(e.get("name")) for e in people.values() if e.get("name")]
    meeting_date = args.date or dt.date.today()
    result = extract(args.notes.read_text(encoding="utf-8"), meeting_date, attendees)
    result["topic"] = args.topic
    result["source"] = args.source or str(args.notes)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "md":
        print(render_md(result, args.topic), end="")
    else:
        print(render_org(result, args.topic, result["source"], args.level), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
