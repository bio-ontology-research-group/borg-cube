"""``cube budget``: daily token, run, cost, and runner availability telemetry."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.model import Tier
from cube.patrols.budget import import_interactive
from cube.router import Backoff, BudgetLedger, TierState

REPORT_TIERS = (Tier.plan, Tier.implement, Tier.bulk, Tier.local)
REPORT_RUNNERS = ("claude", "codex", "openrouter", "local", "hermes")


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("days must be at least 1")
    return parsed


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _usage() -> dict[str, int | float]:
    return {"runs": 0, "tokens": 0, "cost_usd": 0.0, "equivalent_usd": 0.0}


def _add(total: dict[str, int | float], raw: object) -> None:
    if not isinstance(raw, dict):
        return
    total["runs"] = int(total["runs"]) + int(raw.get("runs", 0))
    total["tokens"] = int(total["tokens"]) + int(raw.get("tokens", 0))
    total["cost_usd"] = float(total["cost_usd"]) + float(raw.get("cost_usd", 0.0))
    total["equivalent_usd"] = float(total["equivalent_usd"]) + float(raw.get("equivalent_usd", 0.0))


def _percentage(
    runs: int,
    cost_usd: float,
    equivalent_usd: float,
    cap_runs: int | None,
    cap_cost_usd: float | None,
    cap_equivalent_usd: float | None,
) -> float | None:
    values: list[float] = []
    if cap_runs is not None:
        values.append(100.0 if cap_runs <= 0 else 100.0 * runs / cap_runs)
    if cap_cost_usd is not None:
        values.append(100.0 if cap_cost_usd <= 0 else 100.0 * cost_usd / cap_cost_usd)
    if cap_equivalent_usd is not None:
        values.append(
            100.0 if cap_equivalent_usd <= 0 else 100.0 * equivalent_usd / cap_equivalent_usd
        )
    if not values:
        return None
    return min(100.0, round(max(values), 1))


def budget_data(
    settings: Settings, *, days: int = 1, now: datetime | None = None
) -> dict[str, Any]:
    current = _now(now)
    ledger = BudgetLedger(settings.state_dir(), settings)
    raw_window = ledger.window(days, current)
    tier_totals = {tier.value: _usage() for tier in REPORT_TIERS}
    runner_totals = {runner: _usage() for runner in REPORT_RUNNERS}

    configured = {
        entry.runner_name
        for entries in settings.tiers.values()
        for entry in entries
        if entry.runner_name != "stub"
    }
    recorded = {
        str(runner)
        for raw_day in raw_window.values()
        for runner in ((raw_day.get("runners") or {}) if isinstance(raw_day, dict) else {})
        if runner != "stub"
    }
    for runner in sorted(configured | recorded):
        runner_totals.setdefault(runner, _usage())

    for raw_day in raw_window.values():
        for tier in REPORT_TIERS:
            _add(tier_totals[tier.value], raw_day.get(tier.value))
        raw_runners = raw_day.get("runners") or {}
        if isinstance(raw_runners, dict):
            for runner, raw in raw_runners.items():
                if runner != "stub":
                    _add(runner_totals.setdefault(str(runner), _usage()), raw)

    caps = ledger.caps()
    cost_caps = ledger.cost_caps()
    equivalent_caps = ledger.equivalent_caps()
    tiers: dict[str, dict[str, int | float | None]] = {}
    for tier in REPORT_TIERS:
        total = tier_totals[tier.value]
        daily_cap = caps.get(tier.value)
        cap_runs = daily_cap * days if daily_cap is not None else None
        daily_cost_cap = cost_caps.get(tier.value)
        cap_cost = daily_cost_cap * days if daily_cost_cap is not None else None
        daily_equivalent_cap = equivalent_caps.get(tier.value)
        cap_equivalent = daily_equivalent_cap * days if daily_equivalent_cap is not None else None
        runs = int(total["runs"])
        cost = float(total["cost_usd"])
        equivalent = float(total["equivalent_usd"])
        tiers[tier.value] = {
            "runs": runs,
            "tokens": int(total["tokens"]),
            "cost_usd": cost,
            "equivalent_usd": equivalent,
            "cap_runs": cap_runs,
            "cap_cost_usd": cap_cost,
            "cap_equivalent_usd": cap_equivalent,
            "pct": _percentage(runs, cost, equivalent, cap_runs, cap_cost, cap_equivalent),
        }

    controls = TierState(settings.state_dir())
    backoff = Backoff(settings.state_dir())
    backoff_state = backoff.state()
    runners: dict[str, dict[str, int | float | str | None]] = {}
    for runner, total in runner_totals.items():
        control = controls.control(runner, now=current)
        if control is not None:
            state, until, reason = control.state, control.until, control.reason
        else:
            blocked_until = backoff.blocked_until(runner, current)
            state = "backoff" if blocked_until else "ok"
            until = blocked_until.isoformat(timespec="seconds") if blocked_until else None
            raw_backoff = backoff_state.get(runner) or {}
            reason = (
                str(raw_backoff.get("last_error"))
                if blocked_until and raw_backoff.get("last_error")
                else None
            )
        runners[runner] = {
            "runs": int(total["runs"]),
            "tokens": int(total["tokens"]),
            "cost_usd": float(total["cost_usd"]),
            "equivalent_usd": float(total["equivalent_usd"]),
            "state": state,
            "until": until,
            "reason": reason,
        }

    since_day = current.date() - timedelta(days=days - 1)
    since = datetime.combine(since_day, time.min, tzinfo=current.tzinfo or UTC)
    window_until = datetime.combine(
        current.date() + timedelta(days=1), time.min, tzinfo=current.tzinfo or UTC
    )
    stored_credits = ledger.credits().get("openrouter")
    credits = (
        {
            "remaining_usd": stored_credits.get("remaining_usd"),
            "checked": stored_credits.get("checked"),
        }
        if isinstance(stored_credits, dict)
        else {"remaining_usd": None, "checked": None}
    )
    attribution_today = ledger.attribution(current)
    attribution_week = ledger.attribution(current, days=7)
    projects: dict[str, dict[str, Any]] = {}
    project_names = (
        set(attribution_today["projects"])
        | set(attribution_week["projects"])
        | set(settings.projects)
    )
    for slug in sorted(project_names):
        profile = settings.projects.get(slug)
        projects[slug] = {
            "today": attribution_today["projects"].get(slug, _usage()),
            "week": attribution_week["projects"].get(slug, _usage()),
            "cap_usd_per_day": profile.budget_usd_per_day if profile else None,
        }
    epics: dict[str, dict[str, Any]] = {}
    epic_names = set(attribution_today["goals"]) | set(attribution_week["goals"])
    for goal in sorted(epic_names):
        epics[goal] = {
            "today": attribution_today["goals"].get(goal, _usage()),
            "week": attribution_week["goals"].get(goal, _usage()),
            "total": ledger.attribution_total("goals", goal),
            "cap_usd": settings.pipeline.budget_usd_per_epic,
        }
    swaps = controls.budget_swaps(now=current)
    downgrades = [
        {"tier": tier, **value} for tier, value in controls.downgrades(now=current).items()
    ]
    return {
        "generated": current.isoformat(timespec="seconds"),
        "day": current.date().isoformat(),
        "days": days,
        "tiers": tiers,
        "runners": runners,
        "windows": ledger.window_info(current),
        "credits": {"openrouter": credits},
        "swaps": swaps,
        "attribution": {"projects": projects, "epics": epics},
        "forecast": {"hours": 3, "tiers": ledger.forecast(current)},
        "controls": {"swaps": swaps, "downgrades": downgrades},
        "ceilings": ledger.ceilings(current),
        "window": {
            "since": since.isoformat(timespec="seconds"),
            "until": window_until.isoformat(timespec="seconds"),
        },
    }


def budget_status(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    data = budget_data(settings, now=now)
    runners = data["runners"]
    return {
        **{tier.value: data["tiers"][tier.value]["pct"] for tier in REPORT_TIERS},
        "exhausted": [
            runner for runner, values in runners.items() if values["state"] == "exhausted"
        ],
        "swaps": data["swaps"],
    }


def _table(data: dict[str, Any]) -> str:
    lines = ["TIER        RUNS       CAP      TOKENS   BILLED EQUIVALENT    PCT"]
    for tier, values in data["tiers"].items():
        cap = "-" if values["cap_runs"] is None else str(values["cap_runs"])
        pct = "-" if values["pct"] is None else f"{values['pct']:.1f}%"
        lines.append(
            f"{tier:10} {values['runs']:5} {cap:>9} {values['tokens']:11} "
            f"${values['cost_usd']:7.4f} ${values['equivalent_usd']:9.4f} {pct:>7}"
        )
    lines += ["", "RUNNER          RUNS      TOKENS   BILLED EQUIVALENT STATE"]
    for runner, values in data["runners"].items():
        until = f" until {values['until']}" if values["until"] else ""
        lines.append(
            f"{runner:15} {values['runs']:5} {values['tokens']:11} "
            f"${values['cost_usd']:7.4f} ${values['equivalent_usd']:9.4f} "
            f"{values['state']}{until}"
        )
    if data.get("swaps"):
        lines += ["", "SWAPS"]
        lines.extend(
            f"{swap['tier']}: {swap['from']} -> {swap['to']} until {swap['until']} "
            f"({swap['reason']})"
            for swap in data["swaps"]
        )
    if data["controls"]["downgrades"]:
        lines += ["", "DOWNGRADES"]
        lines.extend(
            f"{item['tier']} -> {item['to']} until {item['until']} ({item['reason']})"
            for item in data["controls"]["downgrades"]
        )
    lines += ["", "ATTRIBUTION", "TARGET                 TODAY EQ     WEEK EQ"]
    lines.extend(
        f"project:{slug:20} ${row['today']['equivalent_usd']:9.4f} "
        f"${row['week']['equivalent_usd']:9.4f}"
        for slug, row in data["attribution"]["projects"].items()
    )
    lines.extend(
        f"epic:{goal:23} ${row['today']['equivalent_usd']:9.4f} "
        f"${row['week']['equivalent_usd']:9.4f}"
        for goal, row in data["attribution"]["epics"].items()
    )
    lines += ["", "CEILINGS", "NAME                         USED        CAP     PCT"]
    lines.extend(
        f"{item['name']:28} {item['used']:10.4f} {item['cap']:10.4f} {item['pct']:6.1f}%"
        for item in data["ceilings"]
    )
    lines += ["", "FORECAST", "TIER       USD/HOUR  DAY END"]
    lines.extend(
        f"{tier:10} ${row['burn_usd_per_hour']:8.4f} ${row['projected_day_end_usd']:8.4f}"
        for tier, row in data["forecast"]["tiers"].items()
    )
    return "\n".join(lines)


def cmd_budget(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    data = budget_data(settings, days=7 if args.week else args.days)
    helpers.emit(args, data, _table(data))
    return 0


def cmd_budget_import(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    result = import_interactive(
        settings,
        since=args.since,
        apply=not args.dry_run,
    )
    added = ", ".join(f"{runner}={tokens}" for runner, tokens in sorted(result["added"].items()))
    text = f"{'DRY-RUN would add' if args.dry_run else 'added'} interactive usage" + (
        f": {added}" if added else ": nothing"
    )
    helpers.emit(args, result, text)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    # The patrol package initializer is intentionally not part of this feature's
    # edit surface. Importing here still registers `cube patrol budget` during
    # normal CLI module discovery.
    from cube.patrols import budget as _budget_patrol  # noqa: F401

    sp = sub.add_parser("budget", help="token, run, cost, and runner availability telemetry")
    period = sp.add_mutually_exclusive_group()
    period.add_argument("--days", type=_positive, default=1, help="aggregate the last N days")
    period.add_argument("--week", action="store_true", help="aggregate the last seven days")
    helpers.add_json(sp)
    commands = sp.add_subparsers(dest="budget_cmd")
    imp = commands.add_parser("import", help="import local Claude and Codex interactive usage")
    imp.add_argument("--since", type=date.fromisoformat)
    helpers.add_json(imp)
    helpers.add_dry(imp)
    imp.set_defaults(fn=lambda args, settings: cmd_budget_import(args, settings, helpers))
    sp.set_defaults(fn=lambda args, settings: cmd_budget(args, settings, helpers))
