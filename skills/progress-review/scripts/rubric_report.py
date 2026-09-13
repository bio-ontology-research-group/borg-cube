#!/usr/bin/env python3
"""Render a Robert-only progress report from evidence JSON and a scores file.

Inputs:

* ``--evidence`` JSON from ``collect_evidence.py``;
* ``--scores`` YAML with one block per student (see ``--example``): for each
  rubric dimension a ``score`` of 1 to 5 or the string ``no evidence``, the
  list of ``evidence`` ids that justify it, and an optional ``note``;
* ``--template`` Markdown with ``{{placeholders}}`` (default
  ``assets/progress-report.md``).

The script exits 2 and writes nothing when a numeric score has no evidence id,
cites an id that the evidence file does not contain, uses a score outside 1 to
5, or leaves a dimension out. ``no evidence`` is the only way to record a
dimension without evidence; it is never a low score. Flags (stale commits,
stale meeting entry, unchanged drafts) are computed from the evidence with the
thresholds given on the command line.

Dry run by default: the report goes to stdout. ``--out PATH`` writes it.

Example:
  rubric_report.py --evidence runs/9/evidence.json --scores runs/9/scores.yaml --student alex
  rubric_report.py --example > scores.yaml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "progress-report.md"

DIMENSIONS: list[tuple[str, str]] = [
    ("question_and_plan", "Research question and plan"),
    ("evidence_velocity", "Evidence velocity"),
    ("rigor", "Methodological rigor"),
    ("writing", "Writing progress"),
    ("milestone", "Milestone standing"),
    ("communication", "Communication"),
    ("independence", "Independence"),
]
NO_EVIDENCE = "no evidence"
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

EXAMPLE_SCORES = """\
# One block per student id (as in students.yaml). Every numeric score lists
# the evidence ids from collect_evidence.py that justify it. Use the string
# "no evidence" when nothing in the window speaks to a dimension.
alex:
  reviewer: Robert Hoehndorf
  question_and_plan:
    score: 3
    evidence: [alex-org-01]
    note: question stated in the 12 Aug entry; no success criteria yet
  evidence_velocity:
    score: 4
    evidence: [alex-git-01]
  rigor:
    score: no evidence
    evidence: []
  writing:
    score: 2
    evidence: [alex-draft-01]
  milestone:
    score: 3
    evidence: [alex-org-01]
  communication:
    score: 4
    evidence: [alex-org-01, alex-org-02]
  independence:
    score: 3
    evidence: [alex-org-02]
  agenda:
    - success criteria for the benchmark experiment
    - what blocks the methods draft
