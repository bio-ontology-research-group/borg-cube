"""Proactive budget patrol and offline interactive-usage importer.

The patrol checks OpenRouter credits and refreshes its model-list cache at most
once per day. Claude Max and ChatGPT windows are learned from local transcripts
after a usage-limit message identifies their reset time.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from cube.config import Settings, TierEntry
from cube.model import Tier
from cube.patrols.base import PatrolReport, attention_event, register
from cube.router import Backoff, BudgetLedger, TierState, parse_reset_time
from cube.router.controls import entry_target
from cube.router.free_pool import free_models_from_catalogue, rank
from cube.router.prices import is_free, rank_usd
from cube.runners.naming import uses_openrouter

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _now(parsed)
        except ValueError:
            pass
    return _now(fallback)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_remaining(payload: object) -> float | None:
    if isinstance(payload, bytes):
        try:
            payload = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
    if not isinstance(payload, dict):
        return _number(payload)
    data = payload.get("data")
    if isinstance(data, dict):
        payload = data
    for key in ("remaining_usd", "remaining", "balance"):
        value = _number(payload.get(key))
        if value is not None:
            return value
    total = _number(payload.get("total_credits"))
    usage = _number(payload.get("total_usage"))
    if total is not None and usage is not None:
        return total - usage
    credits = _number(payload.get("credits"))
    usage = _number(payload.get("usage"))
    if credits is not None and usage is not None:
        return credits - usage
    return None


def fetch_openrouter_credits(api_key: str, *, timeout: float = 10.0) -> float | None:
    """Fetch remaining OpenRouter credits without exposing the bearer key."""
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return _payload_remaining(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("OpenRouter credits request failed") from exc


def fetch_openrouter_models(*, timeout: float = 10.0) -> object:
    """Fetch OpenRouter's public model catalogue."""
    request = urllib.request.Request(OPENROUTER_MODELS_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError("OpenRouter models request failed") from exc


def _model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    return [
        str(item["id"])
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _read_model_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _write_model_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def refresh_openrouter_models(
    settings: Settings,
    *,
    current: datetime,
    fetcher: Callable[[], object] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Refresh the local model id cache no more than once per UTC day."""
    path = settings.state_dir() / "cache" / "openrouter-models.json"
    cached = _read_model_cache(path)
    checked = _timestamp(cached.get("checked"), current)
    if cached.get("checked") and checked.date() == current.date() and "free" in cached:
        return {"status": "cached", **cached}
    if not apply:
        return {
            "status": "would-refresh",
            "checked": cached.get("checked"),
            "models": list(cached.get("models") or []),
        }
    try:
        payload = (fetcher or fetch_openrouter_models)()
        models = _model_ids(payload)
        if not models:
            raise RuntimeError("OpenRouter models response contained no model ids")
        updated = {
            "checked": current.isoformat(timespec="seconds"),
            "models": models,
            # The free pool (ADR-0018): what an open-data run may try, ranked by the router.
            "free": [item.as_dict() for item in rank(free_models_from_catalogue(payload))],
        }
        _write_model_cache(path, updated)
        return {"status": "refreshed", **updated}
    except Exception as exc:
        attempted = {
            "checked": current.isoformat(timespec="seconds"),
            "models": list(cached.get("models") or []),
            "error": str(exc),
        }
        _write_model_cache(path, attempted)
        raise


@dataclass(frozen=True)
class InteractiveRecord:
    runner: str
    session_id: str
    timestamp: datetime
    tokens: int
    source: str = "interactive"


@dataclass(frozen=True)
class LimitObservation:
    runner: str
    timestamp: datetime
    resets: datetime


def _tokens(usage: object) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in ("total_tokens", "token_count"):
        value = usage.get(key)
        if isinstance(value, int | float):
            return int(value)
    values = [usage.get(key) for key in ("input_tokens", "output_tokens")]
    if any(isinstance(value, int | float) for value in values):
        return sum(int(value) for value in values if isinstance(value, int | float))
    return 0


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(
            _text(value[key])
            for key in ("message", "content", "text", "reason", "error")
            if key in value
        )
    return ""


def _is_limit_message(text: str) -> bool:
    lowered = text.lower()
    return (
        "usage limit" in lowered
        or "rate limit" in lowered
        or "hit your limit" in lowered
        or "reached your limit" in lowered
    )


def _session_id(raw: dict[str, Any], fallback: str) -> str:
    for key in ("sessionId", "session_id", "session-id"):
        if raw.get(key):
            return str(raw[key])
    payload = raw.get("payload")
    if isinstance(payload, dict) and payload.get("session_id"):
        return str(payload["session_id"])
    return fallback


def _read_json_lines(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def _codex_file(
    path: Path, since: date | None
) -> tuple[InteractiveRecord | None, list[LimitObservation]]:
    fallback = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    session_id = path.stem.removeprefix("rollout-")
    latest: tuple[datetime, int] | None = None
    limits: list[LimitObservation] = []
    for raw in _read_json_lines(path):
        stamp = _timestamp(raw.get("timestamp"), fallback)
        if raw.get("type") == "session_meta":
            payload = raw.get("payload")
            if isinstance(payload, dict) and payload.get("session_id"):
                session_id = str(payload["session_id"])
        payload = raw.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "token_count":
            info = payload.get("info")
            usage = info.get("total_token_usage") if isinstance(info, dict) else None
            usage = usage if isinstance(usage, dict) else payload.get("usage", info)
            token_count = _tokens(usage)
            if token_count and (latest is None or stamp >= latest[0]):
                latest = (stamp, token_count)
        text = _text(payload)
        if _is_limit_message(text):
            reset = parse_reset_time(text, stamp)
            if reset is not None and (since is None or stamp.date() >= since):
                limits.append(LimitObservation("codex", stamp, reset))
    record = None
    if latest is not None and (since is None or latest[0].date() >= since):
        record = InteractiveRecord("codex", session_id, latest[0], latest[1])
    return record, limits


def _claude_file(
    path: Path, since: date | None
) -> tuple[InteractiveRecord | None, list[LimitObservation]]:
    fallback = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    session_id = path.stem
    total = 0
    latest: datetime | None = None
    seen_usage: set[tuple[str, str]] = set()
    limits: list[LimitObservation] = []
    for raw in _read_json_lines(path):
        stamp = _timestamp(raw.get("timestamp"), fallback)
        session_id = _session_id(raw, session_id)
        message = raw.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            usage = message.get("usage")
            amount = _tokens(usage)
            usage_key = (session_id, stamp.isoformat(timespec="seconds"))
            if amount and usage_key not in seen_usage and (since is None or stamp.date() >= since):
                seen_usage.add(usage_key)
                total += amount
                latest = max(latest, stamp) if latest else stamp
        text = _text(message if message is not None else raw)
        if _is_limit_message(text):
            reset = parse_reset_time(text, stamp)
            if reset is not None and (since is None or stamp.date() >= since):
                limits.append(LimitObservation("claude", stamp, reset))
    record = None
    if total and latest is not None and (since is None or latest.date() >= since):
        record = InteractiveRecord("claude", session_id, latest, total)
    return record, limits


def discover_interactive(
    *,
    since: date | None = None,
    codex_root: Path | None = None,
    claude_root: Path | None = None,
) -> tuple[list[InteractiveRecord], list[LimitObservation], dict[str, int]]:
    """Read the two local transcript formats without writing to either source."""
    codex_root = codex_root or Path.home() / ".codex" / "sessions"
    claude_root = claude_root or Path.home() / ".claude" / "projects"
    records: dict[tuple[str, str], InteractiveRecord] = {}
    limits: list[LimitObservation] = []
    files = {"codex": 0, "claude": 0}
    for path in sorted(codex_root.rglob("rollout-*.jsonl")) if codex_root.exists() else []:
        files["codex"] += 1
        record, found = _codex_file(path, since)
        if record:
            key = (record.runner, record.session_id)
            previous = records.get(key)
            if previous is None or record.tokens >= previous.tokens:
                records[key] = record
        limits.extend(found)
    for path in sorted(claude_root.glob("*/*.jsonl")) if claude_root.exists() else []:
        files["claude"] += 1
        record, found = _claude_file(path, since)
        if record:
            key = (record.runner, record.session_id)
            previous = records.get(key)
            if previous is None:
                records[key] = record
            else:
                records[key] = InteractiveRecord(
                    "claude",
                    record.session_id,
                    max(previous.timestamp, record.timestamp),
                    previous.tokens + record.tokens,
                )
        limits.extend(found)
    return (
        sorted(records.values(), key=lambda item: (item.runner, item.session_id)),
        sorted(limits, key=lambda item: item.timestamp),
        files,
    )


def import_interactive(
    settings: Settings,
    *,
    since: date | None = None,
    apply: bool = False,
    now: datetime | None = None,
    codex_root: Path | None = None,
    claude_root: Path | None = None,
) -> dict[str, Any]:
    """Import local interactive usage; with ``apply=False`` this is read-only."""
    current = _now(now)
    records, limits, files = discover_interactive(
        since=since, codex_root=codex_root, claude_root=claude_root
    )
    ledger = BudgetLedger(settings.state_dir(), settings)
    rows: list[dict[str, Any]] = []
    added: dict[str, int] = {}
    for record in records:
        amount = ledger.record_interactive(
            record.runner,
            session_id=record.session_id,
            timestamp=record.timestamp,
            tokens=record.tokens,
            apply=apply,
        )
        rows.append(
            {
                "runner": record.runner,
                "session_id": record.session_id,
                "timestamp": record.timestamp.isoformat(timespec="seconds"),
                "tokens": record.tokens,
                "add_tokens": amount,
                "source": record.source,
            }
        )
        added[record.runner] = added.get(record.runner, 0) + amount

    learned: list[dict[str, Any]] = []
    for runner in ("claude", "codex"):
        observation = next((item for item in limits if item.runner == runner), None)
        config = settings.budget.windows.get(runner)
        if observation is None or config is None:
            continue
        started = observation.resets - timedelta(hours=config.hours)
        used = sum(
            record.tokens
            for record in records
            if record.runner == runner and started <= record.timestamp <= observation.resets
        )
        if used <= 0:
            continue
        ledger.learn_window(
            runner,
            started=started,
            resets=observation.resets,
            tokens=used,
            apply=apply,
        )
        learned.append(
            {
                "runner": runner,
                "started": started.isoformat(timespec="seconds"),
                "resets": observation.resets.isoformat(timespec="seconds"),
                "tokens": used,
                "cap": used,
            }
        )
    return {
        "source": "interactive",
        "dry_run": not apply,
        "since": since.isoformat() if since else None,
        "files": files,
        "records": rows,
        "added": added,
        "windows": learned,
        "generated": current.isoformat(timespec="seconds"),
    }


def _percentage(
    runs: float,
    cost: float,
    equivalent: float,
    run_cap: int | None,
    cost_cap: float | None,
    equivalent_cap: float | None,
) -> float | None:
    values: list[float] = []
    if run_cap is not None:
        values.append(100.0 if run_cap <= 0 else 100.0 * runs / run_cap)
    if cost_cap is not None:
        values.append(100.0 if cost_cap <= 0 else 100.0 * cost / cost_cap)
    if equivalent_cap is not None:
        values.append(100.0 if equivalent_cap <= 0 else 100.0 * equivalent / equivalent_cap)
    return round(min(100.0, max(values)), 1) if values else None


def _next_midnight(current: datetime) -> datetime:
    return datetime.combine(
        current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo or UTC
    )


def _active_entries(
    settings: Settings,
    tier: Tier,
    controls: TierState,
    backoff: Backoff,
    available: Callable[[str], bool],
    current: datetime,
) -> list[TierEntry]:
    entries: list[TierEntry] = []
    for entry in settings.tiers.get(tier.value, []):
        if controls.control(entry.runner_name, entry.model, current) is not None:
            continue
        if backoff.is_blocked(entry.runner_name, current, model=entry.model) or not available(
            entry.runner_name
        ):
            continue
        entries.append(entry)
    return entries


@dataclass(frozen=True)
class BudgetTrigger:
    source: str
    pct: float
    until: datetime
    ceiling: str
    used: float
    cap: float


@dataclass
class BudgetPatrol:
    name: str = "budget"
    availability: Callable[[str], bool] | None = None
    credits_fetcher: Callable[[str], float | dict[str, Any] | bytes | None] | None = None
    models_fetcher: Callable[[], object] | None = None

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Any = None
    ) -> PatrolReport:
        del beads
        current = _now()
        ledger = BudgetLedger(settings.state_dir(), settings)
        controls = TierState(settings.state_dir())
        backoff = Backoff(settings.state_dir())
        available = self.availability or self._default_available(settings)
        report = PatrolReport(self.name, today, dry_run)

        try:
            report.data["openrouter_models"] = refresh_openrouter_models(
                settings,
                current=current,
                fetcher=self.models_fetcher,
                apply=not dry_run,
            )
        except Exception:  # noqa: BLE001 - catalogue failure must not stop budget controls
            report.warnings.append("OpenRouter models refresh failed")

        try:
            imported = import_interactive(
                settings,
                since=today,
                apply=not dry_run,
                now=current,
            )
            report.data["import"] = dict(imported.get("added") or {})
        except Exception:  # noqa: BLE001 - local transcript drift must not stop the patrol
            report.data["import"] = {}
            report.warnings.append("interactive usage import failed")

        remaining: float | None = None
        checked = current.isoformat(timespec="seconds")
        api_key = settings.env.get("OPENROUTER_API_KEY")
        if not api_key:
            report.warnings.append("OPENROUTER_API_KEY missing; skipped OpenRouter credits")
        else:
            fetch = self.credits_fetcher or fetch_openrouter_credits
            try:
                raw = fetch(api_key)
                remaining = _payload_remaining(raw)
                if remaining is None:
                    report.warnings.append("OpenRouter credits response had no remaining balance")
                else:
                    ledger.save_credits(remaining, checked=current, apply=not dry_run)
            except Exception:  # noqa: BLE001 - a credits outage must not stop local checks
                report.warnings.append("OpenRouter credits check failed")

        windows = ledger.window_info(current)
        credit_payload = {
            "remaining_usd": remaining,
            "checked": checked if remaining is not None else None,
        }
        if remaining is None:
            stored = ledger.credits().get("openrouter")
            if isinstance(stored, dict):
                credit_payload = {
                    "remaining_usd": stored.get("remaining_usd"),
                    "checked": stored.get("checked"),
                }

        effective_remaining = _number(credit_payload.get("remaining_usd"))
        planned_swaps: list[dict[str, str | None]] = []
        planned_downgrades: list[dict[str, str | None]] = []
        for swap in controls.budget_swaps(include_expired=True):
            tier = Tier(str(swap["tier"]))
            if self._recovered(
                settings,
                ledger,
                tier,
                windows,
                effective_remaining,
                current,
                str(swap.get("until") or ""),
            ):
                controls.clear_budget_preference(tier.value, apply=not dry_run)
                report.actions.append({"op": "clear", "kind": "budget", "tier": tier.value})
        for tier_name, downgrade in controls.downgrades(include_expired=True).items():
            tier = Tier(tier_name)
            if self._recovered(
                settings,
                ledger,
                tier,
                windows,
                effective_remaining,
                current,
                str(downgrade.get("until") or ""),
            ):
                controls.undowngrade(tier.value, apply=not dry_run)
                report.actions.append({"op": "undowngrade", "kind": "budget", "tier": tier.value})

        for tier in (Tier.plan, Tier.implement, Tier.bulk, Tier.local):
            if any(
                swap["tier"] == tier.value for swap in controls.budget_swaps(now=current)
            ) or tier.value in controls.downgrades(now=current):
                continue
            entries = _active_entries(settings, tier, controls, backoff, available, current)
            if not entries:
                continue
            trigger = self._trigger(
                settings, ledger, tier, entries, windows, effective_remaining, current
            )
            if trigger is None:
                continue
            source, target = self._swap_targets(settings, entries, trigger.source)
            reset_text = trigger.until.isoformat(timespec="seconds")
            reason = f"soft cap {trigger.pct:g}% on {trigger.source} until {reset_text}"
            action: dict[str, Any]
            if source is not None and target is not None:
                changed = controls.set_budget_preference(
                    tier.value,
                    source=source,
                    target=target,
                    until=trigger.until,
                    reason=reason,
                    apply=not dry_run,
                )
                action = {
                    "op": "prefer",
                    "kind": "budget",
                    "tier": tier.value,
                    "from": source,
                    "to": target,
                    "until": reset_text,
                    "reason": reason,
                }
                planned_swaps.append(
                    {key: action.get(key) for key in ("tier", "from", "to", "until", "reason")}
                )
            else:
                lower = self._lower_tier(tier)
                if lower is None:
                    continue
                changed = controls.downgrade(
                    tier.value,
                    lower.value,
                    until=trigger.until,
                    reason=reason,
                    apply=not dry_run,
                )
                action = {
                    "op": "downgrade",
                    "kind": "budget",
                    "tier": tier.value,
                    "to": lower.value,
                    "until": reset_text,
                    "reason": reason,
                }
                planned_downgrades.append(
                    {key: action.get(key) for key in ("tier", "to", "until", "reason")}
                )
            if changed:
                report.actions.append(action)
                event = attention_event(
                    self.name,
                    reason,
                    body=(
                        f"Ceiling {trigger.ceiling}: used {trigger.used:g}, "
                        f"cap {trigger.cap:g} ({trigger.pct:g}%). Applied "
                        f"{action['op']} {tier.value} to {action['to']} until {reset_text}."
                    ),
                    xid=f"budget:{tier.value}:{trigger.source}:{reset_text}",
                    data={
                        "kind": "budget",
                        "tier": tier.value,
                        "runner": trigger.source.split(":", 1)[0],
                        **{key: value for key, value in action.items() if key != "kind"},
                        "reason": reason,
                    },
                )
                event["severity"] = "high"
                report.events.append(event)

        swaps = controls.budget_swaps(now=current)
        downgrade_map = controls.downgrades(now=current)
        downgrades = [{"tier": tier, **value} for tier, value in downgrade_map.items()]
        if dry_run:
            swaps.extend(planned_swaps)
            downgrades.extend(planned_downgrades)
        controls_text = self._controls_text(swaps, downgrades)
        for ceiling in ledger.ceilings(current):
            pct = float(ceiling["pct"])
            severity = "high" if pct >= 100 else "warn" if pct >= 70 else None
            if severity is None:
                continue
            alert_key = f"{today.isoformat()}:ceiling:{ceiling['name']}:{severity}"
            if not ledger.claim_alert(alert_key, apply=not dry_run):
                continue
            title = (
                f"{ceiling['name']} at {ceiling['used']} of {ceiling['cap']} "
                f"{ceiling['unit']} ({pct:g}%)"
            )
            event = attention_event(
                self.name,
                title,
                body=f"Ceiling {title}. Control applied: {controls_text}.",
                xid=alert_key,
                data={"kind": "budget-alert", "ceiling": ceiling, "controls": controls_text},
            )
            event["severity"] = severity
            report.events.append(event)

        floor = float(settings.budget.openrouter_credits_floor_usd)
        if effective_remaining is not None and effective_remaining < 2 * floor:
            alert_key = f"{today.isoformat()}:ceiling:openrouter credits:high"
            if ledger.claim_alert(alert_key, apply=not dry_run):
                title = (
                    f"OpenRouter credits ${effective_remaining:.4f} below "
                    f"${2 * floor:.4f} safety floor"
                )
                event = attention_event(
                    self.name,
                    title,
                    body=f"Ceiling {title}. Control applied: {controls_text}.",
                    xid=alert_key,
                    data={
                        "kind": "budget-alert",
                        "ceiling": "openrouter credits",
                        "remaining_usd": effective_remaining,
                        "floor_usd": floor,
                        "controls": controls_text,
                    },
                )
                event["severity"] = "high"
                report.events.append(event)

        if today.weekday() == 0:
            alert_key = f"{today.isoformat()}:weekly-total"
            if ledger.claim_alert(alert_key, apply=not dry_run):
                week = ledger.spend_window(7, current)
                title = (
                    f"Weekly total billed ${float(week['cost_usd']):.4f}, "
                    f"equivalent ${float(week['equivalent_usd']):.4f}"
                )
                event = attention_event(
                    self.name,
                    title,
                    body=f"Ceiling weekly total: {title}. Control applied: {controls_text}.",
                    xid=alert_key,
                    data={"kind": "budget-weekly", **week, "controls": controls_text},
                )
                event["severity"] = "info"
                report.events.append(event)

        report.data["windows"] = windows
        report.data["credits"] = {"openrouter": credit_payload}
        report.data["swaps"] = swaps
        report.data["downgrades"] = downgrades
        report.summary = f"{len(swaps)} budget swap(s), {len(downgrades)} downgrade(s)"
        return report

    @staticmethod
    def _default_available(settings: Settings) -> Callable[[str], bool]:
        from cube.router.policy import default_availability

        return default_availability(settings)

    @staticmethod
    def _trigger(
        settings: Settings,
        ledger: BudgetLedger,
        tier: Tier,
        entries: list[TierEntry],
        windows: dict[str, dict[str, Any]],
        remaining: float | None,
        current: datetime,
    ) -> BudgetTrigger | None:
        raw = ledger.day(current).get(tier.value, {})
        values = (
            (
                "runs",
                float(raw.get("runs", 0)),
                ledger.caps().get(tier.value),
            ),
            (
                "billed",
                float(raw.get("cost_usd", 0)),
                ledger.cost_caps().get(tier.value),
            ),
            (
                "equivalent",
                float(raw.get("equivalent_usd", 0)),
                ledger.equivalent_caps().get(tier.value),
            ),
        )
        pressures = [
            (100.0 * used / float(cap), name, used, float(cap))
            for name, used, cap in values
            if cap is not None and cap > 0
        ]
        pressure = max(pressures, default=None)
        soft = float(settings.budget.soft_cap_pct)
        if pressure is not None and pressure[0] >= soft:
            pct = min(100.0, pressure[0])
            preference = TierState(settings.state_dir()).preference(tier.value)
            source = preference or entry_target(entries[0].runner_name, entries[0].model)
            return BudgetTrigger(
                source,
                round(pct, 1),
                _next_midnight(current),
                f"{tier.value} {pressure[1]}",
                pressure[2],
                pressure[3],
            )
        for entry in entries:
            window = windows.get(entry.runner_name) or {}
            window_pct = window.get("pct")
            resets = window.get("resets")
            if isinstance(window_pct, int | float) and float(window_pct) >= soft and resets:
                reset = _timestamp(resets, current)
                if reset > current:
                    return BudgetTrigger(
                        entry_target(entry.runner_name, entry.model),
                        float(window_pct),
                        reset,
                        f"{entry.runner_name} subscription window",
                        float(window.get("tokens", 0)),
                        float(window.get("cap", 0)),
                    )
            if (
                uses_openrouter(entry.runner_name)
                and not is_free(settings, entry.runner_name, entry.model)
                and remaining is not None
            ):
                if remaining < 2 * float(settings.budget.openrouter_credits_floor_usd):
                    return BudgetTrigger(
                        entry_target(entry.runner_name, entry.model),
                        soft,
                        _next_midnight(current),
                        "openrouter credits",
                        remaining,
                        2 * float(settings.budget.openrouter_credits_floor_usd),
                    )
        return None

    @staticmethod
    def _swap_targets(
        settings: Settings, entries: list[TierEntry], source: str
    ) -> tuple[str | None, str | None]:
        source_entry = next(
            (
                entry
                for entry in entries
                if entry_target(entry.runner_name, entry.model) == source
                or (":" not in source and entry.runner_name == source)
            ),
            entries[0] if entries else None,
        )
        if source_entry is None:
            return None, None
        source_target = entry_target(source_entry.runner_name, source_entry.model)
        source_price = rank_usd(settings, source_entry.runner_name, source_entry.model)
        candidates = sorted(
            (entry for entry in entries if entry is not source_entry),
            key=lambda entry: rank_usd(settings, entry.runner_name, entry.model),
        )
        if not candidates:
            return source_target, None
        cheapest = candidates[0]
        if rank_usd(settings, cheapest.runner_name, cheapest.model) >= source_price:
            return source_target, None
        return source_target, entry_target(cheapest.runner_name, cheapest.model)

    @staticmethod
    def _lower_tier(tier: Tier) -> Tier | None:
        return {
            Tier.plan: Tier.implement,
            Tier.implement: Tier.bulk,
            Tier.bulk: Tier.local,
        }.get(tier)

    @staticmethod
    def _recovered(
        settings: Settings,
        ledger: BudgetLedger,
        tier: Tier,
        windows: dict[str, dict[str, Any]],
        remaining: float | None,
        current: datetime,
        until: str,
    ) -> bool:
        if until and _timestamp(until, current) <= current:
            return True
        raw = ledger.day(current).get(tier.value, {})
        pct = _percentage(
            float(raw.get("runs", 0)),
            float(raw.get("cost_usd", 0)),
            float(raw.get("equivalent_usd", 0)),
            ledger.caps().get(tier.value),
            ledger.cost_caps().get(tier.value),
            ledger.equivalent_caps().get(tier.value),
        )
        pressures = [pct] if pct is not None else []
        for entry in settings.tiers.get(tier.value, []):
            window_pct = (windows.get(entry.runner_name) or {}).get("pct")
            if isinstance(window_pct, int | float):
                pressures.append(float(window_pct))
            if (
                uses_openrouter(entry.runner_name)
                and remaining is not None
                and remaining <= 2 * float(settings.budget.openrouter_credits_floor_usd)
            ):
                pressures.append(float(settings.budget.soft_cap_pct))
        recovery = max(0.0, float(settings.budget.soft_cap_pct) - 15.0)
        return not pressures or max(pressures) < recovery

    @staticmethod
    def _controls_text(swaps: list[dict[str, str | None]], downgrades: list[dict[str, Any]]) -> str:
        values = [f"{item['tier']} {item['from']} to {item['to']}" for item in swaps] + [
            f"{item['tier']} to {item['to']}" for item in downgrades
        ]
        return "; ".join(values) if values else "none"


register(BudgetPatrol, "budget")
