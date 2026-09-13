"""Tests for the grant-writing deterministic checkers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "grant-writing"
SCRIPTS = SKILL / "scripts"
CALL_CHECKLIST_FILE = SCRIPTS / "call_checklist.py"
AIMS_LINT_FILE = SCRIPTS / "aims_lint.py"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"grant_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


call_checklist = load("call_checklist")
aims_lint = load("aims_lint")


CALL = """\
title: Test call
requirements:
  page_limits:
    - id: aims
      max_pages: 1
  sections:
    - id: aims
      heading: Specific aims
  fonts:
    - id: body
      allowed: [Arial 11 pt]
  annexes:
    - id: cv
      path: annexes/cv.pdf
  deadlines:
    - id: submit
      date: 2099-12-31
  eligibility:
    - id: pi
"""


DRAFT = """\
<!-- pages: aims: 1 -->
<!-- font: body: Arial 11 pt -->
<!-- deadline: submit: 2099-12-31 -->
<!-- eligibility: pi: confirmed-by-Robert -->

# Specific aims

The gap is that current methods do not measure the relevant outcome.

## Aim 1: Measure the baseline

We will measure accuracy. Success criterion: at least 90%. Our preliminary
data establish feasibility. Risk: sparse data. Mitigation: use a validated
fallback cohort.

## Aim 2: Validate the method

We will compare performance and deliver a benchmark. Success criterion: a
documented improvement. Our pilot provides feasibility evidence. Risk: model
failure. Alternative: use a simpler validated method.
"""


def test_call_checklist_complete_call_and_json(tmp_path: Path, capsys) -> None:
    assert CALL_CHECKLIST_FILE.is_file()
    call = tmp_path / "call.yaml"
    call.write_text(CALL, encoding="utf-8")
    annex = tmp_path / "annexes" / "cv.pdf"
    annex.parent.mkdir()
    annex.write_bytes(b"placeholder")
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert (
        call_checklist.main(
            ["--call", str(call), "--draft", str(draft), "--today", "2026-09-02", "--json"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["summary"] == {"mandatory_unmet": 0, "passed": 6, "total": 6, "unmet": 0}


def test_call_checklist_refuses_unverified_mandatory_evidence(tmp_path: Path, capsys) -> None:
    call = tmp_path / "call.yaml"
    call.write_text(CALL, encoding="utf-8")
    draft = tmp_path / "draft.md"
    draft.write_text("# Specific aims\n", encoding="utf-8")
    assert call_checklist.main(["--call", str(call), "--draft", str(draft), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    statuses = {item["id"]: item["status"] for item in result["findings"]}
    assert statuses["aims"] == "unverified"
    assert statuses["body"] == "unverified"
    assert statuses["submit"] == "unverified"
    assert statuses["pi"] == "unverified"


def test_aims_lint_checks_review_properties_and_house_style(tmp_path: Path, capsys) -> None:
    assert AIMS_LINT_FILE.is_file()
    draft = tmp_path / "aims.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert aims_lint.main(["--draft", str(draft), "--strict", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["summary"] == {"aims": 2, "errors": 0, "warnings": 0}
    draft.write_text("# lower heading\nAim 1: Explore.\n", encoding="utf-8")
    assert aims_lint.main(["--draft", str(draft), "--strict"]) == 1
    output = capsys.readouterr().out
    assert "gap:missing" in output and "aim-1:outcome" in output and "style:heading-1" in output
