"""Run the real parsers against the live files when they exist on this machine."""

from pathlib import Path

import pytest

from cube.sources import calendar, org, pa_kg, rkg

ORG = Path("~/org").expanduser()
PA = Path("~/pa").expanduser()
RKG = Path("~/Public/software/website/research-knowledge-graph/projects.jsonld").expanduser()
ROSTER = Path("~/Public/software/website/borg-website/people/roster.md").expanduser()


def _need(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"{path} not present")


def test_live_staff_org() -> None:
    _need(ORG / "staff.org")
    entries = org.parse_staff(ORG / "staff.org")
    assert entries and any(e.estimates for e in entries)


def test_live_papers_org() -> None:
    _need(ORG / "papers.org")
    papers = org.parse_papers(ORG / "papers.org")
    assert papers and any(p.state for p in papers)


def test_live_person_files() -> None:
    files = [
        p
        for p in ORG.glob("*.org")
        if p.name not in {"staff.org", "papers.org"} and not p.name.startswith(".") and p.exists()
    ]
    if not files:
        pytest.skip("no org files")
    parsed = [org.parse_person_file(p) for p in files]
    assert any(n.last_meeting for n in parsed)


def test_live_pa() -> None:
    _need(PA / "kg" / "projects")
    assert pa_kg.load_projects(PA / "kg" / "projects")
    _need(PA / "deadlines.md")
    assert pa_kg.parse_deadlines(PA / "deadlines.md")
    _need(PA / "contacts")
    assert pa_kg.load_contacts(PA / "contacts")


def test_live_rkg_and_roster() -> None:
    _need(RKG)
    kg = rkg.load_graph(RKG)
    assert kg.people and kg.projects and kg.software
    _need(ROSTER)
    assert rkg.parse_roster(ROSTER)


def test_live_calendars() -> None:
    cals = list(ORG.glob("*.cal"))
    if not cals:
        pytest.skip("no .cal files")
    assert calendar.load_calendars(ORG)
