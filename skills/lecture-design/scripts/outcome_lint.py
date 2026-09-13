#!/usr/bin/env python3
"""Check a lecture plan YAML: observable outcome verbs, alignment, no unassessed outcome.

The plan is one class session (see ``assets/lecture-plan.yaml.example``). This
script checks the parts that can be checked deterministically:

* every outcome is a verb plus a noun with a stated Bloom level and knowledge
  type, and the verb is in the revised-taxonomy verb table below. The category
  names ("understand", "know") and the vague phrases ("learn about", "be
  familiar with") are rejected because they name nothing observable;
* the level stated for an outcome is the level the table gives for its verb;
* every outcome is practised by at least one activity segment whose level sits
  at or above the outcome's level;
* every outcome is evidenced by at least one formative check segment, so no
  outcome is unassessed;
* pre-class work names its minutes and the check that makes it count;
* every demonstration is preceded by a recorded prediction, and every peer
  instruction question names the misconception its wrong options encode.

It never edits the plan and never guesses a level: a segment that practises an
outcome without stating its own verb or level is an error, not an assumption.

Exit status: 2 when any error was found (or the plan could not be read),
0 otherwise. Warnings alone do not change the status.

Examples:
  outcome_lint.py --plan assets/lecture-plan.yaml.example
  outcome_lint.py --plan plans/cs249-08.yaml --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------- taxonomy

# Revised Bloom taxonomy (Anderson and Krathwohl 2001): cognitive process
# dimension, ordered from less to more complex. See
# references/lecture-delivery.md for the evidence and the rules.
LEVELS: list[str] = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
LEVEL_INDEX: dict[str, int] = {name: i + 1 for i, name in enumerate(LEVELS)}

KNOWLEDGE_TYPES: set[str] = {"factual", "conceptual", "procedural", "metacognitive"}

# One verb, one level. A verb that could sit in two cells is assigned the level
# we use it at, so that a plan is checked the same way every time.
VERB_LEVEL: dict[str, str] = {
    # remember: recognizing, recalling
    "define": "remember",
    "identify": "remember",
    "label": "remember",
    "list": "remember",
    "match": "remember",
    "name": "remember",
    "recall": "remember",
    "recite": "remember",
    "recognize": "remember",
    "reproduce": "remember",
    "state": "remember",
    # understand: interpreting, exemplifying, classifying, summarizing,
    # inferring, comparing, explaining
    "classify": "understand",
    "compare": "understand",
    "contrast": "understand",
    "describe": "understand",
    "exemplify": "understand",
    "explain": "understand",
    "generalize": "understand",
    "illustrate": "understand",
    "infer": "understand",
    "interpret": "understand",
    "paraphrase": "understand",
    "predict": "understand",
    "summarize": "understand",
    "translate": "understand",
    # apply: executing, implementing
    "apply": "apply",
    "calculate": "apply",
    "compute": "apply",
    "configure": "apply",
    "demonstrate": "apply",
    "execute": "apply",
    "implement": "apply",
    "modify": "apply",
    "operate": "apply",
    "run": "apply",
    "solve": "apply",
    "use": "apply",
    # analyze: differentiating, organizing, attributing
    "analyze": "analyze",
    "attribute": "analyze",
    "debug": "analyze",
    "deconstruct": "analyze",
    "diagnose": "analyze",
    "differentiate": "analyze",
    "distinguish": "analyze",
    "isolate": "analyze",
    "organize": "analyze",
    "profile": "analyze",
    "trace": "analyze",
    # evaluate: checking, critiquing
    "appraise": "evaluate",
    "argue": "evaluate",
    "assess": "evaluate",
    "critique": "evaluate",
    "defend": "evaluate",
    "evaluate": "evaluate",
    "judge": "evaluate",
    "justify": "evaluate",
    "rank": "evaluate",
    "recommend": "evaluate",
    "review": "evaluate",
    "validate": "evaluate",
    # create: generating, planning, producing
    "build": "create",
    "compose": "create",
    "construct": "create",
    "create": "create",
    "derive": "create",
    "design": "create",
    "develop": "create",
    "formulate": "create",
    "generate": "create",
    "hypothesize": "create",
    "plan": "create",
    "produce": "create",
    "propose": "create",
}

# Rejected outcome verbs and phrases: nothing about them can be observed, so no
# activity or check can be aligned to them.
UNOBSERVABLE: dict[str, str] = {
    "understand": "a taxonomy category, not a process; say explain, interpret, classify, compare or summarize",
    "know": "not observable; say define, state, list or explain",
    "learn": "not observable; name what the student will do with what they learned",
    "learn about": "not observable; name what the student will do with what they learned",
    "appreciate": "not observable; say justify, critique or evaluate",
    "be aware of": "not observable; say identify, describe or recognize",
    "be familiar with": "not observable; say describe, use or apply",
    "become familiar with": "not observable; say describe, use or apply",
    "comprehend": "not observable; say explain, interpret or summarize",
    "consider": "not observable; say compare, evaluate or justify",
    "cover": "describes the teacher, not the student",
    "explore": "not observable; say analyze, compare or investigate a stated question",
    "familiarize": "not observable; say describe, use or apply",
    "gain knowledge of": "not observable; say define, explain or apply",
    "grasp": "not observable; say explain or apply",
    "internalize": "not observable; say apply, justify or design",
    "introduce": "describes the teacher, not the student",
    "master": "not observable at one level; state the verb and the level",
    "realize": "not observable; say explain or infer",
    "see": "not observable; say identify, describe or explain",
    "study": "describes the activity, not the outcome",
    "think about": "not observable; say compare, evaluate or justify",
}

# --------------------------------------------------------------------------- segment kinds

# Direct instruction: the instructor talks or types and the class watches.
DIRECT_KINDS: set[str] = {"lecture", "demo", "worked-example", "recap"}
# Class time that is neither instruction nor practice.
OVERHEAD_KINDS: set[str] = {"admin", "setup"}
BREAK_KINDS: set[str] = {"break"}
# Formative checks: the segment produces evidence of what a named outcome
# reached, while there is still time to act on it.
CHECK_KINDS: set[str] = {
    "code-check",
    "exit-ticket",
    "minute-paper",
    "muddiest-point",
    "peer-instruction",
    "poll",
    "quiz",
    "retrieval",
}
# Activities: the students do the work. Every check is also an activity.
ACTIVITY_KINDS: set[str] = CHECK_KINDS | {
    "discussion",
    "exercise",
    "live-coding",
    "pair-programming",
    "prediction",
    "problem",
    "think-pair-share",
}
KNOWN_KINDS: set[str] = DIRECT_KINDS | OVERHEAD_KINDS | BREAK_KINDS | ACTIVITY_KINDS

REQUIRED_TOP_LEVEL = ("course", "title", "length_minutes", "outcomes", "segments")


class PlanError(Exception):
    """The plan file could not be read or is not shaped like a plan."""


# --------------------------------------------------------------------------- loading


def load_plan(path: Path) -> dict[str, Any]:
    """Read a lecture plan YAML and check the shape the checks depend on."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PlanError(f"{path}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise PlanError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PlanError(f"{path}: the plan must be a YAML mapping")
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise PlanError(f"{path}: missing top-level keys: {', '.join(missing)}")
    for key in ("outcomes", "segments"):
        if not isinstance(data[key], list) or not data[key]:
            raise PlanError(f"{path}: {key} must be a non-empty list")
        if any(not isinstance(item, dict) for item in data[key]):
            raise PlanError(f"{path}: every entry in {key} must be a mapping")
    pre = data.get("pre_class")
    if pre is not None and (
        not isinstance(pre, list) or any(not isinstance(item, dict) for item in pre)
    ):
        raise PlanError(f"{path}: pre_class must be a list of mappings")
    return data


