#!/usr/bin/env python3
# ruff: noqa: E501
"""Structural linter for a LaTeX or Markdown manuscript.

Checks the shape of the paper, not its prose:

* abstract: present, no citations, within the word budget, and showing the
  five moves context, gap, approach, result, implication in that order;
* introduction: its last paragraph states the contribution;
* sections: canonical order (introduction first; discussion after results;
  conclusion before acknowledgments and references) and length balance;
* figures and tables: every one referenced, every reference resolved,
  every caption longer than a bare label;
* citations: every key in the bibliography, every bibliography entry cited
  (orphans), no citations in the abstract;
* acronyms: defined at first use unless allowlisted;
* statements: author contributions (CRediT), data availability, code
  availability, competing interests, funding;
* house style: em-dash (U+2014), banned meta phrases, Title Case headings.

Every finding is ``file:line: severity: code: message. fix: ...``. ``--json``
prints the findings as a list. Exit 1 when any error remains, 0 otherwise,
2 on a usage problem. Warnings become errors with ``--strict``. Nothing is
written; the manuscript is read only.

LaTeX: ``\\input`` and ``\\include`` are expanded relative to the main file;
``\\bibliography{}`` and ``\\addbibresource{}`` locate the .bib files unless
``--bib`` is given. Markdown: ATX headings, pandoc ``{#fig:id}`` and
``{#tbl:id}`` labels, ``@fig:id`` and ``Figure N`` references, ``[@key]``
citations, and a YAML ``abstract:`` or ``bibliography:`` header.

Example:
  paper_lint.py paper/main.tex
  paper_lint.py paper.md --bib refs.bib --acronyms assets/acronyms.txt --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ACRONYMS = HERE.parent / "assets" / "acronyms.txt"
EM_DASH = "\u2014"

SEVERITIES = ("error", "warning", "info")

BANNED_PHRASES: list[tuple[str, re.Pattern[str]]] = [
    ("Note that", re.compile(r"\bNote that\b", re.IGNORECASE)),
    ("Importantly", re.compile(r"\bImportantly\b", re.IGNORECASE)),
    ("Key insight", re.compile(r"\bKey insights?\b", re.IGNORECASE)),
    ("It is worth noting", re.compile(r"\bIt is worth noting\b", re.IGNORECASE)),
    ("In order to", re.compile(r"\bIn order to\b")),
]

# Section names, normalised (lowercase, letters only), mapped to a role.
SECTION_ROLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^abstract$"), "abstract"),
    (re.compile(r"^(introduction|background and introduction)$"), "introduction"),
    (re.compile(r"^(background|related work|preliminaries|state of the art)"), "background"),
    (
        re.compile(r"^(materials? and methods?|methods?|methodology|approach|model|system)"),
        "methods",
    ),
    (re.compile(r"^(experiments?|experimental setup|evaluation)"), "methods"),
    (re.compile(r"^(results?|findings|results and discussion)"), "results"),
    (re.compile(r"^discussion"), "discussion"),
    (re.compile(r"^(conclusions?|summary and outlook|outlook|future work)"), "conclusion"),
    (re.compile(r"^(limitations?)$"), "limitations"),
    (re.compile(r"^(acknowledge?ments?|funding)"), "acknowledgments"),
    (
        re.compile(r"^(author contributions?|credit author(ship)? statement|contributions?)"),
        "credit",
    ),
    (
        re.compile(
            r"^(availability|data availability|code availability|availability of data|"
            r"availability and implementation|data and code availability|"
            r"software availability|data and software availability)"
        ),
        "availability",
    ),
    (
        re.compile(r"^(competing interests?|conflicts? of interest|declaration of interests?)"),
        "competing",
    ),
    (re.compile(r"^(references|bibliography)$"), "references"),
    (re.compile(r"^(appendix|supplementary|supplement)"), "appendix"),
]

CANONICAL_ORDER = {
    "introduction": 1,
    "background": 2,
    "methods": 3,
    "results": 3,
    "discussion": 4,
    "limitations": 4,
    "conclusion": 5,
    "credit": 6,
    "availability": 6,
    "competing": 6,
    "acknowledgments": 6,
    "references": 7,
    "appendix": 8,
}

STATEMENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "credit": re.compile(
        r"(author contributions?|credit author|conceptualization|writing\s*[-\u2013]\s*original draft|"
        r"contributed to the (conception|design|analysis)|conceived (the|and) |designed the (study|experiments))",
        re.IGNORECASE,
    ),
    "data-availability": re.compile(
        r"(data availability|availability of data|data and code availability|data and software availability|"
        r"availability and implementation|(the )?data (are|is|sets are) (freely |publicly )?available|"
        r"data (are|is) deposited|data (can be|may be) (accessed|downloaded))",
        re.IGNORECASE,
    ),
    "code-availability": re.compile(
        r"(code availability|software availability|data and code availability|data and software availability|"
        r"availability and implementation|(source )?code (is|are) (freely |publicly )?available|"
        r"(software|implementation|code) is available (at|from|under)|github\.com|zenodo\.org|doi\.org/10\.5281)",
        re.IGNORECASE,
    ),
    "competing-interests": re.compile(
        r"(competing interests?|conflicts? of interest|declaration of interests?|no competing)",
        re.IGNORECASE,
    ),
    "funding": re.compile(
        r"(funding|was (supported|funded) by|financial support|grant (no|number|agreement)|award number)",
        re.IGNORECASE,
    ),
}

STATEMENT_FIX = {
    "credit": "add an author contributions statement listing each author's CRediT roles (assets/credit-roles.md)",
    "data-availability": "add a data availability statement with a persistent identifier for the deposited data",
    "code-availability": "add a code availability statement with repository and archived release DOI",
    "competing-interests": "add a competing interests statement (or 'The authors declare no competing interests')",
    "funding": "add a funding statement naming the sources and grant numbers, or state that there was none",
}

ABSTRACT_MOVES: list[tuple[str, re.Pattern[str]]] = [
    ("context", re.compile(r".")),  # the first sentence always counts as context
    (
        "gap",
        re.compile(
            r"\b(however|but|yet|although|while|whereas|despite|remains?|remain(ed|s)? (unclear|unknown|open|"
            r"challenging|elusive|limited)|lack(s|ing)?|no (existing|current|method|approach|tool)|"
            r"not (yet|been|well|fully|possible)|unclear|unknown|limited|challeng(e|es|ing)|difficult|"
            r"gap|missing|scarce|few|little is known|cannot|fail(s|ed)? to|hinder(s|ed)?|"
            r"time[- ]consuming|labor[- ]intensive|infeasible|open (problem|question))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "approach",
        re.compile(
            r"\b(here,? we|in this (paper|work|study|article),? we|we (present|propose|introduce|develop|"
            r"developed|describe|report|design|designed|built|build|created|create|implement|implemented|"
            r"formulate|combine|extend|apply|applied|train|trained|use|used|investigate|investigated|"
            r"analy[sz]e|analy[sz]ed|evaluate|evaluated|construct|constructed|derive|derived))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "result",
        re.compile(
            r"\b(we (show|find|found|demonstrate|observe|observed|identify|identified|discover|discovered|"
            r"achieve|achieved|obtain|obtained|report)|results? (show|indicate|demonstrate|reveal)|"
            r"outperform(s|ed)?|improve(s|d)? (the|on|over|by)|increase(s|d)? (the|by)|reduce(s|d)? (the|by)|"
            r"achiev(es|ed|ing)|recover(s|ed)?|predict(s|ed)? [^.]*(correctly|with)|"
            r"\d+(\.\d+)?\s*(%|percent|fold|times|x|percentage points))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "implication",
        re.compile(
            r"\b(suggest(s|ing)?|impl(y|ies|ications?)|enabl(e|es|ing)|allow(s|ing)?|"
            r"open(s|ing)? (the way|new|up)|pav(e|es|ing) the way|can be (used|applied|extended)|"
            r"provid(e|es|ing) a (basis|foundation|framework|resource)|resource for|"
            r"will (help|enable|allow|support)|(is|are) (freely |publicly )?available|"
            r"highlight(s|ing)?|underscore(s)?|generali[sz](e|es|able)|applicable|"
            r"potential|promis(e|es|ing)|towards?|facilitat(e|es|ing)|support(s|ing)?)\b",
            re.IGNORECASE,
        ),
    ),
]

CONTRIBUTION_RE = re.compile(
    r"\b(in this (paper|work|article|study),? we|here,? we|we (present|propose|introduce|develop|"
    r"describe|show|report|make|contribute|address|demonstrate|extend|formulate)|"
    r"our (main |key |primary )?contributions?|the (main |key |primary )?contributions? of this|"
    r"this (paper|work|article|study) (presents|proposes|introduces|describes|makes|shows|reports|"
    r"contributes|addresses)|the remainder of (this|the) paper|the rest of (this|the) paper)\b",
    re.IGNORECASE,
)

ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9\\{@#:/.-])([A-Z][A-Z0-9]{1,7}s?)(?![A-Za-z0-9}/])")
ACRONYM_UNITS = {
    "II",
    "III",
    "IV",
    "VI",
    "VII",
    "VIII",
    "IX",
    "XI",
    "XII",
    "AM",
    "PM",
    "BC",
    "AD",
    "OK",
    "PDF",
    "URL",
    "URI",
    "IRI",
    "HTTP",
    "HTTPS",
    "DOI",
    "ISBN",
    "ISSN",
    "USA",
    "UK",
    "EU",
    "CPU",
    "GPU",
    "RAM",
    "GB",
    "MB",
    "TB",
    "KB",
    "CSV",
    "JSON",
    "XML",
    "YAML",
    "HTML",
    "SQL",
    "DNA",
    "RNA",
    "MRNA",
    "ATP",
    "PCR",
    "SNP",
    "SNPS",
    "FDR",
    "SD",
    "SE",
    "CI",
    "IQR",
    "AUC",
    "ROC",
    "AUROC",
    "AUPR",
    "AUPRC",
    "MAP",
    "MRR",
    "F1",
    "IDE",
    "OS",
    "API",
    "APIS",
    "ID",
    "IDS",
    "MIT",
    "BSD",
    "GPL",
    "CC",
    "BY",
    "SA",
    "NC",
    "ND",
    "ET",
    "AL",
    "IE",
    "EG",
    "NA",
    "TODO",
    "FIXME",
    "XXX",
    "ACK",
    "PI",
    "MS",
    "PHD",
    "TABLE",
    "FIGURE",
    "FIG",
    "SEE",
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
ABBREV_RE = re.compile(
    r"\b(e\.g|i\.e|et al|Fig|Figs|Tab|Eq|Eqs|Sec|vs|cf|approx|resp|no|vol|pp|ca|Dr|Prof|Mr|Ms|Mrs|St)\.\s"
)

LATEX_SECTION_RE = re.compile(
    r"\\(section|subsection|subsubsection|chapter)\*?\s*(\[[^\]]*\])?\s*\{"
)
LATEX_CITE_RE = re.compile(
    r"\\(?:no)?(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|citeyearpar|parencite|textcite|"
    r"autocite|footcite|smartcite|supercite|fullcite|Cite|Citep|Citet|Parencite|Textcite|Autocite|"
    r"citeps?|citets?|cites|parencites|textcites|autocites)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}"
)
LATEX_REF_RE = re.compile(
    r"\\(?:ref|Ref|cref|Cref|autoref|Autoref|vref|Vref|eqref|pageref|nameref|labelcref|crefrange|Crefrange)\*?\{([^}]*)\}"
)
LATEX_LABEL_RE = re.compile(r"\\label\{([^}]*)\}")
LATEX_CAPTION_RE = re.compile(r"\\caption(?:of\{[^}]*\})?\s*(\[[^\]]*\])?\s*\{")
LATEX_INPUT_RE = re.compile(r"^\s*\\(input|include|subfile)\{([^}]+)\}")
LATEX_BIB_RE = re.compile(r"\\(?:bibliography|addbibresource|addglobalbib)\{([^}]+)\}")
LATEX_ACRODEF_RE = re.compile(
    r"\\(?:acrodef|newacronym|DeclareAcronym|newabbreviation)\*?(?:\[[^\]]*\])?\{([^}]+)\}"
)

MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MD_CITE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*[A-Za-z0-9_])")
MD_LABEL_RE = re.compile(r"\{#((?:fig|tbl|tab|table|figure|eq|sec|lst)[:\-][A-Za-z0-9_:.-]+)\}")
MD_HTML_ID_RE = re.compile(
    r"<(?:a|div|span|figure|table)[^>]*\bid=\"((?:fig|tbl|tab|table|figure)[:\-][^\"]+)\""
)
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MD_FIGNUM_RE = re.compile(r"\b(Fig\.?|Figure|Figs\.?|Figures|Table|Tables|Tab\.?)\s*~?\s*(S?\d+)")
MD_PANDOC_REF_RE = re.compile(
    r"(?<![\w@])@((?:fig|tbl|tab|table|figure|eq|sec|lst)[:\-][A-Za-z0-9_:.-]*[A-Za-z0-9_])"
)

BIB_ENTRY_RE = re.compile(r"@(\w+)\s*[{(]\s*([^,\s]+)\s*,", re.MULTILINE)


@dataclass
class Finding:
    path: str
    line: int
    severity: str
    code: str
    message: str
    fix: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.severity}: {self.code}: {self.message}. fix: {self.fix}"


@dataclass
class Line:
    text: str
    path: str
    line: int


@dataclass
class Section:
    title: str
    level: int
    role: str
    start: int  # index into lines
    end: int = 0  # exclusive
    words: int = 0


@dataclass
class Doc:
    kind: str  # "latex" or "markdown"
    lines: list[Line]
    root: Path
    bib_paths: list[Path] = field(default_factory=list)
    abstract: list[Line] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    title: str = ""
    frontmatter_end: int = 0


# --------------------------------------------------------------------------- loading


def strip_latex_comment(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "%":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def load_latex(path: Path, seen: set[Path] | None = None) -> list[Line]:
    seen = seen or set()
    rp = path.resolve()
    if rp in seen:
        return []
    seen.add(rp)
    out: list[Line] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for i, raw in enumerate(text.splitlines(), 1):
        line = strip_latex_comment(raw)
        m = LATEX_INPUT_RE.match(line)
        if m:
            target = m.group(2).strip()
            cand = path.parent / target
            if cand.suffix == "":
                cand = cand.with_suffix(".tex")
            if cand.exists():
                out.extend(load_latex(cand, seen))
                continue
            out.append(Line(f"% missing input {target}", str(path), i))
            continue
        out.append(Line(line, str(path), i))
    return out


def load_markdown(path: Path) -> list[Line]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [Line(raw, str(path), i) for i, raw in enumerate(text.splitlines(), 1)]


def normalise_title(title: str) -> str:
    t = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", title)
    t = re.sub(r"[{}*_`]", "", t)
    t = re.sub(r"\{#[^}]*\}", "", t)
    t = re.sub(r"[^A-Za-z ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def role_of(title: str) -> str:
    n = normalise_title(title)
    for pat, role in SECTION_ROLES:
        if pat.search(n):
            return role
    return "other"


def brace_arg(text: str, start: int) -> tuple[str, int]:
    """Return the contents of the brace group starting at ``start`` ('{') and the index after it."""
    depth = 0
    buf: list[str] = []
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(buf), i + 1
        buf.append(ch)
        i += 1
    return "".join(buf), len(text)


def parse_latex(lines: list[Line], root: Path, bib_override: list[Path]) -> Doc:
    doc = Doc("latex", lines, root)
    in_abstract = False
    in_document = any("\\begin{document}" in ln.text for ln in lines)
    started = not in_document
    for idx, ln in enumerate(lines):
        t = ln.text
        if "\\begin{document}" in t:
            started = True
            doc.frontmatter_end = idx
        if not started:
            m = re.search(r"\\title(\[[^\]]*\])?\{", t)
            if m:
                doc.title, _ = brace_arg(t, m.end() - 1)
            for mb in LATEX_BIB_RE.finditer(t):
                for name in mb.group(1).split(","):
                    doc.bib_paths.append(
                        root
                        / (name.strip() if name.strip().endswith(".bib") else name.strip() + ".bib")
                    )
            continue
        for mb in LATEX_BIB_RE.finditer(t):
            for name in mb.group(1).split(","):
                doc.bib_paths.append(
                    root
                    / (name.strip() if name.strip().endswith(".bib") else name.strip() + ".bib")
                )
        if "\\begin{abstract}" in t:
            in_abstract = True
            rest = t.split("\\begin{abstract}", 1)[1]
            if rest.strip():
                doc.abstract.append(Line(rest, ln.path, ln.line))
            continue
        if "\\end{abstract}" in t:
            in_abstract = False
            rest = t.split("\\end{abstract}", 1)[0]
            if rest.strip():
                doc.abstract.append(Line(rest, ln.path, ln.line))
            continue
        if in_abstract:
            doc.abstract.append(ln)
            continue
        m = LATEX_SECTION_RE.search(t)
        if m:
            title, _ = brace_arg(t, m.end() - 1)
            level = {"chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3}[m.group(1)]
            doc.sections.append(Section(title.strip(), level, role_of(title), idx))
        if "\\bibliography" in t or "\\printbibliography" in t or "\\begin{thebibliography}" in t:
            if not doc.sections or doc.sections[-1].role != "references":
                doc.sections.append(Section("References", 1, "references", idx))
    if bib_override:
        doc.bib_paths = list(bib_override)
    finish_sections(doc)
    return doc


def parse_markdown(lines: list[Line], root: Path, bib_override: list[Path]) -> Doc:
    doc = Doc("markdown", lines, root)
    idx = 0
    if lines and lines[0].text.strip() == "---":
        j = 1
        fm: list[Line] = []
        while j < len(lines) and lines[j].text.strip() not in ("---", "..."):
            fm.append(lines[j])
            j += 1
        doc.frontmatter_end = j + 1
        idx = j + 1
        key = None
        for ln in fm:
            m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", ln.text)
            if m:
                key = m.group(1).lower()
                val = m.group(2).strip()
                if key == "title" and val:
                    doc.title = val.strip("\"'")
                elif key == "abstract" and val and val not in ("|", ">", "|-", ">-"):
                    doc.abstract.append(Line(val.strip("\"'"), ln.path, ln.line))
                elif key == "bibliography" and val:
                    for name in re.split(r"[,\s\[\]]+", val):
                        if name:
                            doc.bib_paths.append(root / name.strip("\"'"))
            elif key == "abstract" and ln.text.strip():
                doc.abstract.append(Line(ln.text.strip(), ln.path, ln.line))
            elif key == "bibliography" and ln.text.strip().startswith("-"):
                doc.bib_paths.append(root / ln.text.strip()[1:].strip().strip("\"'"))
    in_code = False
    abstract_section: Section | None = None
    for i in range(idx, len(lines)):
        t = lines[i].text
        if t.strip().startswith("```") or t.strip().startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = MD_HEADING_RE.match(t)
        if m:
            title = re.sub(r"\{#[^}]*\}", "", m.group(2)).strip()
            level = len(m.group(1))
            sec = Section(title, level, role_of(title), i)
            doc.sections.append(sec)
            if sec.role == "abstract":
                abstract_section = sec
    if bib_override:
        doc.bib_paths = list(bib_override)
    finish_sections(doc)
    if abstract_section and not doc.abstract:
        doc.abstract = [
            ln for ln in lines[abstract_section.start + 1 : abstract_section.end] if ln.text.strip()
        ]
        doc.sections = [s for s in doc.sections if s is not abstract_section]
    return doc


def finish_sections(doc: Doc) -> None:
    secs = doc.sections
    for k, sec in enumerate(secs):
        sec.end = secs[k + 1].start if k + 1 < len(secs) else len(doc.lines)
    if not secs:
        return
    top = min(s.level for s in secs)
    tops = [s for s in secs if s.level == top]
    for k, sec in enumerate(tops):
        end = tops[k + 1].start if k + 1 < len(tops) else len(doc.lines)
        sec.words = sum(word_count(doc.kind, ln.text) for ln in doc.lines[sec.start + 1 : end])


# --------------------------------------------------------------------------- text helpers


def plain_text(kind: str, text: str) -> str:
    t = text
    if kind == "latex":
        t = re.sub(r"\$[^$]*\$", " eqn ", t)
        t = LATEX_CITE_RE.sub(" ", t)
        t = LATEX_REF_RE.sub(" ref ", t)
        t = LATEX_LABEL_RE.sub(" ", t)
        t = re.sub(r"\\(begin|end)\{[^}]*\}", " ", t)
        t = re.sub(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?", " ", t)
        t = re.sub(r"[{}~]", " ", t)
    else:
        t = re.sub(r"`[^`]*`", " ", t)
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
        t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"\[@[^\]]*\]", " ", t)
        t = MD_CITE_RE.sub(" ", t)
        t = re.sub(r"\{#[^}]*\}", " ", t)
        t = re.sub(r"[*_>#|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def word_count(kind: str, text: str) -> int:
    return len([w for w in plain_text(kind, text).split() if re.search(r"[A-Za-z0-9]", w)])


def sentences(text: str) -> list[str]:
    guarded = ABBREV_RE.sub(lambda m: m.group(0).replace(".", "\u0000"), text)
    parts = SENTENCE_SPLIT_RE.split(guarded)
    return [p.replace("\u0000", ".").strip() for p in parts if p.strip()]


def paragraphs(lines: list[Line]) -> list[list[Line]]:
    out: list[list[Line]] = []
    cur: list[Line] = []
    for ln in lines:
        if ln.text.strip() == "":
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(ln)
    if cur:
        out.append(cur)
    return out


def is_heading_line(kind: str, text: str) -> bool:
    if kind == "latex":
        return (
            bool(LATEX_SECTION_RE.search(text))
            or text.strip().startswith("\\begin{")
            or text.strip().startswith("\\end{")
        )
    return bool(MD_HEADING_RE.match(text))


# --------------------------------------------------------------------------- checks


class Linter:
    def __init__(self, doc: Doc, acronyms: set[str], abstract_max: int, strict: bool) -> None:
        self.doc = doc
        self.acronyms = acronyms | ACRONYM_UNITS
        self.abstract_max = abstract_max
        self.strict = strict
        self.findings: list[Finding] = []

    def add(self, ln: Line | None, severity: str, code: str, message: str, fix: str) -> None:
        if self.strict and severity == "warning":
            severity = "error"
        path = ln.path if ln else str(self.doc.root)
        line = ln.line if ln else 0
        self.findings.append(Finding(path, line, severity, code, message, fix))

    def first_line(self) -> Line:
        return self.doc.lines[0] if self.doc.lines else Line("", str(self.doc.root), 1)

    # -- abstract
    def check_abstract(self) -> None:
        doc = self.doc
        if not doc.abstract:
            self.add(
                self.first_line(),
                "error",
                "abstract.missing",
                "no abstract found",
                "add \\begin{abstract} ... \\end{abstract}, an '# Abstract' section or a YAML abstract: field",
            )
            return
        first = doc.abstract[0]
        text = " ".join(plain_text(doc.kind, ln.text) for ln in doc.abstract)
        words = len(text.split())
        if words > self.abstract_max:
            self.add(
                first,
                "warning",
                "abstract.length",
                f"abstract has {words} words, budget {self.abstract_max}",
                "cut context sentences first, then merge result sentences; keep one sentence per move",
            )
        raw = " ".join(ln.text for ln in doc.abstract)
        if (doc.kind == "latex" and LATEX_CITE_RE.search(raw)) or (
            doc.kind == "markdown" and re.search(r"\[@|(?<!\w)@\w", raw)
        ):
            self.add(
                first,
                "warning",
                "abstract.citation",
                "abstract contains a citation",
                "remove citations from the abstract; name the method or resource instead",
            )
        sents = sentences(text)
        if len(sents) < 4:
            self.add(
                first,
                "error",
                "abstract.shape",
                f"abstract has {len(sents)} sentences; the five moves need at least four",
                "write one sentence each for context, gap, approach, result and implication",
            )
            return
        positions: dict[str, int] = {}
        for k, sent in enumerate(sents):
            for move, pat in ABSTRACT_MOVES[1:]:
                if move not in positions and pat.search(sent):
                    positions[move] = k
        positions["context"] = 0
        missing = [m for m, _ in ABSTRACT_MOVES if m not in positions]
        if missing:
            self.add(
                first,
                "error",
                "abstract.shape",
                f"abstract lacks the move(s): {', '.join(missing)}",
                "context, then the gap (what is missing and why it matters), then 'Here we ...', then the result with a number, then what it enables",
            )
        order = [m for m, _ in ABSTRACT_MOVES if m in positions]
        idxs = [positions[m] for m in order]
        if idxs != sorted(idxs):
            self.add(
                first,
                "warning",
                "abstract.order",
                "abstract moves appear out of order: "
                + ", ".join(f"{m}@{positions[m] + 1}" for m in order),
                "reorder so that gap precedes approach and approach precedes result",
            )
        if "approach" in positions and positions["approach"] == 0:
            self.add(
                first,
                "warning",
                "abstract.shape",
                "abstract opens with the approach, before any context or gap",
                "start with one sentence of context and one naming the gap",
            )

    # -- introduction
    def check_introduction(self) -> None:
        doc = self.doc
        intro = next((s for s in doc.sections if s.role == "introduction"), None)
        if intro is None:
            if doc.sections:
                self.add(
                    doc.lines[doc.sections[0].start],
                    "warning",
                    "intro.missing",
                    "no introduction section found",
                    "name the first section Introduction (or accept the venue's name and rerun with the heading renamed)",
                )
            return
        body = [
            ln
            for ln in doc.lines[intro.start + 1 : intro.end]
            if not is_heading_line(doc.kind, ln.text)
        ]
        paras = [
            p for p in paragraphs(body) if word_count(doc.kind, " ".join(x.text for x in p)) >= 8
        ]
        if not paras:
            self.add(
                doc.lines[intro.start],
                "error",
                "intro.empty",
                "introduction has no prose paragraphs",
                "write the gap paragraphs and a final contribution paragraph",
            )
            return
        last = paras[-1]
        text = " ".join(plain_text(doc.kind, x.text) for x in last)
        if not CONTRIBUTION_RE.search(text):
            self.add(
                last[0],
                "error",
                "intro.contribution",
                "last introduction paragraph does not state the contribution",
                "end the introduction with 'Here we ...' or 'In this work we ...' naming what the paper contributes and how it is shown",
            )
        if len(paras) < 2:
            self.add(
                paras[0][0],
                "warning",
                "intro.gap",
                "introduction has a single paragraph; the gap is not developed",
                "add paragraphs that narrow from field gap to the specific gap this paper fills",
            )

    # -- section order and balance
    def check_sections(self) -> None:
        doc = self.doc
        if not doc.sections:
            self.add(
                self.first_line(),
                "error",
                "sections.none",
                "no sections found",
                "use \\section{} or '#' headings",
            )
            return
        top = min(s.level for s in doc.sections)
        tops = [s for s in doc.sections if s.level == top]
        roles = [s.role for s in tops]
        if roles and roles[0] not in ("introduction", "abstract"):
            self.add(
                doc.lines[tops[0].start],
                "warning",
                "sections.order",
                f"first section is {tops[0].title!r}, not the introduction",
                "start the body with the introduction",
            )
        last_rank = 0
        last_sec = None
        for s in tops:
            rank = CANONICAL_ORDER.get(s.role)
            if rank is None:
                continue
            if rank < last_rank and last_sec is not None:
                self.add(
                    doc.lines[s.start],
                    "error"
                    if s.role in ("results", "conclusion", "introduction")
                    or last_sec.role in ("discussion", "conclusion")
                    else "warning",
                    "sections.order",
                    f"{s.title!r} comes after {last_sec.title!r}",
                    "order: introduction, background, methods or results (venue order), discussion, conclusion, statements, references, appendix",
                )
            if rank >= last_rank:
                last_rank, last_sec = rank, s
        body = [
            s
            for s in tops
            if s.role
            in (
                "introduction",
                "background",
                "methods",
                "results",
                "discussion",
                "limitations",
                "conclusion",
                "other",
            )
        ]
        total = sum(s.words for s in body)
        if total > 0:
            for s in body:
                share = s.words / total
                if s.role == "introduction" and share > 0.35:
                    self.add(
                        doc.lines[s.start],
                        "warning",
                        "sections.balance",
                        f"introduction is {share:.0%} of the body ({s.words} words)",
                        "move literature survey into background or cut it; the introduction develops the gap only",
                    )
                elif s.role != "introduction" and share > 0.5:
                    self.add(
                        doc.lines[s.start],
                        "warning",
                        "sections.balance",
                        f"{s.title!r} is {share:.0%} of the body ({s.words} words)",
                        "split into subsections with statement headings or move detail to a supplement",
                    )
                if s.role in ("results", "discussion") and share < 0.08 and total > 800:
                    self.add(
                        doc.lines[s.start],
                        "warning",
                        "sections.balance",
                        f"{s.title!r} is only {share:.0%} of the body ({s.words} words)",
                        "the results carry the evidence and the discussion the caveats; both need room",
                    )
            if not any(s.role == "discussion" for s in tops) and not any(
                s.role == "conclusion" for s in tops
            ):
                self.add(
                    doc.lines[tops[-1].start],
                    "warning",
                    "sections.missing",
                    "no discussion or conclusion section",
                    "add a discussion (summary, limitations, what the contribution enables)",
                )
            if not any(s.role == "results" for s in tops) and not any(
                s.role == "methods" for s in tops
            ):
                self.add(
                    doc.lines[tops[-1].start],
                    "warning",
                    "sections.missing",
                    "no methods or results section",
                    "add the sections the venue expects",
                )
        for s in body:
            self.findings.append(
                Finding(
                    doc.lines[s.start].path,
                    doc.lines[s.start].line,
                    "info",
                    "sections.words",
                    f"{s.title!r}: {s.words} words",
                    "no action",
                )
            )

    # -- figures and tables
    def check_floats(self) -> None:
        doc = self.doc
        labels: dict[str, Line] = {}
        refs: dict[str, Line] = {}
        captions: list[tuple[Line, str]] = []
        if doc.kind == "latex":
            env: list[str] = []
            for ln in doc.lines[doc.frontmatter_end :]:
                t = ln.text
                for m in re.finditer(
                    r"\\begin\{(figure|table|figure\*|table\*|subfigure|wrapfigure|sidewaysfigure|sidewaystable|listing|algorithm)\}",
                    t,
                ):
                    env.append(m.group(1).rstrip("*"))
                for m in LATEX_CAPTION_RE.finditer(t):
                    cap, _ = brace_arg(t, m.end() - 1)
                    captions.append((ln, cap))
                for m in LATEX_LABEL_RE.finditer(t):
                    for lab in m.group(1).split(","):
                        lab = lab.strip()
                        kind_env = env[-1] if env else ""
                        if kind_env in (
                            "figure",
                            "table",
                            "subfigure",
                            "wrapfigure",
                            "sidewaysfigure",
                            "sidewaystable",
                            "listing",
                            "algorithm",
                        ) or re.match(
                            r"^(fig|tab|tbl|table|figure|alg|lst)[:\-_]", lab, re.IGNORECASE
                        ):
                            labels.setdefault(lab, ln)
                for _ in re.finditer(
                    r"\\end\{(figure|table|figure\*|table\*|subfigure|wrapfigure|sidewaysfigure|sidewaystable|listing|algorithm)\}",
                    t,
                ):
                    if env:
                        env.pop()
                for m in LATEX_REF_RE.finditer(t):
                    for lab in m.group(1).split(","):
                        refs.setdefault(lab.strip(), ln)
        else:
            in_code = False
            numbered_figs: list[Line] = []
            numbered_tabs: list[Line] = []
            mention_figs: set[str] = set()
            mention_tabs: set[str] = set()
            for ln in doc.lines[doc.frontmatter_end :]:
                t = ln.text
                if t.strip().startswith("```") or t.strip().startswith("~~~"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                for m in MD_LABEL_RE.finditer(t):
                    labels.setdefault(m.group(1), ln)
                for m in MD_HTML_ID_RE.finditer(t):
                    labels.setdefault(m.group(1), ln)
                for m in MD_IMAGE_RE.finditer(t):
                    captions.append((ln, m.group(1)))
                    if not MD_LABEL_RE.search(t):
                        numbered_figs.append(ln)
                if re.match(r"^\s*(Table|Tab\.)\s*S?\d*[:.]", t) or re.match(r"^\s*:\s*\S", t):
                    if not MD_LABEL_RE.search(t):
                        numbered_tabs.append(ln)
                for m in MD_PANDOC_REF_RE.finditer(t):
                    refs.setdefault(m.group(1), ln)
                for m in MD_FIGNUM_RE.finditer(t):
                    (mention_tabs if m.group(1).lower().startswith("tab") else mention_figs).add(
                        m.group(2)
                    )
            for k, ln in enumerate(numbered_figs, 1):
                if str(k) not in mention_figs:
                    self.add(
                        ln,
                        "error",
                        "figure.unreferenced",
                        f"figure {k} (unlabelled image) is never referenced as 'Figure {k}'",
                        "reference every figure in the text, or label it {#fig:name} and cite it as @fig:name",
                    )
            for k, ln in enumerate(numbered_tabs, 1):
                if str(k) not in mention_tabs:
                    self.add(
                        ln,
                        "error",
                        "table.unreferenced",
                        f"table {k} is never referenced as 'Table {k}'",
                        "reference every table in the text, or label it {#tbl:name} and cite it as @tbl:name",
                    )
            defined_nums = {str(k) for k in range(1, len(numbered_figs) + 1)}
            for n in sorted(mention_figs - defined_nums, key=lambda x: (len(x), x)):
                if not n.startswith("S") and not labels and numbered_figs:
                    self.add(
                        self.first_line(),
                        "warning",
                        "figure.undefined",
                        f"text refers to Figure {n} but only {len(numbered_figs)} images exist",
                        "check figure numbering",
                    )
        for lab, ln in labels.items():
            if lab not in refs:
                what = "table" if re.match(r"^(tab|tbl|table)", lab, re.IGNORECASE) else "figure"
                self.add(
                    ln,
                    "error",
                    f"{what}.unreferenced",
                    f"{what} label {lab!r} is never referenced",
                    f"reference it in the results text where it supports a statement, or remove the {what}",
                )
        for lab, ln in refs.items():
            if (
                re.match(r"^(fig|tab|tbl|table|figure)[:\-_]", lab, re.IGNORECASE)
                and lab not in labels
            ):
                self.add(
                    ln,
                    "error",
                    "ref.undefined",
                    f"reference to undefined label {lab!r}",
                    "add \\label{} inside the float (after \\caption) or fix the key",
                )
        for ln, cap in captions:
            words = plain_text(doc.kind, cap).split()
            if len(words) < 8:
                self.add(
                    ln,
                    "warning",
                    "caption.short",
                    f"caption has {len(words)} words: {' '.join(words)!r}",
                    "first sentence states the claim the figure supports; then what is plotted, n, and what error bars show",
                )

    # -- citations
    def bib_keys(self) -> tuple[dict[str, tuple[Path, int]], list[Path]]:
        keys: dict[str, tuple[Path, int]] = {}
        missing: list[Path] = []
        for bp in self.doc.bib_paths:
            if not bp.exists():
                missing.append(bp)
                continue
            text = bp.read_text(encoding="utf-8", errors="replace")
            for m in BIB_ENTRY_RE.finditer(text):
                if m.group(1).lower() in ("comment", "preamble", "string"):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                keys.setdefault(m.group(2), (bp, line))
        return keys, missing

    def cited_keys(self) -> dict[str, Line]:
        doc = self.doc
        cited: dict[str, Line] = {}
        in_code = False
        for ln in doc.lines[doc.frontmatter_end :]:
            t = ln.text
            if doc.kind == "markdown":
                if t.strip().startswith("```") or t.strip().startswith("~~~"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                for m in MD_CITE_RE.finditer(t):
                    key = m.group(1)
                    if MD_PANDOC_REF_RE.match("@" + key):
                        continue
                    cited.setdefault(key, ln)
            else:
                for m in LATEX_CITE_RE.finditer(t):
                    for key in m.group(1).split(","):
                        key = key.strip()
                        if key:
                            cited.setdefault(key, ln)
        return cited

    def check_citations(self) -> None:
        doc = self.doc
        cited = self.cited_keys()
        if not doc.bib_paths:
            if cited:
                self.add(
                    self.first_line(),
                    "warning",
                    "bib.missing",
                    f"{len(cited)} citation keys but no bibliography file found",
                    "pass --bib refs.bib or add \\bibliography{}/\\addbibresource{} or a YAML bibliography: field",
                )
            return
        keys, missing = self.bib_keys()
        for bp in missing:
            self.add(
                self.first_line(),
                "error",
                "bib.missing",
                f"bibliography file {bp} not found",
                "fix the path or pass --bib",
            )
        if "*" in cited:
            cited.pop("*")
            nocite_all = True
        else:
            nocite_all = False
        for key, ln in cited.items():
            if key not in keys:
                self.add(
                    ln,
                    "error",
                    "cite.undefined",
                    f"citation key {key!r} not in the bibliography",
                    "add the entry (verify it with cite_check.py) or fix the key",
                )
        if not nocite_all:
            for key, (bp, line) in keys.items():
                if key not in cited:
                    self.findings.append(
                        Finding(
                            str(bp),
                            line,
                            "warning" if not self.strict else "error",
                            "cite.orphan",
                            f"bibliography entry {key!r} is never cited",
                            "remove it from the .bib or cite it where it supports a claim",
                        )
                    )

    # -- acronyms
    def check_acronyms(self) -> None:
        doc = self.doc
        defined: set[str] = set()
        for ln in doc.lines:
            for m in LATEX_ACRODEF_RE.finditer(ln.text):
                defined.add(m.group(1).upper())
        seen: set[str] = set()
        in_code = False
        ordered: list[Line] = list(doc.abstract) + doc.lines[doc.frontmatter_end :]
        for ln in ordered:
            t = ln.text
            if doc.kind == "markdown":
                if t.strip().startswith("```") or t.strip().startswith("~~~"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
            if doc.kind == "latex" and (LATEX_SECTION_RE.search(t) or t.strip().startswith("\\")):
                # headings and pure commands are skipped; definitions inside prose are still seen
                if LATEX_SECTION_RE.search(t):
                    continue
            plain = plain_text(doc.kind, t)
            for m in ACRONYM_RE.finditer(plain):
                acr = m.group(1)
                base = (
                    acr[:-1] if acr.endswith("s") and acr[:-1].isupper() and len(acr) > 2 else acr
                )
                if base in self.acronyms or base in seen or base in defined:
                    continue
                if not re.search(r"[A-Z]{2}", base):
                    continue
                seen.add(base)
                start, end = m.start(), m.end()
                after = plain[end : end + 3]
                before = plain[max(0, start - 3) : start]
                defined_here = (
                    bool(re.match(r"^\s*\(", after))
                    or before.endswith("(")
                    or ("(" + base) in plain
                )
                if not defined_here:
                    self.add(
                        ln,
                        "warning",
                        "acronym.undefined",
                        f"acronym {base!r} used before it is defined",
                        f"write the long form followed by ({base}) at first use, or add {base} to the acronym allowlist",
                    )

    # -- statements
    def check_statements(self) -> None:
        doc = self.doc
        text = "\n".join(plain_text(doc.kind, ln.text) for ln in doc.lines[doc.frontmatter_end :])
        headings = " ".join(s.title for s in doc.sections)
        for code, pat in STATEMENT_PATTERNS.items():
            if not pat.search(text) and not pat.search(headings):
                self.add(
                    self.first_line(),
                    "warning",
                    f"statement.{code}",
                    f"no {code.replace('-', ' ')} statement found",
                    STATEMENT_FIX[code],
                )

    # -- house style
    def check_style(self) -> None:
        doc = self.doc
        in_code = False
        for ln in doc.lines:
            t = ln.text
            if doc.kind == "markdown":
                if t.strip().startswith("```") or t.strip().startswith("~~~"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
            if EM_DASH in t:
                self.add(
                    ln,
                    "error",
                    "style.em-dash",
                    "em-dash (U+2014)",
                    "use a comma, colon, semicolon or parentheses, or split the sentence",
                )
            if (
                doc.kind == "latex"
                and re.search(r"(?<!-)---(?!-)", t)
                and not t.strip().startswith("\\")
            ):
                self.add(
                    ln,
                    "error",
                    "style.em-dash",
                    "LaTeX em-dash (---)",
                    "use a comma, colon, semicolon or parentheses, or split the sentence",
                )
            plain = plain_text(doc.kind, t)
            for label, pat in BANNED_PHRASES:
                if pat.search(plain):
                    self.add(
                        ln,
                        "warning",
                        "style.phrase",
                        f"{label!r}",
                        "say the thing without announcing it",
                    )
        for s in doc.sections:
            if s.role in ("references", "appendix"):
                continue
            if heading_is_title_case(s.title, self.acronyms):
                self.add(
                    doc.lines[s.start],
                    "warning",
                    "style.title-case",
                    f"heading looks Title Case: {s.title!r}",
                    "sentence case unless the venue's template requires otherwise",
                )

    def run(self) -> list[Finding]:
        self.check_abstract()
        self.check_sections()
        self.check_introduction()
        self.check_floats()
        self.check_citations()
        self.check_acronyms()
        self.check_statements()
        self.check_style()
        order = {"error": 0, "warning": 1, "info": 2}
        self.findings.sort(key=lambda f: (order[f.severity], f.path, f.line, f.code))
        return self.findings


def heading_is_title_case(text: str, allow: set[str]) -> bool:
    words = plain_text("markdown", text).split()
    if len(words) < 3:
        return False
    caps = 0
    ordinary = 0
    for word in words[1:]:
        bare = word.strip("\"'()[]{}:;,.!?*_")
        if not bare or bare.isupper() or bare in allow or any(ch.isdigit() for ch in bare):
            continue
        ordinary += 1
        if re.match(r"^[A-Z][a-z]", bare):
            caps += 1
    return ordinary >= 2 and caps >= 2 and caps / ordinary > 0.6


# --------------------------------------------------------------------------- cli


def load_acronyms(path: Path | None) -> set[str]:
    out: set[str] = set()
    if path and path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            s = raw.split("#", 1)[0].strip()
            if s:
                out.add(s.upper())
    return out


def lint_file(
    path: Path, bib: Iterable[Path], acronyms: set[str], abstract_max: int, strict: bool
) -> list[Finding]:
    kind = "latex" if path.suffix.lower() in (".tex", ".ltx", ".latex") else "markdown"
    lines = load_latex(path) if kind == "latex" else load_markdown(path)
    doc = (
        parse_latex(lines, path.parent, list(bib))
        if kind == "latex"
        else parse_markdown(lines, path.parent, list(bib))
    )
    return Linter(doc, acronyms, abstract_max, strict).run()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("manuscript", type=Path, help="main .tex or .md file")
    p.add_argument(
        "--bib",
        type=Path,
        action="append",
        default=[],
        help="bibliography file (repeatable); overrides the manuscript's own",
    )
    p.add_argument(
        "--acronyms",
        type=Path,
        default=DEFAULT_ACRONYMS,
        help="allowlist of acronyms needing no definition",
    )
    p.add_argument(
        "--abstract-max", type=int, default=250, help="abstract word budget (default 250)"
    )
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    p.add_argument("--quiet", action="store_true", help="hide info findings")
    args = p.parse_args(argv)
    if not args.manuscript.exists():
        print(f"error: {args.manuscript} not found", file=sys.stderr)
        return 2
    findings = lint_file(
        args.manuscript, args.bib, load_acronyms(args.acronyms), args.abstract_max, args.strict
    )
    shown = [f for f in findings if not (args.quiet and f.severity == "info")]
    if args.json:
        print(json.dumps([asdict(f) for f in shown], indent=2))
    else:
        for f in shown:
            print(f.render())
        counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
        print(f"{counts['error']} errors, {counts['warning']} warnings, {counts['info']} info")
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
