from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import Request

import pytest

from cube.cli import main
from cube.roster import RosterPolicy, SourceFact, reconcile_roster, render_people_yaml
from cube.sources.org import parse_group_roster
from cube.sources.website import (
    GROUPS,
    WebsiteParseError,
    WebsiteSource,
    parse_profile_page,
)

FIX = Path(__file__).parent / "fixtures" / "website"


def test_staff_group_section_does_not_treat_milestone_sections_as_roster(tmp_path: Path) -> None:
    path = tmp_path / "staff.org"
    path.write_text(
        """* Group summer 2026
** Staff
- Ada Person (research scientist)
** Students
- Bea Student
* Students
** Historical Detail
- Graduates: May 2025
* Alumni
** Cal Former
""",
        encoding="utf-8",
    )
    roster = parse_group_roster(path)
    assert roster.section == "Group summer 2026"
    assert [(row.name, row.role_text) for row in roster.current] == [
        ("Ada Person", "research scientist"),
        ("Bea Student", None),
    ]
    assert [row.name for row in roster.alumni] == ["Cal Former"]
    assert all(row.name != "Historical Detail" for row in roster.current)


def test_website_parser_uses_saved_profile_lists_and_fails_loudly() -> None:
    counts = {
        "students": 11,
        "research-scientists": 2,
        "postdoctoral-fellows": 1,
        "research-staff": 4,
        "principal-investigators": 1,
    }
    for group, count in counts.items():
        profiles = parse_profile_page((FIX / f"{group}.html").read_text(), group)
        assert len(profiles) == count
    students = parse_profile_page((FIX / "students.html").read_text(), "students")
    dan = next(profile for profile in students if profile.slug == "dan-doe")
    assert dan.program == "PhD-Bioeng"
    with pytest.raises(WebsiteParseError, match="could not parse"):
        parse_profile_page("<html><h1>Students</h1><p>redesigned</p></html>", "students")


def test_website_source_fetches_each_page_once_then_uses_offline_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(request: Request) -> bytes:
        group = request.full_url.rsplit("/", 1)[-1]
        calls.append(group)
        return (FIX / f"{group}.html").read_bytes()

    source = WebsiteSource(
        tmp_path,
        fetcher=fetch,
        now=datetime(2026, 9, 2, 9, tzinfo=UTC),
    )
    fresh = source.roster()
    assert calls == list(GROUPS)
    assert len(fresh.profiles) == 19 and not fresh.cached and not fresh.errors
    offline = WebsiteSource(tmp_path, fetcher=fetch).roster(offline=True)
    assert calls == list(GROUPS)
    assert len(offline.profiles) == 19 and offline.cached


def _row(facts: list[SourceFact], slug: str):  # type: ignore[no-untyped-def]
    return next(person for person in reconcile_roster(facts) if person.slug == slug)


@pytest.mark.parametrize("name", ["Gus Student", "Kit Scholar", "Mia Novice", "Ned Pupil"])
def test_website_people_absent_from_staff_are_reported(name: str) -> None:
    slug = name.lower().replace(" ", "-")
    person = _row(
        [
            SourceFact("website", slug, name, "student", "MS-Bioeng"),
            SourceFact("people_yaml", slug, name, "student", "MS-Bioeng"),
        ],
        slug,
    )
    assert not person.present["staff_org"] and person.status == "only-in"


@pytest.mark.parametrize("name", ["Fay Former", "Gil Former"])
def test_people_yaml_only_is_reported(name: str) -> None:
    slug = name.lower().replace(" ", "-")
    person = _row([SourceFact("people_yaml", slug, name, "student")], slug)
    assert person.status == "only-in"


@pytest.mark.parametrize(
    "name,role",
    [
        ("Carla Staff", "staff"),
        ("Uma Postdoc", "postdoc"),
        ("Vin Intern", "intern"),
        ("Wen Student", "student"),
        ("Vic Visitor", "visiting"),
    ],
)
def test_current_source_people_missing_from_people_yaml(name: str, role: str) -> None:
    slug = name.lower().replace(" ", "-")
    person = _row([SourceFact("staff_org", slug, name, role)], slug)
    assert person.status == "only-in" and not person.present["people_yaml"]


