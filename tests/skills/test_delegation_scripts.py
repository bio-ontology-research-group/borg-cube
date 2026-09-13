# ruff: noqa: E501
"""Tests for the delegation skill scripts (beads_from_plan.py, dependency_check.py, worker_brief.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "delegation"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"dg_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


beads_from_plan = load("beads_from_plan")
dependency_check = load("dependency_check")
worker_brief = load("worker_brief")

PLAN_MD = """\
# Plan: audit the deepgo repository

Goal: a reviewed audit report with a fix list for deepgo
Pattern: chain
Provenance: bead cube-12; ~/org/papers.org::DeepGO Protocol
Review by: senior

## Bead: Collect repository facts
- id: collect
- kind: audit
- owner: auditor
- privacy: public
- effort: 15 calls
- output: JSON at runs/12/facts.json
- sources: runs/12/repo, skills/code-audit/SKILL.md
- out of scope: judging the findings (bead judge owns it)
- provenance: bead cube-12
Acceptance:
- [ ] `python3 skills/code-audit/scripts/audit_collect.py --repo runs/12/repo --out runs/12/facts.json` exits 0
- [ ] runs/12/facts.json has a license and a tests section

## Bead: Judge and write the report
- id: judge
- kind: audit
- owner: auditor
- depends: collect
- effort: 2h
- output: Markdown report at runs/12/audit.md with a Findings section
- sources: runs/12/facts.json, skills/code-audit/references/research-software-practice.md
- out of scope: fixing anything in the repository
Acceptance:
- [ ] every finding line in runs/12/audit.md names file:line, severity and fix
- [ ] the report lists at least 1 high or medium finding or states that none was found

## Bead: Review the report
- kind: review
- owner: senior
- depends: judge
- output: review comment on bead judge
- sources: runs/12/audit.md
- out of scope: re-auditing the repository
Acceptance:
- [ ] reviewer confirms each finding cites a file:line or a command output
"""

PLAN_BAD = """\
# Plan: vague

Goal: improve things
Pattern: single
Provenance: bead cube-13

## Bead: Make it better
- owner: programmer
- output: nicer code
- sources: cube/
- out of scope: tests
Acceptance:
"""

PLAN_YAML = """\
goal: two independent lookups then a merge
pattern: parallel
provenance: [bead cube-14]
review_by: group-leader
beads:
  - id: a
    title: Lookup A
    kind: research
    owner: senior
    privacy: internal
    output: runs/14/a.md
    sources: [corpus/text/wilson2014.txt]
    out of scope: lookup B
    acceptance: ["runs/14/a.md lists at least 3 practices with page numbers"]
  - id: b
    title: Lookup B
    kind: research
    owner: senior
    privacy: internal
    output: runs/14/b.md
    sources: [corpus/text/wilson2017.txt]
    out of scope: lookup A
    acceptance: ["runs/14/b.md lists at least 3 practices with page numbers"]
  - id: merge
    title: Merge the lookups
    kind: writing
    owner: editor
    privacy: internal
    depends: a, b
    output: runs/14/merged.md
    sources: [runs/14/a.md, runs/14/b.md]
    out of scope: new lookups
    acceptance: ["runs/14/merged.md has one table with a row per practice"]
