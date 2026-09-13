# ruff: noqa: E501
"""Tests for the paper-writing skill scripts (paper_lint.py, cite_check.py) on synthetic manuscripts; no network."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "paper-writing"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"pw_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


paper_lint = load("paper_lint")
cite_check = load("cite_check")

GOOD_BIB = """\
@article{mensh2017,
  author = {Mensh, Brett and Kording, Konrad},
  title = {Ten simple rules for structuring papers},
  journal = {PLoS Computational Biology},
  year = {2017},
  volume = {13},
  number = {9},
  pages = {e1005619},
  doi = {10.1371/journal.pcbi.1005619},
}

@article{rougier2014,
  author = {Rougier, Nicolas P. and Droettboom, Michael and Bourne, Philip E.},
  title = {Ten Simple Rules for Better Figures},
  journal = {PLoS Computational Biology},
  year = 2014,
  doi = {10.1371/journal.pcbi.1003833},
  pmid = {25188968},
}

@misc{tool2023,
  title = {A tool},
  author = {Someone, Ann},
  year = {2023},
  url = {https://example.org/tool},
  urldate = {2024-01-05},
}
"""

GOOD_TEX = r"""
\documentclass{article}
\title{Ontology embeddings predict protein function from text}
\begin{document}
\maketitle
\begin{abstract}
Protein function prediction is a central task in computational biology.
However, existing methods rarely use the axioms of the Gene Ontology (GO) and their accuracy remains limited for rare functions.
Here we present a method that embeds ontology axioms together with protein sequences.
We show that it improves the F-measure by 12 percent over the strongest baseline on the Critical Assessment of Function Annotation (CAFA) benchmark.
The approach suggests that formal axioms carry information that sequence alone does not, and it is freely available.
\end{abstract}

\section{Introduction}
Predicting the functions of proteins is a long-standing problem in biology, and the volume of unannotated sequences keeps growing~\cite{mensh2017}.
Most methods use sequence similarity or deep neural networks, but they treat the Gene Ontology as a flat set of labels and ignore its axioms.

The axioms of an ontology constrain which functions can co-occur, and the state of the art (SOTA) does not exploit them.
Whether these constraints improve prediction has not been tested.

In this paper we present an embedding method that uses the axioms and show that it improves prediction on the CAFA benchmark.

\section{Methods}
We describe the data, the model and the evaluation.
The model is trained with a standard deviation (SD) of the loss reported over five seeds.

\section{Results}
\subsection{Axiom embeddings improve rare-function prediction}
To test whether axioms help, we compared the model with three baselines, as shown in Figure~\ref{fig:main} and Table~\ref{tab:results}.
The model outperforms all baselines~\cite{rougier2014}.

\begin{figure}
\centering
\includegraphics{main.pdf}
\caption{Axiom embeddings improve the F-measure on rare functions. Points show five seeds per method; bars show the median. Error bars are the interquartile range.}
\label{fig:main}
\end{figure}

\begin{table}
\caption{F-measure per method on the CAFA benchmark, median over five seeds with interquartile range.}
\label{tab:results}
\end{table}

\section{Discussion}
Our results show that axioms carry information beyond sequence.
One limitation is the size of the benchmark; larger sets may change the ranking.
The method can be applied to any ontology in OWL.

\section{Conclusion}
Axioms improve function prediction; how to scale the method is open.

\section*{Author contributions}
A.B.: conceptualization, software, writing (original draft). R.H.: supervision, writing (review and editing).

\section*{Data and code availability}
Code is available at https://github.com/bio-ontology-research-group/tool and archived at https://doi.org/10.5281/zenodo.1234567; the data are deposited at the same record.

\section*{Competing interests}
The authors declare no competing interests.

\section*{Funding}
This work was supported by KAUST grant URF/1/1234.

\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""

BAD_TEX = r"""
\documentclass{article}
\begin{document}
\begin{abstract}
We present a new method. It works well.
\end{abstract}
\section{Results}
The method uses a GNN and beats everything~\cite{missingkey}. Note that this is important. See Figure~\ref{fig:nothere}.
\begin{figure}
\caption{Results}
\label{fig:unused}
\end{figure}
\section{Introduction}
Proteins are important --- very important for everything that lives, and their functions are hard to predict.
\section{Discussion}
It is good.
\end{document}
"""

GOOD_MD = """\
---
title: Ontology embeddings predict protein function
abstract: |
  Protein function prediction is a central task in computational biology.
  However, existing methods rarely use ontology axioms and their accuracy remains limited.
  Here we present a method that embeds axioms with sequences.
  We show that it improves the F-measure by 12 percent over the strongest baseline.
  This suggests that axioms carry information that sequence alone does not.
bibliography: refs.bib
---

# Introduction

Predicting protein functions is a long-standing problem [@mensh2017].
Existing methods ignore the axioms of the Gene Ontology (GO).

In this work we present an axiom-aware embedding and show that it improves prediction.

# Methods

We describe data, model and evaluation with the standard deviation (SD) over five seeds.

# Results

## Axiom embeddings improve prediction

As @fig:main shows, the model outperforms three baselines [@rougier2014].

![Axiom embeddings improve the F-measure on rare functions; points are five seeds, bars the median.](main.png){#fig:main}

# Discussion

Axioms carry information beyond sequence. One limitation is benchmark size. The method applies to any ontology.

# Author contributions

A.B.: conceptualization, software. R.H.: supervision.

# Data and code availability

Code and data are available at https://doi.org/10.5281/zenodo.1234567.

# Competing interests

None.

# Funding

Supported by KAUST grant URF/1/1234.
"""


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, check=False
    )