"""


class ReportError(Exception):
    """Validation failure; nothing is written."""


def load_yaml(path: Path) -> Any:
    if not path.exists():
        raise ReportError(f"file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def validate_scores(sid: str, block: Any, evidence_ids: set[str]) -> list[dict[str, Any]]:
    """Return the validated rows for one student or raise ReportError."""
    if not isinstance(block, dict):
        raise ReportError(f"{sid}: scores block must be a mapping")
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for key, label in DIMENSIONS:
        entry = block.get(key)
        if entry is None:
            problems.append(f"{key}: missing (use 'no evidence' if nothing applies)")
            continue
        if not isinstance(entry, dict):
            problems.append(f"{key}: must be a mapping with score and evidence")
            continue
        score = entry.get("score")
        ids = entry.get("evidence") or []
        if isinstance(ids, str):
            ids = [ids]
        ids = [str(i) for i in ids]
        if score == NO_EVIDENCE:
            if ids:
                problems.append(f"{key}: 'no evidence' must not cite evidence ids {ids}")
        else:
            if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
                problems.append(f"{key}: score {score!r} must be 1 to 5 or 'no evidence'")
            if not ids:
                problems.append(f"{key}: score {score!r} cites no evidence id")
        unknown = [i for i in ids if i not in evidence_ids]
        if unknown:
            problems.append(f"{key}: evidence ids not in evidence file: {unknown}")
        rows.append(
            {
                "key": key,
                "label": label,
                "score": score,
                "evidence": ids,
                "note": str(entry.get("note") or ""),
            }
        )
    if problems:
        raise ReportError(f"{sid}: " + "; ".join(problems))
    return rows


def compute_flags(student: dict[str, Any], until: dt.date, stale_days: int) -> list[str]:
    flags: list[str] = []
    cutoff = until - dt.timedelta(days=stale_days)
    for repo in student.get("repos", []):
        eid = repo.get("evidence_id", "?")
        if not repo.get("exists"):
            flags.append(f"{eid}: repository missing or unreadable ({repo.get('repo')})")
        elif repo.get("commits", 0) == 0:
            flags.append(f"{eid}: no commits in window ({repo.get('repo')})")
        elif repo.get("last_commit") and dt.date.fromisoformat(repo["last_commit"]) < cutoff:
            flags.append(
                f"{eid}: last commit {repo['last_commit']}, more than {stale_days} days ago"
            )
    org = student.get("org")
    if org:
        last = org.get("last_dated_heading")
        if not org.get("exists"):
            flags.append(f"org: file missing ({org.get('file')})")
        elif last is None:
            flags.append("org: no dated heading found")
        elif dt.date.fromisoformat(last) < cutoff:
            flags.append(f"org: last dated entry {last}, more than {stale_days} days ago")
    drafts = [d for d in student.get("drafts", []) if d.get("exists")]
    if drafts and not any(d.get("changed_since") for d in drafts):
        flags.append("drafts: no draft changed in window")
    for gap in student.get("gaps", []):
        flags.append(f"gap: {gap}")
    return flags


def render(template: str, values: dict[str, str]) -> str:
    missing = sorted(set(PLACEHOLDER_RE.findall(template)) - set(values))
    if missing:
        raise ReportError(f"template placeholders without values: {missing}")
    return PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)


def evidence_table(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "| (none) | | no evidence in window | |"
    lines = []
    for e in evidence:
        lines.append(f"| {e['id']} | {e['type']} | {e['summary']} | {e['locator']} |")
    return "\n".join(lines)


def scores_table(rows: list[dict[str, Any]]) -> str:
    out = []
    for r in rows:
        ids = ", ".join(r["evidence"]) if r["evidence"] else "(none)"
        out.append(f"| {r['label']} | {r['score']} | {ids} | {r['note']} |")
    return "\n".join(out)


def build_report(
    report_data: dict[str, Any],
    scores: dict[str, Any],
    sid: str,
    template: str,
    stale_days: int,
) -> str:
    students = report_data.get("students", {})
    if sid not in students:
        raise ReportError(f"student {sid!r} not in evidence file")
    if sid not in scores:
        raise ReportError(f"student {sid!r} not in scores file")
    student = students[sid]
    evidence_ids = {e["id"] for e in student.get("evidence", [])}
    rows = validate_scores(sid, scores[sid], evidence_ids)
    until = dt.date.fromisoformat(report_data["until"])
    flags = compute_flags(student, until, stale_days)
    agenda = scores[sid].get("agenda") or []
    if isinstance(agenda, str):
        agenda = [agenda]
    values = {
        "student": f"{student.get('name', sid)} ({sid})",
        "programme": str(student.get("programme") or "unknown"),
        "start": str(student.get("start") or "unknown"),
        "since": report_data["since"],
        "until": report_data["until"],
        "reviewer": str(scores[sid].get("reviewer") or "Robert Hoehndorf"),
        "evidence_table": evidence_table(student.get("evidence", [])),
        "scores_table": scores_table(rows),
        "flags": "\n".join(f"- {f}" for f in flags) if flags else "- none",
        "agenda": "\n".join(f"- {a}" for a in agenda) if agenda else "- (to be filled)",
        "generated": dt.date.today().isoformat(),
    }
    return render(template, values)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--evidence", type=Path, help="evidence JSON from collect_evidence.py")
    p.add_argument("--scores", type=Path, help="scores YAML (see --example)")
    p.add_argument("--student", help="student id to render")
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    p.add_argument("--stale-days", type=int, default=21, help="threshold for stale flags")
    p.add_argument("--out", type=Path, default=None, help="write the report here")
    p.add_argument("--example", action="store_true", help="print an example scores file")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.example:
        print(EXAMPLE_SCORES, end="")
        return 0
    if not (args.evidence and args.scores and args.student):
        print("rubric_report: --evidence, --scores and --student are required", file=sys.stderr)
        return 2
    try:
        report_data = json.loads(args.evidence.read_text(encoding="utf-8"))
        scores = load_yaml(args.scores)
        if not args.template.exists():
            raise ReportError(f"template not found: {args.template}")
        text = build_report(
            report_data,
            scores,
            args.student,
            args.template.read_text(encoding="utf-8"),
            args.stale_days,
        )
    except (ReportError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"rubric_report: {exc}", file=sys.stderr)
        return 2
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"rubric_report: wrote {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
