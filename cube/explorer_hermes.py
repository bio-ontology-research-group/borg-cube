"""Numeric-only, read-only gateway telemetry. Never query message or prompt text."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from cube.config import Settings


def gateway_usage(settings: Settings, days: int) -> dict[str, Any] | None:
    home = settings.dirs["hermes_home"]
    candidates = [home / "profiles" / "hermes-ws" / "state.db", home / "state.db"]
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
    for path in candidates:
        if not path.is_file() or not path.resolve().is_relative_to(home.resolve()):
            continue
        try:
            with sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
            ) as connection:
                connection.execute("PRAGMA query_only=ON")
                columns = {entry[1] for entry in connection.execute("PRAGMA table_info(sessions)")}
                activity = (
                    "coalesce(last_activity_at, started_at)"
                    if "last_activity_at" in columns
                    else "started_at"
                )
                row = connection.execute(
                    "SELECT count(*), sum(api_call_count), sum(input_tokens), "
                    "sum(output_tokens), sum(cache_read_tokens), sum(cache_write_tokens), "
                    "sum(actual_cost_usd), sum(estimated_cost_usd), count(actual_cost_usd) "
                    "FROM sessions WHERE source = 'mattermost' AND " + activity + " >= ?",
                    (since.timestamp(),),
                ).fetchone()
        except sqlite3.Error:
            continue
        if row is None:
            continue
        return {
            "sessions": row[0],
            "api_calls": row[1] or 0,
            "input_tokens": row[2] or 0,
            "output_tokens": row[3] or 0,
            "cache_read_tokens": row[4] or 0,
            "cache_write_tokens": row[5] or 0,
            "actual_cost_usd": row[6],
            "estimated_cost_usd": row[7],
            "cost_sessions_known": row[8],
            "source": str(path.relative_to(home)),
            "note": "Lifetime counters for Mattermost sessions active in this window. "
            "Not per-call daily usage; separate from workday totals. No message text is read.",
        }
    return None
