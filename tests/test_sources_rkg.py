from datetime import date
from pathlib import Path

from cube.sources.rkg import load_graph, parse_roster

FIX = Path(__file__).parent / "fixtures"


def test_graph() -> None:
    kg = load_graph(FIX / "projects.jsonld")
    assert len(kg.people) == 2 and len(kg.projects) == 1
    assert len(kg.software) == 1 and len(kg.courses) == 1 and kg.publication_count == 1
    alex = kg.person("alex-example")
    assert alex is not None
    assert alex.name == "Alex Example" and alex.position == "PhD (current)" and alex.is_current
    assert alex.program == "Bioengineering" and alex.start_year == 2025
    assert alex.projects == ["borg-id:project/test-project"]
    fay = kg.person("fay-former")
    assert fay is not None and not fay.is_current
    assert fay.thesis_defense_date == date(2025, 5, 3) and fay.end_year == 2025
    proj = kg.projects[0]
    assert proj.slug == "test-project"
    assert proj.members == [("borg-id:person/alex-example", "student")]
    assert proj.software == ["borg-id:software/mowl"]
    sw = kg.software[0]
    assert sw.repository == "https://github.com/bio-ontology-research-group/mowl"
    course = kg.courses[0]
    assert course.code == "CS 213" and course.year == 2026 and course.role == "Instructor"
    assert kg.people_named("alex example")[0] is alex
    assert load_graph(FIX / "missing.jsonld").people == []


def test_roster() -> None:
    rows = parse_roster(FIX / "roster.md")
    assert [r.slug for r in rows] == [
        "robert-hoehndorf",
        "alex-example",
        "eve-sample",
        "vic-visitor",
    ]
    alex = rows[1]
    assert alex.section == "Current students" and alex.is_student
    assert alex.program == "PhD-Bioeng" and alex.detail == "PhD, Bioengineering"
    assert rows[2].program == "MS-CS"
    assert rows[3].program == "visiting"
    assert rows[0].program is None and not rows[0].is_student
    assert alex.locator.endswith("roster.md:11")
    assert parse_roster(FIX / "missing.md") == []