def segment_level(segment: dict[str, Any]) -> str | None:
    """The level a segment makes students perform: stated, or read off its verb."""
    level = segment.get("level")
    if isinstance(level, str) and level.strip():
        return level.strip().lower()
    verb = segment.get("verb")
    if isinstance(verb, str) and verb.strip():
        return VERB_LEVEL.get(verb.strip().lower())
    return None


def outcome_refs(segment: dict[str, Any]) -> list[str]:
    refs = segment.get("outcomes")
    if refs is None:
        return []
    if isinstance(refs, str):
        return [refs]
    if isinstance(refs, list):
        return [str(r) for r in refs]
    return []


# --------------------------------------------------------------------------- checks


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "notes": self.notes,
            "summary": {"errors": len(self.errors), "warnings": len(self.warnings)},
        }


def check_outcomes(plan: dict[str, Any], report: Report) -> dict[str, dict[str, Any]]:
    """Verb, level and knowledge type of every outcome. Returns the valid ones by id."""
    valid: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for i, outcome in enumerate(plan["outcomes"], 1):
        oid = str(outcome.get("id") or f"outcome[{i}]")
        where = f"outcome {oid}"
        if not outcome.get("id"):
            report.error(where, "no id")
        elif oid in seen:
            report.error(where, "duplicate outcome id")
        seen.add(oid)

        statement = outcome.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            report.error(where, "no statement")
            statement = ""

        raw_verb = outcome.get("verb")
        verb = raw_verb.strip().lower() if isinstance(raw_verb, str) else ""
        if not verb:
            report.error(where, "no verb; an outcome is a verb plus a noun")
            continue
        if verb in UNOBSERVABLE:
            report.error(where, f"verb {verb!r} is not an outcome verb: {UNOBSERVABLE[verb]}")
            continue
        table_level = VERB_LEVEL.get(verb)
        if table_level is None:
            report.error(
                where,
                f"verb {verb!r} is not in the verb table; use a verb from --verbs or add it there "
                "with its level",
            )
            continue

        raw_level = outcome.get("level")
        level = raw_level.strip().lower() if isinstance(raw_level, str) else ""
        if not level:
            report.error(where, f"no level; the table puts {verb!r} at {table_level}")
            continue
        if level not in LEVEL_INDEX:
            report.error(where, f"level {level!r} is not one of {', '.join(LEVELS)}")
            continue
        if level != table_level:
            report.error(
                where,
                f"verb {verb!r} is {table_level} in the table but the outcome states {level}; "
                "change the verb or the level",
            )
            continue

        knowledge = outcome.get("knowledge")
        knowledge = knowledge.strip().lower() if isinstance(knowledge, str) else ""
        if not knowledge:
            report.error(where, f"no knowledge type; one of {', '.join(sorted(KNOWLEDGE_TYPES))}")
        elif knowledge not in KNOWLEDGE_TYPES:
            report.error(
                where,
                f"knowledge {knowledge!r} is not one of {', '.join(sorted(KNOWLEDGE_TYPES))}",
            )

        words = statement.lower().replace(",", " ").replace(".", " ").split()
        if verb not in words:
            report.error(where, f"the statement does not contain the verb {verb!r}")
        elif words and words[0] != verb:
            report.warn(where, f"the statement does not start with the verb {verb!r}")

        valid[oid] = {"level": level, "verb": verb, "knowledge": knowledge}
    if valid and all(LEVEL_INDEX[o["level"]] <= LEVEL_INDEX["understand"] for o in valid.values()):
        report.warn(
            "outcomes", "every outcome is at remember or understand; the session cannot show transfer"
        )
    return valid


