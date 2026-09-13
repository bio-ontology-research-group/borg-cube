from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cube.agents import agent_context, load_agent
from cube.agents.charter import render_charter
from cube.agents.scaffold import AgentScaffoldSpec
from cube.cli import main
from cube.config import load_settings
from cube.doctor import check_agent_topics
from cube.sources.rkg import KgProjectNode
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures, make_repo

globals().update(fixtures())


def _group_config() -> str:
    return """
group:
  experts:
    ontology:
      topics: [applied-ontology, topic-b]
      gpu_hours: 4
    genomics:
      topics: [genomics]
      gpu_hours: 2
  functional:
    editor:
      role: editor
      topics: [applied-ontology]
      skills: [paper-writing]
      title: Manuscript editor
"""


def _group_repo(tmp_path: Path) -> Path:
    root = make_repo(tmp_path)
    (root / "cube.yaml").write_text(
        (root / "cube.yaml").read_text(encoding="utf-8") + _group_config(), encoding="utf-8"
    )
    agents = root / "agents"
    agents.mkdir()
    for name in ("coordinator", "liaison", "ontology"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", agents / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, agents / name)
    # The fixture ontology agent starts from a placeholder charter whatever the
    # real repo holds, so charter regeneration is exercised deterministically.
    (agents / "ontology" / "charter.md").write_text(
        "# Ontology expert\n\nThis is example charter text for Robert to edit.\n",
        encoding="utf-8",
    )
    (agents / "ontology" / "charter.md.bak").unlink(missing_ok=True)
    graph = {
        "@graph": [
            {"@id": "borg-id:topic/applied-ontology", "@type": "borg:Topic"},
            {"@id": "borg-id:topic/topic-b", "@type": "borg:Topic"},
            {"@id": "borg-id:topic/genomics", "@type": "borg:Topic"},
            {
                "@id": "borg-id:project/covered",
                "@type": "borg:Project",
                "schema:name": "Covered project",
                "borg:startYear": 2025,
                "borg:endYear": 2026,
                "borg:topic": [{"@id": "borg-id:topic/applied-ontology"}],
                "schema:abstract": "Covered aim.",
            },
            {
                "@id": "borg-id:project/uncovered",
                "@type": "borg:Project",
                "schema:name": "Uncovered project",
                "borg:startYear": 2025,
                "borg:endYear": None,
                "borg:topic": [{"@id": "borg-id:topic/genomics"}],
                "schema:abstract": "Genomics aim.",
            },
            {
                "@id": "borg-id:project/old",
                "@type": "borg:Project",
                "schema:name": "Old project",
                "borg:endYear": 2025,
                "borg:topic": [{"@id": "borg-id:topic/genomics"}],
            },
        ]
    }
    (root / "rkg" / "projects.jsonld").write_text(json.dumps(graph), encoding="utf-8")
    (root / "rkg" / "topics").mkdir()
    for slug, text in {
        "applied-ontology": "# Applied\n\nFirst mandate sentence. Second mandate sentence.\n\n"
        "A DOI 10.1234/topic.one appears here.",
        "topic-b": "# Topic B\n\nA third mandate sentence.",
        "genomics": "# Genomics\n\nGenomics mandate.",
    }.items():
        (root / "rkg" / "topics" / f"{slug}.md").write_text(text, encoding="utf-8")
    return root


def _json(capsys: pytest.CaptureFixture[str]) -> object:
    return json.loads(capsys.readouterr().out)


def test_group_config_is_strict_and_doctor_rejects_unknown_topic(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    path = root / "cube.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\ngroup:\n  experts:\n    bad: {topics: [unknown-topic]}\n",
        encoding="utf-8",
    )
    settings = load_settings(root)
    check = check_agent_topics(settings)[0]
    assert not check.ok and "unknown-topic" in check.detail
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("unknown-topic", "known-topic")
        .replace("{topics: [known-topic]}", "{topics: [known-topic], unexpected: true}"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(root)


def test_group_plan_reports_creation_drift_and_coverage(tmp_path: Path, capsys) -> None:
    root = _group_repo(tmp_path)
    assert main(["--root", str(root), "group", "plan", "--json"]) == 0
    data = _json(capsys)
    assert isinstance(data, dict)
    assert {row["name"] for row in data["create"]} == {"editor", "genomics"}
    assert [row["name"] for row in data["drift"]] == ["ontology"]
    assert data["uncovered_topics"] == ["topic-b", "genomics"]
    assert data["active_projects_without_expert"][0]["slug"] == "uncovered"


def test_group_apply_creates_idempotently_and_reconciles_only_declared_fields(
    tmp_path: Path, capsys
) -> None:
    root = _group_repo(tmp_path)
    assert main(["--root", str(root), "group", "apply", "--apply", "--json"]) == 0
    first = _json(capsys)
    assert {row["name"] for row in first["created"]} == {"editor", "genomics"}
    assert (root / "agents/editor/charter.md").read_text(encoding="utf-8").startswith("---")
    assert "example" not in (root / "agents/editor/charter.md").read_text().lower()
    assert main(["--root", str(root), "group", "apply", "--apply", "--json"]) == 0
    second = _json(capsys)
    assert second["created"] == []

    ontology = root / "agents/ontology.yaml"
    before = yaml.safe_load(ontology.read_text(encoding="utf-8"))
    old_charter = (root / "agents/ontology/charter.md").read_text(encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(root),
                "group",
                "apply",
                "--apply",
                "--reconcile",
                "--charters",
                "--json",
            ]
        )
        == 0
    )
    result = _json(capsys)
    after = yaml.safe_load(ontology.read_text(encoding="utf-8"))
    assert result["reconciled"][0]["name"] == "ontology"
    assert before["title"] == after["title"] and before["role"] == after["role"]
    assert before["memory_dir"] == after["memory_dir"]
    assert after["topics"] == ["applied-ontology", "topic-b"]
    assert after["skills"] == ["literature-review", "research-planning"]
    assert (root / "agents/ontology/charter.md.bak").read_text() == old_charter
    assert "example" not in (root / "agents/ontology/charter.md").read_text().lower()


