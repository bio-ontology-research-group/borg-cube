#!/usr/bin/env python3
"""Turn a lecture plan YAML into a minute-by-minute timeline and flag the timing.

Reads the same plan as ``outcome_lint.py`` (see
``assets/lecture-plan.yaml.example``) and prints one row per segment with its
start and end minute, its clock time when the plan gives a ``start``, and its
kind. Then it flags:

* any stretch of direct instruction longer than ``--max-direct`` minutes with
  no activity in it;
* any stretch of class time longer than ``--break-after`` minutes with no
  break;
* any gap longer than ``--check-every`` minutes between formative checks,
  including the gap from the start of class to the first check;
* a session that does not open with retrieval within ``--opening-within``
  minutes, or does not close with a written check (minute paper, muddiest
  point, exit ticket) in its last ``--closing-within`` minutes;
* a segment total that does not match ``length_minutes``;
* a missing timing contingency, which is the segment to drop when the session
  runs late.

The thresholds are our defaults, not findings: no source gives a tested value
for a graduate class (references/lecture-delivery.md, "Not covered"). Every
flag names the threshold it used, so a course can change it and say so.

Exit status: 0 when the plan could be read (flags are printed), 2 when the plan
is malformed, or when ``--strict`` is given and any flag was raised.

Examples:
  timebox.py --plan assets/lecture-plan.yaml.example
  timebox.py --plan plans/cs249-08.yaml --max-direct 12 --strict --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from outcome_lint import (
    ACTIVITY_KINDS,
    BREAK_KINDS,
    CHECK_KINDS,
    DIRECT_KINDS,
    PlanError,
    load_plan,
)

# Checks that leave a written record the instructor reads after class.
WRITTEN_CHECK_KINDS: set[str] = {"exit-ticket", "minute-paper", "muddiest-point"}
# Checks that ask students to retrieve rather than recognise.
RETRIEVAL_KINDS: set[str] = {"peer-instruction", "poll", "quiz", "retrieval"}

DEFAULTS = {
    "max_direct": 15,
    "break_after": 50,
    "check_every": 15,
    "opening_within": 10,
    "closing_within": 10,
    "tolerance": 0,
}


class Row:
    """One segment placed on the clock."""

    def __init__(self, sid: str, kind: str, minutes: int, start: int, what: str) -> None:
        self.id = sid
        self.kind = kind
        self.minutes = minutes
        self.start = start
        self.end = start + minutes
        self.what = what

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "minutes": self.minutes,
            "start": self.start,
            "end": self.end,
            "what": self.what,
        }


def parse_start(plan: dict[str, Any]) -> int | None:
    """Minutes since midnight for the plan's ``start``, or None."""
    raw = plan.get("start")
    if raw is None:
        return None
    text = str(raw).strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise PlanError(f"start {text!r} is not HH:MM")
    hours, minutes = int(parts[0]), int(parts[1])
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise PlanError(f"start {text!r} is not a time of day")
    return hours * 60 + minutes


def clock(base: int | None, offset: int) -> str:
    if base is None:
        return ""
    total = (base + offset) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def build_rows(plan: dict[str, Any]) -> list[Row]:
    rows: list[Row] = []
    cursor = 0
    for i, segment in enumerate(plan["segments"], 1):
        sid = str(segment.get("id") or f"segment[{i}]")
        kind = str(segment.get("kind", "")).strip().lower()
        minutes = segment.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            raise PlanError(f"segment {sid}: minutes must be a positive integer")
        rows.append(Row(sid, kind, minutes, cursor, str(segment.get("what") or "")))
        cursor += minutes
    return rows


def flag_direct_runs(rows: list[Row], limit: int) -> list[str]:
    """Stretches of direct instruction with no activity, longer than the limit."""
    flags: list[str] = []
    run: list[Row] = []

    def close_run() -> None:
        if not run:
            return
        total = sum(r.minutes for r in run)
        if total > limit:
            ids = ", ".join(r.id for r in run)
            flags.append(
                f"direct instruction runs {total} minutes from minute {run[0].start} "
                f"({ids}); our threshold is {limit} minutes, so break it with an activity"
            )
        run.clear()

    for row in rows:
        if row.kind in DIRECT_KINDS:
            run.append(row)
        elif row.kind in ACTIVITY_KINDS or row.kind in BREAK_KINDS:
            close_run()
    close_run()
    return flags