def check_segments(
    plan: dict[str, Any], outcomes: dict[str, dict[str, Any]], report: Report
) -> None:
    segments = plan["segments"]
    seen: set[str] = set()
    for i, segment in enumerate(segments, 1):
        sid = str(segment.get("id") or f"segment[{i}]")
        where = f"segment {sid}"
        if not segment.get("id"):
            report.error(where, "no id")
        elif sid in seen:
            report.error(where, "duplicate segment id")
        seen.add(sid)

        kind = segment.get("kind")
        kind = kind.strip().lower() if isinstance(kind, str) else ""
        if not kind:
            report.error(where, "no kind")
            continue
        if kind not in KNOWN_KINDS:
            report.error(where, f"kind {kind!r} is not one of {', '.join(sorted(KNOWN_KINDS))}")
            continue
        if not segment.get("what") and kind not in BREAK_KINDS:
            report.warn(where, "no 'what': say what happens in this segment")

        refs = outcome_refs(segment)
        for ref in refs:
            if ref not in outcomes:
                report.error(where, f"references unknown outcome {ref!r}")
        if kind in ACTIVITY_KINDS and not refs:
            report.warn(where, "an activity that serves no outcome; drop it or name the outcome")
        if kind in ACTIVITY_KINDS and refs and segment_level(segment) is None:
            report.error(
                where,
                "no verb or level: state what the students do so the level can be compared with "
                "the outcome",
            )
        stated = segment_level(segment)
        if stated is not None and stated not in LEVEL_INDEX:
            report.error(where, f"level {stated!r} is not one of {', '.join(LEVELS)}")
        if kind == "peer-instruction" and not segment.get("misconception"):
            report.error(
                where,
                "a peer instruction question names the misconception its wrong options encode",
            )
        if kind in {"quiz", "poll"} and not segment.get("misconception"):
            report.warn(where, "no misconception named for the wrong options")
        if kind == "demo":
            previous = segments[i - 2] if i >= 2 else None
            previous_kind = str((previous or {}).get("kind", "")).strip().lower()
            if previous_kind != "prediction":
                report.error(
                    where,
                    "a demonstration is preceded by a prediction segment; watching without "
                    "predicting does not teach",
                )


