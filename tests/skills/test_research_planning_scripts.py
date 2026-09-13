# ruff: noqa: E501
"""Tests for the research-planning skill script (plan_to_beads.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "research-planning"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"rp_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


plan_to_beads = load("plan_to_beads")

PLAN = """\
plan: orphan-function
question: Does phenotype similarity add function signal beyond sequence similarity?
privacy: internal
owner: programmer
provenance:
  - ~/org/papers.org::Orphan function transfer
  - bead cube-214
hypotheses:
  - id: h1
    statement: Phenotype embeddings help proteins without a close homolog.
    predicts: Fmax rises on the low-identity subset only.
  - id: h2
    statement: The gain comes from the extra tuning budget.
    predicts: A matched sequence-only model reaches the same Fmax.
experiments:
  - id: e1
    title: Build the split and the baseline table
    tests: [h1, h2]
    baselines: [naive frequency predictor, BLAST label transfer]
    metric: Fmax
    success_threshold: baselines reproduce within 0.02 Fmax
    kill_criterion: not reproducible within 0.05 Fmax after 2 weeks; the plan is rewritten
    deadline: 2026-10-30
    acceptance:
      - runs/orphan/splits.json reports 0 shared clusters
  - id: e2
    title: Train the augmented model at a matched budget
    tests: [h1]
    depends_on: [e1]
    owner: senior
    baselines: [matched sequence-only model]
    metric: Fmax on the low-identity subset
    success_threshold: at least 0.03 Fmax over the best baseline at 40 trials each
    kill_criterion: below 0.01 Fmax at a matched budget; h1 is rejected and the work stops
risks:
  - id: r1
    risk: Phenotype annotations are too sparse.
    likelihood: medium
    impact: high
    mitigation: Fall back to the ortholog-propagated set.
    check: runs/orphan/coverage.json reports the annotated protein count per split
  - id: r2
    risk: A competing group publishes first.
    mitigation: Preprint the split and the baseline table.
checkpoints:
  - id: c1
    date: 2026-10-30
    measure: the baseline table from e1
    decision: continue only if all baselines reproduced
    experiments: [e1]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_plan_becomes_beads_with_headers_and_xids(tmp_path: Path, capsys) -> None:
    plan = write(tmp_path, PLAN)
    out = tmp_path / "beads.json"
    assert plan_to_beads.main(["--plan", str(plan), "--out", str(out), "--json"]) == 0
    captured = capsys.readouterr()
    assert "risk r2: no 'check'" in captured.err
    data = json.loads(captured.out)
    assert data["applied"] is False
    xids = [b["xid"] for b in data["beads"]]
    assert xids == [
        "experiment:orphan-function:e1",
        "experiment:orphan-function:e2",
        "risk:orphan-function:r1",
        "checkpoint:orphan-function:c1",
    ]
    e2 = data["beads"][1]
    assert e2["owner_role"] == "senior"
    assert e2["depends_on"] == ["experiment:orphan-function:e1"]
    assert any("baseline" in c for c in e2["acceptance_criteria"])
    assert any("kill criterion" in c for c in e2["acceptance_criteria"])
    assert data["beads"][0]["deadline"] == "2026-10-30"
    header = plan_to_beads.header_yaml(e2["xid"], e2["provenance"], e2["deadline"], e2["privacy"])
    parsed = yaml.safe_load(header.strip().strip("-"))
    assert parsed["xid"] == "experiment:orphan-function:e2"
    assert parsed["provenance"][0] == {
        "source": "~/org/papers.org",
        "locator": "Orphan function transfer",
    }
    assert parsed["privacy"] == "internal"
    assert json.loads(out.read_text(encoding="utf-8"))["plan"] == "orphan-function"


