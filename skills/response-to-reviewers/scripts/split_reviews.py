#!/usr/bin/env python3
"""Split a decision letter into individually numbered reviewer comments.

Reads the decision letter as plain text or Markdown and emits YAML (default)
or JSON with one entry per comment: reviewer, comment id, the verbatim text,
the reviewer's own numbering, and a detected kind (major, minor,
clarification, experiment request, reference request, unclassified).

Recognised reviewer headings: "Reviewer 1", "Reviewer #2", "Referee II",
"Reviewer B", "Editor", "Associate Editor", with or without Markdown hashes,
bold markers or a trailing "(Remarks to the Author)". Recognised comment
numbering: "1.", "1)", "(1)", "1.2", "Comment 3:", "(a)", "a)", and plain
bullets.

The script never guesses. A block that carries no reviewer heading, or that
follows an unrecognised heading, is reported under ``flags`` with its line
range instead of being attributed to a reviewer. A reviewer block with no
numbering at all is split on blank lines and every comment from it is marked
``confidence: low`` and flagged.

Output goes to stdout unless ``--out PATH`` is given. Exit status is 0, or 1
with ``--strict`` when any flag was raised.

Example:
  split_reviews.py --letter runs/12/decision.txt --out runs/12/comments.yaml
  split_reviews.py --letter decision.md --json --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

KINDS = (
    "major",
    "minor",
    "clarification",
    "experiment request",
    "reference request",
    "unclassified",
)

REVIEWER_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?\**\s*(?:reviewer|referee)\s*(?:#|no\.?|number)?\s*"
    r"([0-9]{1,2}|[ivx]{1,4}|[a-z])\b\s*\**\s*[:.)]?\s*(.*)$",
    re.IGNORECASE,
)
EDITOR_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?\**\s*((?:associate |handling |guest |senior )?editor"
    r"(?:'s|s')?)\b\s*\**\s*[:.)]?\s*(.*)$",
    re.IGNORECASE,
)
UNRECOGNISED_REVIEWER_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?\**\s*(?:reviewer|referee)\b", re.IGNORECASE
)
SECTION_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?\**\s*(major|minor|general|specific|detailed|substantive)\s+"
    r"(?:comments?|points?|issues?|concerns?|revisions?|remarks?)\b",
    re.IGNORECASE,
)
BOILERPLATE_RE = re.compile(
    r"remarks? to the author|comments? to the author|recommendation\s*[:.]|"
    r"confidential|reviewer expertise|^\s*$",
    re.IGNORECASE,
)

ITEM_RES: list[tuple[str, re.Pattern[str]]] = [
    ("paren-number", re.compile(r"^(\s{0,3})\((\d{1,3}[a-z]?)\)\s+(\S.*)$")),
    (
        "comment-label",
        re.compile(r"^(\s{0,3})comment\s*(\d{1,3}(?:\.\d{1,3})*)\s*[:.]\s*(\S.*)$", re.I),
    ),
    ("number", re.compile(r"^(\s{0,3})(\d{1,3}(?:\.\d{1,3})*)[.)]\s+(\S.*)$")),
    ("dotted", re.compile(r"^(\s{0,3})(\d{1,3}(?:\.\d{1,3})+)\s+(\S.*)$")),
    ("paren-letter", re.compile(r"^(\s{0,3})\(([a-z])\)\s+(\S.*)$")),
    ("letter", re.compile(r"^(\s{0,3})([a-z])\)\s+(\S.*)$")),
    ("bullet", re.compile(r"^(\s{0,3})([-*•])\s+(\S.*)$")),
]

KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "experiment request",
        re.compile(
            r"\b(ablation|additional experiment|further experiments?|another experiment|"
            r"repeat the experiment|re-?run|rerun|"
            r"please (?:run|perform|carry out|conduct|repeat|test)|"
            r"should (?:be )?(?:run|test|evaluate|benchmark)|"
            r"additional (?:analysis|analyses|simulation)s?|"
            r"compare (?:against|with) (?:a )?baseline|add a baseline|cross-?validat|"
            r"held-?out|new dataset|larger sample)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reference request",
        re.compile(
            r"\b(cite|citation|citations|references?|the authors? (?:should|must) (?:also )?refer|"
            r"related work|prior work|literature (?:review|is|should)|"
            r"missing (?:the )?(?:work|paper)|"
            r"see (?:also )?(?:e\.g\.,?|the work of))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "clarification",
        re.compile(
            r"\b(unclear|not clear|clarif\w*|please (?:explain|define|specify|state)|"
            r"what do the authors mean|it is confusing|confusing|ambiguous|"
            r"cannot tell|hard to follow|define\b|elaborate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "major",
        re.compile(
            r"\b(fundamental\w*|serious\w*|major concern|not convincing|unconvincing|"
            r"invalid|flawed|incorrect|overstat\w*|unsupported|does not support|"
            r"cannot be accepted|the central claim|threatens?|confound\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "minor",
        re.compile(
            r"\b(typo|typographic\w*|grammar|grammatical|spelling|wording|"
            r"figure legend|caption|axis label|font size|formatting|"
            r"page \d+,? line|minor point)\b",
            re.IGNORECASE,
        ),
    ),
]

SECTION_KIND = {"major": "major", "substantive": "major", "minor": "minor"}


class SplitError(Exception):
    """User-facing failure."""


# --------------------------------------------------------------------------- parsing


def reviewer_key(token: str) -> str:
    token = token.strip().lower()
    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
    if token in roman:
        return roman[token]
    return token.upper() if token.isalpha() else token


def find_headings(lines: list[str]) -> list[dict[str, Any]]:
    """Return reviewer and editor headings with their line numbers (1-based)."""
    heads: list[dict[str, Any]] = []
    for i, line in enumerate(lines, 1):
        m = REVIEWER_RE.match(line)
        if m and not ITEM_RES[2][1].match(line):
            key = reviewer_key(m.group(1))
            heads.append(
                {
                    "id": f"R{key}",
                    "label": line.strip().lstrip("#").strip().strip("*").strip(),
                    "line": i,
                    "tail": m.group(2).strip(),
                }
            )
            continue
        m = EDITOR_RE.match(line)
        if m:
            heads.append(
                {
                    "id": "ED",
                    "label": line.strip().lstrip("#").strip().strip("*").strip(),
                    "line": i,
                    "tail": m.group(2).strip(),
                }
            )
    # a heading repeated for the same reviewer keeps its first id but gets a suffix
    seen: dict[str, int] = {}
    for head in heads:
        seen[head["id"]] = seen.get(head["id"], 0) + 1
        if seen[head["id"]] > 1:
            head["id"] = f"{head['id']}x{seen[head['id']]}"
    return heads


def match_item(line: str) -> tuple[str, str, str] | None:
    for style, pattern in ITEM_RES:
        m = pattern.match(line)
        if m:
            return style, m.group(2), m.group(3)
    return None


def detect_kind(text: str, section: str | None) -> tuple[str, str | None]:
    for kind, pattern in KIND_PATTERNS:
        m = pattern.search(text)
        if m:
            return kind, m.group(0).lower()
    if section:
        base = section.split()[0].lower()
        if base in SECTION_KIND:
            return SECTION_KIND[base], f"section:{section}"
    return "unclassified", None


def block_to_comments(
    prefix: str, lines: list[str], first_line: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Split one reviewer block into comments. Returns comments, flags, header note."""
    comments: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []
    section: str | None = None
    current: dict[str, Any] | None = None
    intro: list[tuple[int, str]] = []

    def close(end: int) -> None:
        nonlocal current
        if current is None:
            return
        text = "\n".join(current["_buf"]).strip()
        if text:
            current["text"] = text
            current["lines"] = [current["_start"], end]
            kind, marker = detect_kind(text, current.get("section"))
            current["kind"] = kind
            current["kind_marker"] = marker
            del current["_buf"], current["_start"]
            comments.append(current)
        current = None

    for offset, line in enumerate(lines):
        lineno = first_line + offset
        sec = SECTION_RE.match(line)
        if sec and match_item(line) is None:
            close(lineno - 1)
            section = sec.group(1).lower()
            continue
        item = match_item(line)
        if item is not None:
            close(lineno - 1)
            style, number, rest = item
            current = {
                "id": "",
                "numbering": number,
                "style": style,
                "section": section,
                "confidence": "high",
                "_buf": [rest],
                "_start": lineno,
            }
            continue
        if current is not None:
            current["_buf"].append(line)
        elif line.strip():
            intro.append((lineno, line))
    close(first_line + len(lines) - 1)

    header_note = None
    intro_text = "\n".join(t for _, t in intro).strip()
    if intro_text:
        if BOILERPLATE_RE.search(intro_text) and len(intro_text) <= 200:
            header_note = intro_text
        elif comments:
            comments.insert(
                0,
                {
                    "id": "",
                    "numbering": None,
                    "style": "unnumbered",
                    "section": None,
                    "confidence": "low",
                    "text": intro_text,
                    "lines": [intro[0][0], intro[-1][0]],
                    **dict(
                        zip(
                            ("kind", "kind_marker"),
                            detect_kind(intro_text, None),
                            strict=True,
                        )
                    ),
                },
            )
            flags.append(
                {
                    "level": "low-confidence",
                    "reviewer": prefix,
                    "lines": [intro[0][0], intro[-1][0]],
                    "reason": "text before the first numbered item; check for a separate point",
                }
            )

    if not comments and intro_text:
        # no numbering anywhere in the block: split on blank lines, never silently
        para: list[tuple[int, str]] = []
        paras: list[list[tuple[int, str]]] = []
        for offset, line in enumerate(lines):
            lineno = first_line + offset
            if line.strip():
                para.append((lineno, line))
            elif para:
                paras.append(para)
                para = []
        if para:
            paras.append(para)
        for chunk in paras:
            text = "\n".join(t for _, t in chunk).strip()
            if not text or (BOILERPLATE_RE.search(text) and len(text) <= 200):
                continue
            kind, marker = detect_kind(text, None)
            comments.append(
                {
                    "id": "",
                    "numbering": None,
                    "style": "paragraph",
                    "section": None,
                    "confidence": "low",
                    "text": text,
                    "lines": [chunk[0][0], chunk[-1][0]],
                    "kind": kind,
                    "kind_marker": marker,
                }
            )
        if comments:
            flags.append(
                {
                    "level": "low-confidence",
                    "reviewer": prefix,
                    "lines": [first_line, first_line + len(lines) - 1],
                    "reason": "no numbering found; split on blank lines, needs a human check",
                }
            )
        header_note = None

    for n, comment in enumerate(comments, 1):
        comment["id"] = f"{prefix}.{n}"
    return comments, flags, header_note


