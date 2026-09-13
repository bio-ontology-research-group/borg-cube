"""``cube goals --json``: goal progress, risks, blockers, and next owners."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, now_iso, today_from
from cube.config import Settings
from cube.goals import goal_header, goal_row, read_goal_ledger


def cmd_goals(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, True)
    issues, ready, blocked = read_goal_ledger(beads)
    today = today_from(args) or date.today()
    rows = [
        goal_row(settings, issue, issues, ready, blocked, today=today)
        for issue in issues
        if goal_header(issue) is not None
    ]
    rows.sort(key=lambda row: (row["status"] in {"done", "dropped"}, row["target"], row["id"]))
    payload = {"generated": now_iso(), "goals": rows}
    text = (
        "\n".join(
            f"{row['id']:12} {row['status']:8} {row['progress']['pct']:3}% "
            f"{row['days_left']:4}d {row['title']}"
            for row in rows
        )
        or "no goals"
    )
    helpers.emit(args, payload, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("goals", help="goal progress, blockers, and next work")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda args, settings: cmd_goals(args, settings, helpers))
