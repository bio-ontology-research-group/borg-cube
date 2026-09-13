#!/usr/bin/env python3
"""Render signals JSON into the group briefing (and a separate Robert-only student file).

Reads the output of diff_state.py and assets/briefing-template.md, fills the
sections (Attention, Changes since last run, Approaching deadlines, Waiting on
Robert, Positive changes, Notes, footer) and writes Markdown. Student signals
(privacy local-only) never enter the group briefing: they go to
``--students-out`` and the briefing states only their count and location.

The renderer enforces the house style on its own output: no em-dash, headings
in sentence case, at most ``--max-lines`` lines. It is dry-run by default;
pass ``--apply`` to write files.

Example:
  briefing_render.py --signals state/signals.json --out briefings/group/2026-09-02.md \
      --students-out briefings/students/2026-09-02.md --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "briefing-template.md"
EM_DASH = "—"
NONE = "- nothing to report"


class RenderError(Exception):
    """Raised when the output would violate the house style."""


def line_for(s: dict[str, Any]) -> str:
    src = f" ({s['source']})" if s.get("source") else ""
    due = f" due {s['deadline']}" if s.get("deadline") else ""
    return f"- {s['message']}{due}{src}"


def sort_key(s: dict[str, Any]) -> tuple[int, str, str]:
    return (0 if s.get("deadline") else 1, s.get("deadline") or "9999", s["message"])


def sections(
    signals: dict[str, Any], attention_max: int, students_path: Path | None
) -> dict[str, str]:
    group = [s for s in signals["signals"] if s.get("privacy") != "local-only"]
    students = [s for s in signals["signals"] if s.get("privacy") == "local-only"]
    attention = sorted((s for s in group if s["severity"] == "attention"), key=sort_key)
    changes = [s for s in group if s["severity"] in ("change", "cleared")]
    deadlines = sorted((s for s in group if s.get("deadline")), key=sort_key)
    waiting = [s for s in group if s["severity"] == "waiting"]
    positive = [s for s in group if s["severity"] == "positive"]
    notes = [s for s in group if s["severity"] == "note"]

    def block(items: list[dict[str, Any]]) -> str:
        return "\n".join(line_for(s) for s in items) if items else NONE

    att_lines = [line_for(s) for s in attention[:attention_max]]
    if len(attention) > attention_max:
        att_lines.append(
            f"- and {len(attention) - attention_max} more attention items in the signals file"
        )
    unchanged = signals.get("unchanged", {})
    change_lines = [line_for(s) for s in changes]
    if unchanged:
        change_lines.append(
            "- unchanged: " + ", ".join(f"{n} {kind}" for kind, n in sorted(unchanged.items()))
        )
    if not signals.get("previous_present"):
        change_lines.append("- first run for these snapshots; no previous state to diff against")
    note_lines = [line_for(s) for s in notes]
    n_students = len([s for s in students if s["severity"] == "attention"])
    if students_path is not None:
        note_lines.append(
            f"- {n_students} student signal(s) need attention; Robert-only file: {students_path}"
        )
    elif students:
        note_lines.append(f"- {n_students} student signal(s) withheld (no --students-out given)")
    return {
        "ATTENTION": "\n".join(att_lines) if att_lines else NONE,
        "CHANGES": "\n".join(change_lines) if change_lines else NONE,
        "DEADLINES": block(deadlines),
        "WAITING": block(waiting),
        "POSITIVE": block(positive),
        "NOTES": "\n".join(note_lines) if note_lines else NONE,
    }


def render(
    signals: dict[str, Any],
    template: str,
    today: dt.date,
    attention_max: int,
    students_path: Path | None,
    signals_path: str,
) -> str:
    parts = sections(signals, attention_max, students_path)
    parts["DATE"] = today.isoformat()
    parts["WEEKDAY"] = today.strftime("%A")
    parts["FOOTER"] = (
        f"state: {signals_path}; thresholds {signals.get('thresholds_version')}; "
        f"generated {signals.get('generated')}; snapshots "
        f"{', '.join(signals.get('current_present', []))}"
    )
    out = template
    for key, val in parts.items():
        out = out.replace("{{" + key + "}}", val)
    return out.rstrip() + "\n"


def render_students(signals: dict[str, Any], today: dt.date) -> str:
    students = [s for s in signals["signals"] if s.get("privacy") == "local-only"]
    lines = [
        f"# Student signals - {today.isoformat()} ({today.strftime('%A')})",
        "",
        "Robert-only. Privacy class local-only; never post or forward.",
        "",
    ]
    for severity, title in (
        ("attention", "Attention"),
        ("positive", "Positive changes"),
        ("change", "Changes"),
        ("cleared", "Cleared"),
        ("note", "Notes"),
    ):
        items = [s for s in students if s["severity"] == severity]
        if not items:
            continue
        lines.append(f"## {title}")
        lines += [line_for(s) for s in sorted(items, key=sort_key)]
        lines.append("")
    if len(lines) == 4:
        lines.append(NONE)
    return "\n".join(lines).rstrip() + "\n"


def check_style(text: str, max_lines: int) -> None:
    if EM_DASH in text:
        raise RenderError("output contains an em-dash")
    for line in text.splitlines():
        if line.startswith("#"):
            words = line.lstrip("#").strip().split()
            for w in words[1:]:
                if re.match(r"^[A-Z][a-z]+$", w) and w not in {"Robert"}:
                    raise RenderError(f"heading not in sentence case: {line!r}")
    if len(text.splitlines()) > max_lines:
        raise RenderError(f"briefing has {len(text.splitlines())} lines (max {max_lines})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--signals", required=True, type=Path)
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p.add_argument("--out", type=Path, default=None, help="group briefing path")
    p.add_argument("--students-out", type=Path, default=None, help="Robert-only student file")
    p.add_argument("--attention-max", type=int, default=5)
    p.add_argument("--max-lines", type=int, default=60)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    p.add_argument(
        "--apply", action="store_true", help="write files (default is a dry run to stdout)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        signals = json.loads(args.signals.read_text(encoding="utf-8"))
        template = args.template.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"briefing-render: {exc}", file=sys.stderr)
        return 1
    today = args.today or dt.date.today()
    briefing = render(
        signals, template, today, args.attention_max, args.students_out, str(args.signals)
    )
    students = render_students(signals, today)
    try:
        check_style(briefing, args.max_lines)
        check_style(students, 10_000)
    except RenderError as exc:
        print(f"briefing-render: {exc}", file=sys.stderr)
        return 2
    if not args.apply or not args.out:
        print(briefing, end="")
        if args.students_out:
            print(
                f"\n[dry-run] student file would be written to {args.students_out} "
                f"({len(students.splitlines())} lines)"
            )
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(briefing, encoding="utf-8")
    written = [str(args.out)]
    if args.students_out:
        args.students_out.parent.mkdir(parents=True, exist_ok=True)
        args.students_out.write_text(students, encoding="utf-8")
        written.append(str(args.students_out))
    print("briefing-render: wrote " + ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
