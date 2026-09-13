#!/usr/bin/env python3
"""Collect progress evidence for one or more students into JSON.

Reads a ``students.yaml`` mapping (see ``assets/students.yaml.example``) and,
for every selected student, gathers three kinds of evidence since a date:

* git activity per configured repository: commits by the student's author
  names or emails, files touched, insertions and deletions, last commit date,
  and the commit subjects (capped);
* dated headings in the student's org file (``* 6 November 2023, topic``,
  ``** 13 Nov 2024``, ``* <2026-05-11 Mon> ...``), with the number of open
  ``- [ ]`` items under each;
* drafts (paths or globs): word count and modification date, with a flag for
  files changed since the date.

Every item receives a stable evidence id (``<student>-git-01``,
``<student>-org-02``, ``<student>-draft-01``) that ``rubric_report.py``
requires next to every score. The script only reads; it never contacts anyone,
never reads grades, contracts or HR files, and reports missing paths as
evidence gaps instead of failing.

Example:
  collect_evidence.py --students students.yaml --student alex --since 2026-08-01
  collect_evidence.py --students students.yaml --since 2026-08-01 --out runs/9/evidence.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

HEADING_RE = re.compile(r"^(\*+)\s+(.*?)\s*(?::[\w:]+:)?\s*$")
ISO_RE = re.compile(r"[<\[]?(\d{4})-(\d{2})-(\d{2})")
DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?(?:,?\s+(\d{4}))?\b",
)
MONTH_DAY_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?\b")
CHECKBOX_OPEN_RE = re.compile(r"^\s*[-+*]\s+\[ \]\s+")
CHECKBOX_DONE_RE = re.compile(r"^\s*[-+*]\s+\[[xX]\]\s+")
TEXT_ARG_CMDS = (
    "emph|textbf|textit|texttt|textsc|text|underline|"
    "chapter|section|subsection|subsubsection|paragraph|caption|title|footnote"
)
# Commands whose braced argument is prose: keep the argument, drop the command.
LATEX_TEXT_CMD_RE = re.compile(r"\\(?:" + TEXT_ARG_CMDS + r")\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
LATEX_CMD_RE = re.compile(r"\\[A-Za-z@]+\*?(\[[^\]]*\])?(\{[^{}]*\})?")
COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
MAX_SUBJECTS = 25


class EvidenceError(Exception):
    """User-facing failure (bad config, unreadable file)."""


# --------------------------------------------------------------------------- config


def load_students(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise EvidenceError(f"students file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    students = data.get("students") if isinstance(data, dict) else None
    if not isinstance(students, dict) or not students:
        raise EvidenceError(f"{path} must contain a non-empty 'students' mapping")
    for sid, entry in students.items():
        if not isinstance(entry, dict):
            raise EvidenceError(f"student {sid!r} must be a mapping")
        for key in ("repos", "drafts", "git_authors"):
            value = entry.get(key) or []
            if isinstance(value, str):
                value = [value]
            entry[key] = [str(v) for v in value]
    return students


def expand(path_str: str, org_root: Path | None = None) -> Path:
    p = Path(path_str).expanduser()
    if org_root is not None and not p.is_absolute() and path_str.endswith(".org"):
        p = org_root / p
    return p


# --------------------------------------------------------------------------- git


def _git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        raise EvidenceError(f"git {' '.join(args[:2])} failed in {repo}: {proc.stderr.strip()}")
    return proc.stdout


def git_evidence(repo: Path, since: dt.date, until: dt.date, authors: list[str]) -> dict[str, Any]:
    """Summarise commits in ``repo`` between the dates, optionally by author."""
    result: dict[str, Any] = {
        "repo": str(repo),
        "exists": repo.is_dir() and (repo / ".git").exists(),
        "commits": 0,
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
        "last_commit": None,
        "subjects": [],
        "authors_seen": [],
        "filtered_by_author": bool(authors),
    }
    if not result["exists"]:
        result["error"] = "not a git repository"
        return result
    fmt = "--format=@@%H\t%aI\t%an\t%ae\t%s"
    args = [
        "log",
        f"--since={since.isoformat()}",
        f"--until={(until + dt.timedelta(days=1)).isoformat()}",
        "--numstat",
        "--no-merges",
        fmt,
    ]
    for author in authors:
        args.append(f"--author={author}")
    try:
        out = _git(repo, args)
    except EvidenceError as exc:
        result["error"] = str(exc)
        return result
    files: set[str] = set()
    seen_authors: set[str] = set()
    last: str | None = None
    for line in out.splitlines():
        if line.startswith("@@"):
            _, when, name, email, subject = line[2:].split("\t", 4)
            result["commits"] += 1
            seen_authors.add(f"{name} <{email}>")
            if last is None or when > last:
                last = when
            if len(result["subjects"]) < MAX_SUBJECTS:
                result["subjects"].append(subject)
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            ins, dele, fname = parts
            files.add(fname)
            if ins.isdigit():
                result["insertions"] += int(ins)
            if dele.isdigit():
                result["deletions"] += int(dele)
    result["files_changed"] = len(files)
    result["last_commit"] = last[:10] if last else None
    result["authors_seen"] = sorted(seen_authors)
    return result


# --------------------------------------------------------------------------- org


def parse_heading_date(text: str) -> dt.date | None:
    """Extract a date from an org heading; None when there is none or no year."""
    m = ISO_RE.search(text)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = DAY_MONTH_RE.search(text)
    if m and m.group(2).lower() in MONTHS and m.group(3):
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    m = MONTH_DAY_RE.search(text)
    if m and m.group(1).lower() in MONTHS and m.group(3):
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


def org_evidence(path: Path, since: dt.date, until: dt.date) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(path),
        "exists": path.is_file(),
        "headings": [],
        "undated_headings": 0,
        "last_dated_heading": None,
        "open_items_total": 0,
    }
    if not result["exists"]:
        result["error"] = "org file not found"
        return result
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    current: dict[str, Any] | None = None
    latest: dt.date | None = None
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            title = m.group(2)
            when = parse_heading_date(title)
            current = None
            if when is None:
                if re.search(r"\d", title):
                    result["undated_headings"] += 1
                continue
            if latest is None or when > latest:
                latest = when
            if since <= when <= until:
                current = {
                    "line": i,
                    "level": len(m.group(1)),
                    "date": when.isoformat(),
                    "title": title,
                    "open_items": 0,
                    "done_items": 0,
                }
                result["headings"].append(current)
            continue
        if current is not None:
            if CHECKBOX_OPEN_RE.match(line):
                current["open_items"] += 1
                result["open_items_total"] += 1
            elif CHECKBOX_DONE_RE.match(line):
                current["done_items"] += 1
    result["last_dated_heading"] = latest.isoformat() if latest else None
    return result


# --------------------------------------------------------------------------- drafts


def word_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".tex":
        text = COMMENT_RE.sub("", text)
        text = LATEX_TEXT_CMD_RE.sub(r" \1 ", text)
        text = LATEX_CMD_RE.sub(" ", text)
        text = re.sub(r"[{}$\\]", " ", text)
    return len(re.findall(r"\b[\w'-]+\b", text))


def draft_evidence(pattern: str, since: dt.date, until: dt.date) -> list[dict[str, Any]]:
    p = Path(pattern).expanduser()
    if any(ch in pattern for ch in "*?["):
        base = Path(p.anchor) if p.is_absolute() else Path(".")
        rel = str(p.relative_to(base)) if p.is_absolute() else str(p)
        matches = sorted(base.glob(rel))
    else:
        matches = [p]
    out: list[dict[str, Any]] = []
    if not matches:
        out.append({"file": pattern, "exists": False, "error": "no file matches"})
        return out
    for f in matches:
        if not f.is_file():
            out.append({"file": str(f), "exists": False, "error": "draft not found"})
            continue
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime).date()
        out.append(
            {
                "file": str(f),
                "exists": True,
                "words": word_count(f),
                "modified": mtime.isoformat(),
                "changed_since": since <= mtime <= until,
            }
        )
    return out


# --------------------------------------------------------------------------- assembly


def collect_student(
    sid: str,
    entry: dict[str, Any],
    since: dt.date,
    until: dt.date,
    org_root: Path | None,
) -> dict[str, Any]:
    repos = [
        git_evidence(expand(r), since, until, entry.get("git_authors", []))
        for r in entry.get("repos", [])
    ]
    org_path = entry.get("org")
    org = org_evidence(expand(org_path, org_root), since, until) if org_path else None
    drafts: list[dict[str, Any]] = []
    for pattern in entry.get("drafts", []):
        drafts.extend(draft_evidence(pattern, since, until))

    evidence: list[dict[str, Any]] = []
    gaps: list[str] = []
    n = 0
    for repo in repos:
        n += 1
        eid = f"{sid}-git-{n:02d}"
        repo["evidence_id"] = eid
        if not repo["exists"] or repo.get("error"):
            gaps.append(f"{eid}: {repo['repo']}: {repo.get('error', 'unreadable')}")
            continue
        evidence.append(
            {
                "id": eid,
                "type": "git",
                "locator": repo["repo"],
                "summary": (
                    f"{repo['commits']} commits, {repo['files_changed']} files, "
                    f"+{repo['insertions']}/-{repo['deletions']}, last {repo['last_commit']}"
                ),
            }
        )
    if org is not None:
        if not org["exists"]:
            gaps.append(f"{sid}-org: {org['file']}: {org.get('error')}")
        for k, h in enumerate(org["headings"], 1):
            eid = f"{sid}-org-{k:02d}"
            h["evidence_id"] = eid
            evidence.append(
                {
                    "id": eid,
                    "type": "org",
                    "locator": f"{org['file']}:{h['line']}",
                    "summary": f"{h['date']} {h['title']} ({h['open_items']} open items)",
                }
            )
    for k, d in enumerate(drafts, 1):
        eid = f"{sid}-draft-{k:02d}"
        d["evidence_id"] = eid
        if not d.get("exists"):
            gaps.append(f"{eid}: {d['file']}: {d.get('error')}")
            continue
        evidence.append(
            {
                "id": eid,
                "type": "draft",
                "locator": d["file"],
                "summary": f"{d['words']} words, modified {d['modified']}"
                + (" (changed in window)" if d["changed_since"] else " (unchanged)"),
            }
        )
    return {
        "name": entry.get("name", sid),
        "programme": entry.get("programme"),
        "start": str(entry["start"]) if entry.get("start") else None,
        "repos": repos,
        "org": org,
        "drafts": drafts,
        "evidence": evidence,
        "gaps": gaps,
    }


def collect(
    students: dict[str, dict[str, Any]],
    selected: list[str],
    since: dt.date,
    until: dt.date,
    org_root: Path | None = None,
) -> dict[str, Any]:
    unknown = [s for s in selected if s not in students]
    if unknown:
        raise EvidenceError(f"unknown student id(s): {unknown}")
    ids = selected or sorted(students)
    return {
        "generated": dt.date.today().isoformat(),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "privacy": "local-only",
        "students": {
            sid: collect_student(sid, students[sid], since, until, org_root) for sid in ids
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Evidence {report['since']} to {report['until']} (privacy: local-only)", ""]
    for sid, s in report["students"].items():
        lines.append(f"## {s['name']} ({sid})")
        lines.append("")
        lines.append("| Id | Type | Summary | Locator |")
        lines.append("| --- | --- | --- | --- |")
        for e in s["evidence"]:
            lines.append(f"| {e['id']} | {e['type']} | {e['summary']} | {e['locator']} |")
        if not s["evidence"]:
            lines.append("| (none) | | no evidence in window | |")
        if s["gaps"]:
            lines.append("")
            lines.append("Gaps:")
            lines.extend(f"- {g}" for g in s["gaps"])
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--students", type=Path, required=True, help="students.yaml mapping")
    p.add_argument(
        "--student", action="append", default=[], help="student id to include (repeatable)"
    )
    p.add_argument("--since", type=dt.date.fromisoformat, required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--until", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD (default today)"
    )
    p.add_argument("--org-root", type=Path, default=None, help="directory for relative org paths")
    p.add_argument("--format", choices=["json", "md"], default="json")
    p.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    until = args.until or dt.date.today()
    try:
        students = load_students(args.students)
        report = collect(students, args.student, args.since, until, args.org_root)
    except EvidenceError as exc:
        print(f"collect_evidence: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) if args.format == "json" else render_markdown(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"collect_evidence: wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