@pytest.fixture
def paper_dir(tmp_path: Path) -> Path:
    (tmp_path / "refs.bib").write_text(GOOD_BIB, encoding="utf-8")
    (tmp_path / "main.tex").write_text(GOOD_TEX, encoding="utf-8")
    (tmp_path / "paper.md").write_text(GOOD_MD, encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- paper_lint


def test_help_exits_zero():
    for script in ("paper_lint.py", "cite_check.py"):
        proc = run(script, "--help")
        assert proc.returncode == 0, proc.stderr
        assert "usage" in proc.stdout.lower()


def test_good_latex_manuscript_has_no_errors(paper_dir: Path):
    findings = paper_lint.lint_file(
        paper_dir / "main.tex", [], paper_lint.load_acronyms(ASSETS / "acronyms.txt"), 250, False
    )
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], [f.render() for f in errors]
    codes = {f.code for f in findings}
    assert "sections.words" in codes
    # tool2023 is in the .bib but never cited: orphan warning with the bib path and line
    orphans = [f for f in findings if f.code == "cite.orphan"]
    assert len(orphans) == 1 and orphans[0].path.endswith("refs.bib") and orphans[0].line > 1
    assert "tool2023" in orphans[0].message
    # acronyms defined at first use (GO, SOTA, CAFA, SD) raise nothing
    assert not [f for f in findings if f.code == "acronym.undefined"], [
        f.render() for f in findings if f.code == "acronym.undefined"
    ]


def test_good_markdown_manuscript_has_no_errors(paper_dir: Path):
    findings = paper_lint.lint_file(
        paper_dir / "paper.md", [], paper_lint.load_acronyms(ASSETS / "acronyms.txt"), 250, False
    )
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], [f.render() for f in errors]
    assert not [f for f in findings if f.code.startswith("statement.")]


def test_bad_manuscript_reports_structure_problems(paper_dir: Path):
    (paper_dir / "bad.tex").write_text(BAD_TEX, encoding="utf-8")
    findings = paper_lint.lint_file(
        paper_dir / "bad.tex", [paper_dir / "refs.bib"], set(), 250, False
    )
    codes = {f.code for f in findings}
    assert "abstract.shape" in codes  # two sentences, no gap
    assert "sections.order" in codes  # introduction after results
    assert "intro.contribution" in codes
    assert "figure.unreferenced" in codes
    assert "ref.undefined" in codes
    assert "cite.undefined" in codes
    assert "caption.short" in codes
    assert "style.em-dash" in codes  # LaTeX ---
    assert "style.phrase" in codes  # Note that
    assert "acronym.undefined" in codes  # GNN
    assert "statement.credit" in codes and "statement.data-availability" in codes
    for f in findings:
        assert f.line >= 0 and f.fix
    em = next(f for f in findings if f.code == "style.em-dash")
    assert em.path.endswith("bad.tex") and em.line == 14
    assert any(f.severity == "error" for f in findings)