def flag_breaks(rows: list[Row], limit: int, length: int) -> list[str]:
    flags: list[str] = []
    if length <= limit:
        return flags
    last_break_end = 0
    for row in rows:
        if row.kind in BREAK_KINDS:
            if row.start - last_break_end > limit:
                flags.append(
                    f"{row.start - last_break_end} minutes of class from minute "
                    f"{last_break_end} to the break at minute {row.start}; our threshold is "
                    f"{limit} minutes"
                )
            last_break_end = row.end
    end = rows[-1].end if rows else 0
    if end - last_break_end > limit:
        flags.append(
            f"{end - last_break_end} minutes of class from minute {last_break_end} to the end "
            f"with no break; our threshold is {limit} minutes"
        )
    return flags


def flag_check_gaps(rows: list[Row], limit: int) -> list[str]:
    """Gaps between formative checks, counting class time only."""
    flags: list[str] = []
    checks = [r for r in rows if r.kind in CHECK_KINDS]
    if not checks:
        flags.append(
            "no formative check in the session: nothing evidences what the class understood "
            "while there is time to act on it"
        )
        return flags
    marker = 0
    for row in checks:
        gap = class_minutes(rows, marker, row.start)
        if gap > limit:
            flags.append(
                f"{gap} minutes of class with no check before {row.id} at minute {row.start}; "
                f"our threshold is {limit} minutes"
            )
        marker = row.end
    end = rows[-1].end
    tail = class_minutes(rows, marker, end)
    if tail > limit:
        flags.append(
            f"{tail} minutes of class after the last check at minute {marker}; our threshold "
            f"is {limit} minutes"
        )
    return flags


def class_minutes(rows: list[Row], start: int, end: int) -> int:
    """Minutes between two offsets that are not break time."""
    total = 0
    for row in rows:
        if row.kind in BREAK_KINDS:
            continue
        overlap = min(row.end, end) - max(row.start, start)
        if overlap > 0:
            total += overlap
    return total


def flag_opening_and_closing(rows: list[Row], opening: int, closing: int) -> list[str]:
    flags: list[str] = []
    end = rows[-1].end if rows else 0
    if not any(r.kind in RETRIEVAL_KINDS and r.start < opening for r in rows):
        flags.append(
            f"the session does not open with retrieval in its first {opening} minutes; students "
            "start from cold"
        )
    if not any(r.kind in WRITTEN_CHECK_KINDS and r.end > end - closing for r in rows):
        flags.append(
            f"the session does not close with a written check (minute paper, muddiest point, "
            f"exit ticket) in its last {closing} minutes; the next session has nothing to answer"
        )
    return flags


def flag_total(plan: dict[str, Any], rows: list[Row], tolerance: int) -> list[str]:
    length = plan.get("length_minutes")
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        raise PlanError("length_minutes must be a positive integer")
    total = rows[-1].end if rows else 0
    if abs(total - length) > tolerance:
        direction = "over" if total > length else "under"
        flags = [
            f"segments total {total} minutes against a class length of {length}: "
            f"{abs(total - length)} minutes {direction}"
        ]
        return flags
    return []


def flag_contingency(plan: dict[str, Any]) -> list[str]:
    value = plan.get("contingency")
    if not isinstance(value, str) or not value.strip():
        return [
            "no contingency: name the segment to drop when the session runs late, and it is "
            "never a check or the closing"
        ]
    segments = plan.get("segments")
    if not isinstance(segments, list):
        return [f"contingency {value!r} does not name a segment"]
    match = re.search(r"\bdrop\s+([A-Za-z0-9][A-Za-z0-9_-]*)\b", value, re.IGNORECASE)
    sid = match.group(1) if match else value.strip()
    matching = [segment for segment in segments if str(segment.get("id", "")) == sid]
    if not matching:
        return [f"contingency {value!r} does not name an existing segment"]
    kind = str(matching[0].get("kind", "")).strip().lower()
    reasons: list[str] = []
    if kind in CHECK_KINDS:
        reasons.append("check")
    if matching[0] is segments[-1]:
        reasons.append("closing")
    if reasons:
        return [f"contingency cannot drop {', '.join(reasons)} segment {sid!r}"]
    return []


