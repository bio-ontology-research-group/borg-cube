"""Tests for the mentoring-compact skill scripts (idp_diff.py)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "mentoring-compact"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module  # dataclasses resolve their module during class creation
    spec.loader.exec_module(module)
    return module


idp_diff = load("idp_diff")

OLD = """\
# Individual development plan: Alex

## Self-assessment

| Skill | Domain | Now | Target | Evidence now |
| --- | --- | --- | --- | --- |
| Scientific writing | B | 2 | 3 | introduction draft |
| Presenting | D | 3 | 4 | group meeting talk |
| Data management | C | 2 | 4 | run manifests |

## Goals for the next twelve months

### Research
- [ ] Submit the first-author paper on ontology alignment (by 2026-03-31)
- [x] Reproduce the published baseline (by 2025-11-30)
- [ ] Pass the proposal defense (by 2026-01-15)

### Career
- [ ] Two informational interviews (by 2026-05-31)
- [ ] Update CV and online profile (by 2025-12-31)

## Mentoring network

| Need | Who | How often |
| --- | --- | --- |
| Methods and code | Sam | weekly |
"""

NEW = """\
# Individual development plan: Alex

## Self-assessment

| Skill | Domain | Now | Target | Evidence now |
| --- | --- | --- | --- | --- |
| Scientific writing | B | 3 | 4 | introduction and methods drafts |
| Presenting | D | 3 | 4 | group meeting talk |
| Data management | C | 2 | 4 | run manifests |

## Goals for the next twelve months

### Research
- [x] Submit the first-author paper on ontology alignment (by 2026-03-31)
- [ ] Reproduce the published baseline (by 2025-11-30)
- [ ] Pass the proposal defense (by 2026-06-15)

### Career
- [ ] Two informational interviews (by 2026-05-31)

### Wellbeing and boundaries
- [ ] Agree the leave plan in the compact (by 2026-10-15)

## Mentoring network

