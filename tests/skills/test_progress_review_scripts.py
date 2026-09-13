"""Tests for the progress-review skill scripts (collect_evidence.py, rubric_report.py)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "progress-review"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "assets" / "progress-report.md"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


collect_evidence = load("collect_evidence")
rubric_report = load("rubric_report")

ORG = """\
#+TITLE: Alex

* Notes

** 20 August 2026, benchmark plan
- [ ] write success criteria (Alex) <2026-08-27 Thu>
- [x] share the dataset list
- source: 1:1

** 6 Aug 2026
- discussed the leakage problem

** Meeting 3 March 2026
- [ ] old item

** Ideas
- no date here
"""


def git(repo: Path, *args: str, date: str | None = None, author: str = "Alex Example") -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": f"{author.split()[0].lower()}@example.org",
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": f"{author.split()[0].lower()}@example.org",
        }
    )
    if date:
        env["GIT_AUTHOR_DATE"] = f"{date}T10:00:00+03:00"
        env["GIT_COMMITTER_DATE"] = f"{date}T10:00:00+03:00"
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q")
    (r / "a.py").write_text("print(1)\n")
    git(r, "add", "a.py")
    git(r, "commit", "-q", "-m", "first commit", date="2026-07-01")
    (r / "a.py").write_text("print(1)\nprint(2)\nprint(3)\n")
    git(r, "add", "a.py")
    git(r, "commit", "-q", "-m", "add benchmark loop", date="2026-08-15")
    (r / "b.py").write_text("x = 1\n")
    git(r, "add", "b.py")
    git(r, "commit", "-q", "-m", "someone else", date="2026-08-20", author="Other Person")
    return r


@pytest.fixture
def students_file(tmp_path: Path, repo: Path) -> Path:
    org = tmp_path / "alex.org"
    org.write_text(ORG, encoding="utf-8")
    draft = tmp_path / "main.tex"
    draft.write_text(
        "\\documentclass{article}\n% comment words\n\\begin{document}\n"
        "We predict protein function with \\emph{ontology} embeddings.\n\\end{document}\n"
    )
    missing_repo = tmp_path / "nowhere"
    data = {
        "students": {
            "alex": {
                "name": "Alex Example",
                "programme": "PhD-CS",
                "start": "2025-01-01",
                "org": str(org),
                "git_authors": ["Alex Example"],
                "repos": [str(repo), str(missing_repo)],
                "drafts": [str(draft), str(tmp_path / "ghost.tex")],
            }
        }
    }
    path = tmp_path / "students.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_parse_heading_date_formats():
    f = collect_evidence.parse_heading_date
    assert f("20 August 2026, benchmark plan") == dt.date(2026, 8, 20)
    assert f("6 Aug 2026") == dt.date(2026, 8, 6)
    assert f("Meeting <2026-05-11 Mon>") == dt.date(2026, 5, 11)
    assert f("Nov 13, 2024") == dt.date(2024, 11, 13)
    assert f("Ideas") is None
    assert f("13 Nov") is None  # no year: undated on purpose


def test_collect_filters_authors_and_assigns_ids(students_file: Path):
    students = collect_evidence.load_students(students_file)
    report = collect_evidence.collect(students, ["alex"], dt.date(2026, 8, 1), dt.date(2026, 9, 1))
    s = report["students"]["alex"]
    good = s["repos"][0]
    assert good["commits"] == 1  # Other Person is filtered out, July commit is outside
    assert good["insertions"] == 2 and good["files_changed"] == 1
    assert good["last_commit"] == "2026-08-15"
    assert good["subjects"] == ["add benchmark loop"]
    assert good["evidence_id"] == "alex-git-01"
    assert s["repos"][1]["exists"] is False
    assert any("alex-git-02" in g for g in s["gaps"])
    dates = [h["date"] for h in s["org"]["headings"]]
    assert dates == ["2026-08-20", "2026-08-06"]
    assert s["org"]["headings"][0]["open_items"] == 1
    assert s["org"]["headings"][0]["done_items"] == 1
    assert s["org"]["last_dated_heading"] == "2026-08-20"
    ids = [e["id"] for e in s["evidence"]]
    assert ids == ["alex-git-01", "alex-org-01", "alex-org-02", "alex-draft-01"]
    draft = s["drafts"][0]
    assert draft["words"] == 7  # comment and commands stripped
    assert any("ghost.tex" in g for g in s["gaps"])
    assert report["privacy"] == "local-only"


def test_collect_unknown_student_fails(students_file: Path):
    students = collect_evidence.load_students(students_file)
    with pytest.raises(collect_evidence.EvidenceError):
        collect_evidence.collect(students, ["nobody"], dt.date(2026, 8, 1), dt.date(2026, 9, 1))


def test_draft_changed_after_window_is_not_counted(tmp_path: Path):
    draft = tmp_path / "future.tex"
    draft.write_text("Future draft\n", encoding="utf-8")
    future = dt.datetime(2026, 9, 15, tzinfo=dt.UTC).timestamp()
    os.utime(draft, (future, future))
    evidence = collect_evidence.draft_evidence(str(draft), dt.date(2026, 8, 1), dt.date(2026, 9, 1))
    assert evidence[0]["changed_since"] is False


def test_collect_cli_writes_json_and_markdown(students_file: Path, tmp_path: Path, capsys):
    out = tmp_path / "ev.json"
    rc = collect_evidence.main(
        [
            "--students",
            str(students_file),
            "--since",
            "2026-08-01",
            "--until",
            "2026-09-01",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text())
    assert "alex" in data["students"]
    rc = collect_evidence.main(
        ["--students", str(students_file), "--since", "2026-08-01", "--format", "md"]
    )
    assert rc == 0
    text = capsys.readouterr().out
    assert "| alex-git-01 | git |" in text


def _evidence(students_file: Path) -> dict:
    students = collect_evidence.load_students(students_file)
    return collect_evidence.collect(students, ["alex"], dt.date(2026, 8, 1), dt.date(2026, 9, 1))


def _scores(**overrides) -> dict:
    base = {
        "question_and_plan": {"score": 3, "evidence": ["alex-org-01"]},
        "evidence_velocity": {"score": 4, "evidence": ["alex-git-01"]},
        "rigor": {"score": "no evidence", "evidence": []},
        "writing": {"score": 2, "evidence": ["alex-draft-01"], "note": "intro only"},
        "milestone": {"score": 3, "evidence": ["alex-org-01"]},
        "communication": {"score": 4, "evidence": ["alex-org-01", "alex-org-02"]},
        "independence": {"score": 3, "evidence": ["alex-org-02"]},
        "agenda": ["success criteria"],
    }
    base.update(overrides)
    return {"alex": base}


def test_rubric_report_renders(students_file: Path):
    text = rubric_report.build_report(
        _evidence(students_file), _scores(), "alex", TEMPLATE.read_text(), 21
    )
    assert "# Progress review: Alex Example (alex)" in text
    assert "| Writing progress | 2 | alex-draft-01 | intro only |" in text
    assert "| Methodological rigor | no evidence | (none) |" in text
    assert "alex-git-02: repository missing" in text
    assert "- success criteria" in text
    assert "{{" not in text


def test_rubric_report_rejects_score_without_evidence(students_file: Path):
    scores = _scores(rigor={"score": 2, "evidence": []})
    with pytest.raises(rubric_report.ReportError, match="cites no evidence id"):
        rubric_report.build_report(_evidence(students_file), scores, "alex", "x", 21)


def test_rubric_report_rejects_unknown_id_and_bad_score(students_file: Path):
    scores = _scores(writing={"score": 2, "evidence": ["alex-draft-99"]})
    with pytest.raises(rubric_report.ReportError, match="not in evidence file"):
        rubric_report.build_report(_evidence(students_file), scores, "alex", "x", 21)
    scores = _scores(writing={"score": 7, "evidence": ["alex-draft-01"]})
    with pytest.raises(rubric_report.ReportError, match="must be 1 to 5"):
        rubric_report.build_report(_evidence(students_file), scores, "alex", "x", 21)
    scores = _scores()
    del scores["alex"]["independence"]
    with pytest.raises(rubric_report.ReportError, match="missing"):
        rubric_report.build_report(_evidence(students_file), scores, "alex", "x", 21)


def test_rubric_report_flags_stale(students_file: Path):
    ev = _evidence(students_file)
    flags = rubric_report.compute_flags(ev["students"]["alex"], dt.date(2026, 9, 30), 21)
    assert any("last commit 2026-08-15" in f for f in flags)
    assert any("last dated entry 2026-08-20" in f for f in flags)


def test_rubric_report_cli(students_file: Path, tmp_path: Path, capsys):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps(_evidence(students_file)))
    sc = tmp_path / "scores.yaml"
    sc.write_text(yaml.safe_dump(_scores()))
    out = tmp_path / "report.md"
    rc = rubric_report.main(
        ["--evidence", str(ev), "--scores", str(sc), "--student", "alex", "--out", str(out)]
    )
    assert rc == 0 and out.exists()
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(_scores(rigor={"score": 1, "evidence": []})))
    rc = rubric_report.main(["--evidence", str(ev), "--scores", str(bad), "--student", "alex"])
    assert rc == 2
    assert "cites no evidence id" in capsys.readouterr().err
    rc = rubric_report.main(["--example"])
    assert rc == 0
    example = yaml.safe_load(capsys.readouterr().out)
    assert set(k for k, _ in rubric_report.DIMENSIONS) <= set(example["alex"])