def test_commands_are_printed_and_nothing_runs(tmp_path: Path, capsys) -> None:
    plan = write(tmp_path, PLAN)
    assert plan_to_beads.main(["--plan", str(plan)]) == 0
    captured = capsys.readouterr()
    assert captured.out.count("bd create") == 4
    assert "--external-ref experiment:orphan-function:e1" in captured.out
    assert "kind:experiment,stage:design,privacy:internal,role:programmer" in captured.out
    assert "dry run, nothing created" in captured.err


def test_apply_failure_does_not_write_a_completed_result(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    plan = write(tmp_path, PLAN)
    out = tmp_path / "result.json"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            return SimpleNamespace(returncode=0, stdout="first-bead\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="bd create failed")

    monkeypatch.setattr(plan_to_beads.subprocess, "run", fake_run)
    assert plan_to_beads.main(["--plan", str(plan), "--apply", "--out", str(out)]) == 3
    assert len(calls) == 2
    assert not out.exists()
    assert "failed" in capsys.readouterr().err


def test_experiment_without_baseline_threshold_or_kill_is_refused(tmp_path: Path, capsys) -> None:
    for field in ("baselines", "success_threshold", "kill_criterion"):
        data = yaml.safe_load(PLAN)
        del data["experiments"][1][field]
        plan = write(tmp_path, yaml.safe_dump(data, sort_keys=False))
        out = tmp_path / "beads.json"
        assert plan_to_beads.main(["--plan", str(plan), "--out", str(out)]) == 2
        err = capsys.readouterr().err
        expected = {"baselines": "missing baseline"}.get(field, f"missing {field}")
        assert f"experiment e2: {expected}" in err
        assert "nothing written" in err
        assert not out.exists()


def test_unverifiable_criteria_and_single_hypothesis(tmp_path: Path, capsys) -> None:
    data = yaml.safe_load(PLAN)
    data["experiments"][0]["acceptance"] = ["looks good overall"]
    plan = write(tmp_path, yaml.safe_dump(data, sort_keys=False))
    assert plan_to_beads.main(["--plan", str(plan)]) == 0
    assert "may not be checkable" in capsys.readouterr().err
    assert plan_to_beads.main(["--plan", str(plan), "--strict"]) == 2
    capsys.readouterr()

    data = yaml.safe_load(PLAN)
    data["hypotheses"] = data["hypotheses"][:1]
    data["experiments"][0]["tests"] = ["h1"]
    data["experiments"][1]["tests"] = ["h1"]
    plan = write(tmp_path, yaml.safe_dump(data, sort_keys=False))
    assert plan_to_beads.main(["--plan", str(plan)]) == 0
    assert "strong inference needs a competing one" in capsys.readouterr().err
    assert plan_to_beads.main(["--plan", str(plan), "--strict"]) == 2


def test_structural_errors(tmp_path: Path, capsys) -> None:
    data = yaml.safe_load(PLAN)
    del data["provenance"]
    data["experiments"][0]["tests"] = ["h9"]
    data["experiments"][1]["owner"] = "intern"
    data["experiments"][1]["depends_on"] = ["ghost"]
    data["checkpoints"][0]["date"] = "next week"
    plan = write(tmp_path, yaml.safe_dump(data, sort_keys=False))
    assert plan_to_beads.main(["--plan", str(plan)]) == 2
    err = capsys.readouterr().err
    assert "plan: missing 'provenance'" in err
    assert "experiment e1: tests unknown hypothesis 'h9'" in err
    assert "experiment e2: owner role 'intern' not in" in err
    assert "experiment e2: depends on unknown experiment 'ghost'" in err
    assert "checkpoint c1: missing or malformed date" in err
    assert plan_to_beads.main(["--plan", str(tmp_path / "none.yaml")]) == 1


def test_shipped_example_plan_is_valid_under_strict(capsys) -> None:
    example = ASSETS / "plan.yaml.example"
    assert plan_to_beads.main(["--plan", str(example), "--strict", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["beads"]) == 7
    assert all(b["provenance"] for b in data["beads"])
    assert all(b["acceptance_criteria"] for b in data["beads"])
    assert "\u2014" not in json.dumps(data)