def test_program_disagreement_is_reported_but_website_wins_by_policy() -> None:
    facts = [
        SourceFact("people_yaml", "dan-doe", "Dan Doe", "student", "PhD-CS"),
        SourceFact("website", "dan-doe", "Dan Doe", "student", "PhD-Bioeng"),
    ]
    person = _row(facts, "dan-doe")
    assert person.status == "conflict" and person.program == "PhD-Bioeng"
    assert person.conflicts == [
        {
            "field": "program",
            "values": {"people_yaml": "PhD-CS", "website": "PhD-Bioeng"},
        }
    ]


@pytest.mark.parametrize(
    ("facts", "membership", "pending", "left"),
    [
        ([SourceFact("website", "site-only", "Site Only", "student")], "current", None, None),
        (
            [
                SourceFact("people_yaml", "alumnus", "Alumnus", "student", data={"source": "old"}),
                SourceFact("staff_org", "alumnus", "Alumnus", current=False),
            ],
            "former",
            None,
            "staff.org Alumni section",
        ),
        (
            [SourceFact("staff_org", "staff-note", "Staff Note", "student")],
            "current",
            "not on roster of record",
            None,
        ),
    ],
)
def test_authority_membership_table(
    facts: list[SourceFact], membership: str, pending: str | None, left: str | None
) -> None:
    person = reconcile_roster(facts)[0]
    assert person.membership == membership and person.pending == pending
    rendered = render_people_yaml([person], noted=date(2026, 9, 2))
    if left:
        assert f"left: {left}" in rendered
    if pending:
        assert f"pending: {pending}" in rendered


def test_configured_field_conflict_remains_a_conflict() -> None:
    person = reconcile_roster(
        [
            SourceFact("website", "case", "Case", "student", "PhD-Bioeng"),
            SourceFact("staff_org", "case", "Case", "student", "PhD-CS"),
        ],
        RosterPolicy(fields_from={"program": ("website", "staff_org")}),
    )[0]
    assert person.program == "PhD-Bioeng"
    assert person.conflicts == [
        {"field": "program", "values": {"website": "PhD-Bioeng", "staff_org": "PhD-CS"}}
    ]


@pytest.mark.parametrize(
    "slug,name",
    [
        ("xia-alumna", "Xia Alumna"),
        ("yan-alumnus", "Yan Alumnus"),
        ("pat-postdoc", "Pat Postdoc"),
        ("zed-former", "Zed Former"),
        ("ron-engineer", "Ron Engineer"),
        ("quinn-specialist", "Quinn Specialist"),
    ],
)
def test_staff_alumni_still_current_in_yaml_are_flagged(slug: str, name: str) -> None:
    facts = [
        SourceFact("people_yaml", slug, name, "staff", current=True),
        SourceFact("staff_org", slug, name, current=False),
    ]
    person = _row(facts, slug)
    assert person.status == "alumni"
    assert [conflict["field"] for conflict in person.conflicts] == ["status"]


def test_yaml_only_scientist_is_not_invented_as_alumni() -> None:
    person = _row(
        [SourceFact("people_yaml", "hope-former", "Hope Former", "research-scientist")],
        "hope-former",
    )
    assert person.status == "only-in" and not person.conflicts


def test_roster_sync_dry_run_returns_expected_text_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = "people:\n  old-person: {name: Old Person, role: staff, source: old}\n"
    people_path = tmp_path / "people.yaml"
    people_path.write_text(before, encoding="utf-8")
    (tmp_path / "cube.yaml").write_text("beads: {bin: missing-bd}\n", encoding="utf-8")
    rows = reconcile_roster(
        [
            SourceFact("staff_org", "new-person", "New Person", "staff"),
            SourceFact(
                "people_yaml",
                "old-person",
                "Old Person",
                "staff",
                current=True,
                data={"name": "Old Person", "role": "staff", "source": "old"},
            ),
            SourceFact("staff_org", "old-person", "Old Person", current=False),
        ]
    )
    expected = render_people_yaml(rows, noted=date(2026, 9, 2))

    import cube.commands.roster as command

    monkeypatch.setattr(command, "roster_payload", lambda *args, **kwargs: ({}, rows))
    rc = main(
        [
            "--root",
            str(tmp_path),
            "roster",
            "sync",
            "--today",
            "2026-09-02",
            "--json",
        ]
    )
    assert rc == 0 and people_path.read_text(encoding="utf-8") == before
    result = json.loads(capsys.readouterr().out)
    assert not result["applied"] and result["diff"]
    assert "former:" in expected and "conflicts:" in expected
    assert "+  new-person:" in result["diff"]
