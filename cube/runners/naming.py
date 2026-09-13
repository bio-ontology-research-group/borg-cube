"""Runner tokens: `<harness>@<provider>` identity used everywhere a runner is a string.

A tier entry names a harness (`claude`, `codex`) and optionally a provider. When the
provider is not the harness's native one the composed token (`claude@openrouter`) is
the runner name carried through routing, tier state, backoff, prices, the budget
ledger and every report. `harness_of` and `provider_of` split it again.
"""

from __future__ import annotations

NATIVE_PROVIDER: dict[str, str] = {"claude": "anthropic", "codex": "chatgpt"}
"""Provider a harness talks to when no provider is configured."""

AGENTIC_HARNESSES: frozenset[str] = frozenset({"claude", "codex", "hermes"})
"""Harnesses that can call tools. `openrouter`, `local` and `stub` are chat only."""

PROVIDERS: frozenset[str] = frozenset({"anthropic", "chatgpt", "openrouter", "local"})
"""`local` is the group's own OpenAI-compatible endpoint (VLLM_BASE_URL, ADR-0021): it
serves chat completions with tools, the Anthropic messages API and the responses
API, so Claude Code, Codex and the plain chat runner all run on it."""

SEPARATOR = "@"


def compose(harness: str, provider: str | None) -> str:
    """Return the runner token for a harness and provider."""
    if not provider or NATIVE_PROVIDER.get(harness) == provider:
        return harness
    return f"{harness}{SEPARATOR}{provider}"


def harness_of(token: str) -> str:
    """Return the harness part of a runner token (`claude@openrouter` -> `claude`)."""
    return token.split(SEPARATOR, 1)[0]


def provider_of(token: str) -> str | None:
    """Return the explicit provider of a runner token, else None."""
    harness, separator, provider = token.partition(SEPARATOR)
    if not separator:
        return None
    return provider or None


def is_agentic(token: str) -> bool:
    """Return whether the runner behind this token can call tools."""
    return harness_of(token) in AGENTIC_HARNESSES


def uses_openrouter(token: str) -> bool:
    """Return whether the token talks to OpenRouter, harness or chat runner alike."""
    return token == "openrouter" or provider_of(token) == "openrouter"


def uses_local(token: str) -> bool:
    """Return whether the token talks to the group's own endpoint, harness or chat runner."""
    return token == "local" or provider_of(token) == "local"