def split_letter(text: str, source: str | None = None) -> dict[str, Any]:
    lines = text.replace("\r\n", "\n").split("\n")
    heads = find_headings(lines)
    reviewers: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []

    preamble_lines = lines[: heads[0]["line"] - 1] if heads else lines
    preamble = "\n".join(preamble_lines).strip()
    if preamble and any(match_item(line) for line in preamble_lines):
        flags.append(
            {
                "level": "unattributed",
                "reviewer": None,
                "lines": [1, (heads[0]["line"] - 1) if heads else len(lines)],
                "reason": "numbered items before the first reviewer heading; attribute by hand",
            }
        )
    if not heads:
        flags.append(
            {
                "level": "unattributed",
                "reviewer": None,
                "lines": [1, len(lines)],
                "reason": "no reviewer or editor heading found; the letter is unattributed",
            }
        )
        return {
            "version": 1,
            "generated_by": "split_reviews.py",
            "source": source,
            "preamble": preamble,
            "reviewers": [],
            "comments_total": 0,
            "flags": flags,
        }

    for index, head in enumerate(heads):
        start = head["line"] + 1
        end = heads[index + 1]["line"] - 1 if index + 1 < len(heads) else len(lines)
        block = lines[start - 1 : end]
        unrecognised_offset = next(
            (offset for offset, line in enumerate(block) if UNRECOGNISED_REVIEWER_RE.match(line)),
            None,
        )
        if unrecognised_offset is not None:
            unrecognised_line = start + unrecognised_offset
            unrecognised_end = end
            while unrecognised_end >= unrecognised_line and not lines[unrecognised_end - 1].strip():
                unrecognised_end -= 1
            flags.append(
                {
                    "level": "unattributed",
                    "reviewer": None,
                    "lines": [unrecognised_line, unrecognised_end],
                    "reason": "unrecognised reviewer heading; attribute this block by hand",
                }
            )
            block = block[:unrecognised_offset]
            end = unrecognised_line - 1
        if head["tail"] and not BOILERPLATE_RE.search(head["tail"]):
            block = [head["tail"], *block]
            start = head["line"]
        comments, block_flags, note = block_to_comments(head["id"], block, start)
        flags.extend(block_flags)
        if not comments:
            flags.append(
                {
                    "level": "unattributed",
                    "reviewer": head["id"],
                    "lines": [head["line"], end],
                    "reason": "heading found but no comment text under it",
                }
            )
        reviewers.append(
            {
                "id": head["id"],
                "label": head["label"],
                "heading_line": head["line"],
                "header_note": note,
                "comments": comments,
            }
        )

    total = sum(len(r["comments"]) for r in reviewers)
    return {
        "version": 1,
        "generated_by": "split_reviews.py",
        "source": source,
        "preamble": preamble,
        "reviewers": reviewers,
        "comments_total": total,
        "flags": flags,
    }


# --------------------------------------------------------------------------- output


def render(data: dict[str, Any], as_json: bool) -> str:
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=88)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--letter", type=Path, help="decision letter (.txt or .md); - for stdin")
    p.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    p.add_argument("--json", action="store_true", help="emit JSON instead of YAML")
    p.add_argument("--strict", action="store_true", help="exit 1 when any block was flagged")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.letter is None:
        print("split_reviews: --letter is required", file=sys.stderr)
        return 2
    try:
        if str(args.letter) == "-":
            text, source = sys.stdin.read(), "<stdin>"
        else:
            text, source = args.letter.read_text(encoding="utf-8"), str(args.letter)
        data = split_letter(text, source)
    except (OSError, SplitError, UnicodeDecodeError) as exc:
        print(f"split_reviews: {exc}", file=sys.stderr)
        return 2
    out = render(data, args.json)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"split_reviews: wrote {args.out} ({data['comments_total']} comments)")
    else:
        sys.stdout.write(out)
    for flag in data["flags"]:
        print(
            f"split_reviews: {flag['level']} lines {flag['lines'][0]}-{flag['lines'][1]}: "
            f"{flag['reason']}",
            file=sys.stderr,
        )
    if args.strict and data["flags"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
