"""Agentic harnesses on OpenRouter: tokens, routing, runners, cost and doctor (ADR-0016)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cube.config import Settings, TierEntry, load_settings
from cube.doctor import check_codex_openrouter_profile, check_codex_profile, check_harness_providers
from cube.engine.run import derive_needs_tools, execute
from cube.model import Tier
from cube.roles import load_role, result_schema
from cube.router import BudgetLedger, Queued, choose
from cube.router.controls import entry_target, split_target
from cube.router.policy import default_availability
from cube.runners import ClaudeCodeRunner, CodexRunner, RunContext, make_runner
from cube.runners.base import ExecResult
from cube.runners.claude_code import (
    OPENROUTER_ANTHROPIC_BASE,
    parse_envelope,
    strip_harmless_stderr,
)
from cube.runners.codex import DEFAULT_PROFILE, OPENROUTER_PROFILE
from cube.runners.naming import (
    AGENTIC_HARNESSES,
    NATIVE_PROVIDER,
    compose,
    harness_of,
    is_agentic,
    provider_of,
)
from tests.helpers_engine import REPO_ROOT, RecordingExec, fixtures, make_repo

globals().update(fixtures())

NOW = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
KEY = "sk-or-secret-token"
GOOD = json.dumps({"summary": "done (source: tests)", "next_actions": ["x"]})

HARNESS_YAML = """\
host: testhost
paths: {pa: pa, org: org, rkg: rkg, runs: runs, state: state, skills_library: skills-lib}
tiers:
  plan:
    - {runner: claude, provider: openrouter, model: z-ai/glm-5.3}
    - {runner: openrouter, model: z-ai/glm-5.3-flash}
    - {runner: claude, model: opus, only: [group-leader]}
  implement:
    - {runner: codex, provider: openrouter, model: z-ai/glm-5.3-flash}
    - {runner: openrouter, model: xiaomi/mimo-v2.5}
  bulk:
    - {runner: openrouter, model: xiaomi/mimo-v2.5}
  local:
    - {runner: local}
prices:
  default: {input_per_mtok: 3.0, output_per_mtok: 15.0}
  claude@openrouter:z-ai/glm-5.3: {input_per_mtok: 1.4, output_per_mtok: 4.4}
  claude@openrouter:z-ai/glm-5.3-flash: {input_per_mtok: 0.075, output_per_mtok: 0.25}
  codex@openrouter:z-ai/glm-5.3-flash: {input_per_mtok: 0.075, output_per_mtok: 0.25}
  openrouter:z-ai/glm-5.3-flash: {input_per_mtok: 0.075, output_per_mtok: 0.25}
