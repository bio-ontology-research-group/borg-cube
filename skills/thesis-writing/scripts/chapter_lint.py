#!/usr/bin/env python3
"""Check observable structural signals in a LaTeX or Markdown thesis chapter.

The checker is deliberately conservative: it finds missing structural
evidence, not scientific truth. Findings report file:line, severity, and a
concrete repair. It reads one chapter and never writes to it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    severity: str
    code: str
    message: str
    fix: str


TITLE_CASE_ALLOW = {"KAUST", "PhD", "MS", "LaTeX", "Markdown"}
COMMON_ACRONYMS = {"DNA", "RNA", "CPU", "GPU", "PDF", "HTML", "JSON", "YAML", "KAUST", "PhD", "MS", "LaTeX", "Markdown"}
POSITION_WORDS = re.compile(r"\b(unlike|whereas|however|in contrast|extends|differs|builds on|limits|complement)\b", re.I)
CITATION = re.compile(r"\\(?:cite\w*|autocite)\s*\{|\[@[^\]]+\]|(?<!!)\[[^\]]+\]\([^)]*\)")
CLAIM = re.compile(r"\b(is|are|was|were|shows?|demonstrates?|proves?|improves?|outperforms?|increases?|decreases?|causes?|enables?|requires?|leads to)\b", re.I)
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,8}\b")


def finding(path: Path, line: int, severity: str, code: str, message: str, fix: str) -> Finding:
    return Finding(str(path), line, severity, code, message, fix)


def clean_line(line: str) -> str:
    return re.sub(r"(?<!\\)%.*$", "", line).strip()


def heading_title_case(text: str) -> bool:
    words = re.sub(r"[`*_#:]", "", text).split()
    return len(words) > 1 and any(word[:1].isupper() and word not in TITLE_CASE_ALLOW for word in words[1:])


def latex_environments(lines: list[str], environment: str) -> list[tuple[int, int, str | None]]:
    found: list[tuple[int, int, str | None]] = []
    begin = re.compile(rf"\\begin\{{{environment}\}}")
    end = re.compile(rf"\\end\{{{environment}\}}")
    label = re.compile(r"\\label\{([^}]+)\}")
    start: int | None = None
    current_label: str | None = None
    for number, raw in enumerate(lines, 1):
        if begin.search(raw):
            start, current_label = number, None
        if start is not None:
            match = label.search(raw)
            if match:
                current_label = match.group(1)
        if start is not None and end.search(raw):
            found.append((start, number, current_label))
            start, current_label = None, None
    if start is not None:
        found.append((start, len(lines), current_label))
    return found


def check_figures_and_tables(path: Path, lines: list[str], findings: list[Finding]) -> None:
    whole = "\n".join(lines)
    for environment, kind in (("figure", "figure"), ("table", "table")):
        for start, end, label in latex_environments(lines, environment):
            if not label:
                findings.append(finding(path, start, "error", f"{kind}-label", f"{kind.title()} has no \\label.", f"Add a stable label such as \\label{{{kind}:meaningful-name}} inside the {kind} environment."))
                continue
            references = re.findall(rf"\\(?:ref|autoref|cref|Cref)\{{{re.escape(label)}\}}", whole)
            if not references:
                findings.append(finding(path, start, "error", f"{kind}-reference", f"{kind.title()} label {label!r} is never referenced in prose.", f"Discuss the {kind} in the text with \\ref{{{label}}}."))
        markdown_kind = "fig" if kind == "figure" else "tbl"
        md_labels: list[tuple[int, str]] = []
        for number, raw in enumerate(lines, 1):
            if kind == "figure" and re.search(r"!\[[^]]*\]\([^)]*\)", raw):
                match = re.search(r"\{#(fig:[^}]+)\}", raw)
                if not match:
                    findings.append(finding(path, number, "error", "figure-label", "Markdown figure has no {#fig:...} identifier.", "Add a Pandoc or Quarto figure identifier and refer to it with @fig:... in prose."))
                else:
                    md_labels.append((number, match.group(1)))
            if kind == "table" and re.match(r"\s*Table:\s+", raw, re.I):
                match = re.search(r"\{#(tbl:[^}]+)\}", raw)
                if not match:
                    findings.append(finding(path, number, "error", "table-label", "Markdown table caption has no {#tbl:...} identifier.", "Add a table identifier and refer to it with @tbl:... in prose."))
                else:
                    md_labels.append((number, match.group(1)))
        for number, label in md_labels:
            if f"@{label}" not in whole:
                findings.append(finding(path, number, "error", f"{kind}-reference", f"{kind.title()} label {label!r} is never referenced in prose.", f"Discuss the {kind} with @{label}."))


def check_contribution_and_related_work(path: Path, lines: list[str], findings: list[Finding]) -> None:
    headings: list[tuple[int, str]] = []
    for number, raw in enumerate(lines, 1):
        latex = re.search(r"\\(?:chapter|section|subsection)\*?\{([^}]+)\}", raw)
        markdown = re.match(r"^#{1,6}\s+(.+)$", raw)
        text = latex.group(1) if latex else markdown.group(1) if markdown else None
        if text:
            headings.append((number, text))
            if heading_title_case(text):
                findings.append(finding(path, number, "error", "sentence-case-heading", f"Heading {text!r} appears to use title case.", "Use sentence case unless a proper name requires capitals."))
    body = "\n".join(lines)
    contribution = re.search(r"\b(this chapter|chapter \d+).{0,100}\b(contribut|establish|show|demonstrat|argue)\b|\bcontribution(s)?\b", body, re.I)
    if not contribution:
        findings.append(finding(path, 1, "error", "chapter-contribution", "No explicit chapter contribution was found.", "State what this chapter contributes near its opening, using a sentence such as 'This chapter establishes ...'."))
    related_positions = [i for i, (_, heading) in enumerate(headings) if re.search(r"related work|literature review", heading, re.I)]
    if not related_positions:
        findings.append(finding(path, 1, "error", "related-work-section", "No related-work or literature-review section was found.", "Add a section that positions the chapter's contribution against the relevant literature."))
        return
    index = related_positions[0]
    start_line = headings[index][0]
    end_line = headings[index + 1][0] - 1 if index + 1 < len(headings) else len(lines)
    section = "\n".join(lines[start_line - 1:end_line])
    if not CITATION.search(section):
        findings.append(finding(path, start_line, "error", "related-work-citations", "Related work contains no citation signal.", "Cite the work being positioned and verify each citation against the original source."))
    if not POSITION_WORDS.search(section):
        findings.append(finding(path, start_line, "error", "related-work-positioning", "Related work appears to list sources without a comparison signal.", "Explain how prior work differs from, supports, limits, or leaves the gap for this chapter."))


def check_acronyms_and_notation(path: Path, lines: list[str], findings: list[Finding]) -> None:
    defined: set[str] = set()
    used: dict[str, list[int]] = {}
    macros: dict[str, tuple[int, str]] = {}
    for number, raw in enumerate(lines, 1):
        for match in re.finditer(r"\b(?:[A-Za-z][A-Za-z-]*\s+){1,8}\(([A-Z][A-Z0-9]{1,8})\)", raw):
            defined.add(match.group(1))
        for match in re.finditer(r"\\newacronym\{[^}]+\}\{([A-Z][A-Z0-9]{1,8})\}", raw):
            defined.add(match.group(1))
        for acronym in ACRONYM.findall(raw):
            if acronym not in COMMON_ACRONYMS:
                used.setdefault(acronym, []).append(number)
        macro = re.search(r"\\(?:newcommand|renewcommand)\{(\\[A-Za-z]+)\}\{([^}]*)\}", raw)
        if macro:
            name, value = macro.groups()
            previous = macros.get(name)
            if previous and previous[1] != value:
                findings.append(finding(path, number, "error", "inconsistent-notation", f"Macro {name} is redefined from {previous[1]!r} to {value!r}.", "Use one macro definition for one concept, or explain a deliberate change in notation."))
            macros[name] = (number, value)
    for acronym, numbers in used.items():
        if len(numbers) >= 2 and acronym not in defined:
            findings.append(finding(path, numbers[0], "error", "undefined-acronym", f"Acronym {acronym} is used repeatedly without a detected definition.", f"Define {acronym} at first use, for example 'long form ({acronym})'."))
    math_defined: set[str] = set()
    math_used: dict[str, int] = {}
    for number, raw in enumerate(lines, 1):
        for expression in re.findall(r"\$([^$]+)\$", raw):
            symbols = re.findall(r"\\[A-Za-z]+|\b[A-Za-z](?:_[A-Za-z0-9]+)?\b", expression)
            for symbol in symbols:
                if symbol in {"text", "ref"}:
                    continue
                math_used.setdefault(symbol, number)
                if re.search(r"\b(let|where|denotes?|defined as)\b", raw, re.I):
                    math_defined.add(symbol)
    for symbol, number in math_used.items():
        if symbol not in math_defined:
            findings.append(finding(path, number, "error", "undefined-notation", f"Mathematical symbol {symbol!r} has no detected definition.", f"Define {symbol} in prose at or before its first use, for example 'Let ${symbol}$ denote ...'."))


def check_claims_and_style(path: Path, lines: list[str], findings: list[Finding]) -> None:
    for number, raw in enumerate(lines, 1):
        line = clean_line(raw)
        if "—" in raw:
            findings.append(finding(path, number, "error", "em-dash", "U+2014 em dash found.", "Use a comma, colon, parentheses, or separate sentence."))
        if re.search(r"\bNote that\b", line, re.I):
            findings.append(finding(path, number, "error", "note-that", "Banned filler phrase 'Note that' found.", "State the point directly."))
        if re.search(r"\b(colour|organisation|analyse)\b", line, re.I):
            findings.append(finding(path, number, "warning", "american-english", "Possible non-American house-style spelling found.", "Use the project house style or document an intentional quoted spelling."))
        if not line or line.startswith(("%", "#", "\\", "|", "![")) or "\\caption" in line:
            continue
        if CLAIM.search(line) and not CITATION.search(line) and not re.search(r"\bThis chapter\b", line, re.I):
            findings.append(finding(path, number, "error", "uncited-claim", "Claim-like sentence has no citation signal.", "Cite the source supporting the factual or methodological claim, or rewrite it as this chapter's stated contribution."))


def lint(path: Path) -> list[Finding]:
    if not path.is_file():
        raise ValueError(f"chapter not found: {path}")
    if path.suffix.lower() not in {".tex", ".md", ".markdown"}:
        raise ValueError("chapter must be LaTeX (.tex) or Markdown (.md, .markdown)")
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[Finding] = []
    check_contribution_and_related_work(path, lines, findings)
    check_figures_and_tables(path, lines, findings)
    check_acronyms_and_notation(path, lines, findings)
    check_claims_and_style(path, lines, findings)
    return sorted(findings, key=lambda item: (item.line, item.severity, item.code))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("chapter", type=Path, help="LaTeX or Markdown chapter source")
    p.add_argument("--json", action="store_true", help="emit findings as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        findings = lint(args.chapter)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"chapter-lint: error: {exc}", file=sys.stderr)
        return 2
    errors = [item for item in findings if item.severity == "error"]
    if args.json:
        print(json.dumps({"findings": [asdict(item) for item in findings], "errors": len(errors)}, indent=2))
    else:
        for item in findings:
            print(f"{item.path}:{item.line}: {item.severity}: {item.code}: {item.message} Fix: {item.fix}")
        print(f"chapter-lint: {len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