def test_charter_rendering_is_source_backed_and_has_three_success_items() -> None:
    spec = AgentScaffoldSpec(
        name="expert",
        kind="expert",
        title="Fixture expert",
        topics=["applied-ontology"],
        role="senior",
        runtime="claude",
    )
    projects = [
        KgProjectNode(
            id="borg-id:project/fixture",
            slug="fixture",
            name="Fixture project",
            start_year=2026,
            end_year=2026,
            topics=["borg-id:topic/applied-ontology"],
            abstract="Build a reproducible fixture.",
        )
    ]
    text = render_charter(
        {
            "applied-ontology": "# Topic\n\nFirst sentence. Second sentence.\n\n"
            "DOI 10.5555/example.1."
        },
        projects,
        spec,
    )
    assert "First sentence. (rkg: topics/applied-ontology.md)" in text
    assert "Second sentence. (rkg: topics/applied-ontology.md)" in text
    assert "Fixture project (2026-2026)" in text
    assert "10.5555/example.1" in text
    assert "example charter text" not in text.lower()
    assert text.count("- ") >= 3


def test_group_status_shape_and_coordinator_context(
    tmp_path: Path, capsys, fake_bd: FakeBd
) -> None:
    root = _group_repo(tmp_path)
    (root / "state/agents/ontology").mkdir(parents=True)
    (root / "state/agents/ontology/resources.json").write_text(
        json.dumps(
            {
                "date": datetime.now(UTC).date().isoformat(),
                "runs": 2,
                "spend_usd": 1.5,
                "gpu_hours": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "agents/ontology/inbox.jsonl").write_text(
        '{"read":false,"text":"pending"}\n', encoding="utf-8"
    )
    fake_bd.add(
        "pipeline-work",
        labels=["agent:ontology", "goal:pipe-1", "pipeline-stage:survey"],
    )
    assert main(["--root", str(root), "group", "status", "--json"]) == 0
    data = _json(capsys)
    assert isinstance(data, dict)
    row = next(item for item in data["agents"] if item["name"] == "ontology")
    assert row["today"] == {"runs": 2, "spend_usd": 1.5}
    assert row["inbox_unread"] == 1
    assert row["pipelines"] == [
        {"bead": "pipeline-work", "pipeline": "pipe-1", "stages": ["survey"]}
    ]
    context = agent_context(load_settings(root), load_agent(root, "coordinator"))
    assert "## Group" in context
    assert "ontology (senior)" in context
    assert "Uncovered configured expert topics" in context


def test_agent_new_extended_flags(tmp_path: Path, capsys) -> None:
    root = make_repo(tmp_path)
    assert (
        main(
            [
                "--root",
                str(root),
                "agent",
                "new",
                "flagged",
                "--kind",
                "expert",
                "--title",
                "Flagged expert",
                "--topic",
                "applied-ontology",
                "--role",
                "senior",
                "--runtime",
                "claude",
                "--skill",
                "reproducibility-check",
                "--gpu-hours",
                "2",
                "--host",
                "ws",
                "--spend-usd",
                "3",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    agent = load_agent(root, "flagged")
    assert agent.skills == ["literature-review", "research-planning", "reproducibility-check"]
    assert agent.resources.node005_gpu_hours_per_day == 2
    assert agent.resources.spend_usd_per_day == 3
