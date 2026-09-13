from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.cli import main
from cube.commands.budget import budget_data
from cube.config import Settings
from cube.model import Privacy, Tier
from cube.roles import load_role
from cube.router import BudgetLedger, TierState, choose
from cube.runners import OpenAICompatRunner, RunContext
from cube.runners.base import runner_usage
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _json(capsys: pytest.CaptureFixture[str]) -> dict:  # type: ignore[type-arg]
    return json.loads(capsys.readouterr().out)


def test_budget_contract_and_history(
    engine_repo: Path,
    engine_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cube.commands.budget._now", lambda now=None: now or NOW)
    ledger = BudgetLedger(engine_repo / "state", engine_settings)
    ledger.record(
        Tier.plan,
        usage=runner_usage({"input_tokens": 7, "output_tokens": 3}, "claude"),
        cost_usd=9.0,
        now=NOW,
    )
    ledger.record(
        Tier.implement,
        usage=runner_usage({"total_tokens": 20}, "openrouter"),
        cost_usd=0.125,
        now=NOW,
    )
    assert main(["--root", str(engine_repo), "budget", "--days", "2", "--json"]) == 0
    out = _json(capsys)
    assert out == budget_data(engine_settings, days=2, now=NOW)
    assert out["generated"] == "2026-09-02T09:00:00+00:00"
    assert out["day"] == "2026-09-02"
    assert out["tiers"]["plan"] == {
        "runs": 1,
        "tokens": 10,
        "cost_usd": 0.0,
        "equivalent_usd": 9.0,
        "cap_runs": 4,
        "cap_cost_usd": None,
        "cap_equivalent_usd": None,
        "pct": 25.0,
    }
    assert out["tiers"]["implement"]["cost_usd"] == 0.125
    assert out["runners"]["claude"]["cost_usd"] == 0.0
    assert out["runners"]["claude"]["equivalent_usd"] == 9.0
    assert out["runners"]["openrouter"]["cost_usd"] == 0.125
    assert out["window"] == {
        "since": "2026-09-01T00:00:00+00:00",
        "until": "2026-09-03T00:00:00+00:00",
    }


def test_openrouter_response_cost_reaches_runner_ledger(
    engine_repo: Path, engine_settings: Settings
) -> None:
    def post(url: str, headers: object, body: bytes, timeout: float) -> tuple[int, bytes]:
        return 200, json.dumps(
            {
                "id": "generation-1",
                "choices": [{"message": {"content": '{"summary":"done"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.004},
            }
        ).encode()

    context = RunContext(
        run_id="r-cost",
        role=load_role(REPO_ROOT, "scribe"),
        prompt="test",
        cwd=engine_repo,
        run_dir=engine_repo / "runs" / "r-cost",
        model="z-ai/glm-5.3-flash",
    )
    outcome = OpenAICompatRunner("openrouter", "https://openrouter.ai/api/v1", http_post=post).run(
        context
    )
    assert outcome.cost_usd == 0.004
    BudgetLedger(engine_repo / "state", engine_settings).record(
        Tier.bulk, usage=outcome.usage, cost_usd=outcome.cost_usd, now=NOW
    )
    runner = BudgetLedger(engine_repo / "state", engine_settings).runner_day(NOW)["openrouter"]
    assert runner == {
        "runs": 1,
        "tokens": 12,
        "cost_usd": 0.004,
        "equivalent_usd": 0.004,
        "estimated": False,
    }


def test_tier_cli_dry_run_apply_show_enable_prefer_and_reset(
    engine_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cube.commands.tier._now", lambda: NOW)
    root = ["--root", str(engine_repo), "tier"]
    assert main([*root, "disable", "codex", "--for", "5h", "--json"]) == 0
    assert _json(capsys) == {
        "action": "disable",
        "target": "codex",
        "until": "2026-09-02T14:00:00+00:00",
        "reason": None,
        "changed": True,
        "dry_run": True,
    }
    assert not (engine_repo / "state" / "tiers.json").exists()

    assert (
        main(
            [
                *root,
                "disable",
                "codex",
                "--for",
                "5h",
                "--reason",
                "subscription reset",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    _json(capsys)
    assert main([*root, "--json"]) == 0
    shown = _json(capsys)
    codex = shown["tiers"]["implement"][0]
    assert codex == {
        "runner": "codex",
        "model": None,
        "profile": "cube-chatgpt",
        "state": "disabled",
        "until": "2026-09-02T14:00:00+00:00",
        "reason": "subscription reset",
        "active": False,
    }

    assert main([*root, "prefer", "plan", "claude:opus", "--apply", "--json"]) == 0
    _json(capsys)
    assert main([*root, "show", "--json"]) == 0
    plan = _json(capsys)["tiers"]["plan"]
    assert [entry["state"] for entry in plan] == ["ok", "preferred"]
    assert [entry["active"] for entry in plan] == [False, True]

    assert main([*root, "enable", "codex", "--apply", "--json"]) == 0
    assert _json(capsys)["changed"] is True
    assert main([*root, "reset", "--apply", "--json"]) == 0
    assert _json(capsys)["changed"] is True
    assert json.loads((engine_repo / "state" / "tiers.json").read_text()) == {}


def test_status_includes_budget_contract(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cube.commands.budget._now", lambda now=None: now or NOW)
    assert main(["--root", str(engine_repo), "status", "--json"]) == 0
    status = _json(capsys)
    assert status["budget"] == {
        "plan": 0.0,
        "implement": 0.0,
        "bulk": None,
        "local": None,
        "exhausted": [],
    }


def test_downgrade_cli_status_and_undowngrade(
    engine_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cube.commands.tier._now", lambda: NOW)
    root = ["--root", str(engine_repo), "tier"]
    assert main([*root, "downgrade", "plan", "implement", "--for", "5h", "--json"]) == 0
    assert _json(capsys)["dry_run"] is True
    assert not (engine_repo / "state" / "tiers.json").exists()

    assert (
        main(
            [
                *root,
                "downgrade",
                "plan",
                "implement",
                "--for",
                "5h",
                "--reason",
                "cost",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    _json(capsys)
    assert main([*root, "status", "--json"]) == 0
    status = _json(capsys)
    assert status["downgrades"] == [
        {
            "tier": "plan",
            "to": "implement",
            "until": "2026-09-02T14:00:00+00:00",
            "reason": "cost",
        }
    ]
    assert status["swaps"] == []

    assert main([*root, "undowngrade", "plan", "--apply", "--json"]) == 0
    assert _json(capsys)["changed"] is True


def test_downgrade_protects_review_design_and_local_only(engine_settings: Settings) -> None:
    controls = TierState(engine_settings.state_dir())
    controls.downgrade("plan", "implement", until=NOW + timedelta(hours=5), reason="soft cap")
    common = {
        "available": lambda runner: True,
        "budget": BudgetLedger(engine_settings.state_dir(), engine_settings),
        "now": NOW,
    }
    task = choose(engine_settings, Tier.plan, labels=["kind:task"], **common)  # type: ignore[arg-type]
    assert task.runner == "codex"
    assert "downgraded from plan to implement" in task.reason
    review = choose(
        engine_settings,
        Tier.plan,
        labels=["kind:review"],
        **common,  # type: ignore[arg-type]
    )
    design = choose(
        engine_settings,
        Tier.plan,
        labels=["stage:design"],
        **common,  # type: ignore[arg-type]
    )
    assert (review.runner, review.model) == ("claude", "fable")
    assert (design.runner, design.model) == ("claude", "fable")

    controls.downgrade("local", "bulk", until=NOW + timedelta(hours=5), reason="manual")
    local = choose(
        engine_settings,
        Tier.local,
        privacy=Privacy.local_only,
        available=lambda runner: True,
        now=NOW,
    )
    assert local.runner == "local"


def test_budget_week_cli_shape(
    engine_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("cube.commands.budget._now", lambda now=None: now or NOW)
    assert main(["--root", str(engine_repo), "budget", "--week", "--json"]) == 0
    data = _json(capsys)
    assert data["days"] == 7
    assert set(data) >= {"attribution", "forecast", "controls", "ceilings"}
    assert main(["--root", str(engine_repo), "budget", "--week"]) == 0
    text = capsys.readouterr().out
    assert "ATTRIBUTION" in text
    assert "CEILINGS" in text
    assert "FORECAST" in text
