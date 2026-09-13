"""``cube tier``: inspect and manage runner controls and tier preferences."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.model import Tier
from cube.router import Backoff, TierState, split_target
from cube.router.controls import entry_target
from cube.router.prices import is_free

SHOW_TIERS = (Tier.plan, Tier.implement, Tier.bulk, Tier.local)
_DURATION = re.compile(r"(\d+(?:\.\d+)?)([smhd])", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(UTC)


def _duration(value: str) -> timedelta:
    match = _DURATION.fullmatch(value.strip())
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 30m, 5h, or 2d")
    amount = float(match.group(1))
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]
    if seconds <= 0:
        raise argparse.ArgumentTypeError("duration must be positive")
    return timedelta(seconds=seconds)


def _until(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("until must be an ISO 8601 timestamp") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _target(value: str) -> str:
    try:
        split_target(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def tier_data(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    controls = TierState(settings.state_dir())
    backoff = Backoff(settings.state_dir())
    backoff_state = backoff.state()
    tiers: dict[str, list[dict[str, Any]]] = {}
    for tier in SHOW_TIERS:
        rows: list[dict[str, Any]] = []
        for entry in settings.tiers.get(tier.value, []):
            control = controls.control(entry.runner_name, entry.model, current)
            if control is not None:
                state, until, reason = control.state, control.until, control.reason
            else:
                blocked_until = backoff.blocked_until(entry.runner_name, current, model=entry.model)
                if blocked_until:
                    state = "backoff"
                    until = blocked_until.isoformat(timespec="seconds")
                    raw = (
                        backoff_state.get(entry_target(entry.runner_name, entry.model))
                        or backoff_state.get(entry.runner_name)
                        or {}
                    )
                    reason = str(raw.get("last_error")) if raw.get("last_error") else None
                elif controls.preferred(tier.value, entry.runner_name, entry.model):
                    state = "preferred"
                    until = None
                    reason = controls.preference_reason(tier.value)
                else:
                    state, until, reason = "ok", None, None
            rows.append(
                {
                    "runner": entry.runner_name,
                    "model": entry.model,
                    "profile": entry.profile,
                    "state": state,
                    "until": until,
                    "reason": reason,
                    "active": False,
                }
            )
        usable = [index for index, row in enumerate(rows) if row["state"] in {"ok", "preferred"}]
        preferred = [index for index in usable if rows[index]["state"] == "preferred"]
        active = (preferred or usable)[:1]
        if active:
            rows[active[0]]["active"] = True
        tiers[tier.value] = rows
    return {"generated": current.isoformat(timespec="seconds"), "tiers": tiers}


def tier_status_data(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or _now()
    controls = TierState(settings.state_dir())
    return {
        "generated": current.isoformat(timespec="seconds"),
        "swaps": controls.budget_swaps(now=current),
        "downgrades": [
            {"tier": tier, **value} for tier, value in controls.downgrades(now=current).items()
        ],
    }


def _table(data: dict[str, Any]) -> str:
    lines = ["TIER       RUNNER          MODEL                    STATE       UNTIL"]
    for tier, entries in data["tiers"].items():
        for entry in entries:
            lines.append(
                f"{tier:10} {entry['runner']:15} {(entry['model'] or '-'):24} "
                f"{entry['state']:11} {entry['until'] or '-'}"
            )
    return "\n".join(lines)


def _action(
    args: argparse.Namespace,
    settings: Settings,
    helpers: Helpers,
    *,
    action: str,
    target: str | None = None,
    until: str | None = None,
    reason: str | None = None,
    changed: bool = True,
) -> int:
    data = {
        "action": action,
        "target": target,
        "until": until,
        "reason": reason,
        "changed": changed,
        "dry_run": args.dry_run,
    }
    prefix = "DRY-RUN would" if args.dry_run else "did"
    helpers.emit(args, data, f"{prefix} {action}{' ' + target if target else ''}")
    return 0


def _valid_preference(settings: Settings, tier: str, target: str) -> bool:
    runner, model = split_target(target)
    return any(
        entry.runner_name == runner and (model is None or entry.model == model)
        for entry in settings.tiers.get(tier, [])
    )


def cmd_tier(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    command = args.tier_cmd or "show"
    state = TierState(settings.state_dir())
    if command == "show":
        data = tier_data(settings)
        helpers.emit(args, data, _table(data))
        return 0
    if command == "status":
        data = tier_status_data(settings)
        lines = ["SWAPS"]
        lines.extend(
            f"{item['tier']}: {item['from']} -> {item['to']} until {item['until']}"
            for item in data["swaps"]
        )
        lines.append("DOWNGRADES")
        lines.extend(
            f"{item['tier']}: -> {item['to']} until {item['until']}" for item in data["downgrades"]
        )
        helpers.emit(args, data, "\n".join(lines))
        return 0
    if command == "disable":
        current = _now()
        until_dt = args.until or current + args.duration
        if until_dt <= current:
            print("cube tier disable: --until must be in the future", file=sys.stderr)
            return 2
        control = state.disable(
            args.target,
            until=until_dt,
            reason=args.reason,
            apply=not args.dry_run,
        )
        return _action(
            args,
            settings,
            helpers,
            action="disable",
            target=args.target,
            until=control.until,
            reason=control.reason,
        )
    if command == "enable":
        changed = state.enable(args.target, apply=not args.dry_run)
        return _action(
            args,
            settings,
            helpers,
            action="enable",
            target=args.target,
            changed=changed,
        )
    if command == "prefer":
        if not _valid_preference(settings, args.tier, args.target):
            print(
                f"cube tier prefer: {args.target!r} is not configured for tier {args.tier!r}",
                file=sys.stderr,
            )
            return 2
        state.prefer(args.tier, args.target, apply=not args.dry_run)
        return _action(
            args,
            settings,
            helpers,
            action="prefer",
            target=f"{args.tier}:{args.target}",
        )
    if command == "free-first":
        reason = "robert: free-first"
        if args.off:
            changed = state.clear_preference(args.tier, reason=reason, apply=not args.dry_run)
            return _action(
                args,
                settings,
                helpers,
                action="free-first off",
                target=args.tier,
                reason=reason,
                changed=changed,
            )
        free_entry = next(
            (
                entry
                for entry in settings.tiers.get(args.tier, [])
                if is_free(settings, entry.runner_name, entry.model)
            ),
            None,
        )
        if free_entry is None:
            print(
                f"cube tier free-first: tier {args.tier!r} has no free entry",
                file=sys.stderr,
            )
            return 2
        target = entry_target(free_entry.runner_name, free_entry.model)
        changed = (
            state.preference(args.tier) != target or state.preference_reason(args.tier) != reason
        )
        state.prefer(
            args.tier,
            target,
            reason=reason,
            apply=not args.dry_run,
        )
        return _action(
            args,
            settings,
            helpers,
            action="free-first",
            target=f"{args.tier}:{target}",
            reason=reason,
            changed=changed,
        )
    if command == "downgrade":
        ranks = {"local": 0, "bulk": 1, "implement": 2, "plan": 3}
        if ranks[args.to] >= ranks[args.tier]:
            print("cube tier downgrade: destination must be a lower tier", file=sys.stderr)
            return 2
        current = _now()
        until_dt = args.until or current + args.duration
        if until_dt <= current:
            print("cube tier downgrade: expiry must be in the future", file=sys.stderr)
            return 2
        changed = state.downgrade(
            args.tier,
            args.to,
            until=until_dt,
            reason=args.reason,
            apply=not args.dry_run,
        )
        return _action(
            args,
            settings,
            helpers,
            action="downgrade",
            target=f"{args.tier}:{args.to}",
            until=until_dt.isoformat(timespec="seconds"),
            reason=args.reason,
            changed=changed,
        )
    if command == "undowngrade":
        changed = state.undowngrade(args.tier, apply=not args.dry_run)
        return _action(
            args,
            settings,
            helpers,
            action="undowngrade",
            target=args.tier,
            changed=changed,
        )
    if command == "reset":
        changed = bool(state.data())
        state.reset(apply=not args.dry_run)
        return _action(args, settings, helpers, action="reset", changed=changed)
    return 2


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable output",
    )


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("tier", help="inspect and manage runner availability")
    helpers.add_json(sp)
    commands = sp.add_subparsers(dest="tier_cmd")

    show = commands.add_parser("show", help="show configured tiers and runner state")
    _add_json(show)

    status = commands.add_parser("status", help="show active budget swaps and downgrades")
    _add_json(status)

    disable = commands.add_parser("disable", help="temporarily disable runner[:model]")
    disable.add_argument("target", type=_target)
    expiry = disable.add_mutually_exclusive_group(required=True)
    expiry.add_argument("--until", type=_until)
    expiry.add_argument("--for", dest="duration", type=_duration)
    disable.add_argument("--reason")
    _add_json(disable)
    helpers.add_dry(disable)

    enable = commands.add_parser("enable", help="clear disabled or exhausted state")
    enable.add_argument("target", type=_target)
    _add_json(enable)
    helpers.add_dry(enable)

    prefer = commands.add_parser("prefer", help="prefer runner[:model] within a tier")
    prefer.add_argument("tier", choices=[tier.value for tier in SHOW_TIERS])
    prefer.add_argument("target", type=_target)
    _add_json(prefer)
    helpers.add_dry(prefer)

    free_first = commands.add_parser(
        "free-first", help="prefer the first explicitly free entry within a tier"
    )
    free_first.add_argument("tier", choices=[tier.value for tier in SHOW_TIERS])
    free_first.add_argument("--off", action="store_true", help="restore configured order")
    _add_json(free_first)
    helpers.add_dry(free_first)

    downgrade = commands.add_parser("downgrade", help="temporarily route to a lower tier")
    downgrade.add_argument("tier", choices=[tier.value for tier in SHOW_TIERS])
    downgrade.add_argument("to", choices=[tier.value for tier in SHOW_TIERS])
    downgrade_expiry = downgrade.add_mutually_exclusive_group(required=True)
    downgrade_expiry.add_argument("--until", type=_until)
    downgrade_expiry.add_argument("--for", dest="duration", type=_duration)
    downgrade.add_argument("--reason")
    _add_json(downgrade)
    helpers.add_dry(downgrade)

    undowngrade = commands.add_parser("undowngrade", help="clear a tier downgrade")
    undowngrade.add_argument("tier", choices=[tier.value for tier in SHOW_TIERS])
    _add_json(undowngrade)
    helpers.add_dry(undowngrade)

    reset = commands.add_parser("reset", help="clear all controls and preferences")
    _add_json(reset)
    helpers.add_dry(reset)

    sp.set_defaults(fn=lambda args, settings: cmd_tier(args, settings, helpers))
