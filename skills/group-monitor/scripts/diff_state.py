#!/usr/bin/env python3
"""Turn state snapshots into signals: changes since the previous run and threshold crossings.

Inputs are the JSON files written by papers_state.py, repos_state.py and
students_state.py (each carries a ``kind``), plus optional ``services`` and
``teaching`` files in the shapes documented in SKILL.md. Give the current
snapshots with ``--current`` and the previous ones with ``--previous``; the
thresholds come from assets/thresholds.yaml (Robert's numbers).

Every signal has an id, a category (papers, repos, students, services,
teaching), a severity (attention, change, positive, cleared, waiting, note), a
message, the source path it was derived from, and the observation date.
Student signals are privacy local-only; briefing_render.py keeps them out of
the group briefing.

Example:
  diff_state.py --current state/papers.json --current state/repos.json \
      --previous state/prev/papers.json --thresholds assets/thresholds.yaml --out state/signals.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_THRESHOLDS = HERE.parent / "assets" / "thresholds.yaml"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def value(thresholds: dict[str, Any], section: str, key: str, default: Any) -> Any:
    entry = thresholds.get(section, {}).get(key)
    if isinstance(entry, dict):
        return entry.get("value", default)
    return entry if entry is not None else default


def message(thresholds: dict[str, Any], section: str, key: str, default: str) -> str:
    entry = thresholds.get(section, {}).get(key)
    if isinstance(entry, dict) and entry.get("message"):
        return str(entry["message"])
    return default


def signal(
    sid: str,
    category: str,
    severity: str,
    msg: str,
    source: str | None,
    today: dt.date,
    deadline: str | None = None,
    privacy: str = "internal",
) -> dict[str, Any]:
    return {
        "id": sid,
        "category": category,
        "severity": severity,
        "message": msg,
        "source": source,
        "observed": today.isoformat(),
        "deadline": deadline,
        "privacy": privacy,
    }


# --------------------------------------------------------------------------- per kind


def papers_threshold_signals(
    state: dict[str, Any], th: dict[str, Any], today: dt.date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    limits = {
        "SUBMITTED": ("submitted_max_days", 120),
        "REVISING": ("revising_idle_days", 30),
        "READY_TO_SUBMIT": ("ready_idle_days", 14),
    }
    for p in state.get("papers", []):
        title = p["title"]
        if p["state"] == "READY_TO_SUBMIT":
            out.append(
                signal(
                    f"papers:waiting:{title}",
                    "papers",
                    "waiting",
                    f"{title} is READY_TO_SUBMIT",
                    p.get("source"),
                    today,
                )
            )
        if p["state"] in limits and p.get("days_since_touch") is not None:
            key, default = limits[p["state"]]
            limit = int(value(th, "papers", key, default))
            if p["days_since_touch"] > limit:
                out.append(
                    signal(
                        f"papers:{key}:{title}",
                        "papers",
                        "attention",
                        f"{title}: {message(th, 'papers', key, key)} "
                        f"({p['days_since_touch']} days since {p['last_touched']})",
                        p.get("source"),
                        today,
                    )
                )
    return out


def papers_change_signals(
    cur: dict[str, Any], prev: dict[str, Any] | None, today: dt.date
) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    if prev is None:
        return out, len(cur.get("papers", []))
    before = {p["title"]: p for p in prev.get("papers", [])}
    done = set(cur.get("done_states", []))
    unchanged = 0
    for p in cur.get("papers", []):
        old = before.get(p["title"])
        if old is None:
            out.append(
                signal(
                    f"papers:new:{p['title']}",
                    "papers",
                    "change",
                    f"new paper {p['title']} ({p['state']})",
                    p.get("source"),
                    today,
                )
            )
        elif old["state"] != p["state"]:
            severity = "positive" if p["state"] in done and p["state"] != "CANCELED" else "change"
            out.append(
                signal(
                    f"papers:transition:{p['title']}",
                    "papers",
                    severity,
                    f"{p['title']}: {old['state']} -> {p['state']}",
                    p.get("source"),
                    today,
                )
            )
        else:
            unchanged += 1
    for title in set(before) - {p["title"] for p in cur.get("papers", [])}:
        out.append(
            signal(
                f"papers:removed:{title}",
                "papers",
                "change",
                f"{title} no longer in papers.org",
                cur.get("source"),
                today,
            )
        )
    return out, unchanged


def repos_threshold_signals(
    state: dict[str, Any], th: dict[str, Any], today: dt.date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    idle = int(value(th, "repos", "idle_days_with_open_issues", 90))
    lag = int(value(th, "repos", "release_lag_days", 365))
    for r in state.get("repos", []):
        name = r.get("name")
        if r.get("error"):
            out.append(
                signal(
                    f"repos:error:{name}",
                    "repos",
                    "note",
                    f"{name}: {r['error']}",
                    r.get("source"),
                    today,
                )
            )
            continue
        days = r.get("days_since_commit")
        issues = r.get("open_issues")
        if days is not None and days > idle and (issues or 0) > 0:
            out.append(
                signal(
                    f"repos:idle_days_with_open_issues:{name}",
                    "repos",
                    "attention",
                    f"{name}: {message(th, 'repos', 'idle_days_with_open_issues', 'idle')} ({days} "
                    f"days, {issues} open issues)",
                    r.get("source"),
                    today,
                )
            )
        if r.get("release_lag_days") is not None and r["release_lag_days"] > lag:
            out.append(
                signal(
                    f"repos:release_lag_days:{name}",
                    "repos",
                    "attention",
                    f"{name}: {message(th, 'repos', 'release_lag_days', 'release lag')} "
                    f"({r['release_lag_days']} days since {r.get('last_tag')})",
                    r.get("source"),
                    today,
                )
            )
        if str(r.get("ci_status", "")).lower() in {"failing", "failure", "failed"}:
            out.append(
                signal(
                    f"repos:ci_failing:{name}",
                    "repos",
                    "attention",
                    f"{name}: {message(th, 'repos', 'ci_failing', 'CI failing')}",
                    r.get("source"),
                    today,
                )
            )
    return out


def repos_change_signals(
    cur: dict[str, Any], prev: dict[str, Any] | None, today: dt.date
) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    if prev is None:
        return out, len(cur.get("repos", []))
    before = {r["name"]: r for r in prev.get("repos", [])}
    unchanged = 0
    for r in cur.get("repos", []):
        old = before.get(r["name"])
        if old is None:
            out.append(
                signal(
                    f"repos:new:{r['name']}",
                    "repos",
                    "change",
                    f"new repository {r['name']}",
                    r.get("source"),
                    today,
                )
            )
            continue
        changed = False
        if old.get("last_commit_hash") != r.get("last_commit_hash"):
            out.append(
                signal(
                    f"repos:commits:{r['name']}",
                    "repos",
                    "change",
                    f"{r['name']}: new commits (last {r.get('last_commit')})",
                    r.get("source"),
                    today,
                )
            )
            changed = True
        if old.get("last_tag") != r.get("last_tag") and r.get("last_tag"):
            out.append(
                signal(
                    f"repos:release:{r['name']}",
                    "repos",
                    "positive",
                    f"{r['name']}: release {r['last_tag']}",
                    r.get("source"),
                    today,
                )
            )
            changed = True
        if str(old.get("ci_status", "")).lower() in {"failing", "failure", "failed"} and str(
            r.get("ci_status", "")
        ).lower() in {"passing", "success", "ok"}:
            out.append(
                signal(
                    f"repos:ci_green:{r['name']}",
                    "repos",
                    "positive",
                    f"{r['name']}: CI green again",
                    r.get("source"),
                    today,
                )
            )
            changed = True
        if not changed:
            unchanged += 1
    return out, unchanged


def students_threshold_signals(
    state: dict[str, Any], th: dict[str, Any], today: dt.date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gap = int(value(th, "students", "meeting_gap_days", 21))
    window = int(value(th, "students", "milestone_window_days", 60))
    plan_months = int(value(th, "students", "final_year_plan_months", 12))
    factor = float(value(th, "students", "new_member_factor", 0.5))
    for s in state.get("students", []):
        slug = s["slug"]
        if s.get("error"):
            out.append(
                signal(
                    f"students:error:{slug}",
                    "students",
                    "note",
                    f"{slug}: {s['error']}",
                    s.get("org_file"),
                    today,
                    privacy="local-only",
                )
            )
            continue
        this_gap = gap * factor if s.get("new_member") else gap
        days = s.get("days_since_meeting")
        if days is None:
            out.append(
                signal(
                    f"students:meeting_gap_days:{slug}",
                    "students",
                    "attention",
                    f"{slug}: no dated meeting entry found",
                    s.get("last_meeting_source"),
                    today,
                    privacy="local-only",
                )
            )
        elif days > this_gap:
            out.append(
                signal(
                    f"students:meeting_gap_days:{slug}",
                    "students",
                    "attention",
                    f"{slug}: {message(th, 'students', 'meeting_gap_days', 'meeting gap')} ({days} "
                    f"days since {s.get('last_meeting')})",
                    s.get("last_meeting_source"),
                    today,
                    privacy="local-only",
                )
            )
        nm = s.get("next_milestone")
        if nm and nm.get("days_left") is not None and nm["days_left"] <= window:
            out.append(
                signal(
                    f"students:milestone_window_days:{slug}:{nm['id']}",
                    "students",
                    "attention",
                    f"{slug}: {nm['label']} due {nm['deadline']} ({nm['days_left']} days); check "
                    "for an artifact",
                    s.get("org_file"),
                    today,
                    deadline=nm["deadline"],
                    privacy="local-only",
                )
            )
        for flag in s.get("milestone_flags", []):
            if flag.get("kind") == "overdue":
                out.append(
                    signal(
                        f"students:overdue:{slug}:{flag['milestone']}",
                        "students",
                        "attention",
                        f"{slug}: {flag['message']}",
                        s.get("org_file"),
                        today,
                        privacy="local-only",
                    )
                )
        defense = s.get("expected_defense")
        if defense and not s.get("final_year_plan"):
            months_left = (dt.date.fromisoformat(defense) - today).days / 30.4
            if 0 < months_left <= plan_months:
                out.append(
                    signal(
                        f"students:final_year_plan_months:{slug}",
                        "students",
                        "attention",
                        f"{slug}: {message(th, 'students', 'final_year_plan_months', 'final-year plan missing')} (defense {defense})",
                        s.get("org_file"),
                        today,
                        deadline=defense,
                        privacy="local-only",
                    )
                )
    return out


def students_change_signals(
    cur: dict[str, Any], prev: dict[str, Any] | None, today: dt.date
) -> tuple[list[dict[str, Any]], int]:
    out: list[dict[str, Any]] = []
    if prev is None:
        return out, len(cur.get("students", []))
    before = {s["slug"]: s for s in prev.get("students", [])}
    unchanged = 0
    for s in cur.get("students", []):
        old = before.get(s["slug"])
        if old and old.get("last_meeting") != s.get("last_meeting") and s.get("last_meeting"):
            out.append(
                signal(
                    f"students:meeting:{s['slug']}",
                    "students",
                    "positive",
                    f"{s['slug']}: meeting entry {s['last_meeting']}",
                    s.get("last_meeting_source"),
                    today,
                    privacy="local-only",
                )
            )
        else:
            unchanged += 1
    return out, unchanged


def services_signals(
    state: dict[str, Any], th: dict[str, Any], today: dt.date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    factor = float(value(th, "services", "stale_factor", 2))
    generated = state.get("generated")
    interval = state.get("interval_minutes")
    source = state.get("source", "services")
    if generated and interval:
        try:
            gen = dt.datetime.fromisoformat(generated)
            now = dt.datetime.combine(today, dt.time.max, tzinfo=gen.tzinfo)
            age_min = (now - gen).total_seconds() / 60
            if age_min > interval * factor:
                out.append(
                    signal(
                        "services:stale",
                        "services",
                        "attention",
                        f"{message(th, 'services', 'stale_factor', 'status stale')} (age "
                        f"{int(age_min)} min, interval {interval} min)",
                        source,
                        today,
                    )
                )
        except ValueError:
            out.append(
                signal(
                    "services:bad-timestamp",
                    "services",
                    "note",
                    f"cannot parse generated {generated!r}",
                    source,
                    today,
                )
            )
    for c in state.get("checks", []):
        if str(c.get("status", "")).lower() not in {"ok", "pass", "passing", "up"}:
            out.append(
                signal(
                    f"services:{c.get('name')}",
                    "services",
                    "attention",
                    f"{c.get('name')}: {c.get('status')} {c.get('detail', '')}".strip(),
                    c.get("source", source),
                    today,
                )
            )
    return out


def teaching_signals(
    state: dict[str, Any], th: dict[str, Any], today: dt.date
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    window = int(value(th, "teaching", "deadline_window_days", 14))
    for d in state.get("deadlines", []):
        due = dt.date.fromisoformat(d["due"])
        days = (due - today).days
        label = f"{d.get('course', '')} {d.get('item', '')}".strip()
        if days < 0 and not d.get("artifact"):
            out.append(
                signal(
                    f"teaching:overdue:{label}",
                    "teaching",
                    "attention",
                    f"{label}: due {d['due']} passed without an artifact",
                    d.get("source"),
                    today,
                    deadline=d["due"],
                )
            )
        elif days <= window and not d.get("artifact"):
            out.append(
                signal(
                    f"teaching:deadline_window_days:{label}",
                    "teaching",
                    "attention",
                    f"{label}: {message(th, 'teaching', 'deadline_window_days', 'deadline near')} "
                    f"(due {d['due']}, {days} days)",
                    d.get("source"),
                    today,
                    deadline=d["due"],
                )
            )
        elif days <= window:
            out.append(
                signal(
                    f"teaching:ready:{label}",
                    "teaching",
                    "positive",
                    f"{label}: due {d['due']}, artifact {d['artifact']}",
                    d.get("source"),
                    today,
                    deadline=d["due"],
                )
            )
    return out


THRESHOLD_FUNCS = {
    "papers": papers_threshold_signals,
    "repos": repos_threshold_signals,
    "students": students_threshold_signals,
    "services": services_signals,
    "teaching": teaching_signals,
}
CHANGE_FUNCS = {
    "papers": papers_change_signals,
    "repos": repos_change_signals,
    "students": students_change_signals,
}


def compute(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    th: dict[str, Any],
    today: dt.date,
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    unchanged: dict[str, int] = {}
    for kind, state in current.items():
        func = THRESHOLD_FUNCS.get(kind)
        if func is None:
            signals.append(
                signal(
                    f"{kind}:unknown-kind", kind, "note", f"no rules for kind {kind!r}", None, today
                )
            )
            continue
        now_signals = func(state, th, today)
        signals += now_signals
        prev_state = previous.get(kind)
        if prev_state is not None and kind in CHANGE_FUNCS:
            changes, same = CHANGE_FUNCS[kind](state, prev_state, today)
            signals += changes
            unchanged[kind] = same
            prev_attention = {
                s["id"]: s for s in func(prev_state, th, today) if s["severity"] == "attention"
            }
            now_ids = {s["id"] for s in now_signals}
            for sid, old in prev_attention.items():
                if sid not in now_ids:
                    signals.append(
                        signal(
                            f"cleared:{sid}",
                            old["category"],
                            "cleared",
                            f"cleared: {old['message']}",
                            old.get("source"),
                            today,
                            privacy=old.get("privacy", "internal"),
                        )
                    )
        elif kind in CHANGE_FUNCS:
            unchanged[kind] = len(state.get(kind, []))
    counts: dict[str, int] = {}
    for s in signals:
        counts[s["severity"]] = counts.get(s["severity"], 0) + 1
    return {
        "kind": "signals",
        "generated": today.isoformat(),
        "thresholds_version": str(th.get("version")),
        "previous_present": sorted(previous),
        "current_present": sorted(current),
        "counts": counts,
        "unchanged": unchanged,
        "signals": signals,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--current",
        action="append",
        type=Path,
        default=[],
        required=True,
        help="current snapshot JSON (repeatable)",
    )
    p.add_argument(
        "--previous",
        action="append",
        type=Path,
        default=[],
        help="previous snapshot JSON (repeatable)",
    )
    p.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    return p


def load_by_kind(paths: list[Path]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in paths:
        data = load_json(path)
        kind = data.get("kind")
        if not kind:
            raise ValueError(f"{path} has no 'kind' field")
        data.setdefault("source", str(path))
        out[kind] = data
    return out


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        current = load_by_kind(args.current)
        previous = load_by_kind([p for p in args.previous if p.exists()])
        with args.thresholds.open(encoding="utf-8") as fh:
            th = yaml.safe_load(fh) or {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"diff-state: {exc}", file=sys.stderr)
        return 1
    result = compute(current, previous, th, args.today or dt.date.today())
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"diff-state: {len(result['signals'])} signals -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
