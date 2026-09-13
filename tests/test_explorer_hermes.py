import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cube.config import Settings
from cube.explorer_hermes import gateway_usage


@pytest.fixture(autouse=True)
def isolated_gateway(settings: Settings) -> None:
    settings.paths.hermes_home = settings.root / "hermes-fixture"


def test_gateway_telemetry_is_numeric_readonly_and_separate(settings: Settings) -> None:
    home = settings.dirs["hermes_home"]
    home.mkdir(parents=True, exist_ok=True)
    path = home / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sessions (source TEXT, started_at REAL, "
            "api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER, "
            "cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
            "actual_cost_usd REAL, estimated_cost_usd REAL)"
        )
        for source, calls in [("mattermost", 9), ("cli", 1000)]:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, 100, 20, 40, 0, NULL, 0.03)",
                (source, datetime.now(UTC).timestamp(), calls),
            )
    before = path.read_bytes()
    result = gateway_usage(settings, 7)
    assert result is not None
    assert result["api_calls"] == 9 and result["sessions"] == 1
    assert result["actual_cost_usd"] is None
    assert result["estimated_cost_usd"] == 0.03
    assert "Lifetime counters" in result["note"]
    assert path.read_bytes() == before


def test_long_running_gateway_session_uses_recent_activity(settings: Settings) -> None:
    home = settings.dirs["hermes_home"]
    home.mkdir(parents=True)
    with sqlite3.connect(home / "state.db") as connection:
        connection.execute(
            "CREATE TABLE sessions (source TEXT, started_at REAL, "
            "last_activity_at REAL, api_call_count INTEGER, input_tokens INTEGER, "
            "output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, "
            "actual_cost_usd REAL, estimated_cost_usd REAL)"
        )
        connection.execute(
            "INSERT INTO sessions VALUES ('mattermost', 0, ?, 312, 100, 20, 0, 0, NULL, 1.0)",
            (datetime.now(UTC).timestamp(),),
        )
    result = gateway_usage(settings, 7)
    assert result and result["api_calls"] == 312 and result["sessions"] == 1
    assert "active in this window" in result["note"]


def test_gateway_unknown_schema_and_missing_database_are_unavailable(settings: Settings) -> None:
    assert gateway_usage(settings, 7) is None
    home = settings.dirs["hermes_home"]
    home.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(home / "state.db") as connection:
        connection.execute("CREATE TABLE sessions (id TEXT)")
    assert gateway_usage(settings, 7) is None


def test_gateway_never_follows_external_database_symlink(
    settings: Settings, tmp_path: Path
) -> None:
    home = settings.dirs["hermes_home"]
    home.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.db"
    outside.write_text("not a database")
    (home / "state.db").symlink_to(outside)
    assert gateway_usage(settings, 7) is None
