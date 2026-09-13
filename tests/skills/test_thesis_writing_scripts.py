"""Behavioral tests for the thesis-writing deterministic helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMELINE = ROOT / "skills" / "thesis-writing" / "scripts" / "thesis_timeline.py"
LINT = ROOT / "skills" / "thesis-writing" / "scripts" / "chapter_lint.py"


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], text=True, capture_output=True, check=False
    )


def test_scripts_answer_help() -> None:
    assert run(TIMELINE, "--help").returncode == 0
    assert run(LINT, "--help").returncode == 0


def test_timeline_includes_six_week_committee_deadline_and_sources() -> None:
    result = run(
        TIMELINE,
        "--defense",
        "2030-10-15",
        "--programme",
        "phd",
        "--committee-size",
        "4",
        "--registrar-deadline",
        "2030-07-01",
        "--dean-deadline",
        "2030-08-01",
        "--today",
        "2030-01-01",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    committee = next(item for item in plan["official"] if item["id"] == "committee-copy")
    assert committee["date"] == "2030-09-03"
    assert committee["source"] == "kaust-graduate-affairs-thesis-policy"
    assert committee["verified_on"] == "2026-09-02"
    assert any(item["id"] == "chapter-drafts" for item in plan["internal"])


def test_timeline_rejects_wrong_committee_size_with_rule() -> None:
    result = run(
        TIMELINE,
        "--defense",
        "2030-10-15",
        "--programme",
        "ms-thesis",
        "--committee-size",
        "5",
        "--today",
        "2030-01-01",
    )
    assert result.returncode == 2
    assert "violates KAUST rule" in result.stderr
    assert "kaust-registrar-program-guide" in result.stderr


def test_chapter_lint_accepts_structurally_grounded_latex(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.tex"
    chapter.write_text(
        r"""\chapter{Results}
\section{Contribution}
This chapter establishes the contribution from the evidence \cite{evidence}.
\section{Related work}
Unlike prior methods \cite{prior}, this chapter establishes a reproducible result \cite{evidence}.
Let $x$ denote the measured score \cite{metric}.
As shown in Figure~\ref{fig:result}, the score is reproducible \cite{evidence}.
\begin{figure}
\caption{Measured score.}
\label{fig:result}
\end{figure}
As shown in Table~\ref{tab:result}, the comparison is complete \cite{evidence}.
\begin{table}
\caption{Comparison.}
\label{tab:result}
\end{table}
Knowledge Graph (KG) provides the representation \cite{kg}.
KG is used for the final analysis \cite{kg}.
""",
        encoding="utf-8",
    )
    result = run(LINT, str(chapter), "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["errors"] == 0


def test_chapter_lint_reports_actionable_errors(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text(
        "# Related Work\nA system is useful.\n![result](result.png)\n", encoding="utf-8"
    )
    result = run(LINT, str(chapter), "--json")
    assert result.returncode == 1
    codes = {item["code"] for item in json.loads(result.stdout)["findings"]}
    assert {
        "chapter-contribution",
        "related-work-citations",
        "related-work-positioning",
        "figure-label",
        "uncited-claim",
    } <= codes
