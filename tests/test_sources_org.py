from datetime import date
from pathlib import Path

from cube.sources.dates import parse_day_month, parse_fuzzy_date
from cube.sources.org import (
    classify_bullet,
    match_staff_entry,
    parse_org,
    parse_papers,
    parse_person_file,
    parse_staff,
    parse_todo_keywords,
    slugify,
)

FIX = Path(__file__).parent / "fixtures"


def test_fuzzy_dates() -> None:
    assert parse_fuzzy_date("Graduates: Dec 2026", month_anchor="end").value == date(2026, 12, 31)
    assert parse_fuzzy_date("December 2026").value == date(2026, 12, 1)
    assert parse_fuzzy_date("start PhD: 1 Jan 2025").value == date(2025, 1, 1)
    assert parse_fuzzy_date("** 27 January 2025").value == date(2025, 1, 27)
    assert parse_fuzzy_date("Sept 2024", month_anchor="end").value == date(2024, 9, 30)
    assert parse_fuzzy_date("<2023-10-26 Thu>").value == date(2023, 10, 26)
    assert parse_fuzzy_date("CLOSED: [2025-10-23 Thu 07:21]").value == date(2025, 10, 23)
    assert parse_fuzzy_date("started MSc Spring 2026").value == date(2026, 1, 15)
    assert parse_fuzzy_date("Internship: summer 2025").precision == "season"
    assert parse_fuzzy_date("Group meeting 15 Feb 2024").value == date(2024, 2, 15)
    assert parse_fuzzy_date("no date here") is None
    assert parse_fuzzy_date("* 9 April") is None
    assert parse_day_month("* 9 April", 2026) == date(2026, 4, 9)


def test_todo_keywords_and_generic_parse() -> None:
    text = (
        "#+TODO: A B | C\n* A first :tag1:tag2:\n:PROPERTIES:\n:VENUE: X\n:END:\nbody\n"
        "** C sub\nCLOSED: [2025-01-02 Thu 07:21]\n"
    )
    assert parse_todo_keywords(text) == ("A", "B", "C")
    hs = parse_org(text, Path("x.org"))
    assert hs[0].todo == "A" and hs[0].title == "first" and hs[0].tags == ["tag1", "tag2"]
    assert hs[0].properties == {"VENUE": "X"}
    assert hs[1].todo == "C" and hs[1].closed == date(2025, 1, 2)
    assert hs[1].parents == ["first"] and hs[1].outline == "first / sub"


def test_staff_org() -> None:
    entries = parse_staff(FIX / "staff.org")
    by_name = {e.name: e for e in entries}
    alex = by_name["Alex"]
    assert alex.section == "Students"
    kinds = {e.kind: e.when for e in alex.estimates}
    assert kinds["start"] == date(2025, 1, 1)
    assert kinds["preproposal"] == date(2026, 1, 31)
    assert kinds["proposal"] == date(2026, 12, 31)
    assert kinds["graduates"] == date(2028, 12, 31)
    bea = by_name["Bea Sample"]
    assert bea.first("proposal_done") is not None
    assert bea.first("proposal_done").when == date(2025, 5, 31)  # type: ignore[union-attr]
    dan = by_name["Dan"]
    assert dan.first("transfer_phd").when == date(2026, 6, 1)  # type: ignore[union-attr]
    assert dan.first("msc_graduates").when == date(2026, 5, 31)  # type: ignore[union-attr]
    assert by_name["Carla"].section == "Research staff"
    assert by_name["Carla"].first("contract_end").when == date(2026, 6, 30)  # type: ignore[union-attr]
    assert by_name["Fay"].section == "Alumni"
    assert "staff.org:" in alex.locator and "** Alex" in alex.locator
    # the summary block under "* Group summer 2026" is level 2 too but has no estimates
    assert by_name["Students"].estimates == []


def test_match_staff_entry() -> None:
    entries = parse_staff(FIX / "staff.org")
    assert match_staff_entry(entries, "Alex Example").name == "Alex"  # type: ignore[union-attr]
    assert match_staff_entry(entries, "Bea Sample").name == "Bea Sample"  # type: ignore[union-attr]
    assert match_staff_entry(entries, "Nobody Here") is None


def test_classify_bullet() -> None:
    assert classify_bullet("PhD Proposal completed May 2025") == "proposal_done"
    assert classify_bullet("Preproposal: May 2025") == "preproposal"
    assert classify_bullet("Proposal: May 2026") == "proposal"
    assert classify_bullet("Graduates (estimate): May 2028") == "graduates"
    assert classify_bullet("contract end: 30 June 2026") == "contract_end"
    assert classify_bullet("end date: June 2025") == "contract_end"
    assert classify_bullet("co-supervision with Prof. Cosupervisor") is None


def test_papers_org() -> None:
    papers = parse_papers(FIX / "papers.org")
    by_slug = {p.slug: p for p in papers}
    assert by_slug["metabolic-reconstruction"].state is None
    assert by_slug["metabolic-reconstruction"].people == ["Alex"]
    assert by_slug["empty-quarter"].tags == ["eq"]
    enz = by_slug["enzymes"]
    assert enz.level == 3 and enz.parent_slug == "empty-quarter"
    assert enz.people == ["Alex", "Bea"] and enz.deadline_text == "Deadline: after Eid, June"
    assert by_slug["adverse-event-prediction"].state == "SUBMITTED"
    gda = by_slug["inductive-gda"]
    assert gda.state == "REVISING" and gda.properties == {"VENUE": "Bioinformatics"}
    nano = by_slug["nanobodies"]
    assert nano.state == "PUBLISHED" and nano.closed == date(2025, 10, 23)
    assert nano.people == ["Eve", "Carla"]
    assert by_slug["fpdl"].state == "CANCELED"
    assert nano.outline == "Published 2025 / Nanobodies"
    assert slugify("DELE: Deductive EL Embeddings") == "dele-deductive-el-embeddings"


def test_person_file() -> None:
    notes = parse_person_file(FIX / "person.org")
    assert notes.last_meeting == date(2026, 4, 16)
    assert notes.open_checkboxes == 2 and notes.done_checkboxes == 1
    dated = [(d.when.isoformat(), d.title) for d in notes.recent(3)]
    assert dated[0] == ("2026-04-16", "16 April 2026")
    assert ("2024-11-04", "Todo 4 Nov 2024") in dated
    assert notes.todo_headings == ["Start work on paper"]
    assert all(d.when.year != 9 for d in notes.dated)  # "* 9 April" ignored
