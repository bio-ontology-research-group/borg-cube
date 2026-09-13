from datetime import date
from typing import Any

import pytest

from cube.milestones.kaust_rules import (
    Semester,
    first_semester,
    next_open,
    nth_semester,
    plan_for,
    semester_index,
    semester_of,
    status_for,
    uses_new_rules,
)

TODAY = date(2026, 9, 2)


def test_semester_calendar() -> None:
    assert semester_of(date(2026, 8, 25)) == Semester(2026, "fall")
    assert semester_of(date(2026, 8, 24)) == Semester(2026, "summer")
    assert semester_of(date(2026, 1, 15)) == Semester(2026, "spring")
    assert semester_of(date(2026, 1, 14)) == Semester(2025, "fall")
    assert Semester(2025, "fall").end() == date(2025, 12, 20)
    assert Semester(2026, "spring").end() == date(2026, 5, 31)
    assert Semester(2026, "summer").end() == date(2026, 8, 24)
    # program starts: 1 Jan counts as Spring, June as Fall
    assert first_semester(date(2025, 1, 1)) == Semester(2025, "spring")
    assert first_semester(date(2026, 6, 1)) == Semester(2026, "fall")
    assert first_semester(date(2023, 9, 1)) == Semester(2023, "fall")
    assert nth_semester(date(2025, 1, 1), 3) == Semester(2026, "spring")
    assert semester_index(date(2025, 1, 1), TODAY) == 4
    assert semester_index(date(2025, 1, 1), date(2025, 7, 1)) == 1  # summer sticks to spring
    assert semester_index(date(2026, 6, 1), date(2026, 7, 1)) == 0
    assert uses_new_rules(date(2023, 8, 25)) and not uses_new_rules(date(2022, 8, 25))


def test_status_thresholds() -> None:
    assert status_for(TODAY.replace(day=1), TODAY) == "overdue"
    assert status_for(date(2026, 9, 30), TODAY) == "at_risk"
    assert status_for(date(2026, 11, 20), TODAY) == "due_soon"
    assert status_for(date(2027, 1, 1), TODAY) == "on_track"
    assert status_for(None, TODAY) == "unknown"
    assert status_for(date(2020, 1, 1), TODAY, done=True) == "done"


def _due(ms: list[Any]) -> dict[str, Any]:
    return {m.name: (m.due, m.status) for m in ms}


CASES: list[tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, tuple[date, str]]]] = [
    (
        "hal: PhD from 1 Jan 2025, new rules, estimates from staff.org",
        {"id": "hal", "program": "PhD-Bioeng", "start": date(2025, 1, 1)},
        [
            {"kind": "preproposal", "date": date(2026, 1, 31), "raw": "Preproposal: Jan 2026"},
            {"kind": "proposal", "date": date(2026, 12, 31), "raw": "Proposal: Dec 2026"},
            {"kind": "graduates", "date": date(2028, 12, 31), "raw": "Graduates: Dec 2028"},
        ],
        {
            "qualifying exam": (date(2026, 5, 31), "unknown"),
            "proposal defense": (date(2027, 5, 31), "on_track"),
            "dissertation defense": (date(2029, 1, 1), "on_track"),
            "extension limit": (date(2030, 1, 1), "on_track"),
        },
    ),
    (
        "dan: PhD clock restarts at the MS-to-PhD transfer on 1 June 2026",
        {"id": "dan", "program": "PhD-CS", "start": date(2026, 6, 1)},
        [
            {
                "kind": "msc_graduates",
                "date": date(2026, 5, 31),
                "raw": "Graduates (MSc): May 2026",
            },
            {"kind": "transfer_phd", "date": date(2026, 6, 1), "raw": "move to PhD from June 2026"},
        ],
        {
            "qualifying exam": (date(2027, 12, 20), "on_track"),
            "proposal defense": (date(2028, 12, 20), "on_track"),
            "dissertation defense": (date(2030, 6, 1), "on_track"),
            "extension limit": (date(2031, 6, 1), "on_track"),
        },
    ),
    (
        "eve: MSc thesis from Spring 2026",
        {"id": "eve", "program": "MS-CS", "start": date(2026, 1, 15)},
        [],
        {
            "thesis application": (date(2027, 1, 22), "on_track"),
            "thesis defense": (date(2027, 12, 20), "on_track"),
        },
    ),
    (
        "fall 2022 PhD cohort: old rules (4 / 7 semesters, 5 + 2 years)",
        {"id": "old", "program": "PhD-CS", "start": date(2022, 8, 25)},
        [],
        {
            "qualifying exam": (date(2024, 5, 31), "overdue"),
            "proposal defense": (date(2025, 12, 20), "overdue"),
            "dissertation defense": (date(2027, 8, 25), "on_track"),
            "extension limit": (date(2029, 8, 25), "on_track"),
        },
    ),
    (
        "non-thesis MS: 3 semesters + summer",
        {"id": "nt", "program": "MS-Bioeng", "start": date(2025, 8, 25), "thesis": False},
        [],
        {"degree completion": (date(2026, 12, 20), "on_track")},
    ),
]


