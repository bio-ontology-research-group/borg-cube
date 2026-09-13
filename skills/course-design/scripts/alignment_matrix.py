#!/usr/bin/env python3
"""Render the constructive-alignment matrix of a course and refuse a broken design.

Input is the course YAML described in references/course-yaml.md: outcomes
with Bloom levels, assessments that test outcomes with grade weights,
activities that serve outcomes at a level, and a week plan. The script prints
two matrices (outcomes by assessments, outcomes by activities), a level
summary per outcome and a findings list.

Exit status 2 (design error) when
  * an outcome is never tested by any assessment,
  * an assessment tests no declared outcome or names an unknown one,
  * an activity practises a level below an outcome it serves,
  * assessment weights do not sum to 100,
  * an id is duplicated, or a level is not a Bloom level (we do not guess).

Warnings (exit 0, exit 2 with --strict) when an outcome has no activity, an
assessment sits below the level of an outcome it tests, every outcome is at
remember or understand, a week refers to an unknown id, or an assessment is
due before any activity that serves one of its outcomes.

Example:
  alignment_matrix.py --course state/courses/cs3xx.yaml
  alignment_matrix.py --course assets/course.yaml.example --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

BLOOM = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
BLOOM_ALIASES = {
    "remembering": "remember",
    "recall": "remember",
    "knowledge": "remember",
    "understanding": "understand",
    "comprehend": "understand",
    "comprehension": "understand",
    "applying": "apply",
    "application": "apply",
    "analyse": "analyze",
    "analysing": "analyze",
    "analyzing": "analyze",
    "analysis": "analyze",
    "evaluating": "evaluate",
    "evaluation": "evaluate",
    "creating": "create",
    "synthesis": "create",
    "synthesize": "create",
}
KNOWLEDGE_TYPES = {"factual", "conceptual", "procedural", "metacognitive"}
FINK_KINDS = {
    "foundational",
    "application",
    "integration",
    "human",
    "caring",
    "learning-how-to-learn",
}


class DesignError(Exception):
    """Raised when the YAML cannot be interpreted without guessing."""


def normalise_level(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DesignError(f"{where}: missing Bloom level")
    key = value.strip().lower()
    key = BLOOM_ALIASES.get(key, key)
    if key not in BLOOM:
        raise DesignError(f"{where}: unknown Bloom level {value!r}; use one of {', '.join(BLOOM)}")
    return key


def level_rank(level: str) -> int:
    return BLOOM.index(level)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_course(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DesignError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DesignError(f"{path}: top level must be a mapping")
    for key in ("course", "outcomes", "assessments", "activities"):
        if key not in data:
            raise DesignError(f"{path}: missing top-level key {key!r}")
    return data


def _index(items: list[dict[str, Any]], what: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("id"):
            raise DesignError(f"{what}[{i}]: every entry needs an id")
        iid = str(item["id"])
        if iid in out:
            raise DesignError(f"{what}: duplicate id {iid!r}")
        out[iid] = item
    return out


def analyse(data: dict[str, Any]) -> dict[str, Any]:
    """Return the matrix, the level table and the findings for a course."""
    outcomes = _index(as_list(data.get("outcomes")), "outcomes")
    assessments = _index(as_list(data.get("assessments")), "assessments")
    activities = _index(as_list(data.get("activities")), "activities")
    all_ids = set(outcomes) | set(assessments) | set(activities)
    if len(all_ids) != len(outcomes) + len(assessments) + len(activities):
        raise DesignError("ids must be unique across outcomes, assessments and activities")

    errors: list[str] = []
    warnings: list[str] = []

    out_levels = {oid: normalise_level(o.get("level"), f"outcome {oid}") for oid, o in outcomes.items()}
    for oid, o in outcomes.items():
        kt = o.get("knowledge")
        if kt is not None and str(kt).lower() not in KNOWLEDGE_TYPES:
            errors.append(f"outcome {oid}: unknown knowledge type {kt!r}")
        kind = o.get("kind")
        if kind is not None and str(kind).lower() not in FINK_KINDS:
            errors.append(f"outcome {oid}: unknown significant-learning kind {kind!r}")
        if not str(o.get("text", "")).strip():
            errors.append(f"outcome {oid}: missing text")

    tested_by: dict[str, list[str]] = {oid: [] for oid in outcomes}
    served_by: dict[str, list[str]] = {oid: [] for oid in outcomes}

    total_weight = 0.0
    for aid, a in assessments.items():
        level = normalise_level(a.get("level"), f"assessment {aid}")
        tests = [str(t) for t in as_list(a.get("tests"))]
        if not tests:
            errors.append(f"assessment {aid}: tests no declared outcome")
        for t in tests:
            if t not in outcomes:
                errors.append(f"assessment {aid}: tests unknown outcome {t!r}")
                continue
            tested_by[t].append(aid)
            if level_rank(level) < level_rank(out_levels[t]):
                warnings.append(
                    f"assessment {aid} ({level}) sits below outcome {t} ({out_levels[t]})"
                )
        weight = a.get("weight")
        if weight is None:
            errors.append(f"assessment {aid}: missing weight")
        else:
            try:
                total_weight += float(weight)
            except (TypeError, ValueError):
                errors.append(f"assessment {aid}: weight {weight!r} is not a number")

    if assessments and abs(total_weight - 100.0) > 1e-6:
        errors.append(f"assessment weights sum to {total_weight:g}, not 100")

    for tid, t in activities.items():
        level = normalise_level(t.get("level"), f"activity {tid}")
        serves = [str(s) for s in as_list(t.get("serves"))]
        if not serves:
            warnings.append(f"activity {tid}: serves no outcome")
        for s in serves:
            if s not in outcomes:
                errors.append(f"activity {tid}: serves unknown outcome {s!r}")
                continue
            served_by[s].append(tid)
            if level_rank(level) < level_rank(out_levels[s]):
                errors.append(
                    f"activity {tid} ({level}) practises below outcome {s} ({out_levels[s]})"
                )

    for oid in outcomes:
        if not tested_by[oid]:
            errors.append(f"outcome {oid} is never assessed")
        if not served_by[oid]:
            warnings.append(f"outcome {oid} has no activity that practises it")

    if outcomes and all(level_rank(lv) <= level_rank("understand") for lv in out_levels.values()):
        warnings.append("every outcome is at remember or understand; add higher-level outcomes")

    # week plan checks
    weeks = as_list(data.get("weeks"))
    activity_weeks: dict[str, list[int]] = {tid: [] for tid in activities}
    assessment_weeks: dict[str, list[int]] = {aid: [] for aid in assessments}
    for w in weeks:
        if not isinstance(w, dict) or "week" not in w:
            errors.append("weeks: every entry needs a week number")
            continue
        try:
            num = int(w["week"])
        except (TypeError, ValueError):
            errors.append(f"weeks: week {w.get('week')!r} is not an integer")
            continue
        for tid in as_list(w.get("activities")):
            tid = str(tid)
            if tid not in activities:
                warnings.append(f"week {num}: unknown activity {tid!r}")
            else:
                activity_weeks[tid].append(num)
        for aid in as_list(w.get("due")):
            aid = str(aid)
            if aid not in assessments:
                warnings.append(f"week {num}: unknown assessment {aid!r}")
            else:
                assessment_weeks[aid].append(num)
    for tid, t in activities.items():
        for wk in as_list(t.get("weeks")) + as_list(t.get("week")):
            try:
                activity_weeks[tid].append(int(wk))
            except (TypeError, ValueError):
                errors.append(f"activity {tid}: week {wk!r} is not an integer")
    for aid, a in assessments.items():
        if a.get("week") is not None:
            try:
                assessment_weeks[aid].append(int(a["week"]))
            except (TypeError, ValueError):
                errors.append(f"assessment {aid}: week {a['week']!r} is not an integer")

    if weeks:
        for aid, a in assessments.items():
            due = assessment_weeks[aid]
            if not due:
                warnings.append(f"assessment {aid}: no due week in the plan")
                continue
            first_due = min(due)
            for oid in [str(t) for t in as_list(a.get("tests")) if str(t) in outcomes]:
                practice = [wk for tid in served_by[oid] for wk in activity_weeks[tid]]
                if practice and min(practice) > first_due:
                    warnings.append(
                        f"assessment {aid} is due in week {first_due} before any activity "
                        f"for outcome {oid} (first in week {min(practice)})"
                    )
        declared = data.get("course", {}).get("weeks")
        if declared is not None and len(weeks) != int(declared):
            warnings.append(f"course.weeks says {declared} but the plan lists {len(weeks)} weeks")

    matrix_assess = {
        oid: [
            {
                "id": aid,
                "level": normalise_level(assessments[aid]["level"], aid),
                "weight": assessments[aid].get("weight"),
            }
            for aid in tested_by[oid]
        ]
        for oid in outcomes
    }
    matrix_act = {
        oid: [{"id": tid, "level": normalise_level(activities[tid]["level"], tid)} for tid in served_by[oid]]
        for oid in outcomes
    }
    weight_per_outcome = {}
    for oid in outcomes:
        share = 0.0
        for aid in tested_by[oid]:
            n = len([t for t in as_list(assessments[aid].get("tests")) if str(t) in outcomes]) or 1
            try:
                share += float(assessments[aid].get("weight") or 0) / n
            except (TypeError, ValueError):
                pass
        weight_per_outcome[oid] = round(share, 2)

    return {
        "course": {
            "code": data.get("course", {}).get("code"),
            "title": data.get("course", {}).get("title"),
        },
        "outcomes": [
            {
                "id": oid,
                "text": o.get("text"),
                "level": out_levels[oid],
                "knowledge": o.get("knowledge"),
                "kind": o.get("kind"),
                "assessed_by": tested_by[oid],
                "practised_by": served_by[oid],
                "weight_share": weight_per_outcome[oid],
            }
            for oid, o in outcomes.items()
        ],
        "assessments": [
            {
                "id": aid,
                "title": a.get("title"),
                "level": normalise_level(a.get("level"), aid),
                "weight": a.get("weight"),
                "tests": [str(t) for t in as_list(a.get("tests"))],
                "weeks": sorted(set(assessment_weeks[aid])),
            }
            for aid, a in assessments.items()
        ],
        "activities": [
            {
                "id": tid,
                "title": t.get("title"),
                "level": normalise_level(t.get("level"), tid),
                "serves": [str(s) for s in as_list(t.get("serves"))],
                "weeks": sorted(set(activity_weeks[tid])),
            }
            for tid, t in activities.items()
        ],
        "matrix": {"assessments": matrix_assess, "activities": matrix_act},
        "total_weight": total_weight,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def _mark(cells: list[dict[str, Any]], key: str) -> str:
    return ", ".join(f"{c['id']} ({c['level'][:3]})" for c in cells) if cells else "none"


def render_markdown(result: dict[str, Any]) -> str:
    c = result["course"]
    lines = [f"# Alignment matrix: {c.get('code') or ''} {c.get('title') or ''}".rstrip(), ""]
    lines.append("## Outcomes by assessments")
    lines.append("")
    lines.append("| Outcome | Level | Assessed by | Weight share |")
    lines.append("| --- | --- | --- | --- |")
    for o in result["outcomes"]:
        cells = result["matrix"]["assessments"][o["id"]]
        lines.append(
            f"| {o['id']}: {o['text']} | {o['level']} | {_mark(cells, 'id')} | {o['weight_share']:g} |"
        )
    lines.append("")
    lines.append("## Outcomes by activities")
    lines.append("")
    lines.append("| Outcome | Level | Practised by |")
    lines.append("| --- | --- | --- |")
    for o in result["outcomes"]:
        cells = result["matrix"]["activities"][o["id"]]
        lines.append(f"| {o['id']} | {o['level']} | {_mark(cells, 'id')} |")
    lines.append("")
    lines.append("## Assessments")
    lines.append("")
    lines.append("| Id | Title | Level | Weight | Tests | Due week |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for a in result["assessments"]:
        due = ", ".join(str(w) for w in a["weeks"]) or "unscheduled"
        lines.append(
            f"| {a['id']} | {a['title'] or ''} | {a['level']} | {a['weight']} | "
            f"{', '.join(a['tests'])} | {due} |"
        )
    lines.append("")
    lines.append(f"Total weight: {result['total_weight']:g}")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not result["errors"] and not result["warnings"]:
        lines.append("- No findings. The design is aligned.")
    for e in result["errors"]:
        lines.append(f"- ERROR: {e}")
    for w in result["warnings"]:
        lines.append(f"- WARNING: {w}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", type=Path, required=True, help="course YAML (see references/course-yaml.md)")
    parser.add_argument("--json", action="store_true", help="print the analysis as JSON instead of Markdown")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors (exit 2)")
    parser.add_argument("--out", type=Path, help="write the rendering to this file instead of stdout")
    args = parser.parse_args(argv)

    try:
        data = load_course(args.course)
        result = analyse(data)
    except DesignError as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(f"ERROR: {args.course} not found", file=sys.stderr)
        return 2

    text = json.dumps(result, indent=2) if args.json else render_markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    if result["errors"] or (args.strict and result["warnings"]):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
