#!/usr/bin/env python3
"""Check a drafted response to reviewers against the split comments and the change log.

Inputs:

* ``--comments`` the YAML or JSON file from ``split_reviews.py``;
* ``--response`` the drafted response letter in Markdown, one block per
  comment id (see ``assets/response-letter.md``);
* ``--change-log`` the change log (Markdown table, Markdown list or YAML). If
  omitted, a ``## Change log`` section inside the response is used.

Checks, all of them errors unless marked warning:

* ``missing-response``   a comment id from the split file has no block.
* ``unknown-block``      a block names an id the split file does not contain.
* ``missing-quote``      a block quotes nothing of the reviewer (warning).
* ``quote-mismatch``     a quoted line is not in that comment verbatim.
* ``no-change-statement`` the block neither records a change nor declares that
  nothing changed.
* ``no-location``        a recorded change names no section, figure, table,
  equation or line.
* ``line-basis``         a line reference does not say original or revised.
* ``promise-not-logged`` a recorded change references no change-log entry.
* ``unknown-change-id``  a referenced change-log id is not in the log.
* ``log-unreferenced``   a log entry no block references (warning).
* ``log-unknown-comment`` a log entry is prompted by an unknown comment id.
* ``no-reason``          a refusal or disagreement with no reason and no evidence.
* ``dismissive-tone``    a remark about the reviewer rather than the science.

Exit status is 1 when any error was found, 0 otherwise; ``--strict`` counts
warnings as errors. ``--json`` prints the findings as JSON. The script reads
only; it never submits, uploads or sends anything.

Example:
  response_check.py --comments runs/12/comments.yaml --response runs/12/response.md
  response_check.py --comments c.yaml --response r.md --change-log log.md --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

CHANGE_ID_RE = re.compile(r"\bCL-(\d{1,4})\b")
COMMENT_ID_RE = re.compile(r"\b((?:R[0-9A-Za-z]{1,4}(?:x\d)?|ED)\.\d{1,3})\b")

CHANGE_VERB_RE = re.compile(
    r"\b((?:we|and|then|also)\s+(?:have\s+|now\s+|therefore\s+|since\s+)?"
    r"(?:added|revised|rewrote|rewritten|removed|deleted|replaced|"
    r"clarified|corrected|expanded|shortened|moved|renamed|reran|re-?ran|repeated|"
    r"updated|split|merged|included)|"
    r"(?:we|and|which)\s+now\s+(?:report|state|show|give|list|explain|describe)|"
    r"(?:has|have) been (?:added|revised|rewritten|removed|replaced|clarified|corrected|"
    r"expanded|moved|updated)|the (?:text|section|figure|table|caption) now)\b",
    re.IGNORECASE,
)
NO_CHANGE_RE = re.compile(
    r"\b(no change (?:was |has been )?(?:made|needed)|we (?:have )?(?:made|make) no change|"
    r"we did not change|we have not changed|we leave (?:the|this)|"
    r"we prefer to keep|we kept|we have kept|we retain(?:ed)?)\b",
    re.IGNORECASE,
)
LOCATION_RE = re.compile(
    r"\b(section\s+[0-9A-Z]|sections\s+[0-9A-Z]|subsection|"
    r"fig(?:ure)?s?\.?\s*[0-9A-Z]|table\s+[0-9A-Z]|"
    r"eq(?:uation)?\.?\s*[0-9(]|algorithm\s+\d|"
    r"lines?\s+\d|p(?:age)?\.?\s*\d+,?\s*lines?\s+\d|"
    r"the (?:abstract|introduction|methods|results|discussion|conclusions?|"
    r"related work|appendix|supplement(?:ary material)?)|"
    r"appendix\s+[A-Z0-9]|supplement(?:ary)?\s+(?:figure|table|note|section)\s*[0-9A-Z])\b",
    re.IGNORECASE,
)
LINE_REF_RE = re.compile(r"\blines?\s+\d", re.IGNORECASE)
LINE_BASIS_RE = re.compile(
    r"\b(revised|original|previous|new|current|submitted)\s+(?:manuscript|version|"
    r"submission|draft)|\bof the (?:revised|original)\b|\bin the (?:revised|original)\b",
    re.IGNORECASE,
)
DISAGREE_RE = re.compile(
    r"\b(we disagree|we do not agree|we respectfully disagree|we cannot agree|"
    r"we decline|we (?:have )?(?:chosen )?not to|we did not (?:run|perform|add|include)|"
    r"out of scope|beyond the scope|outside the scope|we cannot|is not possible|"
    r"we believe (?:this|the reviewer) is (?:incorrect|mistaken)|"
    r"this is not (?:correct|the case)|we do not think)\b",
    re.IGNORECASE,
)
EVIDENCE_RE = re.compile(
    r"\b(because|since|as shown|shown in|reported in|the results? (?:show|indicate)|"
    r"our (?:results?|data|experiments?)|we ran|we measured|we computed|we tested|"
    r"p\s*[<=]\s*0|n\s*=\s*\d|accuracy|auc|fig(?:ure)?\.?\s*\d|table\s+\d|"
    r"section\s+[0-9A-Z]|et al\.|\[\d+\]|which would require|the reason is)\b",
    re.IGNORECASE,
)
DISMISSIVE_RE = re.compile(
    r"\b(the reviewer (?:clearly |obviously |apparently |evidently )?"
    r"(?:misunderstand\w*|misread\w*|failed to|did not read|does not understand|"
    r"is confused|is wrong|is mistaken|lacks?)|"
    r"any (?:expert|competent) (?:reader|reviewer)|as anyone (?:familiar|who)|"
    r"this (?:comment|criticism|remark) is (?:irrelevant|absurd|nonsense|meaningless|"
    r"unfounded|misguided|pointless)|nonsense|absurd|"
    r"we are surprised that the reviewer|the reviewer should (?:read|know)|"
    r"trivially (?:wrong|obvious)|obviously (?:wrong|false))\b",
    re.IGNORECASE,
)
CHECK_HELP = {
    "missing-response": "answer every comment; an unanswered point is the top reviewer complaint",
    "quote-mismatch": "quote the reviewer verbatim; edit only whitespace",
    "no-change-statement": "say what changed, or state that nothing changed and why",
    "no-location": "give the section, figure, table, equation or line where the change is",
    "line-basis": "say whether the line numbers are the original or the revised ones",
    "promise-not-logged": "record the change in the change log and reference its id",
    "no-reason": "a disagreement carries evidence and a stated position",
    "dismissive-tone": "write about the science, never about the reviewer",
}


class CheckError(Exception):
    """User-facing failure."""


@dataclass
class Finding:
    level: str  # "error" | "warning"
    check: str
    comment_id: str | None
    message: str
    line: int | None = None


# --------------------------------------------------------------------------- loading


def load_structured(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def comments_index(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict) or "reviewers" not in data:
        raise CheckError("comments file has no 'reviewers' key; run split_reviews.py first")
    index: dict[str, dict[str, Any]] = {}
    for reviewer in data.get("reviewers") or []:
        for comment in reviewer.get("comments") or []:
            cid = comment.get("id")
            if not cid:
                raise CheckError("a comment in the comments file has no id")
            index[cid] = {**comment, "reviewer": reviewer.get("id")}
    if not index:
        raise CheckError("comments file holds no comments")
    return index


def normalize(text: str) -> str:
    """Normalise layout only: a reviewer quotation must retain every character."""
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- response


def split_blocks(response: str, ids: list[str]) -> tuple[dict[str, dict[str, Any]], list[Finding]]:
    """Slice the response into one block per comment id, in file order."""
    lines = response.replace("\r\n", "\n").split("\n")
    starts: list[tuple[int, str]] = []
    findings: list[Finding] = []
    known = set(ids)
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        head = line.strip().lstrip("#").strip().strip("*").strip()
        m = COMMENT_ID_RE.match(head)
        if not m:
            continue
        cid = m.group(1)
        if cid not in known:
            findings.append(
                Finding(
                    "error",
                    "unknown-block",
                    cid,
                    f"block names {cid}, not in the comments file",
                    i + 1,
                )
            )
            continue
        starts.append((i, cid))
    blocks: dict[str, dict[str, Any]] = {}
    for n, (index, cid) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        body = lines[index:end]
        stop = next(
            (
                k
                for k, line in enumerate(body)
                if re.match(r"^\s{0,3}#{1,6}\s*change log\b", line, re.IGNORECASE)
            ),
            None,
        )
        if stop is not None:
            body = body[:stop]
        if cid in blocks:
            findings.append(
                Finding("error", "unknown-block", cid, f"{cid} has more than one block", index + 1)
            )
            continue
        blocks[cid] = {"line": index + 1, "lines": body, "text": "\n".join(body)}
    return blocks, findings


def block_parts(body: list[str]) -> tuple[list[str], str]:
    """Return the quoted reviewer lines and the prose of the response."""
    quotes: list[str] = []
    prose: list[str] = []
    for line in body:
        if line.lstrip().startswith(">"):
            quotes.append(line.lstrip()[1:].strip())
        else:
            prose.append(line)
    return quotes, "\n".join(prose)


def quote_fragments(quotes: list[str]) -> list[str]:
    """Join quoted lines into fragments, cutting at explicit ellipses."""
    joined = " ".join(q for q in quotes if q.strip())
    parts = re.split(r"\[\s*\.\.\.\s*\]|\[\s*…\s*\]|\s\.\.\.\s|\s…\s", joined)
    return [p for p in (part.strip() for part in parts) if len(p) >= 8]


# --------------------------------------------------------------------------- change log


def parse_change_log(text: str) -> dict[str, dict[str, Any]]:
    """Accept a Markdown table, a Markdown list or a YAML mapping/list."""
    stripped = text.strip()
    entries: dict[str, dict[str, Any]] = {}
    if stripped.startswith(("- ", "id:", "changes:", "{")) and "|" not in stripped.split("\n")[0]:
        try:
            data = yaml.safe_load(stripped)
        except yaml.YAMLError:
            data = None
        rows = None
        if isinstance(data, dict) and isinstance(data.get("changes"), list):
            rows = data["changes"]
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            rows = data
        if rows is not None:
            for row in rows:
                cid = str(row.get("id", "")).strip()
                if not CHANGE_ID_RE.fullmatch(cid):
                    continue
                entries[cid] = {
                    "what": str(row.get("what", "")).strip(),
                    "where": str(row.get("where", "")).strip(),
                    "prompted_by": [str(x) for x in (row.get("prompted_by") or [])],
                    "raw": json.dumps(row, ensure_ascii=False, sort_keys=True),
                }
            if entries:
                return entries
    for line in text.replace("\r\n", "\n").split("\n"):
        m = CHANGE_ID_RE.search(line)
        if not m:
            continue
        cid = f"CL-{m.group(1)}"
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if "|" in line else []
        if cells and len(cells) >= 3:
            entries[cid] = {
                "what": cells[1],
                "where": cells[2],
                "prompted_by": COMMENT_ID_RE.findall(" ".join(cells[3:])),
                "raw": line.strip(),
            }
        else:
            rest = line.split(cid, 1)[1].lstrip(" :-\t")
            entries[cid] = {
                "what": rest,
                "where": rest,
                "prompted_by": COMMENT_ID_RE.findall(rest),
                "raw": line.strip(),
            }
    return entries


def change_log_section(response: str) -> str:
    lines = response.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^\s{0,3}#{1,6}\s*change log\b", line, re.IGNORECASE):
            rest = lines[i + 1 :]
            end = next(
                (
                    k
                    for k, later in enumerate(rest)
                    if re.match(r"^\s{0,3}#{1,6}\s+", later)
                    and not re.match(r"^\s{0,3}#{1,6}\s*change log\b", later, re.IGNORECASE)
                ),
                len(rest),
            )
            return "\n".join(rest[:end])
    return ""


# --------------------------------------------------------------------------- checks


def check_response(
    comments: dict[str, dict[str, Any]], response: str, change_log_text: str
) -> list[Finding]:
    findings: list[Finding] = []
    blocks, block_findings = split_blocks(response, list(comments))
    findings.extend(block_findings)
    log = parse_change_log(change_log_text)
    referenced: set[str] = set()

    for cid in comments:
        if cid not in blocks:
            findings.append(
                Finding("error", "missing-response", cid, f"{cid} has no block in the response")
            )
    for cid, block in blocks.items():
        line = block["line"]
        quotes, prose = block_parts(block["lines"])
        source = normalize(comments[cid].get("text", ""))
        fragments = quote_fragments(quotes)
        if not fragments:
            findings.append(
                Finding(
                    "warning",
                    "missing-quote",
                    cid,
                    f"{cid} quotes none of the reviewer's text",
                    line,
                )
            )
        cursor = 0
        for fragment in fragments:
            needle = normalize(fragment)
            at = source.find(needle, cursor)
            if at < 0:
                findings.append(
                    Finding(
                        "error",
                        "quote-mismatch",
                        cid,
                        f"{cid} quotes text that is not in the comment verbatim: {fragment[:60]!r}",
                        line,
                    )
                )
            else:
                cursor = at + len(needle)

        changed = bool(CHANGE_VERB_RE.search(prose))
        unchanged = bool(NO_CHANGE_RE.search(prose))
        if not changed and not unchanged:
            findings.append(
                Finding(
                    "error",
                    "no-change-statement",
                    cid,
                    f"{cid} neither records a change nor states that nothing changed",
                    line,
                )
            )
        if changed:
            if not LOCATION_RE.search(prose):
                findings.append(
                    Finding(
                        "error",
                        "no-location",
                        cid,
                        f"{cid} records a change with no location",
                        line,
                    )
                )
            if LINE_REF_RE.search(prose) and not LINE_BASIS_RE.search(prose):
                findings.append(
                    Finding(
                        "error",
                        "line-basis",
                        cid,
                        f"{cid} gives line numbers without saying original or revised",
                        line,
                    )
                )
            ids = {f"CL-{n}" for n in CHANGE_ID_RE.findall(prose)}
            if not ids:
                findings.append(
                    Finding(
                        "error",
                        "promise-not-logged",
                        cid,
                        f"{cid} promises a change that references no change-log entry",
                        line,
                    )
                )
            for change_id in sorted(ids):
                if change_id not in log:
                    findings.append(
                        Finding(
                            "error",
                            "unknown-change-id",
                            cid,
                            f"{cid} references {change_id}, which the change log does not record",
                            line,
                        )
                    )
                else:
                    referenced.add(change_id)

        if DISMISSIVE_RE.search(prose):
            findings.append(
                Finding(
                    "error",
                    "dismissive-tone",
                    cid,
                    f"{cid} comments on the reviewer rather than the science: "
                    f"{DISMISSIVE_RE.search(prose).group(0)!r}",
                    line,
                )
            )
        if DISAGREE_RE.search(prose) and not EVIDENCE_RE.search(prose):
            findings.append(
                Finding(
                    "error",
                    "no-reason",
                    cid,
                    f"{cid} disagrees or refuses without evidence or a stated reason",
                    line,
                )
            )

    for change_id, entry in sorted(log.items()):
        if change_id not in referenced:
            findings.append(
                Finding(
                    "warning",
                    "log-unreferenced",
                    None,
                    f"{change_id} is in the change log but no response references it",
                )
            )
        for prompted in entry["prompted_by"]:
            if prompted not in comments:
                findings.append(
                    Finding(
                        "error",
                        "log-unknown-comment",
                        prompted,
                        f"{change_id} names {prompted}, which is not a comment id",
                    )
                )
    return findings


def report(findings: list[Finding], comments: dict[str, Any], strict: bool) -> str:
    errors = [f for f in findings if f.level == "error" or (strict and f.level == "warning")]
    warnings = [f for f in findings if f not in errors]
    out = [
        f"response_check: {len(comments)} comments, {len(errors)} errors, {len(warnings)} warnings",
        "",
    ]
    for finding in findings:
        level = "ERROR" if finding in errors else "warning"
        where = f" (response line {finding.line})" if finding.line else ""
        out.append(f"{level} {finding.check}: {finding.message}{where}")
        help_text = CHECK_HELP.get(finding.check)
        if help_text:
            out.append(f"      fix: {help_text}")
    if not findings:
        out.append("no findings; the letter still needs Robert's approval before submission")
    out.append("")
    out.append("This script does not submit anything. Submission is an approval item.")
    return "\n".join(out) + "\n"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--comments", type=Path, help="YAML or JSON from split_reviews.py")
    p.add_argument("--response", type=Path, help="drafted response letter (Markdown)")
    p.add_argument(
        "--change-log",
        type=Path,
        default=None,
        help="change log; default: the response's own section",
    )
    p.add_argument("--json", action="store_true", help="emit findings as JSON")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.comments and args.response):
        print("response_check: --comments and --response are required", file=sys.stderr)
        return 2
    try:
        comments = comments_index(load_structured(args.comments))
        response = args.response.read_text(encoding="utf-8")
        log_text = (
            args.change_log.read_text(encoding="utf-8")
            if args.change_log
            else change_log_section(response)
        )
        findings = check_response(comments, response, log_text)
    except (CheckError, OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"response_check: {exc}", file=sys.stderr)
        return 2
    errors = [f for f in findings if f.level == "error" or (args.strict and f.level == "warning")]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "comments": len(comments),
                    "findings": [asdict(f) for f in findings],
                    "summary": {
                        "errors": len(errors),
                        "warnings": len(findings) - len(errors),
                    },
                    "note": "this script does not submit anything; submission is an approval item",
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        sys.stdout.write(report(findings, comments, args.strict))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
