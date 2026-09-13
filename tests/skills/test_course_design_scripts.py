"""Tests for the course-design skill scripts (alignment_matrix.py, syllabus_build.py)."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "course-design"
SCRIPTS = SKILL / "scripts"
EXAMPLE = SKILL / "assets" / "course.yaml.example"
TEMPLATE = SKILL / "assets" / "syllabus-template.md"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


alignment_matrix = load("alignment_matrix")
syllabus_build = load("syllabus_build")


@pytest.fixture
def example() -> dict:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def write_course(tmp_path: Path, data: dict, name: str = "course.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def run(script: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        timeout=300,
    )


# ------------------------------------------------------------ alignment matrix


def test_help_exits_zero():
    for script in ("alignment_matrix.py", "syllabus_build.py"):
        proc = run(script, "--help")
        assert proc.returncode == 0, proc.stderr
        assert "--course" in proc.stdout


def test_example_is_aligned(example):
    result = alignment_matrix.analyse(example)
    assert result["ok"], result["errors"]
    assert result["warnings"] == []
    assert abs(result["total_weight"] - 100) < 1e-9
    for o in result["outcomes"]:
        assert o["assessed_by"], o["id"]
        assert o["practised_by"], o["id"]


def test_example_cli_markdown_and_json():
    proc = run("alignment_matrix.py", "--course", str(EXAMPLE))
    assert proc.returncode == 0, proc.stderr
    assert "## Outcomes by assessments" in proc.stdout
    assert "No findings" in proc.stdout
    proc = run("alignment_matrix.py", "--course", str(EXAMPLE), "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert {o["id"] for o in data["outcomes"]} == {"O1", "O2", "O3", "O4", "O5", "O6"}
    assert data["matrix"]["assessments"]["O2"][0]["id"] == "E2"


def test_unassessed_outcome_fails(tmp_path, example):
    data = copy.deepcopy(example)
    data["outcomes"].append(
        {"id": "O9", "text": "Explain something nobody tests", "level": "understand"}
    )
    data["activities"][0]["serves"].append("O9")
    proc = run("alignment_matrix.py", "--course", str(write_course(tmp_path, data)))
    assert proc.returncode == 2
    assert "outcome O9 is never assessed" in proc.stdout


def test_orphan_assessment_fails(tmp_path, example):
    data = copy.deepcopy(example)
    data["assessments"][0]["tests"] = []
    result = alignment_matrix.analyse(data)
    assert not result["ok"]
    assert any("tests no declared outcome" in e for e in result["errors"])
    data["assessments"][0]["tests"] = ["O42"]
    result = alignment_matrix.analyse(data)
    assert any("unknown outcome 'O42'" in e for e in result["errors"])


def test_activity_below_outcome_level_fails(example):
    data = copy.deepcopy(example)
    # T3 (create) serves O2 (create); demote it to a lecture at understand
    t3 = next(t for t in data["activities"] if t["id"] == "T3")
    t3["level"] = "understand"
    result = alignment_matrix.analyse(data)
    assert not result["ok"]
    assert any(
        "activity T3 (understand) practises below outcome O2 (create)" in e
        for e in result["errors"]
    )


def test_weights_must_sum_to_100(tmp_path, example):
    data = copy.deepcopy(example)
    data["assessments"][0]["weight"] = 15
    proc = run("alignment_matrix.py", "--course", str(write_course(tmp_path, data)), "--json")
    assert proc.returncode == 2
    out = json.loads(proc.stdout)
    assert any("sum to 105, not 100" in e for e in out["errors"])


def test_unknown_level_is_refused(example):
    data = copy.deepcopy(example)
    data["outcomes"][0]["level"] = "master"
    with pytest.raises(alignment_matrix.DesignError, match="unknown Bloom level"):
        alignment_matrix.analyse(data)


def test_level_aliases_normalise():
    assert alignment_matrix.normalise_level("Analyse", "x") == "analyze"
    assert alignment_matrix.normalise_level("synthesis", "x") == "create"
    assert alignment_matrix.normalise_level("Remembering", "x") == "remember"


def test_warnings_and_strict(tmp_path, example):
    data = copy.deepcopy(example)
    # E3 (evaluate, tests O3) is due in week 8; move the only O3 activities after it
    for t in data["activities"]:
        if t["id"] == "T4":
            t["weeks"] = [12]
    for w in data["weeks"]:
        if "activities" in w and "T4" in w["activities"]:
            w["activities"].remove("T4")
    result = alignment_matrix.analyse(data)
    assert result["ok"]
    assert any(
        "E3 is due in week 8 before any activity for outcome O3" in w for w in result["warnings"]
    )
    proc = run("alignment_matrix.py", "--course", str(write_course(tmp_path, data)), "--strict")
    assert proc.returncode == 2
    proc = run("alignment_matrix.py", "--course", str(write_course(tmp_path, data)))
    assert proc.returncode == 0


def test_low_level_only_warning():
    data = {
        "course": {"code": "X 100", "title": "t"},
        "outcomes": [{"id": "O1", "text": "Recall facts", "level": "remember"}],
        "assessments": [
            {"id": "E1", "title": "quiz", "level": "remember", "tests": ["O1"], "weight": 100}
        ],
        "activities": [{"id": "T1", "title": "lecture", "level": "remember", "serves": ["O1"]}],
    }
    result = alignment_matrix.analyse(data)
    assert result["ok"]
    assert any("remember or understand" in w for w in result["warnings"])


def test_duplicate_ids_refused(example):
    data = copy.deepcopy(example)
    data["activities"][0]["id"] = "O1"
    with pytest.raises(alignment_matrix.DesignError, match="unique"):
        alignment_matrix.analyse(data)


def test_matrix_out_file(tmp_path):
    out = tmp_path / "matrix.md"
    proc = run("alignment_matrix.py", "--course", str(EXAMPLE), "--out", str(out))
    assert proc.returncode == 0
    assert out.exists() and "Alignment matrix" in out.read_text(encoding="utf-8")


# -------------------------------------------------------------- syllabus build


def test_syllabus_stdout_markdown():
    proc = run("syllabus_build.py", "--course", str(EXAMPLE))
    assert proc.returncode == 0, proc.stderr
    md = proc.stdout
    assert md.startswith("# CS 3XX: Bio-ontologies and knowledge graphs for biology")
    for heading in (
        "## Learning outcomes",
        "## Assessment",
        "## Grading",
        "## Week plan",
        "## Policies",
        "## Materials, license and reuse",
    ):
        assert heading in md
    assert "{{" not in md
    assert "B-" in md
    assert "| 14 | Project presentations and peer review |" in md
    assert "—" not in md


def test_template_unknown_placeholder_is_error():
    with pytest.raises(syllabus_build.BuildError, match="unknown placeholders"):
        syllabus_build.render_markdown("# {{nope}}", {"code": "x"})


def test_syllabus_refuses_broken_design(tmp_path, example):
    data = copy.deepcopy(example)
    data["assessments"][0]["weight"] = 1
    course = write_course(tmp_path, data)
    proc = run("syllabus_build.py", "--course", str(course))
    assert proc.returncode == 2
    assert "ALIGNMENT ERROR" in proc.stderr
    proc = run("syllabus_build.py", "--course", str(course), "--skip-alignment")
    assert proc.returncode == 0
    assert "do not publish" in proc.stderr


def test_out_outside_repo_is_dry_run_without_apply(tmp_path):
    out = tmp_path / "syllabus"
    proc = run("syllabus_build.py", "--course", str(EXAMPLE), "--out", str(out), "--json")
    assert proc.returncode == 0, proc.stderr
    assert "DRY RUN" in proc.stderr
    assert not out.exists()
    summary = json.loads(proc.stdout)
    assert summary["dry_run"] is True and summary["written"] == []


def test_out_with_apply_writes_md_and_org(tmp_path):
    out = tmp_path / "syllabus"
    proc = run(
        "syllabus_build.py", "--course", str(EXAMPLE), "--out", str(out), "--apply", "--json"
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    md = out / "cs-3xx-syllabus.md"
    org = out / "cs-3xx-syllabus.org"
    assert md.exists() and org.exists()
    assert set(summary["written"]) == {str(md), str(org)}
    org_text = org.read_text(encoding="utf-8")
    assert org_text.startswith("#+TITLE: CS 3XX: Bio-ontologies and knowledge graphs for biology")
    assert "\n* Learning outcomes\n" in org_text
    assert "|---+---+---+---|" in org_text
    assert "*Attendance.*" in org_text
    assert "## " not in org_text


def test_out_inside_repo_needs_no_apply(tmp_path):
    out = REPO / "runs" / "_test_course_design"
    shutil.rmtree(out, ignore_errors=True)
    try:
        proc = run(
            "syllabus_build.py", "--course", str(EXAMPLE), "--out", str(out), "--formats", "md"
        )
        assert proc.returncode == 0, proc.stderr
        assert (out / "cs-3xx-syllabus.md").exists()
        assert not (out / "cs-3xx-syllabus.org").exists()
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_pdf_degrades_clearly_without_tools(tmp_path):
    out = tmp_path / "syllabus"
    env = os.environ.copy()
    env["PATH"] = str(tmp_path / "empty-bin")
    (tmp_path / "empty-bin").mkdir()
    proc = run(
        "syllabus_build.py",
        "--course",
        str(EXAMPLE),
        "--out",
        str(out),
        "--apply",
        "--formats",
        "md,pdf",
        "--json",
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PDF skipped" in proc.stderr
    summary = json.loads(proc.stdout)
    assert str(out / "cs-3xx-syllabus.md") in summary["written"]
    assert str(out / "cs-3xx-syllabus.pdf") in summary["skipped"]


@pytest.mark.skipif(
    not (shutil.which("pandoc") or shutil.which("latexmk"))
    or not (shutil.which("xelatex") or shutil.which("pdflatex")),
    reason="no PDF tooling on PATH",
)
def test_pdf_builds_when_tooling_present(tmp_path):
    out = tmp_path / "syllabus"
    proc = run(
        "syllabus_build.py",
        "--course",
        str(EXAMPLE),
        "--out",
        str(out),
        "--apply",
        "--formats",
        "pdf",
        "--json",
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    pdf = out / "cs-3xx-syllabus.pdf"
    assert pdf.exists(), summary
    assert pdf.read_bytes()[:4] == b"%PDF"
    assert not (out / "cs-3xx-syllabus.md").exists()


def test_markdown_to_latex_escapes_and_tables():
    md = (
        "# Title\n\n## Section\n\nText with 100% & _under_.\n\n"
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n- item one\n- item two\n"
    )
    tex = syllabus_build.markdown_to_latex(md)
    assert r"\section*{Section}" in tex
    assert r"100\% \& \_under\_" in tex
    assert r"\begin{longtable}" in tex and r"\textbf{A} & \textbf{B}" in tex
    assert tex.count(r"\item") == 2
    assert r"\end{document}" in tex
