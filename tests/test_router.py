from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.config import Settings
from cube.model import Privacy, Tier
from cube.router import (
    Backoff,
    BudgetLedger,
    Queued,
    Refused,
    TierState,
    choose,
    effective_tier,
    parse_reset_time,
)
from cube.runners.base import runner_usage
from cube.runners.codex import parse_events
from tests.helpers_engine import fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def avail(*names: str):  # type: ignore[no-untyped-def]
    return lambda runner: runner in names


def test_first_available_then_fallback(engine_settings: Settings) -> None:
    r = choose(engine_settings, Tier.implement, available=avail("codex", "claude"))
    assert (r.runner, r.profile) == ("codex", "cube-chatgpt")
    r = choose(engine_settings, Tier.implement, available=avail("claude"))
    assert (r.runner, r.model) == ("claude", "sonnet")
    assert "skipping codex unavailable" in r.reason


def test_fleet_paid_cap_does_not_block_local(engine_settings: Settings) -> None:
    from cube.config import TierEntry

    engine_settings.fleet_enabled = True
    engine_settings.budget.daily_total_usd = 10
    engine_settings.tiers = {
        "plan": [
            TierEntry(runner="hermes", provider="local", model="qwen"),
            TierEntry(runner="claude", provider="openrouter", model="glm"),
        ]
    }
    ledger = BudgetLedger(engine_settings.state_dir(), engine_settings)
    ledger.record(Tier.plan, runner="claude@openrouter", cost_usd=10, now=NOW)
    route = choose(
        engine_settings,
        Tier.plan,
        budget=ledger,
        now=NOW,
        available=avail("hermes@local", "claude@openrouter"),
    )
    assert route.runner == "hermes@local"
    with pytest.raises(Queued):
        choose(
            engine_settings, Tier.plan, budget=ledger, now=NOW, available=avail("claude@openrouter")
        )


def test_plan_falls_back_but_explicit_downgrade_is_refused(engine_settings: Settings) -> None:
    route = choose(engine_settings, Tier.plan, available=avail("codex", "openrouter"))
    assert route.runner == "codex" and "fallback from tier plan to implement" in route.reason
    with pytest.raises(Refused, match="never downgraded"):
        choose(
            engine_settings, Tier.plan, requested_runner="openrouter", available=avail("openrouter")
        )
    with pytest.raises(Refused, match="downgrade"):
        effective_tier(Tier.plan, Tier.bulk)
    assert effective_tier(Tier.implement, Tier.plan) == Tier.plan
    assert effective_tier(Tier.bulk, None) == Tier.bulk


def test_requested_runner_within_tier(engine_settings: Settings) -> None:
    r = choose(engine_settings, Tier.plan, requested_runner="claude", available=avail("claude"))
    assert r.model == "fable"
    r = choose(
        engine_settings,
        Tier.plan,
        requested_runner="claude",
        requested_model="opus",
        available=avail("claude"),
    )
    assert r.model == "opus"
    assert choose(engine_settings, Tier.plan, requested_runner="stub").runner == "stub"


def test_local_only_privacy(engine_settings: Settings) -> None:
    with pytest.raises(Queued, match="never goes to cloud"):
        choose(
            engine_settings,
            Tier.bulk,
            privacy=Privacy.local_only,
            available=avail("openrouter", "claude", "codex"),
        )
    r = choose(engine_settings, Tier.bulk, privacy=Privacy.local_only, available=avail("local"))
    assert r.runner == "local"
    r = choose(engine_settings, Tier.plan, privacy=Privacy.local_only, available=avail("local"))
    assert r.runner == "local"
    with pytest.raises(Refused, match="local-only allows only runner"):
        choose(
            engine_settings, Tier.bulk, privacy=Privacy.local_only, requested_runner="openrouter"
        )


def test_tier_none_and_unknown(engine_settings: Settings) -> None:
    with pytest.raises(Refused):
        choose(engine_settings, Tier.none)
    engine_settings.tiers.pop("bulk")
    route = choose(engine_settings, Tier.bulk, available=avail("local"))
    assert route.runner == "local" and "fallback" in route.reason