def check_alignment(
    plan: dict[str, Any], outcomes: dict[str, dict[str, Any]], report: Report
) -> None:
    """Every outcome practised at or above its level and evidenced by a check."""
    for oid, outcome in outcomes.items():
        want = LEVEL_INDEX[outcome["level"]]
        activities: list[tuple[str, int | None]] = []
        checks: list[tuple[str, int | None]] = []
        for i, segment in enumerate(plan["segments"], 1):
            if oid not in outcome_refs(segment):
                continue
            kind = str(segment.get("kind", "")).strip().lower()
            sid = str(segment.get("id") or f"segment[{i}]")
            stated = segment_level(segment)
            index = LEVEL_INDEX.get(stated) if stated else None
            if kind in ACTIVITY_KINDS:
                activities.append((sid, index))
            if kind in CHECK_KINDS:
                checks.append((sid, index))
        where = f"outcome {oid}"
        if not activities:
            report.error(
                where,
                f"no activity practises it; add a segment of a kind in "
                f"{', '.join(sorted(ACTIVITY_KINDS))} that names it",
            )
        else:
            reached = [ix for _, ix in activities if ix is not None]
            if reached and max(reached) < want:
                highest = LEVELS[max(reached) - 1]
                report.error(
                    where,
                    f"stated at {outcome['level']} but the highest activity is at {highest} "
                    f"({', '.join(sid for sid, _ in activities)}); raise the activity or lower "
                    "the outcome",
                )
        if not checks:
            report.error(
                where,
                "unassessed: no formative check evidences it; add a segment of a kind in "
                f"{', '.join(sorted(CHECK_KINDS))} that names it",
            )
        else:
            below = [sid for sid, ix in checks if ix is not None and ix < want]
            if below:
                report.warn(
                    where,
                    f"the check {', '.join(below)} sits below {outcome['level']}; it evidences "
                    "less than the outcome claims",
                )


def check_pre_class(plan: dict[str, Any], report: Report) -> None:
    pre = plan.get("pre_class")
    if not pre:
        report.warn(
            "pre_class",
            "no pre-class work: first exposure to notation and definitions then happens in class, "
            "so budget an exposition segment and check it early",
        )
        return
    check_ids = {
        str(s.get("id")): str(s.get("kind", "")).strip().lower()
        for s in plan["segments"]
        if s.get("id")
    }
    for i, item in enumerate(pre, 1):
        pid = str(item.get("id") or f"pre_class[{i}]")
        where = f"pre-class {pid}"
        if not item.get("what"):
            report.error(where, "no 'what': name the reading, video or notebook")
        minutes = item.get("minutes")
        if not isinstance(minutes, int) or minutes <= 0:
            report.error(where, "no expected minutes; students need the budget")
        check = item.get("check")
        if not check:
            report.error(
                where,
                "no check: pre-class work that nothing checks is not done, so name the segment "
                "that makes it count",
            )
            continue
        kind = check_ids.get(str(check))
        if kind is None:
            report.error(where, f"check {str(check)!r} is not a segment in this plan")
        elif kind not in CHECK_KINDS:
            report.error(
                where,
                f"check {str(check)!r} is a {kind} segment, not a formative check",
            )


def lint(plan: dict[str, Any]) -> Report:
    report = Report()
    outcomes = check_outcomes(plan, report)
    check_segments(plan, outcomes, report)
    check_alignment(plan, outcomes, report)
    check_pre_class(plan, report)
    report.notes.append(
        f"{len(plan['outcomes'])} outcomes, {len(plan['segments'])} segments, "
        f"{len(plan.get('pre_class') or [])} pre-class items"
    )
    return report


# --------------------------------------------------------------------------- rendering


def render_text(plan: dict[str, Any], report: Report) -> str:
    lines: list[str] = []
    title = str(plan.get("title", "(untitled)"))
    course = str(plan.get("course", "(no course)"))
    lines.append(f"outcome_lint: {course}, {title}")
    for note in report.notes:
        lines.append(f"  {note}")
    for error in report.errors:
        lines.append(f"  ERROR {error}")
    for warning in report.warnings:
        lines.append(f"  WARNING {warning}")
    verdict = "fail" if report.errors else ("pass with warnings" if report.warnings else "pass")
    lines.append(
        f"  {verdict}: {len(report.errors)} errors, {len(report.warnings)} warnings"
    )
    return "\n".join(lines) + "\n"


def render_verbs() -> str:
    lines = ["Observable outcome verbs by Bloom level (Anderson and Krathwohl 2001):"]
    for level in LEVELS:
        verbs = sorted(v for v, lv in VERB_LEVEL.items() if lv == level)
        lines.append(f"  {level}: {', '.join(verbs)}")
    lines.append("Rejected as outcome verbs:")
    for verb in sorted(UNOBSERVABLE):
        lines.append(f"  {verb}: {UNOBSERVABLE[verb]}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--plan", type=Path, help="lecture plan YAML")
    p.add_argument("--json", action="store_true", help="machine-readable findings")
    p.add_argument("--verbs", action="store_true", help="print the verb table and exit 0")
    p.add_argument("--out", type=Path, default=None, help="write the report here as well")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbs:
        print(render_verbs(), end="")
        return 0
    if not args.plan:
        print("outcome_lint: --plan is required (or --verbs)", file=sys.stderr)
        return 2
    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        if args.json:
            print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, indent=2))
        else:
            print(f"outcome_lint: {exc}", file=sys.stderr)
        return 2
    report = lint(plan)
    text = json.dumps(report.to_json(), indent=2) + "\n" if args.json else render_text(plan, report)
    print(text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 2 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
