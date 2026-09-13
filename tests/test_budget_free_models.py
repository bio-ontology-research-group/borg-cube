from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cube.cli import main
from cube.config import Price, Settings, TierEntry, load_settings
from cube.config import Privacy as PrivacyConfig
from cube.doctor import check_openrouter_free
from cube.model import Tier
from cube.patrols.budget import BudgetPatrol
from cube.roles import load_role
from cube.router import Backoff, TierState, choose
from cube.router.prices import estimate_usd
from cube.runners import OpenAICompatRunner, RunContext
from tests.helpers_engine import REPO_ROOT

NOW = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "minimax/minimax-m3:free",
    "z-ai/glm-5.2:free",
]


# Free entries are open-data endpoints; only listed agents may use them (ADR-0018).
OPEN = {"agent": "literature"}


def _settings(root: Path) -> Settings:
    settings = Settings(
        privacy=PrivacyConfig(open_endpoints_for=["literature"]),
        tiers={
            "implement": [
                TierEntry(runner="codex", profile="cube-chatgpt"),
                TierEntry(runner="openrouter", model=FREE_MODELS[0]),
                TierEntry(runner="openrouter", model=FREE_MODELS[1]),
                TierEntry(runner="claude", model="sonnet"),
            ],
            "bulk": [
                *(TierEntry(runner="openrouter", model=model) for model in FREE_MODELS),
                TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash"),
                TierEntry(runner="local"),
            ],
            "local": [TierEntry(runner="local")],
        },
        prices={
            "default": Price(input_per_mtok=3, output_per_mtok=15),
            **{
                f"openrouter:{model}": Price(input_per_mtok=0, output_per_mtok=0, free=True)
                for model in FREE_MODELS
            },
            "claude:sonnet": Price(input_per_mtok=3, output_per_mtok=15),
            "codex": Price(input_per_mtok=1.25, output_per_mtok=10),
            "openrouter:z-ai/glm-5.3-flash": Price(input_per_mtok=0.1, output_per_mtok=0.4),
            "local": Price(input_per_mtok=0, output_per_mtok=0),
        },
    )
    settings.root = root
    return settings


def test_repo_config_prices_local_and_flash_and_free_by_rule() -> None:
    settings = load_settings(REPO_ROOT)
    # Robert, 2026-09-07: Hermes and the local endpoint first, Flash as the fallback,
    # no hand-listed free models (ADR-0021, ADR-0022).
    assert [entry.runner_name for entry in settings.tiers["bulk"]] == [
        "hermes@local",
        "local",
        "openrouter",
    ]
    assert settings.tiers["implement"][0].runner_name == "codex@local"
    plan = settings.tiers["plan"]
    assert plan[0].runner_name == "hermes@local" and plan[0].not_for == ["sysadmin"]
    assert plan[1].runner_name == "claude@local"
    for runner in ("hermes@local", "claude@local", "codex@local", "local"):
        assert estimate_usd(settings, runner, "qwen3.8-27b", {"prompt_tokens": 1000}) == (0.0, True)
    for model in FREE_MODELS:
        assert f"openrouter:{model}" not in settings.prices
        assert estimate_usd(settings, "openrouter", model, {"prompt_tokens": 1000}) == (0.0, True)


def test_config_rejects_invalid_free_prices() -> None:
    with pytest.raises(ValidationError, match="free prices must be zero"):
        Price(input_per_mtok=0.1, output_per_mtok=0, free=True)
    with pytest.raises(ValidationError, match="must have an exact free price"):
        Settings.model_validate(
            {
                "tiers": {"bulk": [{"runner": "openrouter", "model": "example/model:free"}]},
                "prices": {"default": {"input_per_mtok": 1, "output_per_mtok": 1}},
            }
        )


def test_choose_bulk_is_free_first(tmp_path: Path) -> None:
    route = choose(_settings(tmp_path), Tier.bulk, available=lambda runner: True, now=NOW, **OPEN)
    assert (route.runner, route.model) == ("openrouter", FREE_MODELS[0])


def test_choose_bulk_skips_free_entries_for_everyone_else(tmp_path: Path) -> None:
    route = choose(
        _settings(tmp_path), Tier.bulk, available=lambda runner: True, now=NOW, agent="ontology"
    )
    assert (route.runner, route.model) == ("openrouter", "z-ai/glm-5.3-flash")
    assert "free open-data endpoint" in route.reason


