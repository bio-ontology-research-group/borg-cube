#!/usr/bin/env python3
"""Build a source-bearing KAUST thesis defense schedule without network access.

The program reads the local rule snapshot in ../assets/defense-timeline.yaml.
Every official rule must carry its source id and verified-on date. Exact
Academic Calendar and Dean dates are optional inputs because this script never
guesses them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml


DEFAULT_RULES = Path(__file__).resolve().parent.parent / "assets" / "defense-timeline.yaml"


class TimelineError(Exception):
    """An input or rule record prevents a reliable schedule."""


def parse_date(value: str, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise TimelineError(f"{name} must be an ISO date (YYYY-MM-DD): {value!r}") from exc


def subtract_months(value: dt.date, months: int) -> dt.date:
    """Subtract whole calendar months, preserving the last valid day."""
    month_index = value.year * 12 + value.month - 1 - months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    last_day = (next_month - dt.timedelta(days=1)).day
    return dt.date(year, month, min(value.day, last_day))


def load_rules(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TimelineError(f"rule snapshot not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TimelineError(f"cannot parse rule snapshot {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("programmes"), dict):
        raise TimelineError(f"rule snapshot {path} lacks a programmes mapping")
    return data


def verified_source(item: dict[str, Any]) -> tuple[str, str, str]:
    source = item.get("source")
    verified_on = item.get("verified_on")
    rule = item.get("rule")
    if not all(isinstance(value, str) and value for value in (source, verified_on, rule)):
        raise TimelineError(f"official rule lacks source, verified_on, or rule: {item.get('id')!r}")
    try:
        dt.date.fromisoformat(verified_on)
    except ValueError as exc:
        raise TimelineError(f"official rule has invalid verified_on {verified_on!r}") from exc
    return source, verified_on, rule


def resolve_programme(rules: dict[str, Any], requested: str) -> tuple[str, dict[str, Any]]:
    for key, programme in rules["programmes"].items():
        if not isinstance(programme, dict):
            continue
        aliases = programme.get("aliases", [])
        if requested.lower() == key or requested.lower() in aliases:
            return key, programme
    choices = sorted({name for p in rules["programmes"].values() for name in p.get("aliases", [])})
    raise TimelineError(f"unknown programme {requested!r}; choose one of {', '.join(choices)}")


def rule_date(defense: dt.date, step: dict[str, Any]) -> dt.date:
    timing = step.get("timing")
    value = step.get("value")
    if not isinstance(value, int):
        raise TimelineError(f"official rule has non-integer timing: {step.get('id')!r}")
    if timing == "days_before":
        return defense - dt.timedelta(days=value)
    if timing == "days_after":
        return defense + dt.timedelta(days=value)
    if timing == "months_before":
        return subtract_months(defense, value)
    raise TimelineError(f"official rule has unknown timing {timing!r}: {step.get('id')!r}")


def make_item(
    item_id: str,
    label: str,
    date: dt.date | None,
    authority: str,
    source: str | None = None,
    verified_on: str | None = None,
    rule: str | None = None,
    status: str = "scheduled",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "date": date.isoformat() if date else None,
        "authority": authority,
        "status": status,
        "source": source,
        "verified_on": verified_on,
        "rule": rule,
    }


def build_plan(
    defense: dt.date,
    programme_name: str,
    committee_size: int,
    rules: dict[str, Any],
    today: dt.date,
    registrar_deadline: dt.date | None = None,
    dean_deadline: dt.date | None = None,
) -> dict[str, Any]:
    key, programme = resolve_programme(rules, programme_name)
    committee = programme.get("committee")
    if not isinstance(committee, dict):
        raise TimelineError(f"programme {key} lacks committee rules")
    committee_source, committee_verified_on, committee_rule = verified_source(committee)
    minimum, maximum = committee.get("minimum"), committee.get("maximum")
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        raise TimelineError(f"programme {key} has invalid committee bounds")
    if not minimum <= committee_size <= maximum:
        raise TimelineError(
            f"committee size {committee_size} violates KAUST rule "
            f"[{committee_source}; verified {committee_verified_on}]: "
            f"{committee_rule} Required size is {minimum} to {maximum}."
        )
    if defense <= today:
        raise TimelineError(f"defense date {defense.isoformat()} must be after today {today.isoformat()}")

    official: list[dict[str, Any]] = []
    dates: dict[str, dt.date] = {}
    for step in programme.get("official_steps", []):
        if not isinstance(step, dict):
            raise TimelineError(f"programme {key} contains an invalid official step")
        source, verified_on, rule = verified_source(step)
        due = rule_date(defense, step)
        item_id = str(step.get("id", ""))
        if not item_id or not isinstance(step.get("label"), str):
            raise TimelineError("official rule lacks id or label")
        dates[item_id] = due
        official.append(make_item(item_id, step["label"], due, "KAUST", source, verified_on, rule))

    petition_due = dates.get("petition")
    committee_due = dates.get("committee-copy")
    if committee_due and today > committee_due:
        step = next(s for s in programme["official_steps"] if s["id"] == "committee-copy")
        source, verified_on, rule = verified_source(step)
        raise TimelineError(
            f"defense date {defense.isoformat()} violates KAUST rule [{source}; verified {verified_on}]: "
            f"{rule} The committee deadline {committee_due.isoformat()} has passed."
        )
    if petition_due and today > petition_due:
        step = next(s for s in programme["official_steps"] if s["id"] == "petition")
        source, verified_on, rule = verified_source(step)
        raise TimelineError(
            f"defense date {defense.isoformat()} violates KAUST rule [{source}; verified {verified_on}]: "
            f"{rule} The minimum petition deadline {petition_due.isoformat()} has passed."
        )
    if registrar_deadline and registrar_deadline > defense:
        raise TimelineError("registrar deadline must not fall after the defense date")
    if dean_deadline and committee_due and dean_deadline > committee_due:
        raise TimelineError("Dean approval deadline must be on or before the committee-delivery deadline")

    official.append(
        make_item(
            "registrar-calendar",
            "Confirm the published Registrar petition and archiving deadlines",
            registrar_deadline,
            "KAUST",
            "kaust-registrar-program-guide",
            "2026-09-02",
            "The Academic Calendar publishes the petition, result, and archiving deadlines.",
            "scheduled" if registrar_deadline else "needs-calendar",
        )
    )
    dean_date = dean_deadline or petition_due
    official.append(
        make_item(
            "dean-approval",
            "Confirm Dean approval of the defense committee",
            dean_date,
            "planning dependency" if dean_deadline is None else "KAUST",
            committee_source,
            committee_verified_on,
            committee_rule,
            "scheduled" if dean_deadline else "needs-dean-date",
        )
    )

    internal: list[dict[str, Any]] = []
    for step in rules.get("internal_steps", []):
        if not isinstance(step, dict) or not isinstance(step.get("days_before"), int):
            raise TimelineError("internal step lacks an integer days_before")
        internal.append(
            make_item(
                str(step.get("id")),
                str(step.get("label")),
                defense - dt.timedelta(days=step["days_before"]),
                "internal target",
                status="scheduled",
            )
        )

    all_items = official + internal
    all_items.sort(key=lambda item: (item["date"] is None, item["date"] or "", item["id"]))
    return {
        "defense": defense.isoformat(),
        "programme": key,
        "committee_size": committee_size,
        "rule_snapshot_version": rules.get("version"),
        "rule_snapshot_verified_on": rules.get("verified_on"),
        "official": official,
        "internal": internal,
        "schedule": all_items,
        "caveat": (
            "Academic Calendar dates and the current KAUST template are not inferred. "
            "Items marked needs-calendar or needs-dean-date require Robert's verified record."
        ),
    }


def render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Defense timeline: {plan['programme']} defense on {plan['defense']}",
        f"Committee size: {plan['committee_size']}; rule snapshot {plan['rule_snapshot_version']} "
        f"verified {plan['rule_snapshot_verified_on']}",
        "",
        "Schedule",
    ]
    for item in plan["schedule"]:
        date = item["date"] or "unresolved"
        lines.append(f"  {date}  {item['status']:16} {item['label']} [{item['authority']}]")
        if item["rule"]:
            lines.append(f"              Rule: {item['rule']} [{item['source']}; verified {item['verified_on']}]")
    lines.extend(["", plan["caveat"]])
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--defense", required=True, help="intended defense date, YYYY-MM-DD")
    p.add_argument("--programme", "--program", dest="programme", required=True, help="phd or ms-thesis")
    p.add_argument("--committee-size", type=int, required=True)
    p.add_argument("--registrar-deadline", help="verified Academic Calendar deadline, YYYY-MM-DD")
    p.add_argument("--dean-deadline", help="verified Dean approval date, YYYY-MM-DD")
    p.add_argument("--today", help="override today's date for a reproducible plan, YYYY-MM-DD")
    p.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="local YAML rule snapshot")
    p.add_argument("--json", action="store_true", help="emit JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        defense = parse_date(args.defense, "defense")
        today = parse_date(args.today, "today") if args.today else dt.date.today()
        registrar_deadline = (
            parse_date(args.registrar_deadline, "registrar deadline") if args.registrar_deadline else None
        )
        dean_deadline = parse_date(args.dean_deadline, "Dean deadline") if args.dean_deadline else None
        plan = build_plan(
            defense,
            args.programme,
            args.committee_size,
            load_rules(args.rules),
            today,
            registrar_deadline,
            dean_deadline,
        )
    except TimelineError as exc:
        print(f"thesis-timeline: error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, sort_keys=True) if args.json else render_text(plan), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
