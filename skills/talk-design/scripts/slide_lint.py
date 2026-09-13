#!/usr/bin/env python3
"""Lint a Beamer or Markdown deck for talk-design checks.

The linter checks content that can be verified from source: assertion titles,
sentence case, em-dashes, density, figure credits, captions, and slide
numbers. It does not judge whether a figure actually proves its title.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


EM_DASH = "\u2014"
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*#*\s*$")
MARKDOWN_NUMBER_RE = re.compile(r"<!--\s*slide\s*:\s*(\d+)\s*-->", re.IGNORECASE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
MARKDOWN_SOURCE_RE = re.compile(
    r"(?:^\s*(?:source|data source|image source)\s*:\s*\S|<!--\s*source\s*:\s*\S)",
    re.IGNORECASE | re.MULTILINE,
)
FRAME_BEGIN_RE = re.compile(r"\\begin\{frame\}(?:\[[^\]]*\])?(?:\{([^{}]*)\})?")
FRAME_END_RE = re.compile(r"\\end\{frame\}")
FRAME_TITLE_RE = re.compile(r"\\frametitle(?:\[[^\]]*\])?\{([^{}]*)\}")
TEX_FIGURE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]+\}")
TEX_CAPTION_RE = re.compile(r"\\(?:caption|captionof|figcaption)(?:\[[^\]]*\])?\{\s*\S")
TEX_SOURCE_RE = re.compile(
    r"(?:\\source(?:\[[^\]]*\])?\{\s*\S|\\(?:cite|citep|citet|footcite|fullcite)(?:\[[^\]]*\])?\{\s*\S|\bsource\s*:\s*\S)",
    re.IGNORECASE,
)
TEX_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?")
COMMENT_RE = re.compile(r"(?<!\\)%.*$")

TOPIC_LABELS = {
    "acknowledgments",
    "analysis",
    "approach",
    "background",
    "conclusion",
    "conclusions",
    "data",
    "dataset",
    "datasets",
    "discussion",
    "experiment",
    "experiments",
    "future work",
    "implementation",
    "introduction",
    "methods",
    "motivation",
    "overview",
    "question",
    "questions",
    "references",
    "results",
    "summary",
    "take-home messages",
}
FINITE_VERBS = {
    "am",
    "are",
    "be",
    "become",
    "becomes",
    "been",
    "being",
    "cause",
    "causes",
    "demonstrate",
    "demonstrates",
    "did",
    "do",
    "does",
    "enable",
    "enables",
    "estimate",
    "estimates",
    "explain",
    "explains",
    "fail",
    "fails",
    "find",
    "finds",
    "has",
    "have",
    "identify",
    "identifies",
    "improve",
    "improves",
    "increase",
    "increases",
    "indicate",
    "indicates",
    "is",
    "lead",
    "leads",
    "matter",
    "matters",
    "match",
    "matches",
    "outperform",
    "outperforms",
    "persist",
    "persists",
    "predict",
    "predicts",
    "provide",
    "provides",
    "reduce",
    "reduces",
    "reveal",
    "reveals",
    "remain",
    "remains",
    "require",
    "requires",
    "show",
    "shows",
    "support",
    "supports",
    "was",
    "were",
    "will",
}


@dataclass
class Issue:
    path: str
    line: int
    severity: str
    rule: str
    message: str
    fix: str


@dataclass
class Slide:
    start_line: int
    title: str
    title_line: int
    lines: list[tuple[int, str]]
    number: int | None = None


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def tex_to_text(text: str) -> str:
    """Return rough visible text while leaving arguments to formatting commands."""
    text = COMMENT_RE.sub("", text)
    text = TEX_FIGURE_RE.sub(" ", text)
    text = TEX_COMMAND_RE.sub(" ", text)
    return re.sub(r"[{}$&~_^\\]", " ", text)


def markdown_slides(lines: list[str]) -> list[Slide]:
    starts: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines, 1):
        match = MARKDOWN_HEADING_RE.match(line)
        if match:
            starts.append((line_no, match.group(2).strip()))
    slides: list[Slide] = []
    for index, (line_no, title) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        preceding = lines[max(0, line_no - 4) : line_no - 1]
        number: int | None = None
        for candidate in reversed(preceding):
            marker = MARKDOWN_NUMBER_RE.search(candidate)
            if marker:
                number = int(marker.group(1))
                break
        slides.append(
            Slide(
                start_line=line_no,
                title=title,
                title_line=line_no,
                lines=[(n, lines[n - 1]) for n in range(line_no, end + 1)],
                number=number,
            )
        )
    return slides


def beamer_slides(lines: list[str]) -> list[Slide]:
    slides: list[Slide] = []
    current: Slide | None = None
    for line_no, line in enumerate(lines, 1):
        code = COMMENT_RE.sub("", line)
        if current is None:
            begin = FRAME_BEGIN_RE.search(code)
            if begin:
                title = begin.group(1) or ""
                current = Slide(line_no, title, line_no if title else 0, [(line_no, line)])
                continue
        else:
            current.lines.append((line_no, line))
            if not current.title:
                title = FRAME_TITLE_RE.search(code)
                if title:
                    current.title = title.group(1).strip()
                    current.title_line = line_no
            if FRAME_END_RE.search(code):
                slides.append(current)
                current = None
    if current is not None:
        slides.append(current)
    return slides


def looks_title_case(title: str) -> bool:
    tokens = words(title)
    if len(tokens) < 3:
        return False
    capitalized = 0
    for word in tokens[1:]:
        if re.fullmatch(r"[A-Z0-9]{2,}", word):
            continue
        if re.fullmatch(r"[A-Z][a-z]+", word):
            capitalized += 1
    return capitalized >= 2


def is_assertion(title: str) -> bool:
    normalized = " ".join(words(title)).lower()
    if normalized in TOPIC_LABELS or len(words(title)) < 4:
        return False
    return any(word.lower() in FINITE_VERBS for word in words(title))


def bullet_items(slide: Slide, deck_type: str) -> list[tuple[int, str]]:
    if deck_type == "markdown":
        return [
            (line_no, re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line))
            for line_no, line in slide.lines
            if re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line)
        ]
    items: list[tuple[int, str]] = []
    for index, (line_no, line) in enumerate(slide.lines):
        if "\\item" not in line:
            continue
        start = line.split("\\item", 1)[1]
        following: list[str] = [start]
        for _, next_line in slide.lines[index + 1 :]:
            if "\\item" in next_line:
                break
            following.append(next_line)
        items.append((line_no, " ".join(following)))
    return items


def body_word_count(slide: Slide, deck_type: str) -> int:
    body: list[str] = []
    for line_no, line in slide.lines:
        if line_no == slide.title_line:
            continue
        if deck_type == "markdown":
            if MARKDOWN_IMAGE_RE.search(line) or MARKDOWN_SOURCE_RE.search(line):
                continue
            if line.strip().startswith("<!--"):
                continue
            body.append(re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line))
        else:
            code = COMMENT_RE.sub("", line)
            if (
                "\\begin{frame}" in code
                or "\\end{frame}" in code
                or FRAME_TITLE_RE.search(code)
                or TEX_FIGURE_RE.search(code)
                or TEX_CAPTION_RE.search(code)
                or TEX_SOURCE_RE.search(code)
            ):
                continue
            body.append(tex_to_text(line))
    return len(words(" ".join(body)))


def figures(slide: Slide, deck_type: str) -> Iterable[tuple[int, bool, bool]]:
    whole = "\n".join(line for _, line in slide.lines)
    if deck_type == "markdown":
        has_source = bool(MARKDOWN_SOURCE_RE.search(whole))
        for line_no, line in slide.lines:
            for figure in MARKDOWN_IMAGE_RE.finditer(line):
                yield line_no, bool(figure.group(1).strip()), has_source
    else:
        whole = "\n".join(COMMENT_RE.sub("", line) for _, line in slide.lines)
        has_caption = bool(TEX_CAPTION_RE.search(whole))
        has_source = bool(TEX_SOURCE_RE.search(whole))
        for line_no, line in slide.lines:
            for _ in TEX_FIGURE_RE.finditer(COMMENT_RE.sub("", line)):
                yield line_no, has_caption, has_source


def add_issue(
    issues: list[Issue],
    path: Path,
    line: int,
    severity: str,
    rule: str,
    message: str,
    fix: str,
) -> None:
    issues.append(Issue(str(path), line, severity, rule, message, fix))


def lint(deck: Path, max_bullets: int, max_bullet_words: int, max_slide_words: int) -> list[Issue]:
    """Return deterministic lint issues for one supported deck source."""
    issues: list[Issue] = []
    if not deck.is_file():
        add_issue(issues, deck, 1, "error", "input", "deck file does not exist", "Pass an existing .tex, .md, or .markdown deck.")
        return issues
    suffix = deck.suffix.lower()
    if suffix not in {".tex", ".md", ".markdown"}:
        add_issue(issues, deck, 1, "error", "input", "unsupported deck type", "Use a Beamer .tex or Markdown .md/.markdown source file.")
        return issues
    try:
        lines = deck.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        add_issue(issues, deck, 1, "error", "input", "deck is not UTF-8 text", "Save the source as UTF-8 text and rerun the linter.")
        return issues

    deck_type = "beamer" if suffix == ".tex" else "markdown"
    slides = beamer_slides(lines) if deck_type == "beamer" else markdown_slides(lines)
    if not slides:
        expected = "\\begin{frame}...\\end{frame}" if deck_type == "beamer" else "a level-one or level-two Markdown heading"
        add_issue(issues, deck, 1, "error", "slides", f"no slides found ({expected})", "Use the documented source convention and rerun.")
        return issues

    if deck_type == "beamer":
        source = "\n".join(COMMENT_RE.sub("", line) for line in lines)
        if "\\insertframenumber" not in source and "frame number" not in source.lower():
            add_issue(issues, deck, 1, "error", "slide-number", "Beamer footline does not show a frame number", "Add \\insertframenumber to the footline or use Beamer's frame-number footline template.")
    else:
        expected_number = 1
        for slide in slides:
            if slide.number is None:
                add_issue(issues, deck, slide.start_line, "error", "slide-number", "slide has no <!-- slide: N --> marker", "Put <!-- slide: N --> immediately before this slide heading.")
            elif slide.number != expected_number:
                add_issue(issues, deck, slide.start_line, "error", "slide-number", f"expected slide number {expected_number}, found {slide.number}", "Use consecutive <!-- slide: N --> markers starting at 1.")
            expected_number += 1

    for slide in slides:
        title = tex_to_text(slide.title).strip() if deck_type == "beamer" else slide.title
        title_line = slide.title_line or slide.start_line
        if not title:
            add_issue(issues, deck, title_line, "error", "assertion-title", "slide has no title", "Add a complete-sentence assertion that the body supports.")
        elif title.rstrip().endswith("?"):
            add_issue(issues, deck, title_line, "error", "assertion-title", f"title is a question: {title!r}", "State the slide's answer as a complete assertion.")
        elif not is_assertion(title):
            add_issue(issues, deck, title_line, "error", "assertion-title", f"title is not a full assertion: {title!r}", "Replace the topic label with a complete sentence that states the slide's takeaway.")
        if title and looks_title_case(title):
            add_issue(issues, deck, title_line, "error", "sentence-case", f"title looks like title case: {title!r}", "Use sentence case, retaining capitals only for proper nouns and acronyms.")

        item_list = bullet_items(slide, deck_type)
        if len(item_list) > max_bullets:
            add_issue(issues, deck, slide.start_line, "warning", "bullet-count", f"slide has {len(item_list)} bullets (threshold {max_bullets})", "Cut, split, or replace the list with visual evidence.")
        for line_no, item in item_list:
            item_text = tex_to_text(item) if deck_type == "beamer" else item
            count = len(words(item_text))
            if count > max_bullet_words:
                add_issue(issues, deck, line_no, "warning", "bullet-words", f"bullet has {count} words (threshold {max_bullet_words})", "Reduce the bullet to a short guidepost or move its explanation into speech.")
        slide_words = body_word_count(slide, deck_type)
        if slide_words > max_slide_words:
            add_issue(issues, deck, slide.start_line, "warning", "slide-words", f"slide has {slide_words} body words (threshold {max_slide_words})", "Cut, split, or replace body text with a labeled visual.")

        for figure_line, has_caption, has_source in figures(slide, deck_type):
            if not has_caption:
                add_issue(issues, deck, figure_line, "error", "figure-caption", "figure has no caption", "Add a concise caption or non-empty Markdown image alt text explaining the figure.")
            if not has_source:
                add_issue(issues, deck, figure_line, "error", "figure-source", "figure has no source", "Add a source credit on this slide, such as 'Source: Author, year, figure N'.")

    for line_no, line in enumerate(lines, 1):
        if EM_DASH in line:
            add_issue(issues, deck, line_no, "error", "em-dash", "contains a U+2014 em-dash", "Replace it with a comma, colon, semicolon, parentheses, or an en-dash for a range.")
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lint a Beamer or Markdown deck for talk-design checks.",
        epilog=(
            "Errors fail the command: assertion titles, sentence case, figure captions and sources, "
            "slide numbers, and em-dashes. Warnings use these density thresholds: at most 4 bullets, "
            "12 words per bullet, and 40 body words per slide. Markdown slides need <!-- slide: N --> "
            "immediately before each level-one or level-two heading."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("deck", type=Path, help="Beamer .tex or Markdown .md/.markdown deck source")
    parser.add_argument("--max-bullets", type=positive_int, default=4, help="warning threshold per slide (default: 4)")
    parser.add_argument("--max-bullet-words", type=positive_int, default=12, help="warning threshold per bullet (default: 12)")
    parser.add_argument("--max-slide-words", type=positive_int, default=40, help="warning threshold for body words per slide (default: 40)")
    parser.add_argument("--json", action="store_true", help="write a JSON report to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    issues = lint(args.deck, args.max_bullets, args.max_bullet_words, args.max_slide_words)
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    if args.json:
        print(
            json.dumps(
                {
                    "deck": str(args.deck),
                    "issues": [asdict(issue) for issue in issues],
                    "summary": {"errors": errors, "warnings": warnings},
                    "thresholds": {
                        "max_bullets": args.max_bullets,
                        "max_bullet_words": args.max_bullet_words,
                        "max_slide_words": args.max_slide_words,
                    },
                },
                indent=2,
            )
        )
    else:
        for issue in issues:
            print(
                f"{issue.path}:{issue.line}: {issue.severity.upper()} [{issue.rule}] "
                f"{issue.message}. Fix: {issue.fix}"
            )
        print(f"slide-lint: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
