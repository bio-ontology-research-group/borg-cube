# ruff: noqa: E501
"""Tests for the phd-milestones skill scripts (milestones.py, roster_scan.py)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "phd-milestones"
SCRIPTS = SKILL / "scripts"
PROGRAMS = SKILL / "assets" / "programs.yaml"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


milestones = load("milestones")
roster_scan = load("roster_scan")

TODAY = dt.date(2026, 9, 2)
STAFF_ORG = """\
* Group summer 2026

** Students
- Alex Example
- Bea Sample

* Research staff

** Carla
- contract end date: 30 June 2026

* Students

** Alex Example
- start PhD: 1 Jan 2025
- Preproposal: Jan 2026
- Proposal: Dec 2026
- Graduates: Dec 2028

** Bea Sample
- PhD Proposal completed May 2025
- Graduates: May 2027

** Carl Transfer
- Graduates (MSc): May 2026
- move to PhD from June 2026
"""
PEOPLE = """\
people:
  alex-example: {name: Alex Example, role: student, program: PhD-Bioeng, start: 2025-01-01}
  bea-sample: {name: Bea Sample, role: student, program: PhD-CS, start: 2022-08-21}
"""


@pytest.fixture(scope="module")
def rules():
    return milestones.load_programs(PROGRAMS)


def deadlines(result):
    return {m["id"]: m["deadline"] for m in result["milestones"]}


def test_programs_yaml_rules_carry_sources_and_dates(rules) -> None:
    for degree, sets in rules["milestones"].items():
        for name, block in sets.items():
            for rule in block["rules"]:
                assert rule["sources"], f"{degree}/{name}/{rule['id']} has no sources"
                assert "verified_on" in rule
    for steps in rules["preparation"].values():
        for step in steps:
            assert step["sources"]


def test_spring_start_phd_current_rules(rules) -> None:
    result = milestones.plan(dt.date(2025, 1, 1), "PhD-Bioeng", rules, today=TODAY)
    assert result["rule_set"] == "current"
    assert result["start_term"] == "spring"
    d = deadlines(result)
    assert d["qualifier"] == "2026-05-20"  # end of the 3rd Fall/Spring semester
    assert d["proposal"] == "2027-05-20"  # end of the 5th semester
    assert d["defense"] == "2028-12-15"  # 8 semesters and 4 summers
    assert any(f["kind"] == "overdue" and f["milestone"] == "qualifier" for f in result["flags"])


def test_fall_start_phd_current_rules_and_passed(rules) -> None:
    result = milestones.plan(
        dt.date(2024, 8, 25), "phd-cs", rules, today=TODAY, passed=["qualifier"]
    )
    d = deadlines(result)
    assert d["qualifier"] == "2025-12-15"
    assert d["proposal"] == "2026-12-15"
    assert d["defense"] == "2028-08-10"
    status = {m["id"]: m["status"] for m in result["milestones"]}
    assert status["qualifier"] == "passed"
    assert status["proposal"] == "upcoming"  # 104 days, beyond the 60-day window
    assert all(f["milestone"] != "qualifier" for f in result["flags"])


def test_due_soon_window(rules) -> None:
    result = milestones.plan(
        dt.date(2024, 8, 25), "phd-cs", rules, today=dt.date(2026, 11, 1), passed=["qualifier"]
    )
    status = {m["id"]: m["status"] for m in result["milestones"]}
    assert status["proposal"] == "due-soon"
    assert any(f["kind"] == "due-soon" for f in result["flags"])


def test_pre_fall_2023_counts_summers(rules) -> None:
    result = milestones.plan(dt.date(2021, 8, 22), "PhD-CS", rules, today=TODAY)
    assert result["rule_set"] == "pre-fall-2023"
    d = deadlines(result)
    assert d["qualifier"] == "2022-12-15"  # 4 terms including summer
    assert d["proposal"] == "2023-12-15"  # 7 terms
    assert d["defense"] == "2026-08-22"  # 5 calendar years
    assert "probation" in result["consequence"]


def test_ms_to_phd_transfer_summer_start(rules) -> None:
    result = milestones.plan(dt.date(2026, 6, 1), "phd-cs", rules, today=TODAY)
    d = deadlines(result)
    assert result["start_term"] == "summer"
    assert d["qualifier"] == "2027-12-15"  # Fall 2026 is the first counted semester
    assert d["proposal"] == "2028-12-15"


def test_ms_thesis_fall_and_spring_start(rules) -> None:
    fall = deadlines(milestones.plan(dt.date(2024, 8, 25), "MS-CS", rules, today=TODAY))
    assert fall["thesis-defense"] == "2026-05-20"  # 4 semesters and 1 summer
    assert fall["thesis-application"] == "2025-08-27"  # week one of the 3rd semester
    spring = deadlines(milestones.plan(dt.date(2026, 1, 15), "ms-cs", rules, today=TODAY))
    assert spring["thesis-defense"] == "2027-08-10"  # 3 semesters and 2 summers
    non_thesis = deadlines(
        milestones.plan(dt.date(2026, 1, 15), "ms-bioeng", rules, track="non-thesis", today=TODAY)
    )
    assert non_thesis["degree-completion"] == "2027-05-20"
    assert "thesis-defense" not in non_thesis


def test_preparation_anchored_to_scheduled_date(rules) -> None:
    result = milestones.plan(
        dt.date(2024, 8, 25),
        "phd-cs",
        rules,
        today=TODAY,
        event_dates={"proposal": dt.date(2026, 11, 20)},
    )
    steps = {(p["event"], p["id"]): p for p in result["preparation"]}
    assert steps[("proposal", "petition")]["date"] == "2026-11-06"
    assert steps[("proposal", "document")]["date"] == "2026-11-10"
    assert steps[("proposal", "petition")]["relative_to"] == "scheduled date"
    assert steps[("defense", "announcement")]["relative_to"] == "deadline"
    unverified = [p for p in result["preparation"] if not p["verified_on"]]
    assert any(p["id"] == "dissertation-to-committee" for p in unverified)


def test_unknown_program_is_an_error(rules) -> None:
    with pytest.raises(milestones.MilestoneError):
        milestones.plan(dt.date(2025, 1, 1), "phd-physics", rules, today=TODAY)


def test_cli_json_and_text(capsys) -> None:
    rc = milestones.main(
        ["--start", "2025-01-01", "--program", "phd-bioeng", "--today", "2026-09-02", "--json"]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["program"] == "phd-bioeng"
    rc = milestones.main(
        ["--start", "2025-01-01", "--program", "phd-bioeng", "--today", "2026-09-02"]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "Qualifying exam" in out and "[unverified]" in out


def test_org_out_respects_lock_and_dry_run(tmp_path: Path, capsys) -> None:
    target = tmp_path / "alex.org"
    target.write_text("#+STARTUP: overview\n* Notes\n", encoding="utf-8")
    args = ["--start", "2025-01-01", "--program", "phd-bioeng", "--today", "2026-09-02"]
    assert milestones.main([*args, "--org-out", str(target), "--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == "#+STARTUP: overview\n* Notes\n"
    lock = tmp_path / "#alex.org#"
    lock.write_text("lock", encoding="utf-8")
    assert milestones.main([*args, "--org-out", str(target)]) == 1
    assert "open in Emacs" in capsys.readouterr().err
    lock.unlink()
    assert milestones.main([*args, "--org-out", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert "* Milestones (PhD phd-bioeng" in text and "<2027-05-20 Thu>" in text


def test_roster_parse_and_flags(tmp_path: Path) -> None:
    people = roster_scan.parse_roster(STAFF_ORG)
    by_name = {p["name"]: p for p in people}
    alex = by_name["Alex Example"]
    assert alex["section"] == "Students"
    assert alex["fields"]["start"]["date"] == "2025-01-01"
    assert alex["fields"]["qualifier"]["date"] == "2026-01-01"
    assert alex["fields"]["proposal"]["date"] == "2026-12-01"
    assert alex["fields"]["graduates"]["date"] == "2028-12-01"
    bea = by_name["Bea Sample"]
    assert bea["fields"]["proposal"]["status"] == "passed"
    assert "start" not in bea["fields"]
    carl = by_name["Carl Transfer"]
    assert carl["fields"]["transfer"]["date"] == "2026-06-01"
    assert by_name["Carla"]["fields"]["contract_end"]["date"] == "2026-06-30"

    import yaml

    people_yaml = yaml.safe_load(PEOPLE)
    rules = milestones.load_programs(PROGRAMS)
    records = {r["name"]: r for r in roster_scan.analyse(people, people_yaml, rules, TODAY)}
    assert records["Alex Example"]["computed"]["defense"] == "2028-12-15"
    assert records["Alex Example"]["flags"] == []
    assert "start" in records["Carl Transfer"]["missing"]
    assert records["Bea Sample"]["program"] == "PhD-CS"
    assert records["Bea Sample"]["computed"]["qualifier"] == "2023-12-15"
    assert any("qualifier deadline" in f for f in records["Bea Sample"]["flags"])
    assert any("in the past" in f for f in records["Carla"]["flags"])


def test_roster_cli(tmp_path: Path, capsys) -> None:
    staff = tmp_path / "staff.org"
    staff.write_text(STAFF_ORG, encoding="utf-8")
    people = tmp_path / "people.yaml"
    people.write_text(PEOPLE, encoding="utf-8")
    rc = roster_scan.main(
        [
            "--staff-org",
            str(staff),
            "--people",
            str(people),
            "--programs",
            str(PROGRAMS),
            "--section",
            "Students",
            "--today",
            "2026-09-02",
            "--json",
        ]
    )
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert {d["name"] for d in data} == {"Alex Example", "Bea Sample", "Carl Transfer"}
    assert roster_scan.main(["--staff-org", str(tmp_path / "missing.org")]) == 1
    assert roster_scan.main(["--staff-org", str(staff)]) == 0
    assert "Alex Example" in capsys.readouterr().out