@pytest.mark.parametrize("label,person,estimates,expected", CASES, ids=[c[0] for c in CASES])
def test_plan_for_table(
    label: str,
    person: dict[str, Any],
    estimates: list[dict[str, Any]],
    expected: dict[str, tuple[date, str]],
) -> None:
    got = _due(plan_for(person, TODAY, estimates))
    assert got == expected, label


def test_estimates_become_provenance_and_done() -> None:
    ms = plan_for(
        {"id": "bea", "program": "PhD-CS", "start": date(2022, 8, 25)},
        TODAY,
        [
            {
                "kind": "proposal_done",
                "date": date(2025, 5, 31),
                "raw": "PhD Proposal completed May 2025",
            },
            {"kind": "graduates", "date": date(2027, 5, 31), "raw": "Graduates: May 2027"},
        ],
    )
    by = {m.name: m for m in ms}
    assert by["proposal defense"].status == "done" and by["proposal defense"].done_on == date(
        2025, 5, 31
    )
    assert by["qualifying exam"].status == "done" and "implied" in by["qualifying exam"].notes[0]
    dd = by["dissertation defense"]
    assert dd.due == date(2027, 8, 25) and dd.estimate == date(2027, 5, 31)
    assert dd.estimate_source is not None and "Graduates: May 2027" in dd.estimate_source
    assert next_open(ms) is dd


def test_no_start_date_uses_estimates_only() -> None:
    ms = plan_for(
        {"id": "alex", "program": "PhD-Bioeng"},
        TODAY,
        [{"kind": "graduates", "date": date(2026, 12, 31), "raw": "Graduates: Dec 2026"}],
    )
    assert len(ms) == 1
    assert ms[0].name == "dissertation defense" and ms[0].due == date(2026, 12, 31)
    assert ms[0].source == "staff.org" and ms[0].status == "on_track"
    assert any("no start date" in n for n in ms[0].notes)


def test_estimate_later_than_rule_is_noted() -> None:
    ms = plan_for(
        {"id": "x", "program": "PhD-CS", "start": date(2024, 8, 25)},
        TODAY,
        [{"kind": "proposal", "date": date(2027, 5, 31), "raw": "Proposal: May 2027"}],
    )
    prop = next(m for m in ms if m.name == "proposal defense")
    assert prop.due == date(2026, 12, 20) and prop.estimate == date(2027, 5, 31)
    assert any("later than rule due" in n for n in prop.notes)


def test_visiting_has_no_milestones() -> None:
    assert plan_for({"id": "v", "program": "visiting"}, TODAY) == []
    assert plan_for({"id": "v", "program": None}, TODAY) == []
