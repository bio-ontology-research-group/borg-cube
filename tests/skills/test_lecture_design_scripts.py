"""Tests for the lecture-design skill scripts (outcome_lint.py, timebox.py)."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SKILL = Path(__file__).resolve().parents[2] / "skills" / "lecture-design"
SCRIPTS = SKILL / "scripts"
EXAMPLE = SKILL / "assets" / "lecture-plan.yaml.example"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


outcome_lint = load("outcome_lint")
timebox = load("timebox")


@pytest.fixture
def plan() -> dict:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def write(tmp_path: Path, data: dict, name: str = "plan.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def segment(plan: dict, sid: str) -> dict:
    return next(s for s in plan["segments"] if s["id"] == sid)


def outcome(plan: dict, oid: str) -> dict:
    return next(o for o in plan["outcomes"] if o["id"] == oid)


# --------------------------------------------------------------------------- assets


def test_example_plan_passes_both_scripts(tmp_path: Path) -> None:
    assert outcome_lint.main(["--plan", str(EXAMPLE)]) == 0
    assert timebox.main(["--plan", str(EXAMPLE), "--strict"]) == 0


def test_template_documents_the_kinds() -> None:
    text = (SKILL / "assets" / "lecture-plan-template.md").read_text(encoding="utf-8")
    for kind in ("peer-instruction", "prediction", "live-coding", "muddiest-point"):
        assert kind in text


# --------------------------------------------------------------------------- verb table


def test_verb_table_covers_every_level() -> None:
    for level in outcome_lint.LEVELS:
        assert any(lv == level for lv in outcome_lint.VERB_LEVEL.values())
    assert outcome_lint.VERB_LEVEL["explain"] == "understand"
    assert outcome_lint.VERB_LEVEL["implement"] == "apply"
    assert outcome_lint.VERB_LEVEL["design"] == "create"


def test_unobservable_verbs_are_not_in_the_table() -> None:
    for verb in outcome_lint.UNOBSERVABLE:
        assert verb not in outcome_lint.VERB_LEVEL


def test_verbs_flag_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert outcome_lint.main(["--verbs"]) == 0
    out = capsys.readouterr().out
    assert "remember:" in out and "understand" in out


def test_every_check_kind_is_also_an_activity() -> None:
    assert outcome_lint.CHECK_KINDS <= outcome_lint.ACTIVITY_KINDS


# --------------------------------------------------------------------------- outcome checks


def test_unobservable_verb_fails(tmp_path: Path, plan: dict) -> None:
    target = outcome(plan, "o1")
    target["verb"] = "understand"
    target["statement"] = "Understand how information leaks from a validation split"
    path = write(tmp_path, plan)
    assert outcome_lint.main(["--plan", str(path)]) == 2
    report = outcome_lint.lint(outcome_lint.load_plan(path))
    assert any("not an outcome verb" in e for e in report.errors)


def test_verb_level_mismatch_fails(tmp_path: Path, plan: dict) -> None:
    outcome(plan, "o1")["level"] = "create"
    path = write(tmp_path, plan)
    report = outcome_lint.lint(outcome_lint.load_plan(path))
    assert any("is understand in the table" in e for e in report.errors)


def test_unknown_verb_fails(tmp_path: Path, plan: dict) -> None:
    target = outcome(plan, "o1")
    target["verb"] = "vibe"
    target["statement"] = "Vibe with the validation split"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("not in the verb table" in e for e in report.errors)


def test_missing_knowledge_type_fails(tmp_path: Path, plan: dict) -> None:
    del outcome(plan, "o2")["knowledge"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("no knowledge type" in e for e in report.errors)


def test_statement_must_contain_the_verb(tmp_path: Path, plan: dict) -> None:
    outcome(plan, "o1")["statement"] = "Leakage in validation splits"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("does not contain the verb" in e for e in report.errors)


def test_statement_not_starting_with_the_verb_warns(tmp_path: Path, plan: dict) -> None:
    outcome(plan, "o1")["statement"] = "Given a split, explain how information leaks from it"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert not report.errors
    assert any("does not start with the verb" in w for w in report.warnings)


def test_all_low_level_outcomes_warn(tmp_path: Path, plan: dict) -> None:
    plan["outcomes"] = [outcome(plan, "o1")]
    plan["segments"] = [s for s in plan["segments"] if s.get("outcomes") in (None, ["o1"])]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("remember or understand" in w for w in report.warnings)


# --------------------------------------------------------------------------- alignment


def test_unassessed_outcome_fails(tmp_path: Path, plan: dict) -> None:
    # o3 keeps its live-coding activity but loses both of its checks.
    for sid in ("s10",):
        segment(plan, sid)["outcomes"] = []
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("unassessed" in e and "o3" in e for e in report.errors)


def test_outcome_without_any_activity_fails(tmp_path: Path, plan: dict) -> None:
    for sid in ("s12", "s13"):
        segment(plan, sid)["outcomes"] = []
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("no activity practises it" in e and "o4" in e for e in report.errors)


def test_activity_below_the_outcome_level_fails(tmp_path: Path, plan: dict) -> None:
    for sid in ("s12", "s13"):
        segment(plan, sid)["verb"] = "recall"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("highest activity is at remember" in e for e in report.errors)


def test_check_below_the_outcome_level_warns(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s13")["verb"] = "recall"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("sits below evaluate" in w for w in report.warnings)


def test_activity_without_a_level_fails(tmp_path: Path, plan: dict) -> None:
    del segment(plan, "s9")["verb"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("no verb or level" in e for e in report.errors)


def test_unknown_outcome_reference_fails(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s9")["outcomes"] = ["o9"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("unknown outcome 'o9'" in e for e in report.errors)


# --------------------------------------------------------------------------- segments


def test_peer_instruction_without_a_misconception_fails(tmp_path: Path, plan: dict) -> None:
    del segment(plan, "s3")["misconception"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("names the misconception" in e for e in report.errors)


def test_demo_without_a_prediction_fails(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s5")["kind"] = "discussion"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("preceded by a prediction" in e for e in report.errors)


def test_unknown_segment_kind_fails(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s2")["kind"] = "storytime"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("kind 'storytime' is not one of" in e for e in report.errors)


def test_duplicate_ids_fail(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s4")["id"] = "s2"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("duplicate segment id" in e for e in report.errors)


# --------------------------------------------------------------------------- pre-class


def test_pre_class_item_without_a_check_fails(tmp_path: Path, plan: dict) -> None:
    del plan["pre_class"][0]["check"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("no check" in e for e in report.errors)


def test_pre_class_check_must_be_a_check_segment(tmp_path: Path, plan: dict) -> None:
    plan["pre_class"][0]["check"] = "s2"
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("not a formative check" in e for e in report.errors)


def test_missing_pre_class_warns(tmp_path: Path, plan: dict) -> None:
    del plan["pre_class"]
    report = outcome_lint.lint(outcome_lint.load_plan(write(tmp_path, plan)))
    assert any("no pre-class work" in w for w in report.warnings)


# --------------------------------------------------------------------------- plan loading


def test_missing_keys_are_reported(tmp_path: Path, plan: dict) -> None:
    del plan["outcomes"]
    path = write(tmp_path, plan)
    with pytest.raises(outcome_lint.PlanError, match="missing top-level keys"):
        outcome_lint.load_plan(path)
    assert outcome_lint.main(["--plan", str(path)]) == 2


def test_broken_yaml_exits_two(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("course: [unterminated\n", encoding="utf-8")
    assert outcome_lint.main(["--plan", str(path)]) == 2
    assert timebox.main(["--plan", str(path)]) == 2


def test_json_output_is_machine_readable(
    tmp_path: Path, plan: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    outcome(plan, "o1")["verb"] = "know"
    path = write(tmp_path, plan)
    assert outcome_lint.main(["--plan", str(path), "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["summary"]["errors"] >= 1


def test_out_writes_the_report(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "report.txt"
    assert outcome_lint.main(["--plan", str(EXAMPLE), "--out", str(out)]) == 0
    assert "pass" in out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- timebox


def test_timeline_places_every_segment_on_the_clock(plan: dict) -> None:
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert len(result["timeline"]) == len(plan["segments"])
    assert result["timeline"][0]["start"] == 0
    assert result["timeline"][-1]["end"] == plan["length_minutes"]
    assert result["flags"] == []
    assert result["direct_minutes"] > 0 and result["active_minutes"] > 0


def test_clock_times_come_from_start(plan: dict, capsys: pytest.CaptureFixture[str]) -> None:
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    text = timebox.render_text(plan, result)
    assert "10:00-10:06" in text


def test_bad_start_time_is_rejected(tmp_path: Path, plan: dict) -> None:
    plan["start"] = "25:00"
    path = write(tmp_path, plan)
    assert timebox.main(["--plan", str(path)]) == 2


def test_long_direct_instruction_is_flagged(plan: dict) -> None:
    segment(plan, "s2")["minutes"] = 30
    plan["length_minutes"] = 108
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("direct instruction runs 30 minutes" in f for f in result["flags"])


def test_consecutive_direct_segments_are_one_stretch(plan: dict) -> None:
    plan["segments"] = [
        {"id": "a", "kind": "retrieval", "minutes": 5, "outcomes": [], "verb": "recall"},
        {"id": "b", "kind": "lecture", "minutes": 10},
        {"id": "c", "kind": "worked-example", "minutes": 10},
        {"id": "d", "kind": "minute-paper", "minutes": 5},
    ]
    plan["length_minutes"] = 30
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("direct instruction runs 20 minutes" in f for f in result["flags"])


def test_missing_break_is_flagged(plan: dict) -> None:
    segment(plan, "s8")["kind"] = "discussion"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("no break" in f for f in result["flags"])


def test_check_gap_is_flagged(plan: dict) -> None:
    for sid in ("s3", "s7"):
        segment(plan, sid)["kind"] = "discussion"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("with no check before s10" in f for f in result["flags"])


def test_no_check_at_all_is_flagged(plan: dict) -> None:
    for seg in plan["segments"]:
        if seg["kind"] in timebox.CHECK_KINDS:
            seg["kind"] = "discussion"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("no formative check in the session" in f for f in result["flags"])


def test_missing_opening_and_closing_are_flagged(plan: dict) -> None:
    segment(plan, "s1")["kind"] = "lecture"
    segment(plan, "s13")["kind"] = "discussion"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("does not open with retrieval" in f for f in result["flags"])
    assert any("does not close with a written check" in f for f in result["flags"])


def test_total_mismatch_is_flagged(plan: dict) -> None:
    plan["length_minutes"] = 75
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("15 minutes over" in f for f in result["flags"])


def test_missing_contingency_is_flagged(plan: dict) -> None:
    del plan["contingency"]
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("no contingency" in f for f in result["flags"])


def test_contingency_must_name_a_droppable_segment(plan: dict) -> None:
    plan["contingency"] = "ghost"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("does not name an existing segment" in f for f in result["flags"])

    plan["contingency"] = "drop s13"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("cannot drop" in f and "s13" in f for f in result["flags"])

    plan["contingency"] = "drop s3"
    result = timebox.analyze(plan, dict(timebox.DEFAULTS))
    assert any("cannot drop check" in f for f in result["flags"])


def test_thresholds_are_reported_and_configurable(tmp_path: Path, plan: dict) -> None:
    thresholds = dict(timebox.DEFAULTS, max_direct=10)
    result = timebox.analyze(plan, thresholds)
    assert result["thresholds"]["max_direct"] == 10
    assert any("our threshold is 10 minutes" in f for f in result["flags"])
    path = write(tmp_path, plan)
    assert timebox.main(["--plan", str(path), "--max-direct", "10"]) == 0
    assert timebox.main(["--plan", str(path), "--max-direct", "10", "--strict"]) == 2


def test_segment_minutes_must_be_positive(tmp_path: Path, plan: dict) -> None:
    segment(plan, "s2")["minutes"] = 0
    path = write(tmp_path, plan)
    assert timebox.main(["--plan", str(path)]) == 2


def test_timebox_json_and_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "timeline.json"
    assert timebox.main(["--plan", str(EXAMPLE), "--json", "--out", str(out)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["length_minutes"] == 90
    assert json.loads(out.read_text(encoding="utf-8"))["flags"] == []


# --------------------------------------------------------------------------- command line


@pytest.mark.parametrize("script", ["outcome_lint.py", "timebox.py"])
def test_help_exits_zero(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--plan" in proc.stdout


@pytest.mark.parametrize("script", ["outcome_lint.py", "timebox.py"])
def test_missing_plan_exits_two(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 2
    assert "--plan is required" in proc.stderr
