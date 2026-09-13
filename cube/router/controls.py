"""Persistent runner controls in ``state/tiers.json``.

``disabled`` is a manual operator decision and ``exhausted`` is an automatic
usage-limit decision. Both are checked before transient ``backoff.json`` state.
Usage-limit failures live only here and bypass backoff; transient failures live
only in backoff. This keeps one failure from being recorded or surfaced twice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_EXHAUSTION = timedelta(hours=5)
CONTROL_STATES = {"disabled", "exhausted"}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def split_target(target: str) -> tuple[str, str | None]:
    runner, separator, model = target.partition(":")
    if not runner or (separator and not model):
        raise ValueError("target must be runner or runner:model")
    return runner, model or None


def entry_target(runner: str, model: str | None = None) -> str:
    return f"{runner}:{model}" if model else runner


@dataclass(frozen=True)
class Control:
    state: str
    until: str | None
    reason: str | None

    def active_at(self, now: datetime | None = None) -> bool:
        if self.state not in CONTROL_STATES:
            return False
        if not self.until:
            return True
        try:
            until = _aware(datetime.fromisoformat(self.until.replace("Z", "+00:00")))
        except ValueError:
            return True
        return until > _aware(_now(now))


_EPOCH_RESET = re.compile(r"(?:reset[^\n|]{0,80})?\|(\d{10,13})\b", re.IGNORECASE)
_ISO_RESET = re.compile(
    r"(?:reset(?:s|ting)?|try again)[^\n]{0,80}?"
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)",
    re.IGNORECASE,
)
_RELATIVE_RESET = re.compile(
    r"(?:reset(?:s|ting)?|try again)\s+in\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h))?\s*"
    r"(?:(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m))?",
    re.IGNORECASE,
)
_CLOCK_RESET = re.compile(
    r"(?:reset(?:s|ting)?|try again)(?:\s+at)?\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_CLOCK_24_RESET = re.compile(
    r"(?:reset(?:s|ting)?|try again)(?:\s+at)?\s+"
    r"(\d{1,2}):(\d{2})(?:\s*(?:UTC|GMT))?\b",
    re.IGNORECASE,
)


def parse_reset_time(text: str, now: datetime | None = None) -> datetime | None:
    """Parse the reset forms emitted by Claude and Codex command-line clients."""
    current = _aware(_now(now))
    epoch = _EPOCH_RESET.search(text)
    if epoch:
        stamp = int(epoch.group(1))
        if len(epoch.group(1)) == 13:
            stamp //= 1000
        parsed = datetime.fromtimestamp(stamp, UTC)
        return parsed if parsed > current else None

    iso = _ISO_RESET.search(text)
    if iso:
        try:
            parsed = _aware(datetime.fromisoformat(iso.group(1).replace("Z", "+00:00")))
        except ValueError:
            parsed = current
        return parsed if parsed > current else None

    relative = _RELATIVE_RESET.search(text)
    if relative and (relative.group(1) or relative.group(2)):
        hours = float(relative.group(1) or 0)
        minutes = float(relative.group(2) or 0)
        return current + timedelta(hours=hours, minutes=minutes)

    clock = _CLOCK_RESET.search(text)
    if clock:
        hour = int(clock.group(1)) % 12
        if clock.group(3).lower() == "pm":
            hour += 12
        parsed = current.replace(
            hour=hour, minute=int(clock.group(2) or 0), second=0, microsecond=0
        )
        if parsed <= current:
            parsed += timedelta(days=1)
        return parsed
    clock_24 = _CLOCK_24_RESET.search(text)
    if clock_24:
        parsed = current.replace(
            hour=int(clock_24.group(1)),
            minute=int(clock_24.group(2)),
            second=0,
            microsecond=0,
        )
        if parsed <= current:
            parsed += timedelta(days=1)
        return parsed
    return None


class TierState:
    """Read and update manual preferences and runner availability controls."""

    def __init__(self, state_dir: Path):
        self.path = state_dir / "tiers.json"

    def data(self) -> dict[str, Any]:
        return _load(self.path)

    def control(
        self, runner: str, model: str | None = None, now: datetime | None = None
    ) -> Control | None:
        entries = self.data().get("entries") or {}
        if not isinstance(entries, dict):
            return None
        keys = [entry_target(runner, model)] if model else []
        keys.append(runner)
        for key in keys:
            raw = entries.get(key)
            if not isinstance(raw, dict):
                continue
            item = Control(
                state=str(raw.get("state") or ""),
                until=str(raw["until"]) if raw.get("until") else None,
                reason=str(raw["reason"]) if raw.get("reason") else None,
            )
            if item.active_at(now):
                return item
        return None

    def preference(self, tier: str) -> str | None:
        preferences = self.data().get("preferences") or {}
        if not isinstance(preferences, dict) or not preferences.get(tier):
            return None
        raw = preferences[tier]
        if isinstance(raw, dict):
            return str(raw["target"]) if raw.get("target") else None
        return str(raw)

    def preference_reason(self, tier: str) -> str | None:
        preferences = self.data().get("preferences") or {}
        raw = preferences.get(tier) if isinstance(preferences, dict) else None
        if not isinstance(raw, dict) or not raw.get("reason"):
            return None
        return str(raw["reason"])

    def budget_swaps(
        self, *, now: datetime | None = None, include_expired: bool = False
    ) -> list[dict[str, str | None]]:
        """Return preferences installed by the budget patrol, in tier order."""
        raw = self.data().get("budget_swaps") or {}
        if not isinstance(raw, dict):
            return []
        current = _aware(_now(now))
        swaps: list[dict[str, str | None]] = []
        for tier, value in raw.items():
            if not isinstance(value, dict):
                continue
            until = str(value["until"]) if value.get("until") else None
            if not include_expired and until:
                try:
                    if _aware(datetime.fromisoformat(until.replace("Z", "+00:00"))) <= current:
                        continue
                except ValueError:
                    pass
            swaps.append(
                {
                    "tier": str(value.get("tier") or tier),
                    "from": str(value["from"]) if value.get("from") else None,
                    "to": str(value["to"]) if value.get("to") else None,
                    "until": until,
                    "reason": str(value["reason"]) if value.get("reason") else None,
                }
            )
        return sorted(swaps, key=lambda item: str(item["tier"]))

    def downgrades(
        self, *, now: datetime | None = None, include_expired: bool = False
    ) -> dict[str, dict[str, str | None]]:
        """Return active tier downgrades keyed by their source tier."""
        raw = self.data().get("downgrades") or {}
        if not isinstance(raw, dict):
            return {}
        current = _aware(_now(now))
        result: dict[str, dict[str, str | None]] = {}
        for tier, value in raw.items():
            if not isinstance(value, dict) or not value.get("to"):
                continue
            until = str(value["until"]) if value.get("until") else None
            if not include_expired and until:
                try:
                    if _aware(datetime.fromisoformat(until.replace("Z", "+00:00"))) <= current:
                        continue
                except ValueError:
                    pass
            result[str(tier)] = {
                "to": str(value["to"]),
                "until": until,
                "reason": str(value["reason"]) if value.get("reason") else None,
            }
        return dict(sorted(result.items()))

    def downgrade(
        self,
        tier: str,
        to: str,
        *,
        until: datetime,
        reason: str | None = None,
        apply: bool = True,
    ) -> bool:
        """Set a reversible tier downgrade and report whether it changed."""
        desired = {
            "to": to,
            "until": _aware(until).isoformat(timespec="seconds"),
            "reason": reason,
        }
        current = self.downgrades(include_expired=True).get(tier)
        changed = current != desired
        if not apply or not changed:
            return changed
        data = self.data()
        downgrades = data.setdefault("downgrades", {})
        if not isinstance(downgrades, dict):
            downgrades = {}
            data["downgrades"] = downgrades
        downgrades[tier] = desired
        _save(self.path, data)
        return True

    def undowngrade(self, tier: str, *, apply: bool = True) -> bool:
        data = self.data()
        downgrades = data.get("downgrades") or {}
        if not isinstance(downgrades, dict) or tier not in downgrades:
            return False
        if apply:
            downgrades.pop(tier, None)
            data["downgrades"] = downgrades
            _save(self.path, data)
        return True

    def preferred(self, tier: str, runner: str, model: str | None = None) -> bool:
        target = self.preference(tier)
        if not target:
            return False
        wanted_runner, wanted_model = split_target(target)
        return runner == wanted_runner and (wanted_model is None or model == wanted_model)

    def disable(
        self,
        target: str,
        *,
        until: datetime,
        reason: str | None = None,
        apply: bool = True,
    ) -> Control:
        split_target(target)
        item = Control("disabled", _aware(until).isoformat(timespec="seconds"), reason)
        if apply:
            data = self.data()
            entries = data.setdefault("entries", {})
            if not isinstance(entries, dict):
                entries = {}
                data["entries"] = entries
            entries[target] = {
                "state": item.state,
                "until": item.until,
                "reason": item.reason,
            }
            _save(self.path, data)
        return item

    def exhaust(
        self,
        runner: str,
        *,
        error: str,
        now: datetime | None = None,
    ) -> tuple[Control, bool]:
        split_target(runner)
        current = _aware(_now(now))
        existing = self.control(runner, now=current)
        if existing is not None and existing.state == "exhausted":
            return existing, False
        until = parse_reset_time(error, current) or current + DEFAULT_EXHAUSTION
        item = Control(
            "exhausted", until.isoformat(timespec="seconds"), error.strip()[:500] or None
        )
        data = self.data()
        entries = data.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            data["entries"] = entries
        entries[runner] = {
            "state": item.state,
            "until": item.until,
            "reason": item.reason,
        }
        _save(self.path, data)
        return item, True

    def enable(self, target: str, *, apply: bool = True) -> bool:
        runner, model = split_target(target)
        data = self.data()
        entries = data.get("entries") or {}
        if not isinstance(entries, dict):
            return False
        keys = (
            [target]
            if model
            else [key for key in entries if key == runner or key.startswith(f"{runner}:")]
        )
        removed = any(key in entries for key in keys)
        if apply and removed:
            for key in keys:
                entries.pop(key, None)
            data["entries"] = entries
            _save(self.path, data)
        return removed

    def prefer(
        self,
        tier: str,
        target: str,
        *,
        reason: str | None = None,
        apply: bool = True,
    ) -> None:
        split_target(target)
        if not apply:
            return
        data = self.data()
        preferences = data.setdefault("preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
            data["preferences"] = preferences
        preferences[tier] = {"target": target, "reason": reason} if reason else target
        _save(self.path, data)

    def clear_preference(self, tier: str, *, reason: str | None = None, apply: bool = True) -> bool:
        data = self.data()
        preferences = data.get("preferences") or {}
        if not isinstance(preferences, dict) or tier not in preferences:
            return False
        if reason is not None:
            raw = preferences[tier]
            stored_reason = raw.get("reason") if isinstance(raw, dict) else None
            if stored_reason != reason:
                return False
        if apply:
            preferences.pop(tier, None)
            data["preferences"] = preferences
            _save(self.path, data)
        return True

    def set_budget_preference(
        self,
        tier: str,
        *,
        source: str,
        target: str,
        until: datetime,
        reason: str,
        apply: bool = True,
    ) -> bool:
        """Set a reversible patrol preference and report whether it changed."""
        split_target(target)
        desired = {
            "tier": tier,
            "from": source,
            "to": target,
            "until": _aware(until).isoformat(timespec="seconds"),
            "reason": reason,
        }
        current = next(
            (item for item in self.budget_swaps(include_expired=True) if item["tier"] == tier),
            None,
        )
        changed = current != desired or self.preference(tier) != target
        if not apply or not changed:
            return changed
        data = self.data()
        preferences = data.setdefault("preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
            data["preferences"] = preferences
        preferences[tier] = target
        swaps = data.setdefault("budget_swaps", {})
        if not isinstance(swaps, dict):
            swaps = {}
            data["budget_swaps"] = swaps
        swaps[tier] = desired
        _save(self.path, data)
        return True

    def clear_budget_preference(self, tier: str, *, apply: bool = True) -> bool:
        """Clear a patrol preference after its recorded window has reset."""
        data = self.data()
        swaps = data.get("budget_swaps") or {}
        if not isinstance(swaps, dict) or tier not in swaps:
            return False
        item = swaps.get(tier)
        preferences = data.get("preferences") or {}
        if isinstance(preferences, dict) and isinstance(item, dict):
            raw_preference = preferences.get(tier)
            target = (
                raw_preference.get("target") if isinstance(raw_preference, dict) else raw_preference
            )
            if target == item.get("to"):
                preferences.pop(tier, None)
        swaps.pop(tier, None)
        if apply:
            data["preferences"] = preferences
            data["budget_swaps"] = swaps
            _save(self.path, data)
        return True

    def reset(self, *, apply: bool = True) -> None:
        if apply:
            _save(self.path, {})