def test_budget_window(engine_settings: Settings, engine_repo: Path) -> None:
    ledger = BudgetLedger(engine_repo / "state", engine_settings)
    assert ledger.remaining(Tier.plan, NOW) == 2
    assert ledger.remaining(Tier.bulk, NOW) is None
    ledger.record(Tier.plan, usage={"input_tokens": 10, "output_tokens": 5}, cost_usd=0.5, now=NOW)
    ledger.record(Tier.plan, now=NOW)
    assert ledger.exhausted(Tier.plan, NOW)
    assert ledger.day(NOW)["plan"]["tokens"] == 15
    route = choose(engine_settings, Tier.plan, available=avail("claude"), budget=ledger, now=NOW)
    assert route.tier == Tier.implement
    assert "plan budget exhausted" in route.reason
    # a new day resets the window
    assert not ledger.exhausted(Tier.plan, NOW + timedelta(days=1))


def test_budget_records_runner_usage_and_only_billable_cost(
    engine_settings: Settings, engine_repo: Path
) -> None:
    ledger = BudgetLedger(engine_repo / "state", engine_settings)
    ledger.record(
        Tier.plan,
        runner="claude",
        usage={"input_tokens": 10, "output_tokens": 5},
        cost_usd=3.0,
        now=NOW,
    )
    ledger.record(
        Tier.plan,
        usage=runner_usage({"total_tokens": 20, "prompt_tokens": 20}, "openrouter"),
        cost_usd=0.25,
        now=NOW,
    )
    assert ledger.day(NOW)["plan"] == {
        "runs": 2,
        "tokens": 35,
        "cost_usd": 0.25,
        "equivalent_usd": 3.25,
        "estimated": False,
    }
    assert ledger.runner_day(NOW) == {
        "claude": {
            "runs": 1,
            "tokens": 15,
            "cost_usd": 0.0,
            "equivalent_usd": 3.0,
            "estimated": False,
        },
        "openrouter": {
            "runs": 1,
            "tokens": 20,
            "cost_usd": 0.25,
            "equivalent_usd": 0.25,
            "estimated": False,
        },
    }


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("disable", "claude"),
        ("prefer", "claude"),
        ("exhausted", "claude"),
        ("privacy_refusal", "refused"),
    ],
)
def test_runner_controls_are_applied_before_routing(
    engine_settings: Settings,
    engine_repo: Path,
    case: str,
    expected: str,
) -> None:
    controls = TierState(engine_repo / "state")
    if case == "disable":
        controls.disable("codex", until=NOW + timedelta(hours=1), reason="maintenance")
    elif case == "prefer":
        controls.prefer("implement", "claude:sonnet")
    elif case == "exhausted":
        controls.exhaust("codex", error="usage limit reached", now=NOW)
    else:
        with pytest.raises(Refused):
            choose(
                engine_settings,
                Tier.implement,
                privacy=Privacy.local_only,
                requested_runner="claude",
                available=avail("claude", "local"),
                tier_state=controls,
                now=NOW,
            )
        return
    route = choose(
        engine_settings,
        Tier.implement,
        available=avail("codex", "claude"),
        tier_state=controls,
        now=NOW,
    )
    assert route.runner == expected


def test_model_preference_is_first_within_tier(
    engine_settings: Settings, engine_repo: Path
) -> None:
    controls = TierState(engine_repo / "state")
    controls.prefer("plan", "claude:opus")
    route = choose(
        engine_settings,
        Tier.plan,
        available=avail("claude"),
        tier_state=controls,
        now=NOW,
    )
    assert route.model == "opus"


def test_local_only_queues_when_its_runner_is_exhausted(
    engine_settings: Settings, engine_repo: Path
) -> None:
    controls = TierState(engine_repo / "state")
    controls.exhaust("local", error="usage limit reached", now=NOW)
    with pytest.raises(Queued, match="never goes to cloud"):
        choose(
            engine_settings,
            Tier.plan,
            privacy=Privacy.local_only,
            available=avail("local", "claude", "codex"),
            tier_state=controls,
            now=NOW,
        )


def test_backoff_exponential_capped(engine_settings: Settings, engine_repo: Path) -> None:
    b = Backoff(engine_repo / "state")
    until = b.record_failure("codex", error="transient connection failure", now=NOW)
    assert until == NOW + timedelta(seconds=60)
    until = b.record_failure("codex", now=NOW)
    assert until == NOW + timedelta(seconds=120)
    for _ in range(12):
        until = b.record_failure("codex", now=NOW)
    assert until == NOW + timedelta(hours=6)
    assert b.is_blocked("codex", NOW)
    assert not b.is_blocked("codex", NOW + timedelta(hours=7))
    r = choose(
        engine_settings, Tier.implement, available=avail("codex", "claude"), backoff=b, now=NOW
    )
    assert r.runner == "claude" and "backing off" in r.reason
    b.record_success("codex")
    assert not b.is_blocked("codex", NOW)


