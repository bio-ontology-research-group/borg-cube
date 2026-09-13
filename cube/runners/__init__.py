"""Runner registry: name -> Runner instance built from Settings and injectable I/O."""

from __future__ import annotations

from cube.config import Settings
from cube.runners.base import (
    Exec,
    ExecResult,
    HttpGet,
    HttpPost,
    RunContext,
    Runner,
    RunOutcome,
    default_exec,
    default_http_get,
    default_http_post,
    looks_rate_limited,
    parse_result,
    runner_usage,
)
from cube.runners.claude_code import ClaudeCodeRunner
from cube.runners.codex import CodexRunner
from cube.runners.hermes import HermesRunner
from cube.runners.naming import (
    AGENTIC_HARNESSES,
    NATIVE_PROVIDER,
    PROVIDERS,
    compose,
    harness_of,
    is_agentic,
    provider_of,
    uses_openrouter,
)
from cube.runners.openai_compat import LOCAL_DEFAULT_BASE, OPENROUTER_BASE, OpenAICompatRunner
from cube.runners.stub import StubRunner

RUNNER_NAMES = (
    "claude",
    "claude@openrouter",
    "codex",
    "codex@openrouter",
    "hermes",
    "openrouter",
    "local",
    "stub",
)
CLAUDE_OPENROUTER_CONFIG_DIRNAME = "claude-openrouter"
CLAUDE_CONFIG_DIRNAMES = {"openrouter": "claude-openrouter", "local": "claude-local"}


def make_runner(
    name: str,
    settings: Settings,
    *,
    exec_fn: Exec | None = None,
    http_post: HttpPost | None = None,
) -> Runner:
    """Build the runner for a runner token (`claude`, `claude@openrouter`, ...)."""
    harness = harness_of(name)
    provider = provider_of(name)
    if provider is not None and provider not in PROVIDERS:
        raise ValueError(f"unknown runner {name!r}; known: {', '.join(RUNNER_NAMES)}")
    if harness in NATIVE_PROVIDER:
        provider = provider or NATIVE_PROVIDER[harness]
    if harness == "claude":
        return ClaudeCodeRunner(
            exec_fn,
            provider=provider or "anthropic",
            env=dict(settings.env),
            config_dir=(
                settings.state_dir() / "harness" / CLAUDE_CONFIG_DIRNAMES[provider]
                if provider in CLAUDE_CONFIG_DIRNAMES
                else None
            ),
        )
    if harness == "codex":
        return CodexRunner(exec_fn, provider=provider or "chatgpt")
    if harness == "hermes":
        return HermesRunner(exec_fn, provider=provider, env=dict(settings.env))
    if name == "openrouter":
        return OpenAICompatRunner(
            "openrouter",
            settings.env.get("OPENROUTER_BASE_URL", OPENROUTER_BASE),
            api_key=settings.env.get("OPENROUTER_API_KEY"),
            http_post=http_post,
        )
    if name == "local":
        return OpenAICompatRunner(
            "local",
            settings.env.get("VLLM_BASE_URL", LOCAL_DEFAULT_BASE),
            api_key=settings.env.get("VLLM_API_KEY"),
            default_model=settings.env.get("VLLM_MODEL"),
            http_post=http_post,
        )
    if name == "stub":
        return StubRunner()
    raise ValueError(f"unknown runner {name!r}; known: {', '.join(RUNNER_NAMES)}")


__all__ = [
    "AGENTIC_HARNESSES",
    "NATIVE_PROVIDER",
    "PROVIDERS",
    "RUNNER_NAMES",
    "ClaudeCodeRunner",
    "CodexRunner",
    "Exec",
    "ExecResult",
    "HermesRunner",
    "HttpGet",
    "HttpPost",
    "OpenAICompatRunner",
    "RunContext",
    "RunOutcome",
    "Runner",
    "StubRunner",
    "compose",
    "default_exec",
    "default_http_get",
    "default_http_post",
    "harness_of",
    "is_agentic",
    "looks_rate_limited",
    "make_runner",
    "parse_result",
    "provider_of",
    "runner_usage",
    "uses_openrouter",
]
