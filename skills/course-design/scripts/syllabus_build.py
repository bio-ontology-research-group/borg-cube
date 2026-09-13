#!/usr/bin/env python3
"""Render a KAUST-shaped syllabus from the course YAML in Markdown, Org and PDF.

The same YAML that alignment_matrix.py checks is filled into
assets/syllabus-template.md (placeholders in double braces). The Markdown is
converted to Org by a small deterministic converter, and to PDF with pandoc
(preferred) or, failing that, latexmk on a minimal LaTeX rendering. When
neither tool is on PATH the script says so and still writes the other
formats.

The alignment check runs first; a design error stops the build (exit 2), so a
syllabus is never published for a course whose outcomes are not all assessed.
Use --skip-alignment only to preview a draft.

Without --out the Markdown goes to stdout. With --out inside this repository
the files are written. With --out outside the repository the script only
prints what it would write unless --apply is given.

Examples:
  syllabus_build.py --course assets/course.yaml.example
  syllabus_build.py --course state/courses/cs3xx.yaml --out runs/cs3xx --formats md,org,pdf
  syllabus_build.py --course c.yaml --out ~/teaching/cs3xx --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

import alignment_matrix as am

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent / "assets" / "syllabus-template.md"
REPO_ROOT = HERE.parents[2]
FORMATS = ("md", "org", "pdf")
PLACEHOLDER_RE = re.compile(r"\{\{([a-z_]+)\}\}")


class BuildError(Exception):
    pass


# ----------------------------------------------------------------- rendering


def _bullets(items: Any, empty: str = "None stated.") -> str:
    items = am.as_list(items)
    if not items:
        return empty
    return "\n".join(f"- {str(i).strip()}" for i in items)


def _table(header: list[str], rows: list[list[str]]) -> str:
    def clean(cell: Any) -> str:
        return str(cell if cell is not None else "").replace("|", "\\|").replace("\n", " ").strip()

    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(clean(c) for c in row) + " |")
    return "\n".join(lines)


def _instructor_block(course: dict[str, Any]) -> str:
    ins = course.get("instructor") or {}
    lines = []
    if isinstance(ins, dict):
        if ins.get("name"):
            lines.append(f"Instructor: {ins['name']}")
        if ins.get("email"):
            lines.append(f"Email: {ins['email']}")
        if ins.get("office"):
            lines.append(f"Office: {ins['office']}")
        if ins.get("office_hours"):
            lines.append(f"Office hours: {ins['office_hours']}")
    else:
        lines.append(f"Instructor: {ins}")
    tas = am.as_list(course.get("teaching_assistants"))
    if tas:
        names = []
        for ta in tas:
            if isinstance(ta, dict):
                names.append(", ".join(str(v) for v in ta.values() if v))
            else:
                names.append(str(ta))
        lines.append("Teaching assistants: " + "; ".join(names))
    return "  \n".join(lines) if lines else "Instructor: to be confirmed"


def _outcomes_table(result: dict[str, Any]) -> str:
    rows = []
    for o in result["outcomes"]:
        rows.append(
            [
                o["id"],
                o["text"],
                o["level"],
                ", ".join(o["assessed_by"]) or "none",
            ]
        )
    return _table(["Id", "Outcome", "Level", "Assessed by"], rows)


def _assessments_table(result: dict[str, Any], data: dict[str, Any]) -> str:
    by_id = {a["id"]: a for a in am.as_list(data.get("assessments"))}
    rows = []
    for a in result["assessments"]:
        raw = by_id.get(a["id"], {})
        due = ", ".join(str(w) for w in a["weeks"]) or "see plan"
        rows.append(
            [
                a["id"],
                a["title"] or "",
                raw.get("kind", ""),
                ", ".join(a["tests"]),
                f"{a['weight']}%",
                due,
                raw.get("grading", ""),
            ]
        )
    return _table(["Id", "Assessment", "Kind", "Outcomes", "Weight", "Due week", "Graded by"], rows)


def _specifications_block(data: dict[str, Any]) -> str:
    parts = []
    for a in am.as_list(data.get("assessments")):
        spec = am.as_list(a.get("specification"))
        if not spec:
            continue
        parts.append(f"### Specification for {a['id']}: {a.get('title', '')}".rstrip())
        parts.append("")
        parts.append("Pass requires every item:")
        parts.append("")
        parts.append("\n".join(f"- {s}" for s in spec))
        parts.append("")
    if not parts:
        return "Specifications for graded work are published with each task."
    return "\n".join(parts).rstrip()


def _grading_block(course: dict[str, Any]) -> str:
    g = course.get("grading") or {}
    lines = []
    scheme = g.get("scheme")
    if scheme:
        lines.append(f"Grading scheme: {scheme}.")
    if g.get("minimum_for_credit"):
        lines.append(
            f"The KAUST program guide sets {g['minimum_for_credit']} as the minimum grade for "
            "course credit; a 300-level course grade may also count toward the CS qualifier."
        )
    scale = am.as_list(g.get("scale"))
    if scale:
        lines.append("")
        lines.append("Letter grades (percentage thresholds, confirm against the registrar's grading policy):")
        lines.append("")
        lines.append(_table(["Grade", "Minimum"], [[s.get("grade", ""), s.get("min", "")] for s in scale]))
    bundles = am.as_list(g.get("bundles"))
    if bundles:
        lines.append("")
        lines.append("Specification bundles (which set of passed items earns which grade):")
        lines.append("")
        lines.append(
            _table(["Grade", "Requires"], [[b.get("grade", ""), b.get("requires", "")] for b in bundles])
        )
    return "\n".join(lines) if lines else "Grading is described with each assessment."


def _schedule_table(data: dict[str, Any]) -> str:
    acts = {a["id"]: a for a in am.as_list(data.get("activities"))}
    asses = {a["id"]: a for a in am.as_list(data.get("assessments"))}
    rows = []
    for w in am.as_list(data.get("weeks")):
        act_titles = []
        for tid in am.as_list(w.get("activities")):
            a = acts.get(str(tid))
            act_titles.append(a.get("title", str(tid)) if a else str(tid))
        due = []
        for aid in am.as_list(w.get("due")):
            a = asses.get(str(aid))
            due.append(f"{aid}: {a.get('title', '')}" if a else str(aid))
        rows.append(
            [
                w.get("week", ""),
                w.get("topic", ""),
                "; ".join(act_titles),
                w.get("reading", ""),
                "; ".join(due),
            ]
        )
    if not rows:
        return "The week plan is published before the first class."
    return _table(["Week", "Topic", "Activities", "Preparation", "Due"], rows)


def _policies_block(course: dict[str, Any]) -> str:
    pol = course.get("policies") or {}
    if not isinstance(pol, dict) or not pol:
        return "Course policies follow the KAUST academic policies."
    labels = {
        "attendance": "Attendance",
        "integrity": "Academic integrity",
        "late_work": "Late work and tokens",
        "accommodation": "Accommodation",
        "ai_use": "Use of generative AI",
        "communication": "Communication",
    }
    lines = []
    for key, text in pol.items():
        label = labels.get(key, key.replace("_", " ").capitalize())
        lines.append(f"**{label}.** {str(text).strip()}")
    return "\n\n".join(lines)


def _fair_block(course: dict[str, Any]) -> str:
    fair = course.get("fair") or {}
    if not fair:
        return "Materials are shared in editable form under an open license; details with the first class."
    lines = []
    if fair.get("license"):
        lines.append(f"License: {fair['license']}")
    if fair.get("repository"):
        lines.append(f"Repository: {fair['repository']}")
    if fair.get("citation"):
        lines.append(f"Cite as: {fair['citation']}")
    if fair.get("identifier"):
        lines.append(f"Identifier: {fair['identifier']}")
    kws = am.as_list(fair.get("keywords"))
    if kws:
        lines.append("Keywords: " + ", ".join(str(k) for k in kws))
    if fair.get("last_revision"):
        lines.append(f"Last revision: {fair['last_revision']}")
    lines.append(
        "Sources of all PDFs are published alongside them. Student work, grades and recordings "
        "are never part of the shared materials."
    )
    return "  \n".join(lines)


def build_context(data: dict[str, Any], result: dict[str, Any], source: Path) -> dict[str, str]:
    course = data.get("course") or {}
    return {
        "code": str(course.get("code", "")),
        "title": str(course.get("title", "")),
        "semester": str(course.get("semester", "")),
        "credits": str(course.get("credits", "")),
        "level": str(course.get("level", "")),
        "meetings": str(course.get("meetings", "")),
        "location": str(course.get("location", "to be assigned")),
        "instructor_block": _instructor_block(course),
        "description": str(course.get("description", "")).strip(),
        "essential_questions_list": _bullets(course.get("essential_questions")),
        "not_covered_list": _bullets(course.get("not_covered")),
        "target_audience": str(course.get("target_audience", "")).strip(),
        "prerequisites_list": _bullets(course.get("prerequisites"), "No formal prerequisites."),
        "outcomes_table": _outcomes_table(result),
        "assessments_table": _assessments_table(result, data),
        "specifications_block": _specifications_block(data),
        "grading_block": _grading_block(course),
        "schedule_table": _schedule_table(data),
        "materials_list": _bullets(course.get("materials")),
        "policies_block": _policies_block(course),
        "evaluation_list": _bullets(course.get("evaluation_plan")),
        "fair_block": _fair_block(course),
        "generated_on": dt.date.today().isoformat(),
        "source_file": source.name,
    }


def render_markdown(template: str, context: dict[str, str]) -> str:
    missing = sorted({m.group(1) for m in PLACEHOLDER_RE.finditer(template)} - set(context))
    if missing:
        raise BuildError(f"template uses unknown placeholders: {', '.join(missing)}")
    return PLACEHOLDER_RE.sub(lambda m: context[m.group(1)], template)


# ---------------------------------------------------------------- converters


def _inline_org(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"`([^`]+)`", r"=\1=", text)
    return text


def markdown_to_org(md: str, title: str = "") -> str:
    out: list[str] = []
    if title:
        out.append(f"#+TITLE: {title}")
        out.append("#+OPTIONS: toc:nil")
        out.append("")
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            depth = len(m.group(1))
            if depth == 1 and title:
                continue
            out.append("*" * max(1, depth - (1 if title else 0)) + " " + _inline_org(m.group(2)))
            continue
        if re.match(r"^\|\s*-{3,}", line):
            cells = line.count("|") - 1
            out.append("|" + "+".join("---" for _ in range(cells)) + "|")
            continue
        if line.startswith("|"):
            out.append(_inline_org(line))
            continue
        if line.startswith("- "):
            out.append("- " + _inline_org(line[2:]))
            continue
        out.append(_inline_org(line.rstrip("  ")))
    return "\n".join(out) + "\n"


def _tex_escape(text: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(repl.get(ch, ch) for ch in text)


def _inline_tex(text: str) -> str:
    parts = re.split(r"(\*\*.+?\*\*|`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("**") and p.endswith("**"):
            out.append(r"\textbf{" + _tex_escape(p[2:-2]) + "}")
        elif p.startswith("`") and p.endswith("`"):
            out.append(r"\texttt{" + _tex_escape(p[1:-1]) + "}")
        else:
            out.append(_tex_escape(p))
    return "".join(out)


def markdown_to_latex(md: str) -> str:
    """Minimal Markdown to LaTeX for the syllabus (headings, lists, tables, paragraphs)."""
    body: list[str] = []
    lines = md.splitlines()
    i = 0
    in_list = False
    title = ""
    while i < len(lines):
        line = lines[i]
        if in_list and not line.startswith("- "):
            body.append(r"\end{itemize}")
            in_list = False
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            depth = len(m.group(1))
            text = _inline_tex(m.group(2))
            if depth == 1 and not title:
                title = text
            else:
                cmd = {2: "section*", 3: "subsection*"}.get(depth, "paragraph*")
                body.append(f"\\{cmd}{{{text}}}")
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|\s*-{3,}", lines[i]):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                spec = "|" + "|".join(["p{" + f"{0.9 / ncol:.2f}" + r"\linewidth}"] * ncol) + "|"
                body.append(r"\begin{footnotesize}")
                body.append(r"\begin{longtable}{" + spec + "}")
                body.append(r"\hline")
                for k, r in enumerate(rows):
                    r = r + [""] * (ncol - len(r))
                    cells = [_inline_tex(c.replace("\\|", "|")) for c in r]
                    if k == 0:
                        cells = [r"\textbf{" + c + "}" for c in cells]
                    body.append(" & ".join(cells) + r" \\ \hline")
                body.append(r"\end{longtable}")
                body.append(r"\end{footnotesize}")
            continue
        if line.startswith("- "):
            if not in_list:
                body.append(r"\begin{itemize}")
                in_list = True
            body.append(r"\item " + _inline_tex(line[2:]))
            i += 1
            continue
        if not line.strip():
            body.append("")
        else:
            body.append(_inline_tex(line.rstrip()) + (r"\\" if line.endswith("  ") else ""))
        i += 1
    if in_list:
        body.append(r"\end{itemize}")
    preamble = "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[margin=2.2cm]{geometry}",
            r"\usepackage{longtable}",
            r"\usepackage{array}",
            r"\usepackage{parskip}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\setlength{\emergencystretch}{3em}",
            r"\begin{document}",
            r"{\LARGE\bfseries " + (title or "Syllabus") + r"\par}",
            r"\vspace{1em}",
        ]
    )
    return preamble + "\n" + "\n".join(body) + "\n\\end{document}\n"


# ---------------------------------------------------------------------- pdf


def pdf_tooling() -> tuple[str | None, str | None]:
    """Return (pandoc path, latexmk path); None where missing."""
    return shutil.which("pandoc"), shutil.which("latexmk")


def build_pdf(md_path: Path, md_text: str, pdf_path: Path, timeout: int = 300) -> tuple[bool, str]:
    pandoc, latexmk = pdf_tooling()
    engine = next((e for e in ("xelatex", "pdflatex", "lualatex") if shutil.which(e)), None)
    if pandoc and engine:
        cmd = [
            pandoc,
            str(md_path),
            "-o",
            str(pdf_path),
            f"--pdf-engine={engine}",
            "-V",
            "geometry:margin=2.2cm",
            "-V",
            "colorlinks=true",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0 and pdf_path.exists():
            return True, f"pdf via pandoc ({engine})"
        return False, f"pandoc failed: {proc.stderr.strip()[-800:]}"
    if latexmk and engine:
        tex_path = pdf_path.with_suffix(".tex")
        tex_path.write_text(markdown_to_latex(md_text), encoding="utf-8")
        flag = "-xelatex" if engine == "xelatex" else ("-lualatex" if engine == "lualatex" else "-pdf")
        cmd = [latexmk, flag, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={pdf_path.parent}", str(tex_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0 and pdf_path.exists():
            return True, f"pdf via latexmk ({engine})"
        return False, f"latexmk failed: {proc.stdout.strip()[-800:]}"
    missing = []
    if not pandoc:
        missing.append("pandoc")
    if not latexmk:
        missing.append("latexmk")
    if not engine:
        missing.append("a LaTeX engine (xelatex or pdflatex)")
    return False, "PDF skipped: " + " and ".join(missing) + " not on PATH; Markdown and Org were still built"


# --------------------------------------------------------------------- main


def inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def stem_for(data: dict[str, Any], course_path: Path) -> str:
    code = str((data.get("course") or {}).get("code") or course_path.stem)
    return re.sub(r"[^A-Za-z0-9]+", "-", code).strip("-").lower() or "syllabus"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", type=Path, required=True, help="course YAML")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Markdown template with {{placeholders}}")
    parser.add_argument("--out", type=Path, help="directory to write <code>-syllabus.{md,org,pdf}; stdout when omitted")
    parser.add_argument("--formats", default="md,org", help="comma list from md,org,pdf (default md,org)")
    parser.add_argument("--apply", action="store_true", help="allow writing outside this repository")
    parser.add_argument("--skip-alignment", action="store_true", help="build even when the alignment check fails (drafts only)")
    parser.add_argument("--json", action="store_true", help="print a JSON summary of what was written")
    args = parser.parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        print(f"ERROR: unknown format(s) {bad}; choose from {', '.join(FORMATS)}", file=sys.stderr)
        return 2

    try:
        data = am.load_course(args.course)
        result = am.analyse(data)
    except (am.DesignError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if result["errors"]:
        for e in result["errors"]:
            print(f"ALIGNMENT ERROR: {e}", file=sys.stderr)
        if not args.skip_alignment:
            print("Fix the course design (alignment_matrix.py) before building a syllabus.", file=sys.stderr)
            return 2
        print("Continuing because --skip-alignment was given; do not publish this draft.", file=sys.stderr)
    for w in result["warnings"]:
        print(f"ALIGNMENT WARNING: {w}", file=sys.stderr)

    try:
        template = args.template.read_text(encoding="utf-8")
        md = render_markdown(template, build_context(data, result, args.course))
    except (BuildError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.out:
        print(md)
        return 0

    stem = stem_for(data, args.course) + "-syllabus"
    planned = {f: args.out / f"{stem}.{f}" for f in formats}
    summary: dict[str, Any] = {"out": str(args.out), "written": [], "skipped": [], "messages": []}

    if not inside_repo(args.out) and not args.apply:
        for f, p in planned.items():
            print(f"DRY RUN: would write {p}", file=sys.stderr)
        print("Target is outside the repository; rerun with --apply to write.", file=sys.stderr)
        summary["dry_run"] = True
        if args.json:
            print(json.dumps(summary, indent=2))
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    md_path = planned.get("md") or (args.out / f"{stem}.md")
    if "md" in formats or "pdf" in formats:
        md_path.write_text(md, encoding="utf-8")
        if "md" in formats:
            summary["written"].append(str(md_path))
    if "org" in formats:
        title = f"{data['course'].get('code', '')}: {data['course'].get('title', '')}".strip(": ")
        planned["org"].write_text(markdown_to_org(md, title), encoding="utf-8")
        summary["written"].append(str(planned["org"]))
    if "pdf" in formats:
        ok, message = build_pdf(md_path, md, planned["pdf"])
        summary["messages"].append(message)
        if ok:
            summary["written"].append(str(planned["pdf"]))
        else:
            summary["skipped"].append(str(planned["pdf"]))
            print(message, file=sys.stderr)
        if "md" not in formats:
            md_path.unlink(missing_ok=True)

    for p in summary["written"]:
        print(f"wrote {p}", file=sys.stderr)
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
