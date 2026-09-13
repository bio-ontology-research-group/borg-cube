#!/usr/bin/env python3
"""Inspect a specific-aims style page for explicit, reviewable properties."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


GAP = re.compile(r"\b(gap|unknown|not understood|unclear|limited|limitation|lack|remains? unknown|remains? unclear)\b", re.IGNORECASE)
MEASURE = re.compile(r"\b(measure|quantif|estimate|compare|test|benchmark|validate|assess|determine|deliver|produce)\w*\b", re.IGNORECASE)
OUTCOME = re.compile(r"\b(success|criterion|threshold|milestone|deliverable|endpoint|accuracy|precision|sensitivity|specificity|increase|decrease|at least|no more than|%)\b|\d", re.IGNORECASE)
FEASIBILITY = re.compile(r"\b(preliminary|pilot|existing|prior|published|our data|we have|access to|expertise|feasib|resource)\b", re.IGNORECASE)
RISK = re.compile(r"\b(risk|challenge|problem|failure|limitation|if .* fail)\b", re.IGNORECASE)
MITIGATION = re.compile(r"\b(mitigat|alternative|fallback|contingen|instead|adapt)\b", re.IGNORECASE)
DEPENDENCY = re.compile(r"\b(depends? on|after|once|upon completion|if aim\s+\d+\s+succeeds?)\b", re.IGNORECASE)
BANNED = ("note that",)


def finding(identifier: str, severity: str, message: str, fix: str) -> dict[str, str]:
    return {"id": identifier, "severity": severity, "message": message, "fix": fix}


def aim_blocks(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"^(?:#{1,6}\s*)?(?:specific\s+)?aim\s+(\d+)\s*[:.\-]?\s*(.*)$", re.IGNORECASE | re.MULTILINE)
    matches = list(pattern.finditer(text))
    blocks: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append({"number": int(match.group(1)), "title": match.group(2).strip(), "text": text[match.start():end].strip()})
    return blocks


def lint_aims(text: str) -> dict[str, Any]:
    """Return heuristic findings, never presenting a prose check as proof."""
    findings: list[dict[str, str]] = []
    aims = aim_blocks(text)
    if not GAP.search(text):
        findings.append(finding("gap:missing", "warning", "no explicit gap or limitation was detected", "State the unmet need or limit of current practice near the opening."))
    if not aims:
        findings.append(finding("aims:missing", "error", "no numbered Aim heading was detected", "Use headings such as 'Aim 1: ...' and 'Aim 2: ...'."))
    numbers = [aim["number"] for aim in aims]
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        findings.append(finding("aims:numbering", "warning", "aim numbers are not consecutive from 1", "Use a clear consecutive numbering scheme for reviewers."))
    for aim in aims:
        prefix = f"aim-{aim['number']}"
        body = aim["text"]
        if not MEASURE.search(body) or not OUTCOME.search(body):
            findings.append(finding(f"{prefix}:outcome", "warning", "no measurable outcome or success criterion was detected", "Name an observable deliverable or measure and the criterion that counts as success."))
        if not FEASIBILITY.search(body):
            findings.append(finding(f"{prefix}:feasibility", "warning", "no feasibility evidence was detected", "Name preliminary evidence, access, prior work, expertise, or a resource that supports the aim."))
        if not RISK.search(body):
            findings.append(finding(f"{prefix}:risk", "warning", "no material risk was detected", "State a material risk and a corresponding mitigation or fallback."))
        elif not MITIGATION.search(body):
            findings.append(finding(f"{prefix}:mitigation", "warning", "a risk was detected without a mitigation or fallback", "Add a credible mitigation, alternative approach, or fallback deliverable."))
        earlier = [number for number in numbers if number < aim["number"]]
        if earlier and DEPENDENCY.search(body):
            findings.append(finding(f"{prefix}:independence", "warning", "sequential-dependency language was detected", "Redesign the aim so it remains valuable if an earlier aim fails, or state a fallback."))
    if "\u2014" in text:
        findings.append(finding("style:em-dash", "error", "contains an em dash", "Use a comma, colon, or separate sentence."))
    for phrase in BANNED:
        if phrase in text.casefold():
            findings.append(finding(f"style:{phrase.replace(' ', '-')}", "warning", f"contains banned phrase '{phrase}'", "State the point directly."))
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match and match.group(1) and match.group(1)[0].islower():
            findings.append(finding(f"style:heading-{line_number}", "warning", "heading starts with lowercase", "Use sentence-case headings."))
    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    return {
        "aims": [{"number": aim["number"], "title": aim["title"]} for aim in aims],
        "findings": findings,
        "summary": {"aims": len(aims), "errors": errors, "warnings": warnings},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True, help="UTF-8 specific-aims text or Markdown")
    parser.add_argument("--strict", action="store_true", help="exit 1 for advisory warnings as well as errors")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = lint_aims(args.draft.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        print(f"aims-lint: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["findings"]:
            print(f"{item['severity'].upper():7} {item['id']}: {item['message']}")
        summary = result["summary"]
        print(f"aims-lint: {summary['aims']} aim(s), {summary['errors']} error(s), {summary['warnings']} warning(s)")
    return 1 if result["summary"]["errors"] or (args.strict and result["summary"]["warnings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