def test_strict_promotes_warnings(paper_dir: Path):
    warn = paper_lint.lint_file(paper_dir / "main.tex", [], set(), 250, False)
    strict = paper_lint.lint_file(paper_dir / "main.tex", [], set(), 250, True)
    assert any(f.severity == "warning" for f in warn)
    assert not any(f.severity == "warning" for f in strict)


def test_abstract_order_and_missing_moves():
    lines = [
        paper_lint.Line(t, "x.md", i)
        for i, t in enumerate(
            [
                "# Abstract",
                "",
                "We show a 10 percent improvement. Here we present a method. Prediction is a central task. However, it remains hard. This enables new studies.",
                "",
                "# Introduction",
                "",
                "Text here that is long enough to count as a paragraph of prose. In this work we present it.",
                "# Results",
                "Body words words words words words words words.",
                "# Discussion",
                "Body words words words words words words words.",
            ],
            1,
        )
    ]
    doc = paper_lint.parse_markdown(lines, Path("."), [])
    findings = paper_lint.Linter(doc, set(), 250, False).run()
    assert any(f.code == "abstract.order" for f in findings)


def test_latex_input_expansion_keeps_file_and_line(tmp_path: Path):
    (tmp_path / "intro.tex").write_text(
        "\\section{Introduction}\nProteins matter\u2014a lot.\n", encoding="utf-8"
    )
    (tmp_path / "main.tex").write_text(
        "\\begin{document}\n\\begin{abstract}\nA. B. C. D.\n\\end{abstract}\n\\input{intro}\n\\end{document}\n",
        encoding="utf-8",
    )
    findings = paper_lint.lint_file(tmp_path / "main.tex", [], set(), 250, False)
    em = [f for f in findings if f.code == "style.em-dash"]
    assert em and em[0].path.endswith("intro.tex") and em[0].line == 2


def test_cli_json_and_exit_code(paper_dir: Path):
    proc = run("paper_lint.py", str(paper_dir / "main.tex"), "--json", "--quiet")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and all(
        {"path", "line", "severity", "code", "message", "fix"} <= set(d) for d in data
    )
    (paper_dir / "bad.tex").write_text(BAD_TEX, encoding="utf-8")
    proc = run("paper_lint.py", str(paper_dir / "bad.tex"), "--bib", str(paper_dir / "refs.bib"))
    assert proc.returncode == 1
    assert "bad.tex:" in proc.stdout and "error:" in proc.stdout and "fix:" in proc.stdout
    assert run("paper_lint.py", str(paper_dir / "nope.tex")).returncode == 2


def test_missing_bibliography_file_is_an_error(tmp_path: Path):
    (tmp_path / "m.tex").write_text(
        "\\begin{document}\\begin{abstract}A. B. C. D.\\end{abstract}\\section{Introduction}x~\\cite{k}\\bibliography{none}\\end{document}",
        encoding="utf-8",
    )
    findings = paper_lint.lint_file(tmp_path / "m.tex", [], set(), 250, False)
    assert any(f.code == "bib.missing" and f.severity == "error" for f in findings)


def test_empty_bibliography_still_reports_undefined_citation(tmp_path: Path):
    (tmp_path / "refs.bib").write_text("", encoding="utf-8")
    (tmp_path / "m.tex").write_text(
        "\\begin{document}\\cite{missing}\\bibliography{refs}\\end{document}",
        encoding="utf-8",
    )
    findings = paper_lint.lint_file(tmp_path / "m.tex", [], set(), 250, False)
    assert any(f.code == "cite.undefined" and "missing" in f.message for f in findings)