def test_rate_limit_marks_exhausted_parses_reset_and_notifies(engine_repo: Path) -> None:
    b = Backoff(engine_repo / "state")
    message = "codex usage limit reached; resets at 2026-09-02T13:30:00+00:00"
    outcome = parse_events("", message, 1, "")
    assert outcome.rate_limited and outcome.error is not None
    b.record_failure("codex", error=outcome.error, now=NOW)
    control = TierState(engine_repo / "state").control("codex", now=NOW)
    assert control is not None
    assert control.state == "exhausted" and control.until == "2026-09-02T13:30:00+00:00"
    events = (engine_repo / "state" / "events.jsonl").read_text().splitlines()
    event = json.loads(events[0])
    assert event["severity"] == "high" and event["data"]["kind"] == "budget"
    assert "codex" not in b.state()
    b.record_failure("codex", error=outcome.error, now=NOW)
    assert len((engine_repo / "state" / "events.jsonl").read_text().splitlines()) == 1


def test_claude_epoch_reset_time_is_parsed() -> None:
    expected = NOW + timedelta(hours=3)
    message = f"Claude AI usage limit reached|{int(expected.timestamp())}"
    assert parse_reset_time(message, NOW) == expected


def test_tier_entry_reserved_for_a_role(engine_settings: Settings) -> None:
    """`only:` keeps a subscription runner for one role; everyone else skips it."""
    from cube.config import TierEntry

    engine_settings.tiers["plan"] = [
        TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash"),
        TierEntry(runner="claude", model="fable", only=["group-leader"]),
    ]
    engine_settings.tiers["implement"] = [TierEntry(runner="codex", profile="x")]
    engine_settings.tiers["bulk"] = []
    lead = choose(engine_settings, Tier.plan, available=avail("claude"), role="group-leader")
    assert (lead.runner, lead.model) == ("claude", "fable")
    senior = choose(engine_settings, Tier.plan, available=avail("claude", "codex"), role="senior")
    assert senior.runner == "codex" and "reserved for group-leader" in senior.reason
    with pytest.raises(Queued):
        choose(engine_settings, Tier.plan, available=avail("claude"), role="senior")
    with pytest.raises(Queued):
        choose(engine_settings, Tier.plan, available=avail("claude"))


def test_requested_model_named_by_an_entry_prefers_that_entry(engine_settings: Settings) -> None:
    """Robert 2026-09-05: sysadmin and coordinator pinned to GLM 5.3 Flash.

    The pin lands on the Flash harness entry; the other entries keep their own
    models, so the Max fallback never gets a GLM id.
    """
    from cube.config import TierEntry

    engine_settings.tiers["plan"] = [
        TierEntry(runner="claude", provider="openrouter", model="z-ai/glm-5.3"),
        TierEntry(runner="claude", provider="openrouter", model="z-ai/glm-5.3-flash"),
        TierEntry(runner="claude", model="opus", only=["group-leader"]),
    ]
    engine_settings.tiers["implement"] = []
    engine_settings.tiers["bulk"] = []
    ok = avail("claude@openrouter", "claude")
    route = choose(
        engine_settings,
        Tier.plan,
        requested_model="z-ai/glm-5.3-flash",
        available=ok,
        role="sysadmin",
    )
    assert (route.runner, route.model) == ("claude@openrouter", "z-ai/glm-5.3-flash")
    lead = choose(
        engine_settings,
        Tier.plan,
        requested_model="z-ai/glm-5.3-flash",
        available=avail("claude"),
        role="group-leader",
    )
    assert (lead.runner, lead.model) == ("claude", "opus")
    # an unknown model still overrides the chosen entry, as before
    route = choose(engine_settings, Tier.plan, requested_model="z-ai/glm-6", available=ok)
    assert (route.runner, route.model) == ("claude@openrouter", "z-ai/glm-6")


