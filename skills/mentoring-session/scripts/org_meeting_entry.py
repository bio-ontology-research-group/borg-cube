#!/usr/bin/env python3
"""Render a 1:1 meeting record and insert it into a person's org file, newest first.

Reads the session material (agenda, summary, action items, decisions, open
questions) from a YAML or Markdown file and writes the group's meeting entry
form: a heading ``* <D Month YYYY>, <topic>`` with ``- [ ]`` action items that
carry an owner and, when a date was agreed, an active ``<YYYY-MM-DD Day>``
timestamp.

Dry run by default: prints the exact text it would insert and a unified diff.
``--apply`` writes the file. The insertion conventions (anchors, relevelling,
lock files, generated-file guard) follow
``skills/meeting-scribe/scripts/org_append.py``; that script stays the general
tool, this one owns the 1:1 entry format and its refusals.

The script refuses to write when

* an Emacs lock file (``#name.org#`` or ``.#name.org``) sits beside the target,
* the target is outside the configured org root (``--org-root``),
* an entry for the same date and topic is already in the file,
* the input carries grade, contract, visa, salary or health content,
* an action item has no owner.

Wellbeing flags in the input are never written to the org file. They are
printed for Robert with the evidence that was observed.

Examples:
  org_meeting_entry.py --input runs/alex/2026-09-03.yaml
  org_meeting_entry.py --input runs/alex/2026-09-03.yaml --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import os
import re
import sys
from pathlib import Path

import yaml

HEADING_RE = re.compile(r"^(\*+)\s")
HEADER_RE = re.compile(r"^#\+")
NOTES_RE = re.compile(r"^(\*+)\s+Notes\s*$", re.IGNORECASE)
GENERATED_MARKERS = ("BEGIN:VEVENT", "COMMENT original iCal")
MD_SECTION_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s+)?(.*\S)\s*$")
OWNER_RE = re.compile(r"\(([^()]+)\)\s*$")
DUE_RE = re.compile(r"\bdue[:=]?\s*(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MONTHS = [
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
]

# Content classes that never enter an org record, a bead or a briefing
# (CLAUDE.md privacy classes; supervision-and-wellbeing rule 13).
FORBIDDEN = {
    "grade": r"\bgrades?\b|\bgpa\b|\bmarks? out of\b",
    "contract": r"\bcontracts?\b|\bsalary\b|\bstipend\b|\brenewal of (?:the )?contract\b",
    "visa": r"\bvisas?\b|\bresidence permit\b|\biqama\b",
    "health": (
        r"\bdiagnos(?:is|ed)\b|\bdepression\b|\banxiety disorder\b"
        r"|\bmedical (?:leave|report)\b|\btherapy\b|\bmedication\b"
        r"|\bsurger(?:y|ies)\b|\bcancer\b|\billness\b|\bsick leave\b"
    ),
}

# The input has no general-purpose free-form metadata.  A field whose role is
# unknown cannot be classified as a work record, so the safe default is to
# refuse it rather than attempting to enumerate every personal-content term.
CLASSIFIED_FIELDS = {
    "person",
    "student",
    "date",
    "topic",
    "summary",
    "agenda",
    "questions",
    "actions",
    "decisions",
    "open",
    "notes",
    "flags",
    "skills",
}

SECTION_KEYS = {
    "summary": "summary",
    "agenda": "agenda",
    "questions": "questions",
    "actions": "actions",
    "action items": "actions",
    "decisions": "decisions",
    "open": "open",
    "open questions": "open",
    "notes": "notes",
    "flags": "flags",
    "skills": "skills",
}


class EntryError(Exception):
    """User-facing refusal (lock, privacy, missing owner, duplicate, path)."""


# --------------------------------------------------------------------------- input


def parse_markdown(text: str) -> dict:
    """Parse a session note written as Markdown sections into the YAML shape."""
    data: dict = {}
    current: str | None = None
    for line in text.splitlines():
        m = MD_SECTION_RE.match(line)
        if m:
            title = m.group(1).strip().lower().rstrip(":")
            current = SECTION_KEYS.get(title)
            if current and current != "summary":
                data.setdefault(current, [])
            continue
        if current is None:
            m2 = re.match(r"^([A-Za-z ]+):\s*(.+)$", line.strip())
            if m2 and SECTION_KEYS.get(m2.group(1).strip().lower()) is None:
                data[m2.group(1).strip().lower()] = m2.group(2).strip()
            continue
        b = BULLET_RE.match(line)
        if b and current != "summary":
            data.setdefault(current, []).append(b.group(1))
        elif current == "summary" and line.strip():
            data["summary"] = (data.get("summary", "") + " " + line.strip()).strip()
    return data


def load_input(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    name = path.name.lower()
    if ".yaml" in name or ".yml" in name:
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise EntryError(f"{path}: expected a YAML mapping")
    else:
        data = parse_markdown(text)
    if not data:
        raise EntryError(f"{path}: no session content found")
    return data


def check_privacy(data: dict) -> None:
    unknown = sorted(set(data) - CLASSIFIED_FIELDS)
    if unknown:
        raise EntryError(
            "cannot classify input field(s) "
            + ", ".join(repr(field) for field in unknown)
            + "; only documented work-record fields may be written"
        )
    blob = yaml.safe_dump(data, allow_unicode=True, sort_keys=True).lower()
    hits = [name for name, pattern in FORBIDDEN.items() if re.search(pattern, blob)]
    if hits:
        raise EntryError(
            "input mentions "
            + ", ".join(sorted(hits))
            + "; grades, contracts, visas and health never enter a meeting record. "
            "Remove them and keep them between Robert and the student."
        )


def as_list(value) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_action(item) -> dict:
    """Normalise an action item to {text, owner, due} from a mapping or a string."""
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("action") or "").strip()
        owner = str(item.get("owner") or "").strip()
        due = item.get("due")
        due = str(due).strip() if due else ""
    else:
        raw = str(item).strip()
        due_m = DUE_RE.search(raw)
        due = due_m.group(1) if due_m else ""
        if due_m:
            raw = (raw[: due_m.start()] + raw[due_m.end() :]).strip().rstrip(",;")
        owner_m = OWNER_RE.search(raw)
        owner = owner_m.group(1).strip() if owner_m else ""
        text = raw[: owner_m.start()].strip() if owner_m else raw
    if not text:
        raise EntryError("an action item has no text")
    if not owner:
        raise EntryError(f"action item {text!r} has no owner; every action item has exactly one")
    if due and not ISO_DATE_RE.match(due):
        raise EntryError(f"action item {text!r} has due {due!r}; use YYYY-MM-DD")
    return {"text": text, "owner": owner, "due": due}


# --------------------------------------------------------------------------- rendering


def parse_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    if not ISO_DATE_RE.match(text):
        raise EntryError(f"date {text!r} is not YYYY-MM-DD")
    return dt.date.fromisoformat(text)


def org_stamp(day: dt.date) -> str:
    return f"<{day.isoformat()} {day.strftime('%a')}>"


def heading_text(day: dt.date, topic: str) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}, {topic}"


def render_entry(data: dict, source: str) -> tuple[str, dt.date, str]:
    day = parse_date(data.get("date") or dt.date.today().isoformat())
    topic = str(data.get("topic") or "1:1").strip()
    lines = [f"* {heading_text(day, topic)}", f"- source: {source}"]
    summary = str(data.get("summary") or "").strip()
    if summary:
        lines.append(f"- summary: {summary}")
    for item in as_list(data.get("actions")):
        action = parse_action(item)
        stamp = f" {org_stamp(dt.date.fromisoformat(action['due']))}" if action["due"] else ""
        lines.append(f"- [ ] {action['text']} ({action['owner']}){stamp}")
    for item in as_list(data.get("decisions")):
        lines.append(f"- Decided: {str(item).strip()}")
    for item in as_list(data.get("open")):
        lines.append(f"- Open: {str(item).strip()}")
    for item in as_list(data.get("skills")):
        lines.append(f"- Skill practised: {str(item).strip()}")
    agenda = as_list(data.get("agenda"))
    if agenda:
        lines.append("** Agenda")
        for item in agenda:
            if isinstance(item, dict):
                point = str(item.get("point") or item.get("text") or "").strip()
                evidence = str(item.get("evidence") or "").strip()
                lines.append(f"- {point}" + (f" (evidence: {evidence})" if evidence else ""))
            else:
                lines.append(f"- {str(item).strip()}")
    notes = as_list(data.get("notes"))
    if notes:
        lines.append("** Notes")
        lines += [f"- {str(item).strip()}" for item in notes]
    return "\n".join(lines) + "\n", day, topic


# --------------------------------------------------------------------------- org file


def lock_files(target: Path) -> list[Path]:
    candidates = [target.parent / f"#{target.name}#", target.parent / f".#{target.name}"]
    return [p for p in candidates if p.exists() or p.is_symlink()]


def relevel(entry: str, level: int) -> str:
    lines = entry.splitlines()
    first = next((i for i, line in enumerate(lines) if HEADING_RE.match(line)), None)
    if first is None:
        raise EntryError("entry has no org heading (a line starting with '* ')")
    current = len(HEADING_RE.match(lines[first]).group(1))  # type: ignore[union-attr]
    delta = level - current
    out: list[str] = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m and delta:
            stars = len(m.group(1)) + delta
            line = "*" * max(1, stars) + line[len(m.group(1)) :]
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def header_end(lines: list[str]) -> int:
    i = 0
    while i < len(lines) and (HEADER_RE.match(lines[i]) or not lines[i].strip()):
        i += 1
    return i


def drawer_end(lines: list[str], start: int) -> int:
    i = start + 1
    while i < len(lines) and lines[i].strip().startswith(":") and lines[i].strip().endswith(":"):
        name = lines[i].strip()
        if name in (":PROPERTIES:", ":LOGBOOK:"):
            while i < len(lines) and lines[i].strip() != ":END:":
                i += 1
            i += 1
        else:
            break
    return i


def find_duplicate(text: str, day: dt.date, topic: str) -> str | None:
    """Return the existing heading when this date and topic are already recorded."""
    wanted_date = f"{day.day} {MONTHS[day.month - 1]} {day.year}".lower()
    wanted_topic = topic.strip().lower()
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if not m:
            continue
        head = line[len(m.group(1)) :].strip().lower()
        if wanted_date in head and (not wanted_topic or wanted_topic in head):
            return line.strip()
    return None


def insert_entry(text: str, entry: str, anchor: str, level: int | None) -> str:
    for marker in GENERATED_MARKERS:
        if marker in text:
            raise EntryError("file looks generated from a calendar (VEVENT); refusing to edit")
    lines = text.splitlines()
    if anchor == "notes":
        idx = next((i for i, line in enumerate(lines) if NOTES_RE.match(line)), None)
        if idx is None:
            anchor = "top"
        else:
            notes_level = len(NOTES_RE.match(lines[idx]).group(1))  # type: ignore[union-attr]
            body = relevel(entry, level or notes_level + 1)
            pos = drawer_end(lines, idx)
            new = lines[:pos] + body.splitlines() + [""] + lines[pos:]
            return "\n".join(new).rstrip("\n") + "\n"
    if anchor == "top":
        body = relevel(entry, level or 1)
        pos = header_end(lines)
        head = lines[:pos]
        if head and head[-1].strip():
            head.append("")
        new = head + body.splitlines() + [""] + lines[pos:]
        return "\n".join(new).rstrip("\n") + "\n"
    if anchor == "end":
        body = relevel(entry, level or 1)
        tail = text.rstrip("\n")
        return (tail + "\n\n" if tail else "") + body
    raise EntryError(f"unknown anchor {anchor!r}")


def resolve_target(data: dict, args) -> Path:
    root = args.org_root.expanduser().resolve()
    if args.file:
        target = args.file.expanduser().resolve()
    else:
        person = str(data.get("person") or data.get("student") or "").strip()
        if not person:
            raise EntryError("give --file, or a 'person' field in the input")
        target = (root / f"{person}.org").resolve()
    if target != root and root not in target.parents:
        raise EntryError(f"{target} is outside the org root {root}; refusing to write")
    if target.name.endswith("~"):
        raise EntryError("refusing to edit an Emacs backup file")
    return target


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--input", required=True, type=Path, help="session YAML or Markdown file")
    p.add_argument("--file", type=Path, default=None, help="target org file")
    p.add_argument(
        "--org-root",
        type=Path,
        default=Path(os.environ.get("CUBE_ORG_ROOT", "~/org")),
        help="directory the target must live in (default: $CUBE_ORG_ROOT or ~/org)",
    )
    p.add_argument("--anchor", choices=["notes", "top", "end"], default="notes")
    p.add_argument("--level", type=int, default=None, help="heading level for the entry")
    p.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = load_input(args.input)
        check_privacy(data)
        target = resolve_target(data, args)
        entry, day, topic = render_entry(data, str(args.input))
        locks = lock_files(target)
        if locks:
            raise EntryError(f"{target.name} is open in Emacs ({locks[0].name}); try again later")
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        duplicate = find_duplicate(original, day, topic)
        if duplicate:
            raise EntryError(
                f"{target.name} already has an entry for this date and topic: {duplicate!r}"
            )
        updated = insert_entry(original, entry, args.anchor, args.level)
    except (EntryError, OSError, yaml.YAMLError) as exc:
        print(f"org-meeting-entry: {exc}", file=sys.stderr)
        return 2
    flags = as_list(data.get("flags"))
    if flags:
        print("org-meeting-entry: for Robert only, not written to the org file:")
        for flag in flags:
            print(f"  flag: {str(flag).strip()}")
    print("--- entry ---")
    print(entry, end="")
    print("--- end entry ---")
    if not args.apply:
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(target),
                tofile=f"{target} (proposed)",
            )
        )
        print(diff if diff else "org-meeting-entry: no change")
        print(f"org-meeting-entry: dry run, nothing written; rerun with --apply to write {target}")
        return 0
    target.write_text(updated, encoding="utf-8")
    added = updated.count("\n") - original.count("\n")
    print(f"org-meeting-entry: inserted {added} line(s) into {target} at anchor {args.anchor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