"""


@pytest.fixture
def harness_repo(tmp_path: Path) -> Path:
    root = make_repo(tmp_path)
    (root / "cube.yaml").write_text(HARNESS_YAML, encoding="utf-8")
    return root


@pytest.fixture
def harness_settings(harness_repo: Path) -> Settings:
    settings = load_settings(harness_repo)
    settings.env = {"OPENROUTER_API_KEY": KEY}
    return settings


def avail(*names: str):  # type: ignore[no-untyped-def]
    return lambda runner: runner in names


def ctx(tmp_path: Path, role: str, **kw: Any) -> RunContext:
    base: dict[str, Any] = {
        "run_id": "r-test-01",
        "role": load_role(REPO_ROOT, role),
        "prompt": "do the thing",
        "system_prompt": "SYSTEM",
        "cwd": tmp_path,
        "run_dir": tmp_path / "runs" / "2026-09-05" / "r-test-01",
        "state_dir": tmp_path / "state",
        "schema": result_schema(),
        "model": "z-ai/glm-5.3-flash",
    }
    base.update(kw)
    return RunContext(**base)


# --- naming ------------------------------------------------------------------


def test_naming_helpers_split_and_compose_tokens() -> None:
    assert harness_of("claude@openrouter") == "claude"
    assert harness_of("claude") == "claude"
    assert provider_of("claude@openrouter") == "openrouter"
    assert provider_of("claude") is None
    assert provider_of("openrouter") is None
    assert compose("claude", "openrouter") == "claude@openrouter"
    # The native provider is never spelled out; it is just the harness.
    assert compose("claude", "anthropic") == "claude"
    assert compose("codex", "chatgpt") == "codex"
    assert compose("codex", None) == "codex"
    assert NATIVE_PROVIDER == {"claude": "anthropic", "codex": "chatgpt"}
    assert AGENTIC_HARNESSES == frozenset({"claude", "codex", "hermes"})


def test_is_agentic_separates_harnesses_from_chat_runners() -> None:
    for token in ("claude", "claude@openrouter", "codex", "codex@openrouter", "hermes"):
        assert is_agentic(token), token
    for token in ("openrouter", "local", "stub"):
        assert not is_agentic(token), token


def test_split_and_entry_target_round_trip_tokens() -> None:
    assert split_target("claude@openrouter:z-ai/glm-5.3") == ("claude@openrouter", "z-ai/glm-5.3")
    assert split_target("claude@openrouter") == ("claude@openrouter", None)
    assert entry_target("claude@openrouter", "z-ai/glm-5.3") == "claude@openrouter:z-ai/glm-5.3"
    assert entry_target("codex@openrouter") == "codex@openrouter"


# --- config ------------------------------------------------------------------


def test_both_spellings_produce_the_same_entry() -> None:
    fields = {"model": "z-ai/glm-5.3", "only": ["group-leader"]}
    a = TierEntry.model_validate({"runner": "claude", "provider": "openrouter", **fields})
    b = TierEntry.model_validate({"runner": "claude@openrouter", **fields})
    assert a == b
    assert a.runner == "claude" and a.provider == "openrouter"
    assert a.runner_name == "claude@openrouter"
    assert TierEntry(runner="codex", profile="cube-chatgpt").runner_name == "codex"
    assert TierEntry(runner="openrouter", model="x/y").runner_name == "openrouter"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"runner": "openrouter", "provider": "openrouter", "model": "x/y"}, "only valid for"),
        ({"runner": "local", "provider": "anthropic"}, "only valid for"),
        ({"runner": "claude", "provider": "openrouter"}, "requires an explicit model"),
        ({"runner": "claude", "provider": "chatgpt"}, "only valid for runner"),
        ({"runner": "codex", "provider": "anthropic"}, "only valid for runner"),
        ({"runner": "claude", "provider": "bedrock", "model": "x/y"}, "unknown provider"),
        (
            {"runner": "claude@openrouter", "provider": "chatgpt", "model": "x/y"},
            "contradicts provider",
        ),
        ({"runner": "claude", "model": "x", "sandbox": "read-only"}, "Extra inputs"),
    ],
)
def test_tier_entry_validation_errors(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        TierEntry.model_validate(raw)


def test_native_provider_spelled_out_is_accepted_and_normalised() -> None:
    entry = TierEntry.model_validate({"runner": "claude", "provider": "anthropic", "model": "opus"})
    assert entry.runner_name == "claude"


def test_shipped_config_prices_every_harness_target() -> None:
    settings = load_settings(REPO_ROOT)
    for entries in settings.tiers.values():
        for entry in entries:
            if entry.provider != "openrouter":
                continue
            assert f"{entry.runner_name}:{entry.model}" in settings.prices


# --- availability ------------------------------------------------------------


def test_availability_needs_binary_and_key(
    harness_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    present = {"claude", "codex"}
    monkeypatch.setattr(
        "cube.router.policy.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in present else None,
    )
    available = default_availability(harness_settings)
    assert available("claude") and available("claude@openrouter")
    assert available("codex") and available("codex@openrouter")
    assert available("openrouter")
    assert not available("hermes")
    assert not available("local")
    assert available("stub")

    harness_settings.env = {}
    available = default_availability(harness_settings)
    # The subscription still works without an OpenRouter key; the provider does not.
    assert available("claude") and not available("claude@openrouter")
    assert available("codex") and not available("codex@openrouter")
    assert not available("openrouter")

    present.clear()
    harness_settings.env = {"OPENROUTER_API_KEY": KEY}
    available = default_availability(harness_settings)
    assert not available("claude@openrouter") and not available("codex@openrouter")
    assert available("openrouter")


# --- routing -----------------------------------------------------------------


def test_needs_tools_picks_the_harness_in_each_tier(harness_settings: Settings) -> None:
    every = lambda runner: True  # noqa: E731 - one-line stub
    plan = choose(harness_settings, Tier.plan, available=every, needs_tools=True)
    assert (plan.runner, plan.model) == ("claude@openrouter", "z-ai/glm-5.3")
    assert plan.needs_tools is True
    assert plan.as_dict()["needs_tools"] is True
    implement = choose(harness_settings, Tier.implement, available=every, needs_tools=True)
    assert (implement.runner, implement.model) == ("codex@openrouter", "z-ai/glm-5.3-flash")


def test_needs_tools_skips_chat_entries_and_falls_through_tiers(
    harness_settings: Settings,
) -> None:
    route = choose(
        harness_settings,
        Tier.plan,
        available=avail("codex", "codex@openrouter", "openrouter", "local"),
        needs_tools=True,
    )
    assert route.runner == "codex@openrouter" and route.tier == Tier.implement
    assert "openrouter:z-ai/glm-5.3-flash has no tools" in route.reason
    assert "claude@openrouter unavailable" in route.reason


def test_needs_tools_queues_when_only_chat_runners_are_left(harness_settings: Settings) -> None:
    with pytest.raises(Queued) as exc:
        choose(
            harness_settings,
            Tier.bulk,
            available=avail("openrouter", "local"),
            needs_tools=True,
        )
    assert "openrouter:xiaomi/mimo-v2.5 has no tools" in str(exc.value)


def test_needs_tools_still_reserves_the_subscription_for_the_group_leader(
    harness_settings: Settings,
) -> None:
    with pytest.raises(Queued) as exc:
        choose(
            harness_settings,
            Tier.plan,
            available=avail("claude", "local"),
            needs_tools=True,
            role="editor",
        )
    # `claude:opus` is reserved, so a non-coordinator never reaches the subscription.
    assert "claude:opus reserved for group-leader" in str(exc.value)
    leader = choose(
        harness_settings,
        Tier.plan,
        available=avail("claude", "local"),
        needs_tools=True,
        role="group-leader",
    )
    assert (leader.runner, leader.model) == ("claude", "opus")


def test_needs_tools_false_keeps_todays_behaviour(harness_settings: Settings) -> None:
    every = lambda runner: True  # noqa: E731 - one-line stub
    route = choose(harness_settings, Tier.plan, available=every)
    assert route.runner == "claude@openrouter"
    assert route.needs_tools is False
    chat = choose(harness_settings, Tier.plan, available=avail("openrouter"))
    assert (chat.runner, chat.model) == ("openrouter", "z-ai/glm-5.3-flash")
    assert "has no tools" not in chat.reason


def test_requested_runner_accepts_the_token_or_the_bare_harness(
    harness_settings: Settings,
) -> None:
    every = lambda runner: True  # noqa: E731 - one-line stub
    by_token = choose(
        harness_settings, Tier.implement, requested_runner="codex@openrouter", available=every
    )
    assert by_token.runner == "codex@openrouter"
    by_harness = choose(harness_settings, Tier.implement, requested_runner="codex", available=every)
    assert by_harness.runner == "codex@openrouter"


@pytest.mark.parametrize(
    ("role", "expected"),
    [("sysadmin", True), ("editor", True), ("scribe", True), ("sentinel", False)],
)
def test_derived_needs_tools_per_role(role: str, expected: bool) -> None:
    assert derive_needs_tools(load_role(REPO_ROOT, role)) is expected


# --- claude code on openrouter ----------------------------------------------


def test_claude_openrouter_env_carries_the_token_and_the_command_never_does(
    tmp_path: Path,
) -> None:
    ex = RecordingExec(
        {"claude": ExecResult(0, json.dumps({"type": "result", "result": GOOD}), "")}
    )
    config_dir = tmp_path / "state" / "harness" / "claude-openrouter"
    runner = ClaudeCodeRunner(
        ex,
        provider="openrouter",
        env={"OPENROUTER_API_KEY": KEY},
        config_dir=config_dir,
    )
    assert runner.name == "claude@openrouter"
    context = ctx(tmp_path, "editor")
    runner.run(context)
    env = ex.calls[0]["env"]
    cmd = ex.calls[0]["cmd"]

    assert env["ANTHROPIC_AUTH_TOKEN"] == KEY
    assert env["ANTHROPIC_BASE_URL"] == OPENROUTER_ANTHROPIC_BASE
    assert env["ANTHROPIC_API_KEY"] == ""
    for key in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    ):
        assert env[key] == "z-ai/glm-5.3-flash", key
    assert env["CLAUDE_CONFIG_DIR"] == str(config_dir)
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["DISABLE_TELEMETRY"] == "1"
    assert env["DISABLE_ERROR_REPORTING"] == "1"

    # The secret is in the environment and nowhere else.
    assert KEY not in " ".join(cmd)
    assert not any(KEY in str(value) for value in cmd)
    assert cmd[cmd.index("--model") + 1] == "z-ai/glm-5.3-flash"

    assert config_dir.is_dir()
    assert config_dir.stat().st_mode & 0o777 == 0o700
    # `~/.claude` and the Max login are untouched.
    assert config_dir != Path.home() / ".claude"


def test_claude_openrouter_base_url_is_overridable(tmp_path: Path) -> None:
    ex = RecordingExec(
        {"claude": ExecResult(0, json.dumps({"type": "result", "result": GOOD}), "")}
    )
    ClaudeCodeRunner(
        ex,
        provider="openrouter",
        env={
            "OPENROUTER_API_KEY": KEY,
            "OPENROUTER_ANTHROPIC_BASE_URL": "https://proxy.example/api",
        },
        config_dir=tmp_path / "cfg",
    ).run(ctx(tmp_path, "editor"))
    assert ex.calls[0]["env"]["ANTHROPIC_BASE_URL"] == "https://proxy.example/api"


def test_native_claude_injects_nothing(tmp_path: Path) -> None:
    ex = RecordingExec(
        {"claude": ExecResult(0, json.dumps({"type": "result", "result": GOOD}), "")}
    )
    runner = ClaudeCodeRunner(ex, env={"OPENROUTER_API_KEY": KEY})
    assert runner.name == "claude"
    assert runner.provider_env(ctx(tmp_path, "editor")) == {}
    runner.run(ctx(tmp_path, "editor"))
    env = ex.calls[0]["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "CLAUDE_CONFIG_DIR" not in env


def test_claude_openrouter_drops_the_wrong_cost_but_keeps_usage(tmp_path: Path) -> None:
    envelope = json.dumps(
        {
            "type": "result",
            "result": GOOD,
            "session_id": "s-9",
            "total_cost_usd": 0.158,  # Anthropic rates applied to a GLM run
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }
    )
    ex = RecordingExec({"claude": ExecResult(0, envelope, "")})
    outcome = ClaudeCodeRunner(
        ex, provider="openrouter", env={"OPENROUTER_API_KEY": KEY}, config_dir=tmp_path / "cfg"
    ).run(ctx(tmp_path, "editor"))
    assert outcome.cost_usd is None
    assert outcome.usage == {"input_tokens": 1000, "output_tokens": 500}
    assert outcome.usage.runner == "claude@openrouter"  # type: ignore[attr-defined]

    native = RecordingExec({"claude": ExecResult(0, envelope, "")})
    assert ClaudeCodeRunner(native).run(ctx(tmp_path, "editor")).cost_usd == 0.158


def test_unrecognized_model_stderr_is_neither_error_nor_rate_limit() -> None:
    noise = '[claude-code:unrecognized_model] {"model":"z-ai/glm-5.3-flash"}\n'
    assert strip_harmless_stderr(noise) == ""
    assert strip_harmless_stderr(f"{noise}real trouble") == "real trouble"
    outcome = parse_envelope(json.dumps({"type": "result", "result": GOOD}), noise, 0)
    assert outcome.error is None
    assert outcome.rate_limited is False
    assert outcome.result is not None
    # A genuine limit message on the same stream is still caught.
    assert parse_envelope("", f"{noise}HTTP 429 rate limit", 1).rate_limited is True


# --- codex on openrouter -----------------------------------------------------


def test_codex_openrouter_command_uses_the_profile_and_disables_web_search(
    tmp_path: Path,
) -> None:
    runner = CodexRunner(provider="openrouter")
    assert runner.name == "codex@openrouter"
    assert runner.default_profile == OPENROUTER_PROFILE
    cmd = runner.command(ctx(tmp_path, "programmer", dry_run=True))
    assert cmd[cmd.index("-p") + 1] == OPENROUTER_PROFILE
    assert "model=z-ai/glm-5.3-flash" in cmd
    assert 'web_search="disabled"' in cmd
    assert "--sandbox" in cmd and "--json" in cmd

    native = CodexRunner()
    assert native.name == "codex" and native.default_profile == DEFAULT_PROFILE
    native_cmd = native.command(ctx(tmp_path, "programmer", dry_run=True))
    assert native_cmd[native_cmd.index("-p") + 1] == DEFAULT_PROFILE
    assert 'web_search="disabled"' not in native_cmd
    # An explicit tier profile still wins over the provider default.
    pinned = runner.command(ctx(tmp_path, "programmer", dry_run=True, profile="cube-chatgpt"))
    assert pinned[pinned.index("-p") + 1] == "cube-chatgpt"


def test_make_runner_builds_harnesses_from_tokens(harness_settings: Settings) -> None:
    claude = make_runner("claude@openrouter", harness_settings)
    assert isinstance(claude, ClaudeCodeRunner)
    assert claude.provider == "openrouter" and claude.name == "claude@openrouter"
    assert claude.config_dir == harness_settings.state_dir() / "harness" / "claude-openrouter"
    assert claude.env["OPENROUTER_API_KEY"] == KEY

    codex = make_runner("codex@openrouter", harness_settings)
    assert isinstance(codex, CodexRunner) and codex.provider == "openrouter"
    assert make_runner("claude", harness_settings).provider == "anthropic"  # type: ignore[attr-defined]
    assert make_runner("codex", harness_settings).provider == "chatgpt"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="unknown runner"):
        make_runner("claude@bedrock", harness_settings)


# --- budget ------------------------------------------------------------------


def test_openrouter_provider_runs_bill_the_estimate(
    harness_repo: Path, harness_settings: Settings
) -> None:
    """OpenRouter really charges for these runs, so the estimate is billed, not zero."""
    ledger = BudgetLedger(harness_repo / "state", harness_settings)
    record = ledger.record(
        Tier.plan,
        runner="claude@openrouter",
        model="z-ai/glm-5.3",
        usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        cost_usd=None,
        now=NOW,
    )
    assert record["equivalent_usd"] == pytest.approx(1.4 + 4.4)
    assert record["cost_usd"] == pytest.approx(1.4 + 4.4)
    assert record["estimated"] is True
    assert record["warning"] is None
    day = ledger.day(NOW)
    assert day["plan"]["cost_usd"] == pytest.approx(5.8)
    assert ledger.runner_day(NOW)["claude@openrouter"]["cost_usd"] == pytest.approx(5.8)


def test_subscription_runs_are_still_billed_zero(
    harness_repo: Path, harness_settings: Settings
) -> None:
    ledger = BudgetLedger(harness_repo / "state", harness_settings)
    record = ledger.record(
        Tier.plan,
        runner="claude",
        model="opus",
        usage={"input_tokens": 1_000_000},
        cost_usd=0.9,
        now=NOW,
    )
    assert record["cost_usd"] == 0.0
    assert record["equivalent_usd"] == pytest.approx(0.9)


# --- doctor ------------------------------------------------------------------


OPENROUTER_PROFILE_TOML = """\
model = "z-ai/glm-5.3-flash"
model_provider = "openrouter"
web_search = "disabled"