def test_budget_swap_prefers_free_and_never_swaps_free_to_paid(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    paid = TierEntry(runner="codex")
    zero_cost_local = TierEntry(runner="local")
    free = TierEntry(runner="openrouter", model=FREE_MODELS[0])
    source, target = BudgetPatrol._swap_targets(settings, [paid, zero_cost_local, free], "codex")
    assert source == "codex"
    assert target == f"openrouter:{FREE_MODELS[0]}"
    assert BudgetPatrol._swap_targets(settings, [free, paid], f"openrouter:{FREE_MODELS[0]}") == (
        f"openrouter:{FREE_MODELS[0]}",
        None,
    )


def test_free_first_cli_apply_and_off(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    configured = _settings(root)
    payload = configured.model_dump(mode="json", exclude={"root", "env"})
    (root / "cube.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    command = ["--root", str(root), "tier", "free-first", "implement", "--json"]

    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (root / "state" / "tiers.json").exists()

    assert main([*command, "--apply"]) == 0
    capsys.readouterr()
    raw = json.loads((root / "state" / "tiers.json").read_text(encoding="utf-8"))
    assert raw["preferences"]["implement"] == {
        "target": f"openrouter:{FREE_MODELS[0]}",
        "reason": "robert: free-first",
    }
    assert TierState(root / "state").preference("implement") == (f"openrouter:{FREE_MODELS[0]}")

    assert main([*command, "--off", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert TierState(root / "state").preference("implement") is None


@pytest.mark.parametrize(
    "message",
    [
        "HTTP 429: rate limit reached for free model",
        "free model capacity unavailable",
        "HTTP 404: No endpoints available for this model",
    ],
)
def test_free_model_errors_back_off_for_ten_minutes(tmp_path: Path, message: str) -> None:
    backoff = Backoff(tmp_path)
    assert Backoff.looks_rate_limited(message)
    until = backoff.record_failure("openrouter", model=FREE_MODELS[0], error=message, now=NOW)
    assert until == NOW + timedelta(minutes=10)
    assert backoff.is_blocked("openrouter", NOW, model=FREE_MODELS[0])
    assert not backoff.is_blocked("openrouter", NOW, model=FREE_MODELS[1])


def test_free_model_target_form_uses_the_same_backoff(tmp_path: Path) -> None:
    backoff = Backoff(tmp_path)
    until = backoff.record_failure(
        f"openrouter:{FREE_MODELS[0]}", error="HTTP 404: No endpoints", now=NOW
    )
    assert until == NOW + timedelta(minutes=10)
    assert backoff.is_blocked("openrouter", NOW, model=FREE_MODELS[0])


def test_free_backoff_moves_to_next_free_then_warns_on_paid_fallback(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    backoff = Backoff(settings.state_dir())
    backoff.record_failure("openrouter", model=FREE_MODELS[0], error="HTTP 429", now=NOW)
    route = choose(
        settings,
        Tier.implement,
        available=lambda runner: runner != "codex",
        backoff=backoff,
        now=NOW,
        **OPEN,
    )
    assert route.model == FREE_MODELS[1]

    backoff.record_failure("openrouter", model=FREE_MODELS[1], error="free capacity", now=NOW)
    route = choose(
        settings,
        Tier.implement,
        available=lambda runner: runner != "codex",
        backoff=backoff,
        **OPEN,
        now=NOW,
    )
    assert (route.runner, route.model) == ("claude", "sonnet")
    events = [
        json.loads(line)
        for line in (settings.state_dir() / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "attention"
    assert events[-1]["severity"] == "warn"
    assert events[-1]["title"] == "free models exhausted, paid fallback in use"


def test_openrouter_404_no_endpoints_is_rate_limited(tmp_path: Path) -> None:
    runner = OpenAICompatRunner(
        "openrouter",
        "https://openrouter.ai/api/v1",
        http_post=lambda url, headers, body, timeout: (
            404,
            b'{"error":"No endpoints available for this free model"}',
        ),
    )
    outcome = runner.run(
        RunContext(
            run_id="r-free",
            role=load_role(REPO_ROOT, "concierge"),
            prompt="test",
            cwd=tmp_path,
            run_dir=tmp_path / "run",
            model=FREE_MODELS[0],
        )
    )
    assert outcome.rate_limited is True
    assert f"model={FREE_MODELS[0]}" in outcome.command


def test_doctor_reports_the_free_pool(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    cache = settings.state_dir() / "cache" / "openrouter-models.json"
    cache.parent.mkdir(parents=True)
    # hand-listed free entries in tiers are flagged; a cache without a pool too
    cache.write_text(
        json.dumps({"checked": NOW.isoformat(), "models": FREE_MODELS[:2]}),
        encoding="utf-8",
    )
    checks = {check.name: check for check in check_openrouter_free(settings)}
    assert not checks["openrouter:free-models"].ok
    assert not checks["openrouter:free-pool"].ok
    assert "cube patrol budget --apply" in checks["openrouter:free-pool"].detail

    settings.tiers["implement"] = [
        entry for entry in settings.tiers["implement"] if not entry.model
    ]
    settings.tiers["bulk"] = [
        entry for entry in settings.tiers["bulk"] if not (entry.model or "").endswith(":free")
    ]
    cache.write_text(
        json.dumps(
            {
                "checked": datetime.now(UTC).isoformat(),
                "models": FREE_MODELS,
                "free": [{"id": model, "context_length": 1000} for model in FREE_MODELS],
            }
        ),
        encoding="utf-8",
    )
    checks = {check.name: check for check in check_openrouter_free(settings)}
    assert set(checks) == {"openrouter:free-pool"}
    assert checks["openrouter:free-pool"].ok
    assert "3 of 3 free models" in checks["openrouter:free-pool"].detail


def test_budget_patrol_refreshes_openrouter_models_once_a_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    calls: list[bool] = []
    monkeypatch.setattr("cube.patrols.budget._now", lambda value=None: value or NOW)
    monkeypatch.setattr(
        "cube.patrols.budget.import_interactive",
        lambda settings, **kwargs: {"added": {}, "windows": []},
    )
    patrol = BudgetPatrol(
        availability=lambda runner: True,
        models_fetcher=lambda: (
            calls.append(True) or {"data": [{"id": model} for model in FREE_MODELS]}
        ),
    )
    patrol.run(settings, NOW.date(), False)
    patrol.run(settings, NOW.date(), False)
    assert calls == [True]
    cached = json.loads(
        (settings.state_dir() / "cache" / "openrouter-models.json").read_text(encoding="utf-8")
    )
    assert cached["models"] == FREE_MODELS
    # a `:free` id without pricing data still counts; equal ranks sort by id
    assert [item["id"] for item in cached["free"]] == sorted(FREE_MODELS)


def test_budget_patrol_caches_the_free_pool_with_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("cube.patrols.budget._now", lambda value=None: value or NOW)
    monkeypatch.setattr(
        "cube.patrols.budget.import_interactive",
        lambda settings, **kwargs: {"added": {}, "windows": []},
    )
    cache = settings.state_dir() / "cache" / "openrouter-models.json"
    cache.parent.mkdir(parents=True)
    # an older cache without the pool is refreshed even on the same day
    cache.write_text(json.dumps({"checked": NOW.isoformat(), "models": ["x"]}), encoding="utf-8")
    catalogue = {
        "data": [
            {
                "id": FREE_MODELS[0],
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 1000000,
                "supported_parameters": ["tools", "temperature"],
            },
            {
                "id": FREE_MODELS[1],
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 200000,
                "supported_parameters": ["response_format", "tools"],
            },
            {"id": "paid/model", "pricing": {"prompt": "0.1", "completion": "0.2"}},
            {"id": "odd/zero-priced-not-free", "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }
    calls: list[bool] = []
    patrol = BudgetPatrol(
        availability=lambda runner: True,
        models_fetcher=lambda: calls.append(True) or catalogue,
    )
    patrol.run(settings, NOW.date(), False)
    assert calls == [True]
    cached = json.loads(cache.read_text(encoding="utf-8"))
    assert [item["id"] for item in cached["free"]] == [FREE_MODELS[1], FREE_MODELS[0]]
    assert cached["free"][0] == {
        "id": FREE_MODELS[1],
        "context_length": 200000,
        "tools": True,
        "structured": True,
    }


def test_free_price_estimate_is_zero(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert estimate_usd(
        settings,
        "openrouter",
        FREE_MODELS[0],
        {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    ) == (0.0, True)


def test_every_bulk_role_has_free_runner_hint() -> None:
    bulk = []
    for path in sorted((REPO_ROOT / "roles").glob("[!_]*.yaml")):
        role = load_role(REPO_ROOT, path.stem)
        if role.tier == Tier.bulk:
            bulk.append(role.name)
            assert role.runner_hint == "free"
    assert set(bulk) == {"concierge", "marshal", "scribe"}


def test_openrouter_calls_carry_the_run_data_policy(tmp_path: Path) -> None:
    runner = OpenAICompatRunner("openrouter", "https://openrouter.ai/api", api_key="k")
    ctx = RunContext(
        run_id="r-paid",
        role=load_role(REPO_ROOT, "concierge"),
        prompt="test",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        model="z-ai/glm-5.3-flash",
    )
    assert runner.payload(ctx)["provider"] == {"data_collection": "deny"}
    ctx.model = FREE_MODELS[0]
    assert runner.payload(ctx)["provider"] == {"data_collection": "deny"}
    ctx.open_data = True
    assert runner.payload(ctx)["provider"] == {"data_collection": "allow"}
    local = OpenAICompatRunner("local", "http://node005:8000")
    ctx.model = "qwen"
    assert "provider" not in local.payload(ctx)
