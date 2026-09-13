#!/usr/bin/env python3
"""Read papers.org and emit the state of every paper as JSON.

The file declares its TODO sequence in a ``#+TODO:`` line (for example
``READY_TO_SUBMIT SUBMITTED REVISING PAUSED TODO | PUBLISHED CANCELED``);
keywords are taken from that line, never from a built-in list. Every heading
that starts with one of the keywords is a paper. ``last_touched`` is the most
recent org timestamp (``<2026-05-11 Mon>``, ``[2026-05-11 Mon]``, or a
``CLOSED:`` line) found in the heading or its body; when the body has none it
is null, and ``--mtime`` falls back to the file's modification date.

Only the path given is read. Output goes to stdout or ``--out``.

Example:
  papers_state.py --papers ~/org/papers.org --out state/papers.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

TODO_LINE_RE = re.compile(r"^#\+(?:TODO|SEQ_TODO|TYP_TODO):\s*(.*)$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(\*+)\s+(.*?)\s*$")
TIMESTAMP_RE = re.compile(r"[<\[](\d{4}-\d{2}-\d{2})(?:\s+[A-Za-z]{2,3})?[^\]>]*[>\]]")
TAGS_RE = re.compile(r"\s+(:[A-Za-z0-9_@#%:]+:)\s*$")


def parse_todo_line(line: str) -> tuple[list[str], list[str]]:
    """Split a ``#+TODO:`` value into (active keywords, done keywords)."""
    keywords = [re.sub(r"\(.*?\)", "", tok) for tok in line.split()]
    if "|" in keywords:
        idx = keywords.index("|")
        return [k for k in keywords[:idx] if k], [k for k in keywords[idx + 1 :] if k]
    active = [k for k in keywords if k]
    if not active:
        return ["TODO"], ["DONE"]
    return active[:-1], active[-1:]


def parse_papers(text: str) -> dict[str, Any]:
    active: list[str] = []
    done: list[str] = []
    for line in text.splitlines():
        m = TODO_LINE_RE.match(line.strip())
        if m:
            a, d = parse_todo_line(m.group(1))
            active += a
            done += d
    if not active and not done:
        active, done = ["TODO"], ["DONE"]
    keywords = set(active) | set(done)

    papers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_level = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        hm = HEADING_RE.match(raw)
        if hm:
            level = len(hm.group(1))
            title = hm.group(2)
            if current is not None and level <= current_level:
                current = None
            tags = None
            tm = TAGS_RE.search(title)
            if tm:
                tags = [t for t in tm.group(1).strip(":").split(":") if t]
                title = title[: tm.start()].rstrip()
            first, _, rest = title.partition(" ")
            if first in keywords:
                current = {
                    "title": rest.strip(),
                    "state": first,
                    "done": first in done,
                    "level": level,
                    "line": lineno,
                    "tags": tags or [],
                    "last_touched": None,
                    "timestamps": [],
                }
                current_level = level
                papers.append(current)
            if current is not None:
                for ts in TIMESTAMP_RE.findall(raw):
                    current["timestamps"].append(ts)
            continue
        if current is not None:
            for ts in TIMESTAMP_RE.findall(raw):
                current["timestamps"].append(ts)
    for p in papers:
        if p["timestamps"]:
            p["last_touched"] = max(p["timestamps"])
        p["timestamp_count"] = len(p.pop("timestamps"))
    return {"todo_sequence": active, "done_states": done, "papers": papers}


def build_state(path: Path, use_mtime: bool, today: dt.date) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    parsed = parse_papers(text)
    mtime = dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    for p in parsed["papers"]:
        if p["last_touched"] is None and use_mtime:
            p["last_touched"] = mtime
            p["last_touched_from"] = "mtime"
        elif p["last_touched"] is not None:
            p["last_touched_from"] = "timestamp"
        else:
            p["last_touched_from"] = None
        p["source"] = f"{path}:{p['line']}"
        p["days_since_touch"] = (
            (today - dt.date.fromisoformat(p["last_touched"])).days if p["last_touched"] else None
        )
    counts: dict[str, int] = {}
    for p in parsed["papers"]:
        counts[p["state"]] = counts.get(p["state"], 0) + 1
    return {
        "kind": "papers",
        "generated": today.isoformat(),
        "source": str(path),
        "todo_sequence": parsed["todo_sequence"],
        "done_states": parsed["done_states"],
        "counts": counts,
        "papers": parsed["papers"],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--papers", required=True, type=Path, help="path to papers.org")
    p.add_argument("--out", type=Path, default=None, help="write JSON here instead of stdout")
    p.add_argument("--mtime", action="store_true", help="use file mtime when no timestamp exists")
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.papers.exists():
        print(f"papers-state: {args.papers} not found", file=sys.stderr)
        return 1
    state = build_state(args.papers, args.mtime, args.today or dt.date.today())
    text = json.dumps(state, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"papers-state: {len(state['papers'])} papers -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
