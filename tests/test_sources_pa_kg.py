from datetime import date
from pathlib import Path

from cube.sources.pa_kg import (
    load_contacts,
    load_projects,
    parse_contact,
    parse_deadlines,
    parse_project,
    split_frontmatter,
)

FIX = Path(__file__).parent / "fixtures"


def test_split_frontmatter() -> None:
    fm, body = split_frontmatter("---\na: 1\n---\nbody\n")
    assert fm == {"a": 1} and body.strip() == "body"
    assert split_frontmatter("no fm") == ({}, "no fm")
    assert split_frontmatter("---\nunterminated\n") == ({}, "---\nunterminated\n")


def test_kg_project() -> None:
    proj = parse_project(FIX / "kg" / "projects" / "test-project.md")
    assert proj.slug == "test-project" and proj.id == "pa-id:project/test-project"
    assert proj.name == "Test project" and proj.aliases == ["tp"]
    assert proj.kind == "research" and proj.status == "active" and proj.private is True
    assert [(m.ref, m.ref_kind) for m in proj.members] == [
        ("robert-hoehndorf", "person"),
        ("alex-example", "contact"),
    ]
    assert proj.members[1].role == "student, first author"
    assert proj.papers == ["pa-id:paper/test-2026"] and proj.software == ["borg-id:software/mowl"]
    assert proj.directories[0]["path"] == "~/Documents/papers/test"
    assert proj.status_as_of == date(2026, 8, 1)  # latest of the two mentions
    assert proj.freshness_date() == date(2026, 8, 1)
    projects = load_projects(FIX / "kg" / "projects")
    assert {p.slug for p in projects} == {"test-project", "fresh-project"}
    assert load_projects(FIX / "nope") == []


def test_deadlines() -> None:
    ds = parse_deadlines(FIX / "deadlines.md")
    assert len(ds) == 4
    crg = ds[0]
    assert crg.when == date(2026, 9, 28) and crg.pa_id == "aaaa1111" and crg.status == "open"
    assert crg.text.startswith("CRG2026 full proposal") and "[status" not in crg.text
    assert crg.xid == "pa:aaaa1111" and crg.section == "Open" and crg.line == 5
    bare = ds[2]
    assert (
        bare.pa_id is None
        and bare.status == "open"
        and bare.xid.startswith("pa:deadline:2026-09-05:")
    )
    assert ds[3].status == "done" and not ds[3].is_open
    assert parse_deadlines(FIX / "missing.md") == []


def test_contacts() -> None:
    c = parse_contact(FIX / "contacts" / "alex-example.md")
    assert c.name == "Alex Example" and c.emails == ["alex.example@example.org"]
    assert c.mattermost == "alexexample"
    n = parse_contact(FIX / "contacts" / "no-handle.md")
    assert n.mattermost == "nohandle"
    assert {x.slug for x in load_contacts(FIX / "contacts")} == {"alex-example", "no-handle"}
