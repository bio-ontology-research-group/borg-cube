"""Equivalent model pricing for runners that do not report a billed cost."""

from __future__ import annotations

from typing import Any

from cube.config import Price, Settings

_WARNINGS: list[str] = []
_SEEN_WARNINGS: set[str] = set()


def target_name(runner: str, model: str | None) -> str:
    return f"{runner}:{model}" if model else runner


FREE_PRICE = Price(input_per_mtok=0.0, output_per_mtok=0.0, free=True)


def price_for(settings: Settings, runner: str, model: str | None) -> Price | None:
    """Resolve an exact target, then the `:free` rule, runner default, global default.

    OpenRouter's `:free` variants cost nothing by definition, so a free-pool model
    the budget patrol discovered today needs no price entry.
    """
    exact = settings.prices.get(target_name(runner, model))
    if exact is not None:
        return exact
    if model and model.endswith(":free"):
        return FREE_PRICE
    return settings.prices.get(runner) or settings.prices.get("default")


def _number(usage: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return 0.0


def estimate_usd(
    settings: Settings,
    runner: str,
    model: str | None,
    usage: dict[str, Any] | None,
) -> tuple[float, bool]:
    """Return equivalent USD and whether a configured estimate was available."""
    price = price_for(settings, runner, model)
    if price is None:
        target = target_name(runner, model)
        message = f"no price for {target}; counting 0 USD equivalent"
        if message not in _SEEN_WARNINGS:
            _SEEN_WARNINGS.add(message)
            _WARNINGS.append(message)
        return 0.0, False
    raw = usage or {}
    input_tokens = _number(raw, "input_tokens", "prompt_tokens")
    output_tokens = _number(raw, "output_tokens", "completion_tokens")
    if input_tokens == 0 and output_tokens == 0:
        input_tokens = _number(raw, "total_tokens", "token_count")
    amount = (
        input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
    ) / 1_000_000
    return amount, True


def rank_usd(settings: Settings, runner: str, model: str | None) -> float:
    """Rank a target by its combined input and output unit prices."""
    price = price_for(settings, runner, model)
    if price is None:
        return float("inf")
    if price.free:
        return -1.0
    return price.input_per_mtok + price.output_per_mtok


def is_free(settings: Settings, runner: str, model: str | None) -> bool:
    """Return whether the exact or inherited target price is explicitly free."""
    price = price_for(settings, runner, model)
    return bool(price and price.free)


def price_warnings() -> list[str]:
    return list(_WARNINGS)


def reset_price_warnings() -> None:
    _WARNINGS.clear()
    _SEEN_WARNINGS.clear()