"""


def test_markdown_plan_becomes_valid_beads(tmp_path: Path, capsys) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN_MD, encoding="utf-8")
    out = tmp_path / "beads.json"
    rc = beads_from_plan.main(["--plan", str(plan), "--out", str(out), "--strict", "--bd-commands"])
    assert rc == 0, capsys.readouterr().err
    printed = capsys.readouterr().out
    assert "bd create" in printed and "bd dep add judge collect" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["goal"] == "a reviewed audit report with a fix list for deepgo"
    assert data["pattern"] == "chain"
    assert data["review_by"] == "senior"
    ids = [b["id"] for b in data["beads"]]
    assert ids == ["collect", "judge", "review-the-report"]
    judge = data["beads"][1]
    assert judge["depends_on"] == ["collect"]
    assert judge["owner_role"] == "auditor"
    assert judge["privacy"] == "internal"  # header default
    assert judge["provenance"] == ["bead cube-12", "~/org/papers.org::DeepGO Protocol"]
    assert data["beads"][0]["provenance"] == ["bead cube-12"]
    assert len(judge["acceptance_criteria"]) == 2
    assert judge["review_by"] == "senior"
    assert judge["deadline"] is None


def test_plan_without_criteria_fails_and_writes_nothing(tmp_path: Path, capsys) -> None:
    plan = tmp_path / "bad.md"
    plan.write_text(PLAN_BAD, encoding="utf-8")
    out = tmp_path / "beads.json"
    rc = beads_from_plan.main(["--plan", str(plan), "--out", str(out)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "make-it-better: missing acceptance_criteria" in err
    assert not out.exists()


def test_strict_rejects_unverifiable_criterion(tmp_path: Path, capsys) -> None:
    text = PLAN_MD.replace(
        "- [ ] reviewer confirms each finding cites a file:line or a command output",
        "- [ ] looks good overall",
    )
    plan = tmp_path / "plan.md"
    plan.write_text(text, encoding="utf-8")
    assert beads_from_plan.main(["--plan", str(plan)]) == 0  # warning only
    assert "may not be checkable" in capsys.readouterr().err
    assert beads_from_plan.main(["--plan", str(plan), "--strict"]) == 2


def test_yaml_plan_and_schema_enums(tmp_path: Path, capsys) -> None:
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN_YAML, encoding="utf-8")
    out = tmp_path / "beads.json"
    assert beads_from_plan.main(["--plan", str(plan), "--out", str(out)]) == 0, (
        capsys.readouterr().err
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    merge = data["beads"][2]
    assert merge["depends_on"] == ["a", "b"] and merge["owner_role"] == "editor"
    bad = PLAN_YAML.replace("owner: editor", "owner: intern")
    plan.write_text(bad, encoding="utf-8")
    assert beads_from_plan.main(["--plan", str(plan)]) == 2
    assert "owner_role: 'intern' not in" in capsys.readouterr().err


def test_validate_bead_minimal_schema() -> None:
    schema = beads_from_plan.load_schema(ASSETS / "bead.schema.json")
    bead = {
        "id": "x1",
        "title": "Do it",
        "kind": "implement",
        "owner_role": "programmer",
        "privacy": "internal",
        "output": "file",
        "provenance": ["p"],
        "acceptance_criteria": [{"check": "short"}],
    }
    problems = beads_from_plan.validate_bead(bead, schema)
    assert any("check shorter than" in p for p in problems)
    bead["acceptance_criteria"] = [{"check": "`pytest` exits 0"}]
    bead["id"] = "Bad Id"
    problems = beads_from_plan.validate_bead(bead, schema)
    assert any("does not match" in p for p in problems)


def test_dependency_check_waves_and_errors(tmp_path: Path, capsys) -> None:
    plan = tmp_path / "plan.yaml"
    plan.write_text(PLAN_YAML, encoding="utf-8")
    beads = tmp_path / "beads.json"
    assert beads_from_plan.main(["--plan", str(plan), "--out", str(beads)]) == 0
    capsys.readouterr()
    assert dependency_check.main(["--beads", str(beads)]) == 0
    out = capsys.readouterr().out
    assert "wave 1: a, b" in out and "wave 2: merge" in out
    assert "longest chain: 2" in out
    assert "2 beads for role senior" in out
    data = json.loads(beads.read_text(encoding="utf-8"))
    data["beads"][0]["depends_on"] = ["merge"]  # a -> merge -> a cycle
    data["beads"][1]["depends_on"] = ["ghost", "b"]
    beads.write_text(json.dumps(data), encoding="utf-8")
    assert dependency_check.main(["--beads", str(beads), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any("cycle" in e for e in result["errors"])
    assert "b depends on unknown bead 'ghost'" in result["errors"]
    assert "b depends on itself" in result["errors"]
    assert dependency_check.main(["--beads", str(tmp_path / "none.json")]) == 1


def test_worker_brief_render_and_missing_fields(tmp_path: Path, capsys) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(PLAN_MD, encoding="utf-8")
    beads = tmp_path / "beads.json"
    assert beads_from_plan.main(["--plan", str(plan), "--out", str(beads)]) == 0
    capsys.readouterr()
    out = tmp_path / "briefs" / "judge.md"
    assert worker_brief.main(["--beads", str(beads), "--bead", "judge", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert not out.exists() and "[dry-run]" in printed
    assert (
        worker_brief.main(["--beads", str(beads), "--bead", "judge", "--out", str(out), "--apply"])
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Worker brief: Judge and write the report")
    assert "Bead judge (kind audit, owner role auditor, privacy internal, effort budget 2h)" in text
    assert "- every finding line in runs/12/audit.md names file:line, severity and fix" in text
    assert "- runs/12/facts.json" in text and "fixing anything in the repository" in text
    assert "- collect" in text and "Reviewed by senior" in text
    assert "1. The task requires an outbound action" in text
    assert "{{" not in text and "—" not in text
    data = json.loads(beads.read_text(encoding="utf-8"))
    del data["beads"][1]["out_of_scope"]
    data["beads"][1]["privacy"] = "local-only"
    beads.write_text(json.dumps(data), encoding="utf-8")
    assert worker_brief.main(["--beads", str(beads), "--bead", "judge"]) == 2
    assert "lacks out_of_scope" in capsys.readouterr().err
    assert worker_brief.main(["--beads", str(beads), "--bead", "nope"]) == 1