| Need | Who | How often |
| --- | --- | --- |
| Methods and code | Sam | fortnightly |
"""

TODAY = dt.date(2026, 4, 1)


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    old = tmp_path / "idp-2025-09.md"
    new = tmp_path / "idp-2026-09.md"
    old.write_text(OLD, encoding="utf-8")
    new.write_text(NEW, encoding="utf-8")
    return old, new


def diff(old_text: str = OLD, new_text: str = NEW, today: dt.date = TODAY):
    return idp_diff.diff_idps(idp_diff.parse_idp(old_text), idp_diff.parse_idp(new_text), today)


def goals(items: list[dict]) -> set[str]:
    return {i["goal"] for i in items}


# --------------------------------------------------------------------------- parsing


def test_split_goal_separates_the_date():
    assert idp_diff.split_goal("Give a talk (by 2026-05-31)") == ("Give a talk", "2026-05-31")
    assert idp_diff.split_goal("Give a talk, due 2026-05-31") == ("Give a talk", "2026-05-31")
    assert idp_diff.split_goal("Give a talk") == ("Give a talk", None)


def test_parse_records_section_state_and_line():
    parsed = idp_diff.parse_idp(NEW)
    key = ("Research", idp_diff.normalise("Pass the proposal defense"))
    goal = parsed.goals[key]
    assert goal.done is False
    assert goal.date == "2026-06-15"
    assert goal.section == "Research"
    assert NEW.splitlines()[goal.line - 1].startswith("- [ ] Pass the proposal defense")


def test_parse_skips_the_table_header_and_keeps_rows():
    parsed = idp_diff.parse_idp(OLD)
    rows = {key[1] for key in parsed.rows if key[0] == "Self-assessment"}
    assert "scientific writing" in rows
    assert "skill" not in rows
    row = parsed.rows[("Self-assessment", "scientific writing")]
    assert row.values == ["B", "2", "3", "introduction draft"]


def test_parse_ignores_fenced_blocks():
    text = (
        "## Research\n```\n- [ ] not a goal (by 2026-01-01)\n```\n- [ ] real goal (by 2026-02-01)\n"
    )
    parsed = idp_diff.parse_idp(text)
    assert goals([{"goal": g.text} for g in parsed.goals.values()]) == {"real goal"}


# --------------------------------------------------------------------------- diffing


def test_completed_and_reopened_goals():
    d = diff()
    assert goals(d.completed) == {"Submit the first-author paper on ontology alignment"}
    assert goals(d.reopened) == {"Reproduce the published baseline"}


def test_added_and_dropped_goals():
    d = diff()
    assert goals(d.added) == {"Agree the leave plan in the compact"}
    assert goals(d.dropped) == {"Update CV and online profile"}
    assert d.sections_added == ["Wellbeing and boundaries"]
    assert d.sections_dropped == []


def test_rescheduled_goal_reports_both_dates():
    (moved,) = diff().rescheduled
    assert moved["goal"] == "Pass the proposal defense"
    assert (moved["old_date"], moved["new_date"]) == ("2026-01-15", "2026-06-15")


def test_overdue_uses_today_and_only_unfinished_goals():
    d = diff()
    assert goals(d.overdue) == {"Reproduce the published baseline"}
    assert d.overdue[0]["days_overdue"] == (TODAY - dt.date(2025, 11, 30)).days
    # a completed goal with a past date is not overdue
    assert "Submit the first-author paper on ontology alignment" not in goals(d.overdue)
    # before the due date nothing is overdue
    assert diff(today=dt.date(2025, 11, 1)).overdue == []


def test_rating_changes_only_for_rows_that_moved():
    d = diff()
    changed = {c["key"] for c in d.rating_changes}
    assert changed == {"Scientific writing", "Methods and code"}
    writing = next(c for c in d.rating_changes if c["key"] == "Scientific writing")
    assert writing["old"][1:3] == ["2", "3"]
    assert writing["new"][1:3] == ["3", "4"]


def test_identical_files_report_only_what_is_overdue():
    d = diff(OLD, OLD, TODAY)
    assert d.completed == [] and d.added == [] and d.dropped == [] and d.rating_changes == []
    assert d.rescheduled == [] and d.reopened == []
    # an unchanged file still surfaces goals whose date has passed
    assert goals(d.overdue) == {
        "Submit the first-author paper on ontology alignment",
        "Pass the proposal defense",
        "Update CV and online profile",
    }
    # the goal already ticked in both versions is not overdue
    assert "Reproduce the published baseline" not in goals(d.overdue)
    assert idp_diff.Diff().is_empty() is True
    assert d.is_empty() is False


def test_a_goal_moved_to_another_section_is_added_and_dropped():
    old = "## Research\n- [ ] Write the survey (by 2026-05-01)\n"
    new = "## Skills\n- [ ] Write the survey (by 2026-05-01)\n"
    d = diff(old, new, TODAY)
    assert d.added and d.added[0]["section"] == "Skills"
    assert d.dropped and d.dropped[0]["section"] == "Research"


# --------------------------------------------------------------------------- rendering and CLI


def test_render_text_lists_each_block():
    text = idp_diff.render_text(diff(), "old.md", "new.md")
    assert "IDP diff: old.md -> new.md" in text
    assert "Goals completed (1)" in text
    assert "Goals dropped (1)" in text
    assert "2026-01-15 -> 2026-06-15" in text
    assert "Sections added: Wellbeing and boundaries" in text
    assert "—" not in text


def test_render_text_says_no_changes_when_empty():
    assert "no changes" in idp_diff.render_text(idp_diff.Diff(), "a.md", "b.md")


def test_cli_json_output(files: tuple[Path, Path], capsys):
    old, new = files
    rc = idp_diff.main(["--old", str(old), "--new", str(new), "--today", "2026-04-01", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert goals(payload["completed"]) == {"Submit the first-author paper on ontology alignment"}
    assert payload["overdue"][0]["days_overdue"] > 0


def test_cli_missing_file_exits_2(files: tuple[Path, Path], tmp_path: Path, capsys):
    old, _ = files
    rc = idp_diff.main(["--old", str(old), "--new", str(tmp_path / "absent.md")])
    assert rc == 2
    assert "file not found" in capsys.readouterr().err


def test_cli_never_writes_the_idp_files(files: tuple[Path, Path]):
    old, new = files
    before = (old.read_text(encoding="utf-8"), new.read_text(encoding="utf-8"))
    assert idp_diff.main(["--old", str(old), "--new", str(new), "--today", "2026-04-01"]) == 0
    assert (old.read_text(encoding="utf-8"), new.read_text(encoding="utf-8")) == before


def test_script_help_exits_zero():
    # covers mentoring-compact scripts/idp_diff.py
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "idp_diff.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--old" in proc.stdout
