from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cube.commands.projects import build_project_rows, projects_summary
from cube.sources.github import RepoRecord, Snapshot
from cube.sources.org import parse_papers
from cube.sources.pa_kg import load_projects
from cube.sources.rkg import load_graph


def test_projects_join_kg_pa_papers_github_and_open_beads(tmp_path: Path) -> None:
    graph_path = tmp_path / "projects.jsonld"
    graph_path.write_text(
        json.dumps(
            {
                "@graph": [
                    {
                        "@id": "borg-id:project/active-project",
                        "@type": "borg:Project",
                        "schema:name": "Active project",
                        "borg:startYear": 2025,
                        "borg:endYear": None,
                        "borg:hasMember": [
                            {
                                "@id": "borg-id:person/lead-person",
                                "borg:roleOnProject": "PI",
                            },
                            {
                                "@id": "borg-id:person/member-person",
                                "borg:roleOnProject": "student",
                            },
                        ],
                        "borg:fundedBy": [{"@id": "borg-id:grant/grant-one"}],
                        "borg:topic": [{"@id": "borg-id:topic/topic-one"}],
                        "borg:producedPub": [{"@id": "borg-id:pub/test-publication"}],
                        "borg:producedSW": [{"@id": "borg-id:software/test-software"}],
                    },
                    {
                        "@id": "borg-id:project/ending-project",
                        "@type": "borg:Project",
                        "schema:name": "Ending project",
                        "borg:startYear": 2024,
                        "borg:endYear": 2026,
                    },
                    {
                        "@id": "borg-id:project/ended-project",
                        "@type": "borg:Project",
                        "schema:name": "Ended project",
                        "borg:startYear": 2020,
                        "borg:endYear": 2025,
                    },
                    {
                        "@id": "borg-id:software/test-software",
                        "@type": "schema:SoftwareApplication",
                        "schema:name": "Test software",
                        "schema:codeRepository": "https://github.com/example/test-software",
                    },
                    {
                        "@id": "borg-id:pub/test-publication",
                        "@type": "schema:ScholarlyArticle",
                        "schema:name": "Test publication",
                        "schema:datePublished": "2026-08-01",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    pa_dir = tmp_path / "pa"
    pa_dir.mkdir()
    (pa_dir / "active-project.md").write_text(
        """---
id: pa-id:project/active-project
name: Active project
status: active
members: []
papers: []
software: []
---
# Active project
## Status as of 2026-08-25
Work continues.
""",
        encoding="utf-8",
    )
    papers_path = tmp_path / "papers.org"
    papers_path.write_text(
        """#+TODO: TODO | PUBLISHED
* Published
** PUBLISHED Test publication
CLOSED: [2026-08-22 Sat]
""",
        encoding="utf-8",
    )
    snapshot = Snapshot(
        org="example",
        fetched_at="2026-09-02T08:00:00+00:00",
        repos=[
            RepoRecord(
                full_name="example/test-software",
                name="test-software",
                html_url="https://github.com/example/test-software",
                pushed_at="2026-08-20T12:00:00Z",
            )
        ],
    )
    beads = [
        {
            "id": "cube-1",
            "status": "open",
            "labels": ["project:active-project"],
            "updated_at": "2026-08-30T10:00:00+00:00",
        },
        {
            "id": "cube-2",
            "status": "in_progress",
            "labels": [{"name": "project:active-project"}],
            "updated_at": "2026-09-01T10:00:00+00:00",
        },
        {
            "id": "cube-3",
            "status": "blocked",
            "labels": ["project:active-project"],
            "updated_at": "2026-08-31T10:00:00+00:00",
        },
        {
            "id": "cube-closed",
            "status": "closed",
            "labels": ["project:active-project"],
            "updated_at": "2026-09-02T10:00:00+00:00",
        },
    ]

    rows, warnings = build_project_rows(
        load_graph(graph_path),
        load_projects(pa_dir),
        parse_papers(papers_path),
        snapshot,
        beads,
        today=date(2026, 9, 2),
    )
    assert not warnings and rows[0]["slug"] == "active-project"
    active = next(
        row for row in rows if row["source"] == "research-kg" and row["slug"] == "active-project"
    )
    assert active["status"] == "active" and active["status_source"] == "beads:last-activity"
    assert active["members"] == ["lead-person", "member-person"]
    assert active["lead"] == "lead-person"
    assert active["grants"] == ["grant-one"] and active["topics"] == ["topic-one"]
    assert active["papers"] == {"count": 1, "last": "2026-08-22"}
    assert active["software"] == {
        "count": 1,
        "last_commit": "2026-08-20T12:00:00Z",
    }
    assert active["beads"] == {
        "open": 3,
        "in_progress": 1,
        "blocked": 1,
        "last_activity": "2026-09-01T10:00:00+00:00",
    }
    assert active["pa_status"] == "active"
    assert active["pa_status_as_of"] == "2026-08-25"
    assert active["last_activity"] == "2026-09-01T10:00:00+00:00"
    by_slug = {row["slug"]: row for row in rows}
    assert by_slug["ending-project"]["status"] == "ending"
    assert by_slug["ended-project"]["status"] == "ended"
    assert projects_summary(rows) == {
        "total": 4,
        "active": 2,
        "ending": 1,
        "ended": 1,
        "unknown": 0,
    }


def test_pa_projects_are_first_class_redacted_and_take_paper_activity(tmp_path: Path) -> None:
    graph_path = tmp_path / "projects.jsonld"
    graph_path.write_text(
        json.dumps(
            {
                "@graph": [
                    {
                        "@id": "borg-id:project/grant",
                        "@type": "borg:Project",
                        "schema:name": "Grant",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "private.md").write_text(
        """---
id: pa-id:project/private
name: Private work
kind: research
status: active
private: true
startYear: 2026
abstract: secret
papers: [Linked paper]
public_kg: [borg-id:project/grant]
members: [{person: person-one, role: PI}]
---
# Private work
## Status as of 2026-08-31
""",
        encoding="utf-8",
    )
    papers_path = tmp_path / "papers.org"
    papers_path.write_text(
        "#+TODO: REVISING | PUBLISHED\n"
        "* Current\n"
        "** REVISING Linked paper\n"
        "CLOSED: [2026-09-01 Mon]\n",
        encoding="utf-8",
    )
    rows, _ = build_project_rows(
        load_graph(graph_path),
        load_projects(projects_dir),
        parse_papers(papers_path),
        Snapshot("x", ""),
        [],
        today=date(2026, 9, 2),
    )
    private = next(row for row in rows if row["source"] == "pa")
    assert private["kind"] == "research" and private["privacy"] == "local-only"
    assert private["abstract"] is None and private["papers"]["last"] == "2026-09-01"
    assert private["public_kg"] == [
        {"iri": "borg-id:project/grant", "slug": "grant", "name": "Grant"}
    ]


def test_attach_runner_profiles_adds_profile_or_none(settings) -> None:  # type: ignore[no-untyped-def]
    from cube.commands.projects import attach_runner_profiles

    rows = [{"slug": "kobayashi-marust"}, {"slug": "unknown-project"}]
    attach_runner_profiles(rows, settings)
    assert all("runner_profile" in row for row in rows)
    assert rows[1]["runner_profile"] is None