# --------------------------------------------------------------------------- cite_check


def test_bibtex_parser_handles_braces_quotes_and_numbers(tmp_path: Path):
    bib = tmp_path / "r.bib"
    bib.write_text(
        GOOD_BIB
        + '\n@string{pcb = "PLoS Comput Biol"}\n@article{q, author="A B", title={{Nested} title}, journal=pcb, year=2001, doi={10.1/x}}\n',
        encoding="utf-8",
    )
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []
    keys = {e.key: e for e in entries}
    assert set(keys) == {"mensh2017", "rougier2014", "tool2023", "q"}
    assert keys["rougier2014"].fields["year"] == "2014"
    assert keys["q"].fields["journal"] == "PLoS Comput Biol"
    assert keys["q"].fields["title"] == "{Nested} title"
    assert keys["mensh2017"].line == 1 and keys["rougier2014"].line > keys["mensh2017"].line


def test_cite_checker_matches_literature_review_and_parses_parentheses(tmp_path: Path):
    other = SKILL.parent / "literature-review" / "scripts" / "cite_check.py"
    assert (SCRIPTS / "cite_check.py").read_text(encoding="utf-8") == other.read_text(
        encoding="utf-8"
    )
    bib = tmp_path / "parenthesized.bib"
    bib.write_text("@article(key, title={T}, doi={10.1/x})\n", encoding="utf-8")
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []
    assert [(entry.key, entry.fields["title"], entry.fields["doi"]) for entry in entries] == [
        ("key", "T", "10.1/x")
    ]


def test_offline_checks_find_consistency_problems(tmp_path: Path):
    bib = tmp_path / "r.bib"
    bib.write_text(
        GOOD_BIB
        + """
@article{mensh2017,
  author = {Mensh, Brett and others},
  title = {Ten simple rules for structuring papers},
  journal = {PLoS Comput Biol},
  year = {20177},
  doi = {https://doi.org/10.1371/journal.pcbi.1005619},
}
@article{nodoi,
  author = {Someone, Ann et al.},
  title = {No identifier},
  journal = {J},
  year = {2099},
  url = {https://doi.org/10.1000/hidden},
}
@inproceedings{incomplete,
  title = {Missing things},
  year = {2020},
  pmid = {12ab},
}
@online{web,
  title = {A page},
  url = {https://example.org},
}
@article{mensh2017copy,
  author = {Mensh, Brett and Kording, Konrad},
  title = {Ten simple rules for structuring papers},
  journal = {PLoS Comput Biol},
  year = {2017},
}
""",
        encoding="utf-8",
    )
    entries, _ = cite_check.parse_bibtex(bib)
    findings = cite_check.offline_checks(entries, dt.date(2026, 9, 2))
    codes = {f.code for f in findings}
    assert {
        "bib.duplicate-key",
        "bib.duplicate-doi",
        "bib.duplicate-title",
        "bib.year-format",
        "bib.year-future",
        "bib.author-truncated",
        "bib.doi-in-url",
        "bib.missing-field",
        "bib.pmid-format",
        "bib.url-no-date",
    } <= codes
    assert all(f.path.endswith("r.bib") and f.line > 0 and f.fix for f in findings)


def test_offline_cli_never_touches_network(paper_dir: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):  # pragma: no cover - only runs on regression
        raise AssertionError("network call in offline mode")

    monkeypatch.setattr(cite_check.urllib.request, "urlopen", boom)
    argv = [str(paper_dir / "refs.bib"), "--offline", "--json"]
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cite_check.main(argv)
    data = json.loads(buf.getvalue())
    assert data["offline"] is True and data["entries"] == 3 and data["checked_online"] == 0
    assert rc == 0, data["findings"]
    proc = run("cite_check.py", str(paper_dir / "refs.bib"), "--offline")
    assert proc.returncode == 0 and "offline" in proc.stdout