def analyze(plan: dict[str, Any], thresholds: dict[str, int]) -> dict[str, Any]:
    rows = build_rows(plan)
    length = plan.get("length_minutes")
    flags: list[str] = []
    flags += flag_total(plan, rows, thresholds["tolerance"])
    flags += flag_direct_runs(rows, thresholds["max_direct"])
    flags += flag_breaks(rows, thresholds["break_after"], int(length))
    flags += flag_check_gaps(rows, thresholds["check_every"])
    flags += flag_opening_and_closing(
        rows, thresholds["opening_within"], thresholds["closing_within"]
    )
    flags += flag_contingency(plan)
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row.kind] = kinds.get(row.kind, 0) + row.minutes
    direct = sum(m for k, m in kinds.items() if k in DIRECT_KINDS)
    active = sum(m for k, m in kinds.items() if k in ACTIVITY_KINDS)
    return {
        "course": str(plan.get("course", "")),
        "title": str(plan.get("title", "")),
        "length_minutes": length,
        "start": plan.get("start"),
        "timeline": [row.to_json() for row in rows],
        "minutes_by_kind": dict(sorted(kinds.items())),
        "direct_minutes": direct,
        "active_minutes": active,
        "thresholds": dict(thresholds),
        "flags": flags,
        "ok": not flags,
    }


def render_text(plan: dict[str, Any], result: dict[str, Any]) -> str:
    base = parse_start(plan)
    lines = [f"timebox: {result['course']}, {result['title']}"]
    header = f"  {'min':>7}  {'clock':>11}  {'kind':<16}  segment"
    lines.append(header)
    for row in result["timeline"]:
        span = f"{row['start']:>3}-{row['end']:<3}"
        times = (
            f"{clock(base, row['start'])}-{clock(base, row['end'])}" if base is not None else ""
        )
        what = row["what"]
        label = f"{row['id']}: {what}" if what else row["id"]
        lines.append(f"  {span:>7}  {times:>11}  {row['kind']:<16}  {label}")
    total = result["timeline"][-1]["end"] if result["timeline"] else 0
    lines.append(
        f"  total {total} minutes, {result['direct_minutes']} direct, "
        f"{result['active_minutes']} active, class length {result['length_minutes']}"
    )
    if result["flags"]:
        for flag in result["flags"]:
            lines.append(f"  FLAG {flag}")
    else:
        lines.append("  no flags")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--plan", type=Path, required=False, help="lecture plan YAML")
    p.add_argument(
        "--max-direct",
        type=int,
        default=DEFAULTS["max_direct"],
        help="longest stretch of direct instruction in minutes (group choice)",
    )
    p.add_argument(
        "--break-after",
        type=int,
        default=DEFAULTS["break_after"],
        help="longest stretch of class time before a break (group choice)",
    )
    p.add_argument(
        "--check-every",
        type=int,
        default=DEFAULTS["check_every"],
        help="longest gap between formative checks (group choice)",
    )
    p.add_argument(
        "--opening-within",
        type=int,
        default=DEFAULTS["opening_within"],
        help="the opening retrieval must start within this many minutes",
    )
    p.add_argument(
        "--closing-within",
        type=int,
        default=DEFAULTS["closing_within"],
        help="the written closing check must fall in the last this many minutes",
    )
    p.add_argument(
        "--tolerance", type=int, default=DEFAULTS["tolerance"], help="allowed total mismatch"
    )
    p.add_argument("--json", action="store_true", help="machine-readable timeline and flags")
    p.add_argument("--strict", action="store_true", help="exit 2 when any flag was raised")
    p.add_argument("--out", type=Path, default=None, help="write the timeline here as well")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.plan:
        print("timebox: --plan is required", file=sys.stderr)
        return 2
    thresholds = {
        "max_direct": args.max_direct,
        "break_after": args.break_after,
        "check_every": args.check_every,
        "opening_within": args.opening_within,
        "closing_within": args.closing_within,
        "tolerance": args.tolerance,
    }
    try:
        plan = load_plan(args.plan)
        parse_start(plan)
        result = analyze(plan, thresholds)
        text = json.dumps(result, indent=2) + "\n" if args.json else render_text(plan, result)
    except PlanError as exc:
        print(f"timebox: {exc}", file=sys.stderr)
        return 2
    print(text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 2 if (args.strict and result["flags"]) else 0


if __name__ == "__main__":
    sys.exit(main())