def test_shipped_tiers_run_local_first_and_fall_back_to_flash() -> None:
    """Robert 2026-09-07 (ADR-0021): the group's own endpoint first, OpenRouter GLM 5.3
    Flash only as the fallback, never the Claude subscription."""
    import yaml

    from cube.config import TierEntry

    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "cube.yaml").read_text())
    tiers = {
        tier: [TierEntry.model_validate(raw) for raw in raws]
        for tier, raws in data["tiers"].items()
    }
    entries = [(tier, entry) for tier, items in tiers.items() for entry in items]
    subscription = [
        (tier, entry)
        for tier, entry in entries
        if entry.runner == "claude" and entry.provider is None
    ]
    assert subscription == []
    assert {entry.runner_name for _, entry in entries if entry.runner == "claude"} == {
        "claude@local",
        "claude@openrouter",
    }
    for tier in ("plan", "implement", "bulk", "local"):
        first = tiers[tier][0]
        assert first.provider == "local" or first.runner == "local", tier
        assert first.model == "qwen3.8-27b", tier
    fallbacks = {
        entry.model
        for _, entry in entries
        if entry.runner_name != "local" and entry.provider != "local"
    }
    assert fallbacks == {"z-ai/glm-5.3-flash"}
    # nothing else on OpenRouter: no ChatGPT subscription entry, no hand-listed free model
    assert not [entry for _, entry in entries if entry.runner_name == "codex"]


def test_openrouter_data_policy_refusal_disables_the_entry_for_a_day(
    engine_repo: Path, engine_settings: Settings
) -> None:
    """A 404 'guardrail restrictions and data policy' is not a rate limit: the
    entry is disabled for 24h so the tier falls through, and Robert is told once."""
    from cube.config import TierEntry
    from cube.engine.run import endpoint_policy_block, execute
    from cube.router.controls import TierState
    from cube.runners import StubRunner

    message = (
        'HTTP 404: {"error":{"message":"0 endpoints out of 1 requested are available '
        "matching your guardrail restrictions and data policy. Free model training "
        'violation (account settings): 1 endpoint excluded"}}'
    )
    assert endpoint_policy_block(message)
    assert endpoint_policy_block("HTTP 429 rate limit") is None
    engine_settings.tiers["bulk"] = [
        TierEntry(runner="openrouter", model="nvidia/nemotron-3-ultra-550b-a55b:free"),
        TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash"),
    ]
    engine_settings.privacy.open_endpoints_for = ["scribe"]
    runner = StubRunner(fail=message)
    runner.name = "openrouter"
    report = execute(
        engine_settings,
        "scribe",
        runner=runner,
        dry_run=False,
        prompt_text="digest",
        available=lambda name: True,
        needs_tools=False,
    )
    assert not report.ok
    controls = TierState(engine_repo / "state")
    control = controls.control("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free")
    assert control is not None and control.state == "disabled"
    assert "data policy" in str(control.reason)
    events = (engine_repo / "state" / "events.jsonl").read_text()
    assert "OpenRouter refuses nvidia/nemotron-3-ultra-550b-a55b:free" in events
    # The next choice for the tier skips the disabled entry.
    route = choose(engine_settings, Tier.bulk, available=avail("openrouter"), tier_state=controls)
    assert route.model == "z-ai/glm-5.3-flash"