[model_providers.openrouter]
base_url = "https://openrouter.ai/api/v1"
env_key = "OPENROUTER_API_KEY"
wire_api = "responses"
"""


def test_codex_openrouter_profile_check_reads_the_fixture(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("model = 'x'\n", encoding="utf-8")
    missing = check_codex_openrouter_profile(cfg)
    assert not missing[0].ok
    assert "deploy/codex-openrouter-profile.toml" in missing[0].detail

    profile = tmp_path / "cube-openrouter.config.toml"
    profile.write_text(OPENROUTER_PROFILE_TOML, encoding="utf-8")
    assert check_codex_openrouter_profile(cfg)[0].ok

    profile.write_text(
        OPENROUTER_PROFILE_TOML.replace('wire_api = "responses"', 'wire_api = "chat"'),
        encoding="utf-8",
    )
    bad = check_codex_openrouter_profile(cfg)[0]
    assert not bad.ok and 'wire_api = "responses"' in bad.detail

    profile.write_text(
        OPENROUTER_PROFILE_TOML.replace('web_search = "disabled"\n', ""), encoding="utf-8"
    )
    assert 'web_search = "disabled"' in check_codex_openrouter_profile(cfg)[0].detail


def test_deploy_template_satisfies_the_profile_check(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("model = 'x'\n", encoding="utf-8")
    (tmp_path / "cube-openrouter.config.toml").write_text(
        (REPO_ROOT / "deploy" / "codex-openrouter-profile.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert check_codex_openrouter_profile(cfg)[0].ok


def test_check_codex_profile_ignores_openrouter_without_such_a_tier_entry(
    engine_settings: Settings,
) -> None:
    names = {check.name for check in check_codex_profile(engine_settings)}
    assert "codex:openrouter-profile" not in names


def test_harness_provider_checks_are_warnings_off_the_orchestration_host(
    harness_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cube.doctor._which", lambda name: None)
    checks = {check.name: check for check in check_harness_providers(harness_settings)}
    assert not checks["harness:openrouter:claude"].ok
    # host is `testhost` in the fixture, so this machine is a thin client.
    assert checks["harness:openrouter:claude"].severity == "warn"
    assert checks["harness:openrouter:key"].ok

    harness_settings.env = {}
    checks = {check.name: check for check in check_harness_providers(harness_settings)}
    assert not checks["harness:openrouter:key"].ok
    assert "OPENROUTER_API_KEY" in checks["harness:openrouter:key"].detail


def test_harness_provider_checks_are_errors_on_the_orchestration_host(
    harness_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setattr("cube.doctor._which", lambda name: None)
    harness_settings.host = os.uname().nodename.split(".", 1)[0]
    checks = {check.name: check for check in check_harness_providers(harness_settings)}
    assert checks["harness:openrouter:claude"].severity == "error"
    assert checks["harness:openrouter:codex"].severity == "error"
    assert "codex:openrouter-profile" in checks


def test_harness_provider_check_is_silent_without_provider_entries(
    engine_settings: Settings,
) -> None:
    checks = check_harness_providers(engine_settings)
    assert len(checks) == 1
    assert checks[0].ok and checks[0].severity == "info"


# --- end to end --------------------------------------------------------------


def test_dry_run_report_carries_the_token_and_needs_tools(
    harness_settings: Settings, fake_bd: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cube.router.policy.shutil.which", lambda name: f"/usr/bin/{name}")
    report = execute(harness_settings, "sysadmin", dry_run=True, prompt_text="check the servers")
    data = report.as_dict()
    assert data["state"] == "dry-run"
    assert data["runner"] == "claude@openrouter"
    assert data["model"] == "z-ai/glm-5.3"
    assert data["needs_tools"] is True
    assert KEY not in json.dumps(data)

    chat = execute(
        harness_settings,
        "sysadmin",
        dry_run=True,
        prompt_text="check the servers",
        needs_tools=False,
    )
    assert chat.needs_tools is False


def test_no_needs_tools_allows_a_chat_runner(
    harness_settings: Settings, fake_bd: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-needs-tools` is the escape hatch when no harness binary is installed."""
    monkeypatch.setattr("cube.router.policy.shutil.which", lambda name: None)
    queued = execute(harness_settings, "sysadmin", dry_run=True, prompt_text="watch")
    assert queued.state == "queued"
    assert queued.error is not None and "has no tools" in queued.error
    report = execute(
        harness_settings, "sysadmin", dry_run=True, prompt_text="watch", needs_tools=False
    )
    assert report.needs_tools is False
    assert report.runner == "openrouter"