def test_only_cited_restricts_entries(paper_dir: Path):
    keys = cite_check.cited_keys(paper_dir / "main.tex")
    assert keys == {"mensh2017", "rougier2014"}
    keys_md = cite_check.cited_keys(paper_dir / "paper.md")
    assert keys_md == {"mensh2017", "rougier2014"}


def test_online_checks_with_fake_client(tmp_path: Path):
    bib = tmp_path / "r.bib"
    bib.write_text(GOOD_BIB, encoding="utf-8")
    entries, _ = cite_check.parse_bibtex(bib)

    class FakeClient:
        def get(self, url: str):
            if "filter=updates" in url:
                if "1003833" in url:
                    return 200, {
                        "message": {
                            "items": [
                                {
                                    "DOI": "10.1371/retraction",
                                    "update-to": [
                                        {
                                            "type": "retraction",
                                            "DOI": "10.1371/journal.pcbi.1003833",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                return 200, {"message": {"items": []}}
            if "1005619" in url:
                return 200, {
                    "message": {
                        "title": ["Ten simple rules for structuring papers"],
                        "issued": {"date-parts": [[2017, 9, 28]]},
                        "author": [{"family": "Mensh", "sequence": "first"}, {"family": "Kording"}],
                    }
                }
            if "1003833" in url:
                return 200, {
                    "message": {
                        "title": ["A completely different article about cats"],
                        "issued": {"date-parts": [[2015]]},
                        "author": [{"family": "Nobody", "sequence": "first"}],
                    }
                }
            if "esummary" in url:
                return 200, {
                    "result": {
                        "25188968": {
                            "title": "Ten simple rules for better figures",
                            "pubdate": "2014 Sep",
                            "authors": [{"name": "Rougier NP"}],
                            "articleids": [
                                {"idtype": "doi", "value": "10.1371/journal.pcbi.1003833"}
                            ],
                            "pubtype": ["Journal Article"],
                        }
                    }
                }
            return 404, None

    report = cite_check.Report()
    findings = cite_check.online_checks(entries, FakeClient(), 0.8, report)
    codes = {(f.code, f.message.split(":")[0]) for f in findings}
    assert ("crossref.title-mismatch", "rougier2014") in codes
    assert ("crossref.year-mismatch", "rougier2014") in codes
    assert ("crossref.retracted", "rougier2014") in codes
    assert not any(m == "mensh2017" for _, m in codes)
    assert report.checked_online == 3 and report.skipped_online == 1


def test_unresolvable_doi_is_an_error(tmp_path: Path):
    bib = tmp_path / "r.bib"
    bib.write_text(
        "@article{x, author={A B}, title={T}, journal={J}, year={2020}, doi={10.9999/does.not.exist}}\n",
        encoding="utf-8",
    )
    entries, _ = cite_check.parse_bibtex(bib)

    class Client404:
        def get(self, url: str):
            return 404, None

    findings = cite_check.online_checks(entries, Client404(), 0.8, cite_check.Report())
    assert any(f.code == "crossref.unresolvable" and f.severity == "error" for f in findings)


def test_assets_present_and_consistent():
    venues = (ASSETS / "venues.md").read_text(encoding="utf-8")
    header = next(line for line in venues.splitlines() if line.startswith("| Venue"))
    assert [c.strip() for c in header.strip("|").split("|")] == [
        "Venue",
        "Kind",
        "Deadline pattern",
        "Page limit",
        "Review model",
        "Notes",
    ]
    assert "example row" in venues
    credit = (ASSETS / "credit-roles.md").read_text(encoding="utf-8")
    for role in (
        "Conceptualization",
        "Data curation",
        "Formal analysis",
        "Funding acquisition",
        "Investigation",
        "Methodology",
        "Project administration",
        "Resources",
        "Software",
        "Supervision",
        "Validation",
        "Visualization",
    ):
        assert role in credit
    for name in ("paper-plan.md", "submission-checklist.md", "acronyms.txt"):
        assert (ASSETS / name).exists()
    for path in ASSETS.glob("*.md"):
        assert "\u2014" not in path.read_text(encoding="utf-8"), path