def test_openrouter_expired_key_disables_every_openrouter_entry_for_an_hour(
    engine_repo: Path, engine_settings: Settings
) -> None:
    """2026-09-05 11:06 UTC: every run failed with '401 API key expired' for hours.

    One auth failure disables every OpenRouter entry in every tier for an hour
    and raises one high attention event; the next run within the hour adds none.
    """
    from cube.config import TierEntry
    from cube.engine.run import endpoint_auth_block, execute
    from cube.router.controls import TierState
    from cube.runners import StubRunner

    message = (
        "claude reported is_error (success): Failed to authenticate. "
        "API Error: 401 API key expired."
    )
    assert endpoint_auth_block(message) in {"API key expired", "Failed to authenticate"}
    assert endpoint_auth_block("HTTP 429 rate limit") is None
    engine_settings.tiers["plan"] = [
        TierEntry(runner="claude", provider="openrouter", model="z-ai/glm-5.3-flash"),
        TierEntry(runner="claude", model="opus", only=["group-leader"]),
    ]
    engine_settings.tiers["bulk"] = [TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash")]
    runner = StubRunner(fail=message)
    runner.name = "claude@openrouter"
    for _ in range(2):
        report = execute(
            engine_settings,
            "senior",
            runner=runner,
            dry_run=False,
            prompt_text="work",
            available=lambda name: True,
        )
        assert not report.ok
    controls = TierState(engine_repo / "state")
    for runner_name, model in (
        ("claude@openrouter", "z-ai/glm-5.3-flash"),
        ("openrouter", "z-ai/glm-5.3-flash"),
    ):
        control = controls.control(runner_name, model)
        assert control is not None and control.state == "disabled"
        assert "openrouter auth" in str(control.reason)
    assert controls.control("claude", "opus") is None
    events = (engine_repo / "state" / "events.jsonl").read_text()
    assert events.count("OpenRouter rejects the API key") == 1
    lead = choose(
        engine_settings,
        Tier.plan,
        available=avail("claude", "claude@openrouter"),
        tier_state=controls,
        role="group-leader",
    )
    assert (lead.runner, lead.model) == ("claude", "opus")


def test_free_entries_only_for_open_data_agents(engine_settings: Settings) -> None:
    """Free OpenRouter endpoints may train on prompts: only listed agents go there."""
    from cube.config import Price, TierEntry

    engine_settings.tiers["bulk"] = [
        TierEntry(runner="openrouter", model="minimax/minimax-m3:free"),
        TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash"),
    ]
    engine_settings.prices["openrouter:minimax/minimax-m3:free"] = Price(
        input_per_mtok=0, output_per_mtok=0, free=True
    )
    engine_settings.privacy.open_endpoints_for = ["literature"]
    ok = avail("openrouter")

    paid = choose(engine_settings, Tier.bulk, available=ok, role="scribe", agent="ontology")
    assert paid.model == "z-ai/glm-5.3-flash"
    assert "minimax/minimax-m3:free is a free open-data endpoint" in paid.reason

    by_agent = choose(engine_settings, Tier.bulk, available=ok, role="scribe", agent="literature")
    assert by_agent.model == "minimax/minimax-m3:free"

    by_label = choose(
        engine_settings, Tier.bulk, available=ok, role="scribe", labels=["agent:literature"]
    )
    assert by_label.model == "minimax/minimax-m3:free"

    # public beads of other agents still stay off free endpoints: the prompt carries memory
    public = choose(
        engine_settings, Tier.bulk, available=ok, role="group-leader", privacy=Privacy.public
    )
    assert public.model == "z-ai/glm-5.3-flash"

    engine_settings.privacy.open_endpoints_for = []
    nobody = choose(engine_settings, Tier.bulk, available=ok, role="scribe", agent="literature")
    assert nobody.model == "z-ai/glm-5.3-flash"


def test_shipped_config_has_no_hand_listed_free_models() -> None:
    """Free models come from the daily pool; any `:free` id is priced free by rule."""
    from cube.config import load_settings
    from cube.router.prices import is_free

    settings = load_settings(Path(__file__).resolve().parents[1])
    assert settings.privacy.open_endpoints_for == ["literature"]
    assert not [
        entry.model
        for entries in settings.tiers.values()
        for entry in entries
        if entry.model and entry.model.endswith(":free")
    ]
    assert is_free(settings, "openrouter", "anything/new-model:free")
    assert not is_free(settings, "openrouter", "z-ai/glm-5.3-flash")


def test_free_pool_serves_open_data_runs_only(engine_settings: Settings) -> None:
    """The budget patrol's pool goes in front of the bulk tier for an open-data run."""
    import json

    from cube.config import TierEntry
    from cube.router.free_pool import load_pool

    cache = engine_settings.state_dir() / "cache" / "openrouter-models.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "checked": NOW.isoformat(),
                "models": ["a/one:free", "b/two:free"],
                "free": [
                    {"id": "a/one:free", "context_length": 8000, "tools": False},
                    {
                        "id": "b/two:free",
                        "context_length": 128000,
                        "tools": True,
                        "structured": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    engine_settings.tiers["bulk"] = [TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash")]
    engine_settings.privacy.open_endpoints_for = ["literature"]
    assert [m.id for m in load_pool(engine_settings, now=NOW)] == ["b/two:free", "a/one:free"]
    ok = avail("openrouter")

    open_run = choose(engine_settings, Tier.bulk, available=ok, agent="literature", now=NOW)
    assert open_run.model == "b/two:free"
    private = choose(engine_settings, Tier.bulk, available=ok, agent="ontology", now=NOW)
    assert private.model == "z-ai/glm-5.3-flash"
    assert "free" not in private.reason
    # a stale pool is no pool
    later = NOW + timedelta(days=4)
    assert load_pool(engine_settings, now=later) == []
    stale = choose(engine_settings, Tier.bulk, available=ok, agent="literature", now=later)
    assert stale.model == "z-ai/glm-5.3-flash"


def test_openrouter_rate_limit_backs_off_one_target_for_ten_minutes(engine_repo: Path) -> None:
    """A 429 through OpenRouter never exhausts the harness for five hours."""
    b = Backoff(engine_repo / "state")
    until = b.record_failure(
        "claude@openrouter", model="z-ai/glm-5.3-flash", error="HTTP 429 rate limit", now=NOW
    )
    assert until == NOW + timedelta(minutes=10)
    assert b.is_blocked("claude@openrouter", NOW, model="z-ai/glm-5.3-flash")
    assert not b.is_blocked("claude@openrouter", NOW, model="z-ai/glm-5.3")
    assert TierState(engine_repo / "state").control("claude@openrouter") is None
    events = engine_repo / "state" / "events.jsonl"
    assert not events.exists() or "usage exhausted" not in events.read_text()


def test_local_entries_fall_back_to_flash_when_backed_off(engine_settings: Settings) -> None:
    """A failing local run backs its target off; the next choice is OpenRouter Flash."""
    from cube.config import TierEntry

    engine_settings.tiers["plan"] = [
        TierEntry(runner="claude", provider="local", model="qwen3.8-27b"),
        TierEntry(runner="claude", provider="openrouter", model="z-ai/glm-5.3-flash"),
    ]
    engine_settings.env.update({"VLLM_BASE_URL": "http://unimatrix01:8000/v1", "VLLM_API_KEY": "k"})
    ok = avail("claude@local", "claude@openrouter")
    first = choose(engine_settings, Tier.plan, available=ok, now=NOW)
    assert (first.runner, first.model) == ("claude@local", "qwen3.8-27b")
    backoff = Backoff(engine_settings.state_dir())
    backoff.record_failure("claude@local", model="qwen3.8-27b", error="HTTP 502", now=NOW)
    second = choose(engine_settings, Tier.plan, available=ok, backoff=backoff, now=NOW)
    assert (second.runner, second.model) == ("claude@openrouter", "z-ai/glm-5.3-flash")
    assert "claude@local:qwen3.8-27b backing off" in second.reason


def test_free_pool_sits_behind_the_local_entry(engine_settings: Settings) -> None:
    import json

    from cube.config import TierEntry

    cache = engine_settings.state_dir() / "cache" / "openrouter-models.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {"checked": NOW.isoformat(), "models": ["a/one:free"], "free": [{"id": "a/one:free"}]}
        ),
        encoding="utf-8",
    )
    engine_settings.tiers["bulk"] = [
        TierEntry(runner="local", model="qwen3.8-27b"),
        TierEntry(runner="openrouter", model="z-ai/glm-5.3-flash"),
    ]
    engine_settings.privacy.open_endpoints_for = ["literature"]
    engine_settings.env["VLLM_BASE_URL"] = "http://unimatrix01:8000/v1"
    ok = avail("openrouter", "local")
    route = choose(engine_settings, Tier.bulk, available=ok, agent="literature", now=NOW)
    assert (route.runner, route.model) == ("local", "qwen3.8-27b")
    backoff = Backoff(engine_settings.state_dir())
    backoff.record_failure("local", model="qwen3.8-27b", error="HTTP 502", now=NOW)
    route = choose(
        engine_settings, Tier.bulk, available=ok, agent="literature", backoff=backoff, now=NOW
    )
    assert route.model == "a/one:free"


def test_not_for_keeps_the_sysadmin_on_claude_and_the_programmer_on_codex(
    engine_settings: Settings,
) -> None:
    from cube.config import TierEntry

    engine_settings.tiers["plan"] = [
        TierEntry(
            runner="hermes",
            provider="local",
            model="q",
            profile="cube-worker",
            not_for=["sysadmin"],
        ),
        TierEntry(runner="claude", provider="local", model="q"),
    ]
    engine_settings.env["VLLM_BASE_URL"] = "http://unimatrix01:8000/v1"
    ok = avail("hermes@local", "claude@local")
    senior = choose(engine_settings, Tier.plan, available=ok, role="senior", needs_tools=True)
    assert (senior.runner, senior.profile) == ("hermes@local", "cube-worker")
    sysadmin = choose(engine_settings, Tier.plan, available=ok, role="sysadmin", needs_tools=True)
    assert sysadmin.runner == "claude@local"
    assert "hermes@local:q not for sysadmin" in sysadmin.reason
