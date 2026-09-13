"""Router policy (ADR-0005, ADR-0006, ADR-0007).

Routing is based on tier, availability, budget, privacy, and two related runner
states. ``state/tiers.json`` holds operator controls and usage-limit exhaustion;
``state/backoff.json`` holds transient retry timing and failure counts.
Usage-limit failures bypass backoff and tier state is consulted first, so one
failure is not recorded or surfaced twice.
``state/budget.json`` holds daily per-tier totals plus a ``runners`` sibling.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.config import Settings, TierEntry
from cube.model import Privacy, Tier
from cube.notify import append_event, make_event
from cube.router.controls import TierState, entry_target, split_target
from cube.router.free_pool import load_pool
from cube.router.prices import estimate_usd, is_free, price_for
from cube.runners.naming import harness_of, is_agentic, uses_local, uses_openrouter

TIER_RANK: dict[Tier, int] = {
    Tier.none: 0,
    Tier.local: 1,
    Tier.bulk: 1,
    Tier.implement: 2,
    Tier.plan: 3,
}
RUNNER_BINARIES = {"claude": "claude", "codex": "codex", "hermes": "hermes"}
"""Harness -> binary on PATH. A provider token (`claude@openrouter`) uses the same binary."""
BACKOFF_BASE_SECONDS = 60.0
BACKOFF_MAX_SECONDS = 6 * 3600.0
FREE_MODEL_BACKOFF_SECONDS = 10 * 60.0
STUB = "stub"
TIER_FALLBACKS: dict[Tier, tuple[Tier, ...]] = {
    Tier.plan: (Tier.plan, Tier.implement, Tier.bulk, Tier.local),
    Tier.implement: (Tier.implement, Tier.bulk, Tier.local),
    Tier.bulk: (Tier.bulk, Tier.local),
    Tier.local: (Tier.local,),
}


class RouteError(RuntimeError):
    """Base class for routing outcomes that are not a Route."""


class Queued(RouteError):  # noqa: N818 - name fixed by the plan
    """No privacy-safe runner is usable right now; the bead waits and never leaks."""


class Refused(RouteError):  # noqa: N818 - name fixed by the plan
    """The request violates policy (for example, a cloud runner for local-only work)."""


@dataclass(frozen=True)
class Route:
    tier: Tier
    runner: str
    model: str | None
    profile: str | None
    reason: str
    needs_tools: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "runner": self.runner,
            "model": self.model,
            "profile": self.profile,
            "reason": self.reason,
            "needs_tools": self.needs_tools,
        }


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


AGENT_USAGE_TRANSIENT = ("grants", "grants_file")
"""Keys `cube.agents.resource_usage` adds in memory; resources.json never stores them."""


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _is_day_key(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


def _usage_entry() -> dict[str, int | float | bool]:
    return {
        "runs": 0,
        "cost_usd": 0.0,
        "equivalent_usd": 0.0,
        "tokens": 0,
        "estimated": False,
    }


def _add_usage(
    entry: dict[str, Any],
    *,
    runs: int,
    tokens: int,
    cost_usd: float,
    equivalent_usd: float,
    estimated: bool,
) -> None:
    entry["runs"] = int(entry.get("runs", 0)) + runs
    entry["tokens"] = int(entry.get("tokens", 0)) + tokens
    entry["cost_usd"] = float(entry.get("cost_usd", 0.0)) + cost_usd
    entry["equivalent_usd"] = float(entry.get("equivalent_usd", 0.0)) + equivalent_usd
    entry["estimated"] = bool(entry.get("estimated", False)) or estimated


def _positive_cap(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


class BudgetLedger:
    """Daily tier and runner usage in ``state/budget.json``."""

    def __init__(self, state_dir: Path, settings: Settings):
        self.path = state_dir / "budget.json"
        self.settings = settings

    def caps(self) -> dict[str, int | None]:
        b = self.settings.budget
        return {
            Tier.plan.value: b.plan_runs_per_day,
            Tier.implement.value: b.implement_runs_per_day,
            Tier.bulk.value: b.bulk_runs_per_day,
            Tier.local.value: b.local_runs_per_day,
        }

    def cost_caps(self) -> dict[str, float | None]:
        b = self.settings.budget
        return {
            Tier.plan.value: _positive_cap(b.plan_cost_usd_per_day),
            Tier.implement.value: _positive_cap(b.implement_cost_usd_per_day),
            Tier.bulk.value: _positive_cap(b.bulk_cost_usd_per_day),
            Tier.local.value: _positive_cap(b.local_cost_usd_per_day),
        }

    def equivalent_caps(self) -> dict[str, float | None]:
        configured = self.settings.budget.equivalent_cap_usd_per_day
        return {
            tier.value: _positive_cap(configured.get(tier.value))
            for tier in (Tier.plan, Tier.implement, Tier.bulk, Tier.local)
        }

    def day(self, now: datetime | None = None) -> dict[str, dict[str, float]]:
        data = _load(self.path)
        key = _now(now).date().isoformat()
        raw = data.get(key) or {}
        metadata = {"runners", "hours"}
        return {
            str(k): dict(v) for k, v in raw.items() if k not in metadata and isinstance(v, dict)
        }

    def runner_day(self, now: datetime | None = None) -> dict[str, dict[str, float]]:
        data = _load(self.path)
        key = _now(now).date().isoformat()
        raw = data.get(key) or {}
        runners = raw.get("runners") if isinstance(raw, dict) else {}
        if not isinstance(runners, dict):
            return {}
        return {str(k): dict(v) for k, v in runners.items() if isinstance(v, dict)}

    def window(self, days: int, now: datetime | None = None) -> dict[str, dict[str, Any]]:
        """Return the retained ledger entries in the inclusive N-day window."""
        current = _now(now).date()
        first = current - timedelta(days=max(1, days) - 1)
        data = _load(self.path)
        return {
            key: dict(value)
            for key, value in data.items()
            if _is_day_key(key)
            and first.isoformat() <= key <= current.isoformat()
            and isinstance(value, dict)
        }

    def windows(self) -> dict[str, dict[str, Any]]:
        raw = _load(self.path).get("windows")
        if not isinstance(raw, dict):
            return {}
        return {
            str(runner): dict(value) for runner, value in raw.items() if isinstance(value, dict)
        }

    def credits(self) -> dict[str, Any]:
        raw = _load(self.path).get("credits")
        return dict(raw) if isinstance(raw, dict) else {}

    def window_info(self, now: datetime | None = None) -> dict[str, dict[str, Any]]:
        """Return configured subscription windows and their learned usage state."""
        current = _now(now)
        stored = self.windows()
        runners = set(self.settings.budget.windows) | set(stored)
        result: dict[str, dict[str, Any]] = {}
        for runner in sorted(runners):
            config = self.settings.budget.windows.get(runner)
            item = stored.get(runner, {})
            started = item.get("started")
            resets = item.get("resets")
            cap = item.get("cap")
            if cap is None and config is not None:
                cap = config.tokens
            tokens = int(item.get("tokens", 0))
            if resets:
                try:
                    reset_at = datetime.fromisoformat(str(resets).replace("Z", "+00:00"))
                except ValueError:
                    reset_at = current
                if reset_at <= current:
                    tokens = 0
            pct = None
            if cap is not None:
                pct = round(min(100.0, 100.0 * tokens / max(1, int(cap))), 1)
            result[runner] = {
                "started": str(started) if started else None,
                "resets": str(resets) if resets else None,
                "tokens": tokens,
                "cap": int(cap) if cap is not None else None,
                "pct": pct,
            }
        return result

    def runs_today(self, tier: Tier, now: datetime | None = None) -> int:
        return int(self.day(now).get(tier.value, {}).get("runs", 0))

    def remaining(self, tier: Tier, now: datetime | None = None) -> int | None:
        cap = self.caps().get(tier.value)
        if cap is None:
            return None
        return max(0, cap - self.runs_today(tier, now))

    def exhausted(self, tier: Tier, now: datetime | None = None) -> bool:
        return bool(self.exhaustion_reasons(tier, now))

    def exhaustion_reasons(self, tier: Tier, now: datetime | None = None) -> list[str]:
        current = _now(now)
        raw = self.day(current).get(tier.value, {})
        reasons: list[str] = []
        run_cap = self.caps().get(tier.value)
        cost_cap = self.cost_caps().get(tier.value)
        equivalent_cap = self.equivalent_caps().get(tier.value)
        if run_cap is not None and int(raw.get("runs", 0)) >= run_cap:
            reasons.append("runs")
        if cost_cap is not None and float(raw.get("cost_usd", 0.0)) >= cost_cap:
            reasons.append("billed cost")
        if equivalent_cap is not None and float(raw.get("equivalent_usd", 0.0)) >= equivalent_cap:
            reasons.append("equivalent cost")
        today = self.spend_today(current)
        daily_cap = _positive_cap(self.settings.budget.daily_total_usd)
        if (
            daily_cap is not None
            and max(float(today["cost_usd"]), float(today["equivalent_usd"])) >= daily_cap
        ):
            reasons.append("daily total")
        week = self.spend_window(7, current)
        weekly_cap = _positive_cap(self.settings.budget.weekly_total_usd)
        if (
            weekly_cap is not None
            and max(float(week["cost_usd"]), float(week["equivalent_usd"])) >= weekly_cap
        ):
            reasons.append("weekly total")
        return reasons

    def spend_today(self, now: datetime | None = None) -> dict[str, int | float]:
        return self.spend_window(1, now)

    def spend_window(self, days: int, now: datetime | None = None) -> dict[str, int | float]:
        total: dict[str, int | float] = {
            "runs": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "equivalent_usd": 0.0,
        }
        for raw_day in self.window(days, now).values():
            for tier in (Tier.plan, Tier.implement, Tier.bulk, Tier.local):
                raw = raw_day.get(tier.value)
                if not isinstance(raw, dict):
                    continue
                total["runs"] = int(total["runs"]) + int(raw.get("runs", 0))
                total["tokens"] = int(total["tokens"]) + int(raw.get("tokens", 0))
                total["cost_usd"] = float(total["cost_usd"]) + float(raw.get("cost_usd", 0.0))
                total["equivalent_usd"] = float(total["equivalent_usd"]) + float(
                    raw.get("equivalent_usd", 0.0)
                )
        return total

    def attribution(
        self, now: datetime | None = None, *, days: int = 1
    ) -> dict[str, dict[str, dict[str, int | float]]]:
        """Aggregate project and goal attribution over an inclusive day window."""
        current = _now(now).date()
        first = current - timedelta(days=max(1, days) - 1)
        raw = _load(self.path).get("attribution") or {}
        result: dict[str, dict[str, dict[str, int | float]]] = {
            "projects": {},
            "goals": {},
        }
        if not isinstance(raw, dict):
            return result
        for kind in ("projects", "goals"):
            targets = raw.get(kind) or {}
            if not isinstance(targets, dict):
                continue
            for target, value in targets.items():
                if not isinstance(value, dict):
                    continue
                dates = value.get("days") or {}
                if not isinstance(dates, dict):
                    continue
                total: dict[str, int | float] = {
                    "runs": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "equivalent_usd": 0.0,
                }
                for key, entry in dates.items():
                    if not (
                        isinstance(key, str)
                        and first.isoformat() <= key <= current.isoformat()
                        and isinstance(entry, dict)
                    ):
                        continue
                    for field in ("runs", "tokens"):
                        total[field] = int(total[field]) + int(entry.get(field, 0))
                    for field in ("cost_usd", "equivalent_usd"):
                        total[field] = float(total[field]) + float(entry.get(field, 0.0))
                if int(total["runs"]):
                    result[kind][str(target)] = total
        return result

    def attribution_total(self, kind: str, target: str) -> dict[str, int | float]:
        raw = _load(self.path).get("attribution") or {}
        targets = raw.get(kind) if isinstance(raw, dict) else None
        value = targets.get(target) if isinstance(targets, dict) else None
        total = value.get("total") if isinstance(value, dict) else None
        if not isinstance(total, dict):
            return {"runs": 0, "tokens": 0, "cost_usd": 0.0, "equivalent_usd": 0.0}
        return {
            "runs": int(total.get("runs", 0)),
            "tokens": int(total.get("tokens", 0)),
            "cost_usd": float(total.get("cost_usd", 0.0)),
            "equivalent_usd": float(total.get("equivalent_usd", 0.0)),
        }

    def forecast(self, now: datetime | None = None) -> dict[str, dict[str, float]]:
        current = _now(now)
        data = _load(self.path)
        raw_day = data.get(current.date().isoformat()) or {}
        hours = raw_day.get("hours") if isinstance(raw_day, dict) else {}
        cutoff = current - timedelta(hours=3)
        result: dict[str, dict[str, float]] = {}
        today = self.day(current)
        for tier in (Tier.plan, Tier.implement, Tier.bulk, Tier.local):
            recent = 0.0
            if isinstance(hours, dict):
                for stamp, by_tier in hours.items():
                    try:
                        observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if not cutoff <= observed <= current or not isinstance(by_tier, dict):
                        continue
                    entry = by_tier.get(tier.value)
                    if isinstance(entry, dict):
                        recent += float(entry.get("equivalent_usd", 0.0))
            burn = recent / 3.0
            used = float(today.get(tier.value, {}).get("equivalent_usd", 0.0))
            midnight = datetime.combine(
                current.date() + timedelta(days=1),
                datetime.min.time(),
                tzinfo=current.tzinfo or UTC,
            )
            remaining_hours = max(0.0, (midnight - current).total_seconds() / 3600)
            result[tier.value] = {
                "burn_usd_per_hour": burn,
                "projected_day_end_usd": used + burn * remaining_hours,
            }
        return result

    def ceilings(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return every configured ceiling with current usage and percentage."""
        current = _now(now)
        rows: list[dict[str, Any]] = []
        today = self.day(current)
        for tier in (Tier.plan, Tier.implement, Tier.bulk, Tier.local):
            usage = today.get(tier.value, {})
            values = (
                ("runs", float(usage.get("runs", 0)), self.caps().get(tier.value), "runs"),
                (
                    "billed",
                    float(usage.get("cost_usd", 0.0)),
                    self.cost_caps().get(tier.value),
                    "usd",
                ),
                (
                    "equivalent",
                    float(usage.get("equivalent_usd", 0.0)),
                    self.equivalent_caps().get(tier.value),
                    "usd",
                ),
            )
            for label, used, cap, unit in values:
                if cap is not None:
                    rows.append(
                        self._ceiling(
                            f"{tier.value} {label}", used, float(cap), unit, tier=tier.value
                        )
                    )
        daily_cap = _positive_cap(self.settings.budget.daily_total_usd)
        daily = self.spend_today(current)
        if daily_cap is not None:
            rows.append(
                self._ceiling(
                    "daily total",
                    max(float(daily["cost_usd"]), float(daily["equivalent_usd"])),
                    daily_cap,
                    "usd",
                )
            )
        weekly_cap = _positive_cap(self.settings.budget.weekly_total_usd)
        week = self.spend_window(7, current)
        if weekly_cap is not None:
            rows.append(
                self._ceiling(
                    "weekly total",
                    max(float(week["cost_usd"]), float(week["equivalent_usd"])),
                    weekly_cap,
                    "usd",
                )
            )
        projects = self.attribution(current).get("projects", {})
        for slug, profile in sorted(self.settings.projects.items()):
            cap = _positive_cap(profile.budget_usd_per_day)
            if cap is None:
                continue
            usage = projects.get(slug, {})
            used = max(
                float(usage.get("cost_usd", 0.0)),
                float(usage.get("equivalent_usd", 0.0)),
            )
            rows.append(self._ceiling(f"project {slug}", used, cap, "usd", target=slug))
        epic_cap = _positive_cap(self.settings.pipeline.budget_usd_per_epic)
        raw = _load(self.path).get("attribution") or {}
        goals = raw.get("goals") if isinstance(raw, dict) else {}
        if epic_cap is not None and isinstance(goals, dict):
            for goal in sorted(goals):
                usage = self.attribution_total("goals", str(goal))
                used = max(
                    float(usage.get("cost_usd", 0.0)),
                    float(usage.get("equivalent_usd", 0.0)),
                )
                rows.append(self._ceiling(f"epic {goal}", used, epic_cap, "usd", target=str(goal)))
        return rows

    @staticmethod
    def _ceiling(
        name: str,
        used: float,
        cap: float,
        unit: str,
        *,
        tier: str | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        value: int | float = int(used) if unit == "runs" else used
        return {
            "name": name,
            "used": value,
            "cap": int(cap) if unit == "runs" else cap,
            "pct": round(min(100.0, 100.0 * used / cap), 1),
            "unit": unit,
            "tier": tier,
            "target": target,
        }

    def claim_alert(self, key: str, *, apply: bool = True) -> bool:
        data = _load(self.path)
        alerts = data.setdefault("alerts", [])
        if not isinstance(alerts, list):
            alerts = []
            data["alerts"] = alerts
        if key in alerts:
            return False
        if apply:
            alerts.append(key)
            data["alerts"] = [str(item) for item in alerts[-500:]]
            _save(self.path, data)
        return True

    def record(
        self,
        tier: Tier,
        *,
        runner: str | None = None,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        cost_usd: float | None = None,
        labels: list[str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        data = _load(self.path)
        current = _now(now)
        key = current.date().isoformat()
        day = data.setdefault(key, {})
        usage_runner = getattr(usage, "runner", None)
        runner = runner or (str(usage_runner) if usage_runner else None)
        reported = (
            float(cost_usd)
            if isinstance(cost_usd, int | float) and not isinstance(cost_usd, bool)
            else None
        )
        subscription = runner is not None and runner in {"claude", "codex", "local", "stub"}
        charged = reported if reported is not None and not subscription else 0.0
        warning: str | None = None
        if reported is not None:
            equivalent, estimated = reported, False
        elif runner:
            equivalent, estimated = estimate_usd(self.settings, runner, model, usage)
            if price_for(self.settings, runner, model) is None:
                target = f"{runner}:{model}" if model else runner
                warning = f"no price for {target}; counting 0 USD equivalent"
            if uses_openrouter(runner):
                # OpenRouter bills these runs for real. The harness either reports no
                # cost (Claude Code) or an Anthropic-priced one that is wrong for this
                # provider, so the price-table estimate is what we bill (ADR-0016).
                charged = equivalent
        else:
            equivalent, estimated = 0.0, False
        tokens = self._tokens(usage)
        entry = day.setdefault(tier.value, _usage_entry())
        _add_usage(
            entry,
            runs=1,
            tokens=tokens,
            cost_usd=charged,
            equivalent_usd=equivalent,
            estimated=estimated,
        )
        if runner:
            runners = day.setdefault("runners", {})
            runner_entry = runners.setdefault(runner, _usage_entry())
            _add_usage(
                runner_entry,
                runs=1,
                tokens=tokens,
                cost_usd=charged,
                equivalent_usd=equivalent,
                estimated=estimated,
            )
            self._add_window_tokens(data, runner, tokens, current)
        hour = current.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        hours = day.setdefault("hours", {})
        by_tier = hours.setdefault(hour, {})
        hour_entry = by_tier.setdefault(tier.value, _usage_entry())
        _add_usage(
            hour_entry,
            runs=1,
            tokens=tokens,
            cost_usd=charged,
            equivalent_usd=equivalent,
            estimated=estimated,
        )
        for label in labels or []:
            if label.startswith("project:"):
                self._add_attribution(
                    data,
                    "projects",
                    label.split(":", 1)[1],
                    key,
                    tokens,
                    charged,
                    equivalent,
                    estimated,
                )
            elif label.startswith("goal:"):
                self._add_attribution(
                    data,
                    "goals",
                    label.split(":", 1)[1],
                    key,
                    tokens,
                    charged,
                    equivalent,
                    estimated,
                )
        # Keep at most 14 date-keyed ledger entries; metadata siblings are retained.
        day_keys = sorted(key for key in data if _is_day_key(key))
        for old in day_keys[:-14]:
            del data[old]
        _save(self.path, data)
        return {
            "runs": 1.0,
            "tokens": float(tokens),
            "cost_usd": charged,
            "equivalent_usd": equivalent,
            "estimated": estimated,
            "warning": warning,
        }

    @staticmethod
    def _add_attribution(
        data: dict[str, Any],
        kind: str,
        target: str,
        day: str,
        tokens: int,
        cost_usd: float,
        equivalent_usd: float,
        estimated: bool,
    ) -> None:
        if not target:
            return
        attribution = data.setdefault("attribution", {})
        targets = attribution.setdefault(kind, {})
        value = targets.setdefault(target, {"total": _usage_entry(), "days": {}})
        total = value.setdefault("total", _usage_entry())
        days = value.setdefault("days", {})
        day_entry = days.setdefault(day, _usage_entry())
        for entry in (total, day_entry):
            _add_usage(
                entry,
                runs=1,
                tokens=tokens,
                cost_usd=cost_usd,
                equivalent_usd=equivalent_usd,
                estimated=estimated,
            )

    def record_interactive(
        self,
        runner: str,
        *,
        session_id: str,
        timestamp: datetime,
        tokens: int,
        apply: bool = True,
    ) -> int:
        """Fold one interactive session snapshot into runner totals exactly once.

        Codex token events are cumulative, and Claude transcripts can grow after an
        import. The stored session snapshot therefore contributes only the positive
        delta since the last timestamp for that session.
        """
        stamp = _now(timestamp).astimezone(UTC)
        data = _load(self.path)
        imports = data.get("_imports")
        if not isinstance(imports, dict):
            imports = {}
        key = f"{runner}:{session_id}"
        previous = imports.get(key)
        previous_tokens = int(previous.get("tokens", 0)) if isinstance(previous, dict) else 0
        previous_stamp = str(previous.get("timestamp")) if isinstance(previous, dict) else ""
        iso_stamp = stamp.isoformat(timespec="seconds")
        if previous_stamp and iso_stamp <= previous_stamp:
            return 0
        delta = max(0, int(tokens) - previous_tokens)
        if not apply:
            return delta

        day = data.setdefault(stamp.date().isoformat(), {})
        runner_entries = day.setdefault("runners", {})
        entry = runner_entries.setdefault(runner, _usage_entry())
        if not isinstance(entry, dict):
            entry = _usage_entry()
            runner_entries[runner] = entry
        equivalent, estimated = estimate_usd(self.settings, runner, None, {"total_tokens": delta})
        _add_usage(
            entry,
            runs=1 if previous is None else 0,
            tokens=delta,
            cost_usd=0.0,
            equivalent_usd=equivalent,
            estimated=estimated,
        )
        sources = entry.setdefault("sources", {})
        if isinstance(sources, dict):
            source = sources.setdefault("interactive", {"runs": 0, "tokens": 0})
            if isinstance(source, dict):
                if previous is None:
                    source["runs"] = int(source.get("runs", 0)) + 1
                source["tokens"] = int(source.get("tokens", 0)) + delta
        imports[key] = {
            "source": "interactive",
            "runner": runner,
            "session_id": session_id,
            "timestamp": iso_stamp,
            "tokens": int(tokens),
        }
        data["_imports"] = imports
        self._add_window_tokens(data, runner, delta, stamp)
        _save(self.path, data)
        return delta

    def learn_window(
        self,
        runner: str,
        *,
        started: datetime,
        resets: datetime,
        tokens: int,
        apply: bool = True,
    ) -> None:
        """Persist the first observed subscription cap as an estimate."""
        if not apply:
            return
        data = _load(self.path)
        windows = data.setdefault("windows", {})
        existing = windows.get(runner) if isinstance(windows, dict) else None
        cap = (
            int(existing["cap"])
            if isinstance(existing, dict) and existing.get("cap") is not None
            else int(tokens)
        )
        if not isinstance(windows, dict):
            windows = {}
            data["windows"] = windows
        windows[runner] = {
            "started": _now(started).astimezone(UTC).isoformat(timespec="seconds"),
            "resets": _now(resets).astimezone(UTC).isoformat(timespec="seconds"),
            "tokens": int(tokens),
            "cap": cap,
        }
        _save(self.path, data)

    def save_credits(
        self, remaining_usd: float | None, *, checked: datetime, apply: bool = True
    ) -> None:
        if not apply:
            return
        data = _load(self.path)
        data["credits"] = {
            "openrouter": {
                "remaining_usd": remaining_usd,
                "checked": _now(checked).isoformat(timespec="seconds"),
            }
        }
        _save(self.path, data)

    @staticmethod
    def _add_window_tokens(data: dict[str, Any], runner: str, tokens: int, now: datetime) -> None:
        windows = data.get("windows")
        if not isinstance(windows, dict) or not tokens:
            return
        item = windows.get(runner)
        if not isinstance(item, dict):
            return
        try:
            started = datetime.fromisoformat(str(item["started"]).replace("Z", "+00:00"))
            resets = datetime.fromisoformat(str(item["resets"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return
        if started <= now < resets:
            item["tokens"] = int(item.get("tokens", 0)) + int(tokens)

    @staticmethod
    def _tokens(usage: dict[str, Any] | None) -> int:
        if not usage:
            return 0
        total = usage.get("total_tokens")
        if isinstance(total, int | float):
            return int(total)
        for first, second in (
            ("input_tokens", "output_tokens"),
            ("prompt_tokens", "completion_tokens"),
        ):
            values = (usage.get(first), usage.get(second))
            if any(isinstance(value, int | float) for value in values):
                return sum(int(value) for value in values if isinstance(value, int | float))
        return 0


@dataclass(frozen=True)
class BudgetBlock:
    reason: str
    target: str
    used: float
    cap: float


def budget_block(
    settings: Settings,
    ledger: BudgetLedger,
    labels: list[str],
    *,
    now: datetime | None = None,
) -> BudgetBlock | None:
    """Return the first project or epic ceiling that refuses a new run."""
    project = next(
        (label.split(":", 1)[1] for label in labels if label.startswith("project:")), None
    )
    if project:
        profile = settings.projects.get(project)
        cap = _positive_cap(profile.budget_usd_per_day if profile else None)
        if cap is not None:
            usage = ledger.attribution(now).get("projects", {}).get(project, {})
            used = max(
                float(usage.get("cost_usd", 0.0)),
                float(usage.get("equivalent_usd", 0.0)),
            )
            if used >= cap:
                return BudgetBlock("budget:project", project, used, cap)
    goal = next((label.split(":", 1)[1] for label in labels if label.startswith("goal:")), None)
    cap = _positive_cap(settings.pipeline.budget_usd_per_epic)
    if goal and cap is not None:
        usage = ledger.attribution_total("goals", goal)
        used = max(
            float(usage.get("cost_usd", 0.0)),
            float(usage.get("equivalent_usd", 0.0)),
        )
        if used >= cap:
            return BudgetBlock("budget:epic", goal, used, cap)
    return None


def record_agent_spend(
    settings: Settings,
    agent_name: str,
    report: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add measured workday run cost to an agent's declared resource usage."""
    current = _now(now)
    path = settings.state_dir() / "agents" / agent_name / "resources.json"
    stored = _load(path)
    resources = getattr(report, "resources", None)
    raw = dict(resources) if isinstance(resources, dict) else dict(stored)
    if raw.get("date") != current.date().isoformat():
        raw = {
            "date": current.date().isoformat(),
            "gpu_hours": 0.0,
            "runs": 0,
            "spend_usd": 0.0,
        }
    runs = getattr(report, "runs", [])
    billed = 0.0
    equivalent = 0.0
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            continue
        billed += float(run.get("cost_usd") or 0.0)
        equivalent += float(run.get("equivalent_usd") or 0.0)
    raw["spend_usd"] = float(raw.get("spend_usd", 0.0)) + billed
    previous_equivalent = (
        float(stored.get("equivalent_usd", 0.0))
        if stored.get("date") == current.date().isoformat()
        else 0.0
    )
    raw["equivalent_usd"] = float(raw.get("equivalent_usd", previous_equivalent)) + equivalent
    # `grants`/`grants_file` live only in the in-memory usage mapping (cube.agents).
    stored_usage = {key: value for key, value in raw.items() if key not in AGENT_USAGE_TRANSIENT}
    _save(path, stored_usage)
    if isinstance(resources, dict):
        resources.update(raw)
    return raw


class Backoff:
    """state/backoff.json: {"codex": {"failures": 2, "until": ISO, "last_error": "..."}}."""

    def __init__(self, state_dir: Path):
        self.path = state_dir / "backoff.json"

    def state(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in _load(self.path).items() if isinstance(v, dict)}

    @staticmethod
    def looks_rate_limited(*texts: str | None) -> bool:
        from cube.runners.base import looks_rate_limited

        return looks_rate_limited(*texts)

    def blocked_until(
        self,
        runner: str,
        now: datetime | None = None,
        *,
        model: str | None = None,
    ) -> datetime | None:
        state = self.state()
        keys = [entry_target(runner, model)] if model else []
        keys.append(runner)
        for key in keys:
            entry = state.get(key)
            if not entry or not entry.get("until"):
                continue
            until = datetime.fromisoformat(str(entry["until"]))
            if until > _now(now):
                return until
        return None

    def is_blocked(
        self,
        runner: str,
        now: datetime | None = None,
        *,
        model: str | None = None,
    ) -> bool:
        return self.blocked_until(runner, now, model=model) is not None

    def record_failure(
        self,
        runner: str,
        *,
        model: str | None = None,
        error: str = "",
        now: datetime | None = None,
    ) -> datetime:
        target_runner, target_model = split_target(runner)
        if model is None and target_model is not None:
            runner, model = target_runner, target_model
        target = entry_target(runner, model)
        if model and model.endswith(":free") and self.looks_rate_limited(error):
            data = _load(self.path)
            entry = data.get(target) or {}
            failures = int(entry.get("failures", 0)) + 1
            until = _now(now) + timedelta(seconds=FREE_MODEL_BACKOFF_SECONDS)
            data[target] = {
                "failures": failures,
                "until": until.isoformat(timespec="seconds"),
                "last_error": error[:500],
                "delay_seconds": FREE_MODEL_BACKOFF_SECONDS,
            }
            _save(self.path, data)
            return until

        if uses_openrouter(runner) and self.looks_rate_limited(error):
            # Robert, 2026-09-07: an OpenRouter 429 is one provider's moment, not a
            # subscription window. Back this target off for ten minutes; the other
            # OpenRouter entries stay usable.
            data = _load(self.path)
            entry = data.get(target) or {}
            failures = int(entry.get("failures", 0)) + 1
            until = _now(now) + timedelta(seconds=FREE_MODEL_BACKOFF_SECONDS)
            data[target] = {
                "failures": failures,
                "until": until.isoformat(timespec="seconds"),
                "last_error": error[:500],
                "delay_seconds": FREE_MODEL_BACKOFF_SECONDS,
            }
            _save(self.path, data)
            return until

        if self.looks_rate_limited(error):
            control, changed = TierState(self.path.parent).exhaust(
                runner, error=error or "usage limit reached", now=now
            )
            if changed:
                event = make_event(
                    "attention",
                    source="cube",
                    session="cube",
                    title=f"{runner} usage exhausted until {control.until}",
                    data={
                        "kind": "budget",
                        "runner": runner,
                        "state": "exhausted",
                        "until": control.until,
                        "reason": control.reason,
                    },
                )
                event["ts"] = _now(now).isoformat(timespec="seconds")
                event["severity"] = "high"
                append_event(self.path.parent, event)
            if control.until:
                return datetime.fromisoformat(control.until)
            return _now(now)

        data = _load(self.path)
        entry = data.get(target) or {}
        failures = int(entry.get("failures", 0)) + 1
        delay = min(BACKOFF_BASE_SECONDS * (2 ** (failures - 1)), BACKOFF_MAX_SECONDS)
        until = _now(now) + timedelta(seconds=delay)
        data[target] = {
            "failures": failures,
            "until": until.isoformat(timespec="seconds"),
            "last_error": error[:500],
            "delay_seconds": delay,
        }
        _save(self.path, data)
        return until

    def record_success(self, runner: str, model: str | None = None) -> None:
        data = _load(self.path)
        target = entry_target(runner, model)
        if target in data:
            del data[target]
            _save(self.path, data)


def effective_tier(role_tier: Tier, bead_tier: Tier | None) -> Tier:
    """The bead's tier label wins unless it would downgrade a plan role."""
    if bead_tier is None:
        return role_tier
    if role_tier == Tier.plan and bead_tier != Tier.plan:
        raise Refused(f"refusing to downgrade plan-tier role to {bead_tier.value}")
    if TIER_RANK[bead_tier] > TIER_RANK[role_tier]:
        return bead_tier
    return bead_tier


def default_availability(settings: Settings) -> Callable[[str], bool]:
    """Static availability: binary on PATH, key or URL in .env. Endpoint probes are injectable."""

    def available(runner: str) -> bool:
        if runner == STUB:
            return True
        harness = harness_of(runner)
        if harness in RUNNER_BINARIES:
            if shutil.which(RUNNER_BINARIES[harness]) is None:
                return False
            # A harness on a non-native provider also needs that provider's key.
            if uses_openrouter(runner):
                return bool(settings.env.get("OPENROUTER_API_KEY"))
            if uses_local(runner):
                return bool(settings.env.get("VLLM_BASE_URL"))
            return True
        if runner == "openrouter":
            return bool(settings.env.get("OPENROUTER_API_KEY"))
        if runner == "local":
            return bool(settings.env.get("VLLM_BASE_URL"))
        return False

    return available


def open_endpoints_allowed(
    settings: Settings,
    *,
    role: str | None = None,
    agent: str | None = None,
    labels: list[str] | None = None,
) -> bool:
    """Whether this run may use a free (open-data) endpoint.

    Free OpenRouter endpoints may log, publish or train on prompts. Only the agents
    or roles Robert listed under ``privacy.open_endpoints_for`` qualify; the agent
    comes from the caller or from the bead's ``agent:`` label. Nothing else does,
    whatever the bead's privacy class: the prompt carries the agent's memory.
    """
    allowed = {name.strip() for name in settings.privacy.open_endpoints_for if name}
    if not allowed:
        return False
    names = {agent, role}
    for label in labels or []:
        if label.startswith("agent:"):
            names.add(label[len("agent:") :])
    return any(name in allowed for name in names if name)


def choose(
    settings: Settings,
    tier: Tier,
    *,
    privacy: Privacy = Privacy.internal,
    requested_runner: str | None = None,
    requested_model: str | None = None,
    available: Callable[[str], bool] | None = None,
    budget: BudgetLedger | None = None,
    backoff: Backoff | None = None,
    tier_state: TierState | None = None,
    labels: list[str] | None = None,
    now: datetime | None = None,
    role: str | None = None,
    needs_tools: bool = False,
    agent: str | None = None,
) -> Route:
    """Pick (runner, model, profile) for a tier. Raises Queued or Refused.

    ``role`` is the running role; tier entries with ``only:`` are skipped for any
    other role (a subscription reserved for the coordinator).
    ``needs_tools`` skips chat-only entries: work that must run commands needs an
    agentic harness, and a plain chat completion can only return text (ADR-0016).
    ``agent`` is the standing agent behind the run (or the bead's ``agent:`` label);
    free entries are open-data endpoints and only ``privacy.open_endpoints_for``
    agents or roles may use them (ADR-0018).
    """
    if requested_runner == STUB:
        return Route(tier, STUB, requested_model, None, "stub runner requested", needs_tools)
    if tier == Tier.none:
        raise Refused("tier none has no model runner (python runtime)")
    available = available or default_availability(settings)
    local_runner = settings.privacy.local_only_requires
    tier_state = tier_state or TierState(settings.state_dir())

    labels = labels or []
    open_data_ok = open_endpoints_allowed(settings, role=role, agent=agent, labels=labels)
    protected_plan = tier == Tier.plan and any(
        label in {"kind:review", "stage:design"} for label in labels
    )
    start_tier: Tier = tier
    downgrade = tier_state.downgrades(now=now).get(tier.value)
    if downgrade and privacy != Privacy.local_only and not requested_runner and not protected_plan:
        try:
            proposed = Tier(str(downgrade["to"]))
        except ValueError:
            proposed = tier
        if proposed in TIER_FALLBACKS and TIER_RANK.get(proposed, 0) < TIER_RANK[tier]:
            start_tier = proposed
    candidates = [tier] if protected_plan else list(TIER_FALLBACKS[start_tier])
    if privacy == Privacy.local_only:
        if requested_runner and not uses_local(requested_runner):
            raise Refused(
                f"privacy local-only allows only runner {local_runner!r}, not {requested_runner!r}"
            )
        candidates = [Tier.local]
        entries = [
            entry
            for entry in settings.tiers.get(Tier.local.value, [])
            if uses_local(entry.runner_name)
            and (not requested_runner or requested_runner == entry.runner_name)
        ]
        if not entries:
            if requested_runner and requested_runner != local_runner:
                raise Refused("requested local harness is not configured in the local tier")
            entries = [TierEntry(runner=local_runner)]
        entries_by_tier = {Tier.local: entries}
    elif requested_runner:
        entries = [
            entry
            for entry in settings.tiers.get(tier.value, [])
            if requested_runner in (entry.runner_name, entry.runner)
        ]
        if not entries:
            if tier == Tier.plan:
                raise Refused(
                    f"runner {requested_runner!r} is not in the plan tier; "
                    "planning and review are never downgraded by an explicit runner request"
                )
            entries = [TierEntry(runner=requested_runner, model=requested_model)]
        candidates = [tier]
        entries_by_tier = {tier: entries}
    else:
        entries_by_tier = {
            candidate: list(settings.tiers.get(candidate.value, [])) for candidate in candidates
        }
        if open_data_ok and Tier.bulk in entries_by_tier:
            # The free pool (ADR-0018): discovered daily by the budget patrol, tried
            # before the paid bulk entries, and only by an open-data run.
            pool = [
                TierEntry(runner="openrouter", model=item.id)
                for item in load_pool(settings, now=now)
            ]
            bulk = entries_by_tier[Tier.bulk]
            # Robert, 2026-09-07 (ADR-0021): the group's own endpoint comes first
            # for everyone; the pool sits between it and the paid entries.
            head = 0
            while head < len(bulk) and uses_local(bulk[head].runner_name):
                head += 1
            entries_by_tier[Tier.bulk] = bulk[:head] + pool + bulk[head:]

    skipped: list[str] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    # A requested model that a tier entry already names is a preference for that
    # entry (a role pinned to GLM 5.3 Flash lands on the Flash harness entry and
    # its fallbacks keep their own models). Only when no entry names it does the
    # request override the model of whatever entry is chosen.
    model_pinned = bool(requested_model) and any(
        entry.model == requested_model
        for candidate in candidates
        for entry in entries_by_tier.get(candidate, [])
    )
    for candidate in candidates:
        if budget is not None and budget.exhausted(candidate, now) and not settings.fleet_enabled:
            detail = ", ".join(budget.exhaustion_reasons(candidate, now))
            skipped.append(f"{candidate.value} budget exhausted ({detail})")
            continue
        entries = entries_by_tier.get(candidate, [])
        preference = tier_state.preference(candidate.value)
        if preference and not (requested_runner or requested_model):
            preferred_runner, preferred_model = split_target(preference)
            entries = sorted(
                entries,
                key=lambda entry: (
                    entry.runner_name != preferred_runner
                    or (preferred_model is not None and entry.model != preferred_model)
                ),
            )
        if model_pinned:
            entries = sorted(entries, key=lambda entry: entry.model != requested_model)
        free_backoffs_skipped = 0
        for entry in entries:
            model = entry.model if model_pinned else (requested_model or entry.model)
            token = entry.runner_name
            # The fleet's paid-provider budget must never stop free local work.
            # Check per candidate, not per logical tier (plan can contain both).
            if (
                settings.fleet_enabled
                and budget is not None
                and not uses_local(token)
                and budget.exhausted(candidate, now)
            ):
                skipped.append(f"{token} paid budget exhausted")
                continue
            identity = (token, model, entry.profile)
            if identity in seen:
                continue
            seen.add(identity)
            target = entry_target(token, model)
            if needs_tools and not is_agentic(token):
                skipped.append(f"{target} has no tools")
                continue
            if not entry.allows(role):
                skipped.append(
                    f"{target} not for {role}"
                    if role in entry.not_for
                    else f"{target} reserved for {', '.join(entry.only)}"
                )
                continue
            if not open_data_ok and is_free(settings, token, model):
                skipped.append(f"{target} is a free open-data endpoint")
                continue
            control = tier_state.control(token, model, now)
            if control is not None:
                skipped.append(
                    f"{target} {control.state}"
                    + (f" until {control.until}" if control.until else "")
                )
                continue
            if backoff is not None and backoff.is_blocked(token, now, model=model):
                until = backoff.blocked_until(token, now, model=model)
                skipped.append(f"{target} backing off until {until.isoformat() if until else '?'}")
                if is_free(settings, token, model):
                    free_backoffs_skipped += 1
                continue
            if not available(token):
                skipped.append(f"{token} unavailable")
                continue
            if start_tier != tier and candidate == start_tier:
                reason = f"downgraded from {tier.value} to {start_tier.value}"
            elif start_tier != tier:
                reason = (
                    f"downgraded from {tier.value} to {start_tier.value}, "
                    f"then fallback to {candidate.value}"
                )
            elif candidate == tier:
                reason = f"first available in tier {tier.value}"
            elif privacy == Privacy.local_only:
                reason = f"local-only route for tier {tier.value}"
            else:
                reason = f"fallback from tier {tier.value} to {candidate.value}"
            if (
                backoff is not None
                and free_backoffs_skipped
                and not is_free(settings, token, model)
            ):
                free_entries = [
                    free_entry
                    for free_entry in entries
                    if is_free(settings, free_entry.runner_name, free_entry.model)
                ]
                if free_entries and all(
                    backoff.is_blocked(
                        free_entry.runner_name,
                        now,
                        model=free_entry.model,
                    )
                    for free_entry in free_entries
                ):
                    event = make_event(
                        "attention",
                        source="cube",
                        session="cube",
                        title="free models exhausted, paid fallback in use",
                        data={
                            "kind": "budget",
                            "tier": candidate.value,
                            "runner": token,
                            "model": model,
                        },
                    )
                    event["ts"] = _now(now).isoformat(timespec="seconds")
                    event["severity"] = "warn"
                    append_event(settings.state_dir(), event)
            return Route(
                candidate,
                token,
                model,
                entry.profile,
                reason + (f" after skipping {', '.join(skipped)}" if skipped else ""),
                needs_tools,
            )
    if privacy == Privacy.local_only:
        raise Queued(
            f"local runner unavailable ({'; '.join(skipped)}); local-only work never goes to cloud"
        )
    raise Queued(f"no runner available from tier {tier.value}: {'; '.join(skipped)}")
