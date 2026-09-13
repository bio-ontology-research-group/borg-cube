from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from cube.commands.budget import budget_data
from cube.config import Price, Settings
from cube.model import Tier
from cube.patrols import base
from cube.patrols.budget import BudgetPatrol
from cube.router import BudgetLedger, TierState
from tests.helpers_engine import fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _empty_interactive_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cube.patrols.budget.import_interactive",
        lambda settings, **kwargs: {"added": {}, "windows": []},
    )
    monkeypatch.setattr(
        "cube.patrols.budget.fetch_openrouter_models",
        lambda: {"data": []},
    )


def _run_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr("cube.patrols.budget._now", lambda value=None: value or now)


def test_soft_cap_downgrades_when_no_cheaper_entry_and_is_idempotent(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.budget.plan_runs_per_day = 10
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for _ in range(9):
        ledger.record(Tier.plan, runner="claude", now=NOW)

    patrol = BudgetPatrol(availability=lambda runner: True)
    first = base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    control_events = [event for event in first.events if event["data"]["kind"] == "budget"]
    assert len(control_events) == 1
    assert control_events[0]["severity"] == "high"
    assert "soft cap 90% on claude:fable until" in str(control_events[0]["title"])
    downgrade = TierState(engine_settings.state_dir()).downgrades(now=NOW)["plan"]
    assert downgrade["to"] == "implement"

    second = base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    assert second.events == []
    events = (engine_settings.state_dir() / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2


def test_reset_clears_budget_preference(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.budget.plan_runs_per_day = 10
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for _ in range(9):
        ledger.record(Tier.plan, runner="claude", now=NOW)
    patrol = BudgetPatrol(availability=lambda runner: True)
    base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)

    next_day = NOW + timedelta(days=1)
    _run_now(monkeypatch, next_day)
    report = base.run_patrol(
        engine_settings, patrol, today=next_day.date(), dry_run=False, now=next_day
    )
    assert report.events == []
    assert TierState(engine_settings.state_dir()).preference("plan") is None
    assert TierState(engine_settings.state_dir()).budget_swaps() == []
    assert TierState(engine_settings.state_dir()).downgrades(now=next_day) == {}


def test_openrouter_floor_downgrades_when_no_cheaper_entry(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.env["OPENROUTER_API_KEY"] = "test-secret-token"
    seen: list[str] = []

    def credits(key: str) -> float:
        seen.append(key)
        return 4.0

    report = BudgetPatrol(
        availability=lambda runner: True,
        credits_fetcher=credits,
    ).run(engine_settings, NOW.date(), True)
    assert seen == ["test-secret-token"]
    assert report.events and report.events[0]["data"]["runner"] == "openrouter"
    assert TierState(engine_settings.state_dir()).preference("implement") is None
    downgrade = report.data["downgrades"][0]
    assert downgrade["tier"] == "implement"
    assert downgrade["to"] == "bulk"


def test_missing_openrouter_key_warns_without_secret_output(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    secret = "not-in-settings-or-output"
    engine_settings.env.pop("OPENROUTER_API_KEY", None)
    report = BudgetPatrol(
        availability=lambda runner: True,
        credits_fetcher=lambda key: pytest.fail(f"unexpected key {key}"),
    ).run(engine_settings, NOW.date(), True)
    encoded = json.dumps(report.as_dict())
    assert "OPENROUTER_API_KEY missing" in encoded
    assert secret not in encoded
    assert "Bearer" not in encoded


def test_budget_json_has_windows_credits_and_one_swap(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.learn_window(
        "claude",
        started=NOW - timedelta(hours=5),
        resets=NOW + timedelta(hours=1),
        tokens=100,
    )
    ledger.save_credits(4.0, checked=NOW)
    controls = TierState(engine_settings.state_dir())
    controls.set_budget_preference(
        "implement",
        source="codex",
        target="claude:sonnet",
        until=NOW + timedelta(hours=1),
        reason="soft cap 90% on codex until 2026-09-02T10:00",
    )
    data = budget_data(engine_settings, now=NOW)
    assert set(data) >= {"windows", "credits", "swaps"}
    assert set(data["windows"]["claude"]) == {"started", "resets", "tokens", "cap", "pct"}
    assert data["windows"]["claude"]["pct"] == 100.0
    assert data["credits"] == {
        "openrouter": {"remaining_usd": 4.0, "checked": "2026-09-02T09:00:00+00:00"}
    }
    assert data["swaps"] == [
        {
            "tier": "implement",
            "from": "codex",
            "to": "claude:sonnet",
            "until": "2026-09-02T10:00:00+00:00",
            "reason": "soft cap 90% on codex until 2026-09-02T10:00",
        }
    ]


def test_swap_uses_cheapest_active_entry(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.prices = {
        "default": Price(input_per_mtok=3.0, output_per_mtok=15.0),
        "codex": Price(input_per_mtok=1.25, output_per_mtok=10.0),
        "claude:sonnet": Price(input_per_mtok=3.0, output_per_mtok=15.0),
        "openrouter:qwen/qwen3-coder": Price(input_per_mtok=0.2, output_per_mtok=0.8),
    }
    engine_settings.budget.implement_runs_per_day = 10
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for _ in range(9):
        ledger.record(Tier.implement, runner="codex", now=NOW)

    report = base.run_patrol(
        engine_settings,
        BudgetPatrol(availability=lambda runner: True),
        today=NOW.date(),
        dry_run=False,
        now=NOW,
    )
    swap = next(item for item in report.data["swaps"] if item["tier"] == "implement")
    assert swap["from"] == "codex"
    assert swap["to"] == "openrouter:qwen/qwen3-coder"


def test_downgrade_clears_when_usage_recovers(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.budget.plan_runs_per_day = 10
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for _ in range(9):
        ledger.record(Tier.plan, runner="claude", model="fable", now=NOW)
    patrol = BudgetPatrol(availability=lambda runner: True)
    base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    assert TierState(engine_settings.state_dir()).downgrades(now=NOW)

    engine_settings.budget.plan_runs_per_day = 100
    later = NOW + timedelta(minutes=30)
    _run_now(monkeypatch, later)
    base.run_patrol(engine_settings, patrol, today=later.date(), dry_run=False, now=later)
    assert TierState(engine_settings.state_dir()).downgrades(now=later) == {}


def test_alerts_are_once_per_day_and_patrol_imports_usage(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    calls: list[dict[str, object]] = []

    def fake_import(settings: Settings, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"added": {"claude": 10}, "windows": []}

    monkeypatch.setattr("cube.patrols.budget.import_interactive", fake_import)
    engine_settings.budget.bulk_runs_per_day = 10
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for _ in range(7):
        ledger.record(Tier.bulk, runner="local", now=NOW)
    patrol = BudgetPatrol(availability=lambda runner: True)
    first = base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    second = base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    alerts = [event for event in first.events if event["data"].get("kind") == "budget-alert"]
    assert [event["severity"] for event in alerts] == ["warn"]
    assert [event for event in second.events if event["data"].get("kind") == "budget-alert"] == []
    assert calls and all(call["apply"] is True for call in calls)
    assert first.data["import"] == {"claude": 10}

    for _ in range(3):
        ledger.record(Tier.bulk, runner="local", now=NOW)
    third = base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    high = [event for event in third.events if event["data"].get("kind") == "budget-alert"]
    assert [event["severity"] for event in high] == ["high"]


def test_weekly_event_is_emitted_on_mondays_first_tick(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monday = datetime(2026, 9, 7, 6, 0, tzinfo=UTC)
    _run_now(monkeypatch, monday)
    engine_settings.budget.weekly_total_usd = 100.0
    BudgetLedger(engine_settings.state_dir(), engine_settings).record(
        Tier.plan, runner="claude", cost_usd=3.0, now=monday
    )
    patrol = BudgetPatrol(availability=lambda runner: True)
    first = base.run_patrol(engine_settings, patrol, today=monday.date(), dry_run=False, now=monday)
    second = base.run_patrol(
        engine_settings, patrol, today=monday.date(), dry_run=False, now=monday
    )
    weekly = [event for event in first.events if event["data"].get("kind") == "budget-weekly"]
    assert len(weekly) == 1
    assert weekly[0]["data"]["equivalent_usd"] == pytest.approx(3.0)
    assert [event for event in second.events if event["data"].get("kind") == "budget-weekly"] == []


def test_openrouter_control_clears_above_double_floor(
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_now(monkeypatch, NOW)
    engine_settings.env["OPENROUTER_API_KEY"] = "test-secret-token"
    balances = iter((4.0, 11.0))
    patrol = BudgetPatrol(
        availability=lambda runner: True,
        credits_fetcher=lambda key: next(balances),
    )
    base.run_patrol(engine_settings, patrol, today=NOW.date(), dry_run=False, now=NOW)
    controls = TierState(engine_settings.state_dir())
    assert controls.budget_swaps(now=NOW) or controls.downgrades(now=NOW)

    later = NOW + timedelta(minutes=15)
    _run_now(monkeypatch, later)
    base.run_patrol(engine_settings, patrol, today=later.date(), dry_run=False, now=later)
    assert controls.budget_swaps(now=later) == []
    assert controls.downgrades(now=later) == {}
