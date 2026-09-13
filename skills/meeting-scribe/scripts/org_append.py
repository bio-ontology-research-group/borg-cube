#!/usr/bin/env python3
"""Insert a dated meeting entry into an org file, newest first, without touching anything else.

Dry run by default: prints a unified diff of what would change. ``--apply``
writes the file. The script refuses when Emacs has the file open (``#name#``
auto-save lock or ``.#name`` lock symlink), never edits existing lines, keeps
``#+`` header lines, property drawers and logbooks intact, and inserts at one
of three anchors:

  notes         directly under the first ``* Notes`` heading (default; falls
                back to ``top`` when the file has no Notes heading)
  top           after the ``#+`` header block, before the first heading
  end           at the end of the file

The entry is read from ``--entry FILE`` (org text whose first line is a
heading) or built from ``--heading`` and ``--body FILE``. Heading levels in the
entry are shifted so that its top heading sits at ``--level`` (default: one
level below the anchor heading, or 1 at top and end).

Example:
  org_append.py --file ~/org/alex.org --entry runs/42/entry.org
  org_append.py --file ~/org/alex.org --entry runs/42/entry.org --apply
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(\*+)\s")
HEADER_RE = re.compile(r"^#\+")
NOTES_RE = re.compile(r"^(\*+)\s+Notes\s*$", re.IGNORECASE)
GENERATED_MARKERS = ("BEGIN:VEVENT", "COMMENT original iCal")


class AppendError(Exception):
    """User-facing refusal (lock, generated file, bad entry)."""


def lock_files(target: Path) -> list[Path]:
    candidates = [target.parent / f"#{target.name}#", target.parent / f".#{target.name}"]
    return [p for p in candidates if p.exists() or p.is_symlink()]


def relevel(entry: str, level: int) -> str:
    """Shift all headings in the entry so the first heading has ``level`` stars."""
    lines = entry.splitlines()
    first = next((i for i, l in enumerate(lines) if HEADING_RE.match(l)), None)
    if first is None:
        raise AppendError("entry has no org heading (a line starting with '* ')")
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
    """Index of the first line after the ``#+`` header block and leading blanks."""
    i = 0
    while i < len(lines) and (HEADER_RE.match(lines[i]) or not lines[i].strip()):
        i += 1
    return i


def drawer_end(lines: list[str], start: int) -> int:
    """Skip a :PROPERTIES:/:LOGBOOK: drawer directly under a heading at ``start``."""
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


def insert_entry(text: str, entry: str, anchor: str, level: int | None) -> str:
    for marker in GENERATED_MARKERS:
        if marker in text:
            raise AppendError("file looks generated from a calendar (VEVENT); refusing to edit")
    lines = text.splitlines()
    if anchor == "notes":
        idx = next((i for i, l in enumerate(lines) if NOTES_RE.match(l)), None)
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
    raise AppendError(f"unknown anchor {anchor!r}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--file", required=True, type=Path, help="target org file")
    p.add_argument("--entry", type=Path, default=None, help="org text to insert")
    p.add_argument("--heading", default=None, help="heading text when --entry is not given")
    p.add_argument("--body", type=Path, default=None, help="body text for --heading")
    p.add_argument("--anchor", choices=["notes", "top", "end"], default="notes")
    p.add_argument("--level", type=int, default=None, help="heading level for the entry")
    p.add_argument("--apply", action="store_true", help="write the file (default: dry run)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target: Path = args.file
    try:
        if args.entry:
            entry = args.entry.read_text(encoding="utf-8")
        elif args.heading:
            body = args.body.read_text(encoding="utf-8") if args.body else ""
            entry = f"* {args.heading}\n{body}"
        else:
            raise AppendError("give --entry FILE or --heading TEXT")
        locks = lock_files(target)
        if locks:
            raise AppendError(f"{target.name} is open in Emacs ({locks[0].name}); try again later")
        if target.name.endswith("~"):
            raise AppendError("refusing to edit an Emacs backup file")
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = insert_entry(original, entry, args.anchor, args.level)
    except (AppendError, OSError) as exc:
        print(f"org-append: {exc}", file=sys.stderr)
        return 2
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=str(target),
        tofile=f"{target} (proposed)",
    )
    diff_text = "".join(diff)
    if not args.apply:
        print(diff_text if diff_text else "org-append: no change")
        print(f"org-append: dry run, nothing written; rerun with --apply to write {target}")
        return 0
    target.write_text(updated, encoding="utf-8")
    added = updated.count("\n") - original.count("\n")
    print(f"org-append: inserted {added} line(s) into {target} at anchor {args.anchor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
