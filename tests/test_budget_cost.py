"""Cost measurement, binding ceilings, attribution, and budget views."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from cube.commands.budget import budget_data
from cube.config import Price, ProjectRunnerProfile, Settings
from cube.engine import execute
from cube.model import Tier
from cube.router import BudgetLedger, choose
from cube.router.policy import budget_block, record_agent_spend
from cube.router.prices import estimate_usd, price_warnings, reset_price_warnings
from cube.runners.base import runner_usage
from cube.runners.claude_code import parse_envelope
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)

PRICES = {
    "default": Price(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude:fable": Price(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude:opus": Price(input_per_mtok=15.0, output_per_mtok=75.0),
    "claude:sonnet": Price(input_per_mtok=3.0, output_per_mtok=15.0),
    "codex": Price(input_per_mtok=1.25, output_per_mtok=10.0),
    "openrouter:qwen/qwen3-coder": Price(input_per_mtok=0.2, output_per_mtok=0.8),
    "openrouter:z-ai/glm-5.3-flash": Price(input_per_mtok=0.1, output_per_mtok=0.4),
    "local": Price(input_per_mtok=0.0, output_per_mtok=0.0),
    "stub": Price(input_per_mtok=0.0, output_per_mtok=0.0),
}


@pytest.fixture(autouse=True)
def _clean_price_warnings() -> None:
    reset_price_warnings()


def _priced(settings: Settings) -> Settings:
    settings.prices = dict(PRICES)
    return settings


def _header(privacy: str = "internal") -> str:
    return f"---\nxid: test:1\nprivacy: {privacy}\n---\n"


def test_claude_cli_cost_becomes_equivalent_usd(engine_settings: Settings) -> None:
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "s-1",
            "total_cost_usd": 0.4231,
            "usage": {"input_tokens": 1200, "output_tokens": 400},
            "result": '{"summary":"done (source: runs/x)"}',
        }
    )
    outcome = parse_envelope(envelope, "", 0)
    assert outcome.cost_usd == 0.4231

    ledger = BudgetLedger(engine_settings.state_dir(), _priced(engine_settings))
    record = ledger.record(
        Tier.plan,
        runner="claude",
        model="fable",
        usage=runner_usage(outcome.usage, "claude"),
        cost_usd=outcome.cost_usd,
        now=NOW,
    )
    assert record["estimated"] is False
    assert record["cost_usd"] == 0.0
    assert record["equivalent_usd"] == pytest.approx(0.4231)
    assert ledger.runner_day(NOW)["claude"]["equivalent_usd"] == pytest.approx(0.4231)


def test_codex_equivalent_is_estimated_from_price_table(engine_settings: Settings) -> None:
    ledger = BudgetLedger(engine_settings.state_dir(), _priced(engine_settings))
    record = ledger.record(
        Tier.implement,
        runner="codex",
        usage=runner_usage({"input_tokens": 1_000_000, "output_tokens": 100_000}, "codex"),
        now=NOW,
    )
    assert record["estimated"] is True
    assert record["equivalent_usd"] == pytest.approx(2.25)
    assert ledger.day(NOW)["implement"]["cost_usd"] == 0.0


def test_missing_price_warns_once_and_estimates_zero(engine_settings: Settings) -> None:
    engine_settings.prices = {}
    usage = {"input_tokens": 1000, "output_tokens": 10}
    assert estimate_usd(engine_settings, "mystery", "m-1", usage) == (0.0, False)
    assert estimate_usd(engine_settings, "mystery", "m-1", usage) == (0.0, False)
    assert price_warnings() == ["no price for mystery:m-1; counting 0 USD equivalent"]


def test_price_table_requires_default_and_nonnegative_rates() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"prices": {"codex": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}}
        )
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {"prices": {"default": {"input_per_mtok": -1.0, "output_per_mtok": 2.0}}}
        )


def test_attribution_records_project_and_epic(engine_settings: Settings) -> None:
    ledger = BudgetLedger(engine_settings.state_dir(), _priced(engine_settings))
    ledger.record(
        Tier.implement,
        runner="openrouter",
        model="qwen/qwen3-coder",
        usage=runner_usage({"total_tokens": 100}, "openrouter"),
        cost_usd=0.25,
        labels=["project:widget", "goal:cube-99", "kind:task"],
        now=NOW,
    )
    ledger.record(
        Tier.implement,
        runner="openrouter",
        model="qwen/qwen3-coder",
        usage=runner_usage({"total_tokens": 100}, "openrouter"),
        cost_usd=0.25,
        labels=["project:widget"],
        now=NOW,
    )
    attribution = ledger.attribution(NOW)
    assert attribution["projects"]["widget"]["equivalent_usd"] == pytest.approx(0.5)
    assert attribution["projects"]["widget"]["cost_usd"] == pytest.approx(0.5)
    assert attribution["projects"]["widget"]["runs"] == 2
    assert attribution["goals"]["cube-99"]["equivalent_usd"] == pytest.approx(0.25)
    assert attribution["goals"]["cube-99"]["runs"] == 1


def test_record_agent_spend_reconciles_measured_cost(engine_settings: Settings) -> None:
    path = engine_settings.state_dir() / "agents" / "genomics" / "resources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "date": NOW.date().isoformat(),
                "gpu_hours": 0.0,
                "runs": 1,
                "spend_usd": 2.0,
            }
        ),
        encoding="utf-8",
    )

    class Report:
        runs = [
            {"cost_usd": 0.25, "equivalent_usd": 1.5},
            {"cost_usd": None, "equivalent_usd": 0.5},
        ]

    usage = record_agent_spend(engine_settings, "genomics", Report(), now=NOW)
    assert usage["spend_usd"] == pytest.approx(2.25)
    assert usage["equivalent_usd"] == pytest.approx(2.0)
    assert json.loads(path.read_text(encoding="utf-8"))["equivalent_usd"] == pytest.approx(2.0)


def test_exhausted_by_billed_and_equivalent_cost(engine_settings: Settings) -> None:
    _priced(engine_settings)
    engine_settings.budget.implement_cost_usd_per_day = 1.0
    engine_settings.budget.equivalent_cap_usd_per_day = {"plan": 2.0}
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.record(
        Tier.implement,
        runner="openrouter",
        model="qwen/qwen3-coder",
        cost_usd=1.0,
        now=NOW,
    )
    assert ledger.exhausted(Tier.implement, NOW) is True
    ledger.record(Tier.plan, runner="claude", model="fable", cost_usd=2.5, now=NOW)
    assert ledger.exhausted(Tier.plan, NOW) is True


def test_daily_total_exhausts_every_tier(engine_settings: Settings) -> None:
    _priced(engine_settings)
    engine_settings.budget.daily_total_usd = 1.0
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.record(Tier.plan, runner="claude", model="fable", cost_usd=1.5, now=NOW)
    assert ledger.exhausted(Tier.bulk, NOW) is True
    assert ledger.spend_today(NOW)["equivalent_usd"] == pytest.approx(1.5)


def test_cost_exhausted_tier_falls_back(engine_settings: Settings) -> None:
    _priced(engine_settings)
    engine_settings.budget.equivalent_cap_usd_per_day = {"plan": 1.0}
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.record(Tier.plan, runner="claude", model="fable", cost_usd=1.5, now=NOW)
    route = choose(
        engine_settings,
        Tier.plan,
        available=lambda runner: True,
        budget=ledger,
        now=NOW,
    )
    assert route.runner == "codex"
    assert "fallback from tier plan to implement" in route.reason
    assert "plan budget exhausted" in route.reason


def test_project_and_epic_budget_block(engine_settings: Settings) -> None:
    _priced(engine_settings)
    engine_settings.projects["widget"] = ProjectRunnerProfile(
        path=Path("widget"), runner="stub", budget_usd_per_day=0.5
    )
    engine_settings.pipeline.budget_usd_per_epic = 0.75
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.record(
        Tier.implement,
        runner="openrouter",
        model="qwen/qwen3-coder",
        cost_usd=0.8,
        labels=["project:widget", "goal:cube-99"],
        now=NOW,
    )
    project = budget_block(engine_settings, ledger, ["project:widget"], now=NOW)
    assert project is not None and project.reason == "budget:project"
    assert project.target == "widget"
    epic = budget_block(engine_settings, ledger, ["goal:cube-99"], now=NOW)
    assert epic is not None and epic.reason == "budget:epic"


def test_run_refuses_project_budget_and_alerts_once(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _priced(engine_settings)
    (engine_repo / "widget").mkdir()
    engine_settings.projects["widget"] = ProjectRunnerProfile(
        path=Path("widget"), runner="stub", cwd="checkout", budget_usd_per_day=0.5
    )
    BudgetLedger(engine_settings.state_dir(), engine_settings).record(
        Tier.implement,
        runner="openrouter",
        model="qwen/qwen3-coder",
        cost_usd=0.9,
        labels=["project:widget"],
        now=NOW,
    )
    fake_bd.add(
        "cube-40",
        title="Implement the widget",
        labels=["stage:implement", "project:widget"],
        description=_header(),
    )
    first = execute(engine_settings, "programmer", bead="cube-40", runner_name="stub", now=NOW)
    second = execute(engine_settings, "programmer", bead="cube-40", runner_name="stub", now=NOW)
    assert first.state == second.state == "refused"
    assert first.error is not None and first.error.startswith("budget:project")
    events = [
        json.loads(line)
        for line in (engine_repo / "state" / "events.jsonl").read_text().splitlines()
    ]
    attention = [event for event in events if event["event"] == "attention"]
    assert len(attention) == 1
    assert attention[0]["data"]["needs"] == "robert"
    assert attention[0]["data"]["reason"] == "budget:project"


def test_budget_view_adds_attribution_forecast_controls_and_ceilings(
    engine_settings: Settings,
) -> None:
    _priced(engine_settings)
    engine_settings.budget.plan_runs_per_day = 4
    engine_settings.budget.equivalent_cap_usd_per_day = {"plan": 10.0}
    engine_settings.budget.daily_total_usd = 50.0
    engine_settings.projects["widget"] = ProjectRunnerProfile(
        path=Path("widget"), runner="stub", budget_usd_per_day=5.0
    )
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    for hour in (6, 7, 8):
        ledger.record(
            Tier.plan,
            runner="claude",
            model="fable",
            usage=runner_usage({"input_tokens": 10, "output_tokens": 5}, "claude"),
            cost_usd=1.0,
            labels=["project:widget", "goal:cube-99"],
            now=NOW.replace(hour=hour),
        )
    data = budget_data(engine_settings, now=NOW)
    assert set(data) >= {"attribution", "forecast", "controls", "ceilings"}
    assert data["attribution"]["projects"]["widget"]["today"]["equivalent_usd"] == pytest.approx(
        3.0
    )
    assert data["attribution"]["projects"]["widget"]["cap_usd_per_day"] == 5.0
    assert data["attribution"]["epics"]["cube-99"]["week"]["equivalent_usd"] == pytest.approx(3.0)
    forecast = data["forecast"]["tiers"]["plan"]
    assert forecast["burn_usd_per_hour"] == pytest.approx(1.0)
    assert forecast["projected_day_end_usd"] == pytest.approx(18.0)
    assert data["controls"] == {"swaps": [], "downgrades": []}
    names = {ceiling["name"] for ceiling in data["ceilings"]}
    assert {"plan runs", "plan equivalent", "daily total", "project widget"} <= names
    plan_runs = next(item for item in data["ceilings"] if item["name"] == "plan runs")
    assert plan_runs["used"] == 3
    assert plan_runs["cap"] == 4
    assert plan_runs["pct"] == 75.0


def test_week_view_includes_prior_days(engine_settings: Settings) -> None:
    ledger = BudgetLedger(engine_settings.state_dir(), _priced(engine_settings))
    ledger.record(
        Tier.bulk,
        runner="openrouter",
        model="z-ai/glm-5.3-flash",
        cost_usd=0.5,
        labels=["project:widget"],
        now=NOW - timedelta(days=3),
    )
    data = budget_data(engine_settings, days=7, now=NOW)
    assert data["days"] == 7
    assert data["tiers"]["bulk"]["equivalent_usd"] == pytest.approx(0.5)
    assert data["attribution"]["projects"]["widget"]["week"]["equivalent_usd"] == pytest.approx(0.5)