# --- the group's own endpoint (ADR-0021) -------------------------------------


def test_claude_local_env_points_at_the_anthropic_side_of_the_endpoint(tmp_path: Path) -> None:
    from cube.runners.claude_code import anthropic_base_from_openai

    assert anthropic_base_from_openai("http://unimatrix01:8000/v1") == "http://unimatrix01:8000"
    assert anthropic_base_from_openai("http://unimatrix01:8000/v1/") == "http://unimatrix01:8000"
    assert anthropic_base_from_openai("http://unimatrix01:8000") == "http://unimatrix01:8000"
    ex = RecordingExec(
        {"claude": ExecResult(0, json.dumps({"type": "result", "result": GOOD}), "")}
    )
    config_dir = tmp_path / "state" / "harness" / "claude-local"
    runner = ClaudeCodeRunner(
        ex,
        provider="local",
        env={"VLLM_BASE_URL": "http://unimatrix01:8000/v1", "VLLM_API_KEY": "own-key"},
        config_dir=config_dir,
    )
    assert runner.name == "claude@local"
    outcome = runner.run(ctx(tmp_path, "editor", model="qwen3.8-27b"))
    env = ex.calls[0]["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://unimatrix01:8000"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "own-key"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_MODEL"] == "qwen3.8-27b"
    assert env["CLAUDE_CONFIG_DIR"] == str(config_dir)
    assert outcome.cost_usd is None


def test_codex_local_uses_the_cube_local_profile(tmp_path: Path) -> None:
    from cube.runners.codex import LOCAL_PROFILE

    runner = CodexRunner(RecordingExec({}), provider="local")
    assert runner.name == "codex@local"
    cmd = runner.command(ctx(tmp_path, "programmer", model="qwen3.8-27b"))
    assert cmd[cmd.index("-p") + 1] == LOCAL_PROFILE == "cube-local"
    assert "model=qwen3.8-27b" in cmd
    assert 'web_search="disabled"' in cmd


def test_make_runner_builds_local_harnesses(harness_settings: Settings) -> None:
    claude = make_runner("claude@local", harness_settings)
    codex = make_runner("codex@local", harness_settings)
    assert claude.name == "claude@local" and codex.name == "codex@local"
    assert str(getattr(claude, "config_dir", "")).endswith("harness/claude-local")


def test_local_harness_availability_needs_the_endpoint_url(harness_settings: Settings) -> None:
    harness_settings.env.pop("VLLM_BASE_URL", None)
    available = default_availability(harness_settings)
    if _which_claude():
        assert available("claude@local") is False
        harness_settings.env["VLLM_BASE_URL"] = "http://unimatrix01:8000/v1"
        assert default_availability(harness_settings)("claude@local") is True


def _which_claude() -> bool:
    import shutil

    return shutil.which("claude") is not None


def test_doctor_checks_the_local_profile_and_endpoint(
    tmp_path: Path, harness_settings: Settings
) -> None:
    from cube.config import TierEntry
    from cube.doctor import check_codex_local_profile, check_local_endpoint

    cfg = tmp_path / "codex" / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text("model = 'x'\n", encoding="utf-8")
    missing = check_codex_local_profile(cfg)
    assert not missing[0].ok and "deploy/codex-local-profile.toml" in missing[0].detail
    (cfg.parent / "cube-local.config.toml").write_text(
        (REPO_ROOT / "deploy" / "codex-local-profile.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert check_codex_local_profile(cfg)[0].ok
    harness_settings.tiers["plan"] = [
        TierEntry(runner="claude", provider="local", model="qwen3.8-27b")
    ]
    harness_settings.env.pop("VLLM_BASE_URL", None)
    harness_settings.env.pop("VLLM_API_KEY", None)
    assert not check_local_endpoint(harness_settings)[0].ok
    harness_settings.env.update(
        {"VLLM_BASE_URL": "http://unimatrix01:8000/v1", "VLLM_API_KEY": "k"}
    )
    assert check_local_endpoint(harness_settings)[0].ok


def test_hermes_only_takes_the_local_provider() -> None:
    with pytest.raises(ValidationError, match="provider local only"):
        TierEntry(runner="hermes", provider="openrouter", model="x")
    entry = TierEntry(runner="hermes", provider="local", model="qwen3.8-27b", profile="cube-worker")
    assert entry.runner_name == "hermes@local"


def test_make_runner_builds_the_hermes_worker(harness_settings: Settings) -> None:
    runner = make_runner("hermes@local", harness_settings)
    assert runner.name == "hermes@local" and getattr(runner, "provider", None) == "local"


def test_doctor_checks_the_hermes_worker_profile(
    tmp_path: Path, harness_settings: Settings
) -> None:
    from cube.doctor import check_hermes_worker_profile

    harness_settings.tiers["plan"] = [
        TierEntry(runner="hermes", provider="local", model="q", profile="cube-worker")
    ]
    harness_settings.paths.hermes_home = tmp_path / "hermes"
    missing = check_hermes_worker_profile(harness_settings)
    assert not missing[0].ok and "cube hermes render cube-worker" in missing[0].detail
    cfg = tmp_path / "hermes" / "profiles" / "cube-worker" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("approvals:\n  single_query_mode: deny\n", encoding="utf-8")
    assert check_hermes_worker_profile(harness_settings)[0].ok
