from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cube.beads import Beads
from cube.cli import main
from cube.config import Settings, load_settings
from cube.engine import review_gate
from cube.engine.marshal import role_for, subprocess_dispatch
from cube.engine.run import execute
from cube.goals import GoalHeader
from cube.model import Provenance, RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.patrols.pipeline import PipelinePatrol
from cube.pipeline import (
    advance,
    ask,
    new_pipeline,
    pipeline_status,
    record_plan_artifacts,
    record_team_artifact,
    recruit,
    review_pipeline_progress,
    stage_prompt,
    validate_team_artifact,
)
from cube.roles import load_all
from cube.runners import StubRunner
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())


def _ledger(repo: Path) -> Beads:
    return Beads(bin="bd", cwd=repo)


def _plan(path: Path, *, valid: bool = True) -> Path:
    plan = {
        "plan": "fixture-pipeline",
        "question": "Can the fixture pipeline answer the research question?",
        "provenance": ["bead:fixture::replan"],
        "privacy": "internal",
        "owner": "programmer",
        "deadline": "2026-12-31",
        "hypotheses": [
            {"id": "h1", "statement": "The method helps", "predicts": "score rises"},
            {"id": "h0", "statement": "The method does not help", "predicts": "no rise"},
        ],
        "experiments": [
            {
                "id": "prepare",
                "title": "Prepare the fixture data",
                "baselines": ["unchanged input"],
                "success_threshold": "100% of fixture rows load",
                "kill_criterion": "stop if any fixture row is corrupt",
                "metric": "loaded row percentage",
                "tests": ["h1"],
                "depends_on": [],
                "acceptance": ["the fixture file exists"],
            },
            {
                "id": "evaluate",
                "title": "Evaluate the fixture method",
                "baselines": ["unchanged input"],
                "success_threshold": "score is at least 0.8",
                "kill_criterion": "stop if the score is below 0.2",
                "metric": "fixture score",
                "tests": ["h1", "h0"],
                "depends_on": ["prepare"],
                "acceptance": ["the report contains a score table"],
            },
        ],
        "risks": [],
        "checkpoints": [],
    }
    if not valid:
        plan["experiments"][0].pop("kill_criterion")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    return path


def _new(settings: Settings, ledger: Beads, *, project: str | None = None) -> dict:
    (settings.root / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "liaison", "ontology", "protein-function"):
        target = settings.root / "agents" / f"{name}.yaml"
        if not target.exists():
            shutil.copy2(REPO_ROOT / "agents" / f"{name}.yaml", target)
            shutil.copytree(REPO_ROOT / "agents" / name, settings.root / "agents" / name)
    return new_pipeline(
        settings,
        ledger,
        title="Fixture research",
        target=date(2026, 12, 31),
        success=["gate 2 passes"],
        question=(
            "Collect the email I sent about fixtures: extract the ideas, list the papers "
            "and the code I already have (links, DOIs, local repositories)"
        ),
        person="robert",
        project=project,
        privacy="internal",
        provenance=[Provenance(source="fixture", locator="pipeline request")],
    )


def _fixture_project(settings: Settings, slug: str = "fixture-project") -> Path:
    """Write a PA project page in the temporary test repository."""
    path = settings.dirs["pa"] / "kg" / "projects" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
id: pa-id:project/fixture-project
name: Fixture project
members:
  - person: robert-hoehndorf
    role: principal investigator
  - person: cole-collaborator
    role: external collaborator
---

# Fixture project
""",
        encoding="utf-8",
    )
    return path


def _close_through_replan(settings: Settings, ledger: Beads, created: dict) -> None:
    team_path = settings.runs_dir() / "pipelines" / created["epic"] / "team.yaml"
    team_path.parent.mkdir(parents=True, exist_ok=True)
    team_path.write_text(
        yaml.safe_dump(
            {
                "team": [
                    {
                        "member": "role:programmer",
                        "why": "implements experiments (source: roles/programmer.yaml)",
                    }
                ],
                "lead": "agent:coordinator",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    for name in ("collect", "team", "plan1:draft", "plan1:final", "survey"):
        ledger.close(created["stages"][name], f"fixture closed {name}")
    advance(settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False)
    for bead in ledger.list_issues("--all"):
        if f"goal:{created['epic']}" in bead.get("labels", []) and "planning-round:2" in bead.get(
            "labels", []
        ):
            ledger.close(str(bead["id"]), "fixture closed round two")


def _labels(fake_bd: FakeBd, bead: str) -> set[str]:
    return set(fake_bd.bead(bead)["labels"])


def _team_payload(*members: dict[str, str]) -> dict:
    return {"team": list(members), "lead": "agent:coordinator"}


def _record_team(
    settings: Settings,
    ledger: Beads,
    fake_bd: FakeBd,
    created: dict,
    tmp_path: Path,
    payload: dict | None = None,
) -> dict:
    source = tmp_path / "team-source.yaml"
    source.write_text(
        yaml.safe_dump(
            payload
            or _team_payload(
                {
                    "member": "agent:ontology",
                    "role": "senior",
                    "why": "topic match (source: agents/ontology.yaml)",
                },
                {
                    "member": "role:programmer",
                    "why": "implements experiments (source: roles/programmer.yaml)",
                },
                {
                    "member": "person:gus-student",
                    "role": "student",
                    "why": "current MS-CS roster entry (source: people.yaml)",
                },
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = record_team_artifact(
        settings,
        ledger,
        fake_bd.bead(created["stages"]["team"]),
        tmp_path,
        RunResult(summary="team selected", artifacts=[{"kind": "team", "path": str(source)}]),
        today=date(2026, 9, 3),
    )
    return result


def test_new_pipeline_is_idempotent_and_builds_ordered_stages(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    first = _new(engine_settings, ledger)
    second = _new(engine_settings, ledger)

    assert first == second
    assert len(fake_bd.beads()) == 6
    epic = first["epic"]
    assert {"kind:goal", "pipeline:research", "privacy:internal"} <= _labels(fake_bd, epic)
    expected = {
        "collect": {"kind:request", "agent:liaison", "host:laptop"},
        "team": {
            "kind:design",
            "stage:design",
            "role:group-leader",
            "agent:coordinator",
        },
        "plan1:draft": {"kind:design", "stage:design", "role:group-leader"},
        "plan1:final": {"kind:design", "stage:design", "role:group-leader"},
        "survey": {"kind:research", "role:senior"},
    }
    from cube.agents.liaison import request_question

    for name, labels in expected.items():
        bead = fake_bd.bead(first["stages"][name])
        assert labels <= set(bead["labels"])
        expected_stage = name.split(":")[-1]
        assert {
            f"goal:{epic}",
            f"pipeline-stage:{expected_stage}",
            "privacy:internal",
        } <= set(bead["labels"])
        assert GoalHeader.parse(fake_bd.bead(epic)["description"])
    assert request_question(fake_bd.bead(first["stages"]["collect"])).startswith(
        "Collect the email I sent"
    )
    assert fake_bd.dependencies(first["stages"]["team"]) == [first["stages"]["collect"]]
    assert fake_bd.dependencies(first["stages"]["plan1:draft"]) == [first["stages"]["team"]]
    assert fake_bd.dependencies(first["stages"]["plan1:final"]) == [first["stages"]["plan1:draft"]]
    assert fake_bd.dependencies(first["stages"]["survey"]) == [first["stages"]["plan1:final"]]


def test_status_and_marshal_roles_follow_stage_dependencies(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    status = pipeline_status(engine_settings, ledger, created["epic"], today=date(2026, 9, 3))
    assert status["stage"] == "collect"
    assert status["iteration"] == 0
    assert status["stages"][1]["blocked_by"] == [created["stages"]["collect"]]
    assert "liaison" in status["next"]

    roles, _ = load_all(engine_settings.root)
    assert role_for(fake_bd.bead(created["stages"]["team"]), roles) == "group-leader"
    assert role_for(fake_bd.bead(created["stages"]["plan1:draft"]), roles) == "group-leader"
    assert role_for(fake_bd.bead(created["stages"]["survey"]), roles) == "senior"
    assert created["stages"]["plan1:draft"] not in {row["id"] for row in ledger.ready()}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            _team_payload(
                {
                    "member": "agent:missing",
                    "role": "senior",
                    "why": "topic match (source: agents/missing.yaml)",
                }
            ),
            "no such agent",
        ),
        (
            _team_payload(
                {
                    "member": "role:marshal",
                    "why": "dispatch role (source: roles/marshal.yaml)",
                }
            ),
            "non-python",
        ),
        (
            _team_payload(
                {
                    "member": "person:quinn-specialist",
                    "role": "student",
                    "why": "former roster row (source: people.yaml)",
                }
            ),
            "not current",
        ),
        (
            _team_payload(
                {
                    "member": "person:gus-student",
                    "role": "student",
                    "why": "current roster row (source: people.yaml)",
                }
            ),
            "at least one agent or role",
        ),
        (
            {
                "team": [
                    {
                        "member": "role:programmer",
                        "why": "implementation (source: roles/programmer.yaml)",
                    }
                ],
                "lead": "role:group-leader",
            },
            "lead must be",
        ),
        (
            _team_payload({"member": "role:programmer", "why": ""}),
            "source-backed reason",
        ),
    ],
)
def test_team_artifact_validation_branches(
    engine_settings: Settings,
    fake_bd: FakeBd,
    payload: dict,
    message: str,
) -> None:
    _new(engine_settings, _ledger(engine_settings.root))
    _normalized, errors = validate_team_artifact(engine_settings, payload)

    assert any(message in error for error in errors)


def test_team_artifact_validates_collaborators_from_fixture_project_page(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fixture_project(engine_settings)
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger, project="fixture-project")
    epic = fake_bd.bead(created["epic"])
    valid, errors = validate_team_artifact(
        engine_settings,
        _team_payload(
            {
                "member": "agent:ontology",
                "role": "senior",
                "why": "ontology topic (source: agents/ontology.yaml)",
            },
            {
                "member": "collaborator:cole-collaborator",
                "role": "registered lead",
                "why": (
                    "listed on the fixture project page (source: pa/kg/projects/fixture-project.md)"
                ),
            },
        ),
        epic=epic,
    )
    assert not errors
    assert valid["team"][1]["member"] == "collaborator:cole-collaborator"

    _normalized, errors = validate_team_artifact(
        engine_settings,
        _team_payload(
            {
                "member": "agent:ontology",
                "role": "senior",
                "why": "ontology topic (source: agents/ontology.yaml)",
            },
            {
                "member": "collaborator:unknown-person",
                "role": "external advisor",
                "why": "fixture project membership (source: pa/kg/projects/fixture-project.md)",
            },
        ),
        epic=epic,
    )
    assert any("collaborator:unknown-person is not a member" in error for error in errors)


def test_team_artifact_validates_maximum_and_creates_member_critiques(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    valid = _record_team(engine_settings, ledger, fake_bd, created, tmp_path)

    assert valid["close"] and not valid["errors"]
    assert Path(valid["paths"][0]).is_file()
    critiques = [
        item for item in fake_bd.beads().values() if "pipeline-stage:critique" in item["labels"]
    ]
    assert len(critiques) == 3
    by_member = {
        next(label for label in item["labels"] if label.startswith("pipeline-member:")): item
        for item in critiques
    }
    ontology = by_member["pipeline-member:ontology"]
    programmer = by_member["pipeline-member:programmer"]
    person = by_member["pipeline-member:gus-student"]
    assert {"agent:ontology", "role:senior"} <= set(ontology["labels"])
    assert "role:programmer" in programmer["labels"]
    assert "person:gus-student" in person["labels"]
    assert not any(label.startswith("role:") for label in person["labels"])
    assert fake_bd.dependency_records(person["id"]) == [
        {"id": created["stages"]["plan1:draft"], "dependency_type": "related"}
    ]
    final_dependencies = set(fake_bd.dependencies(created["stages"]["plan1:final"]))
    assert {ontology["id"], programmer["id"]} <= final_dependencies
    assert person["id"] not in final_dependencies

    engine_settings.pipeline.max_team = 2
    _normalized, errors = validate_team_artifact(
        engine_settings, yaml.safe_load(Path(valid["paths"][0]).read_text())
    )
    assert any("maximum is 2" in error for error in errors)


def test_invalid_team_stays_open_and_files_one_finding(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    bad = _record_team(
        engine_settings,
        ledger,
        fake_bd,
        created,
        tmp_path,
        _team_payload(
            {
                "member": "role:marshal",
                "why": "python dispatcher (source: roles/marshal.yaml)",
            }
        ),
    )
    again = _record_team(
        engine_settings,
        ledger,
        fake_bd,
        created,
        tmp_path,
        _team_payload(
            {
                "member": "role:marshal",
                "why": "python dispatcher (source: roles/marshal.yaml)",
            }
        ),
    )

    assert not bad["close"] and not again["close"]
    assert fake_bd.bead(created["stages"]["team"])["status"] == "open"
    findings = [
        item
        for item in fake_bd.beads().values()
        if str(item.get("external_ref") or "").endswith(":team-invalid")
    ]
    assert len(findings) == 1
    assert {"kind:finding", "needs:robert"} <= set(findings[0]["labels"])


def test_discussion_blocks_on_agents_not_people_and_records_artifacts(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    ledger.close(created["stages"]["collect"], "fixture collected")
    ledger.close(created["stages"]["team"], "fixture team")
    draft_source = _plan(tmp_path / "draft.yaml")
    draft_report = record_plan_artifacts(
        engine_settings,
        fake_bd.bead(created["stages"]["plan1:draft"]),
        tmp_path,
        RunResult(summary="draft", artifacts=[{"kind": "plan", "path": str(draft_source)}]),
        beads=ledger,
    )
    assert draft_report["close"]
    ledger.close(created["stages"]["plan1:draft"], "draft recorded")
    critiques = [
        item for item in fake_bd.beads().values() if "pipeline-stage:critique" in item["labels"]
    ]
    person = next(item for item in critiques if "person:gus-student" in item["labels"])
    blocking = [item for item in critiques if item["id"] != person["id"]]
    assert person["id"] in {item["id"] for item in ledger.ready()}
    critique_text = "\n".join(
        [
            "## Agree",
            "- Keep the baseline (source: draft)",
            "## Disagree",
            "- Raise the threshold opinion",
            "## Missing",
            "- Add a sensitivity check (source: DOI:10.1234/fixture)",
            "## Risks",
            "- Fixture drift opinion",
        ]
    )
    critique_source = tmp_path / "critique.md"
    critique_source.write_text(critique_text, encoding="utf-8")
    for item in blocking:
        report = record_plan_artifacts(
            engine_settings,
            item,
            tmp_path,
            RunResult(
                summary="critique",
                artifacts=[{"kind": "critique", "path": str(critique_source)}],
            ),
            beads=ledger,
        )
        assert report["close"]
        ledger.close(item["id"], "critique recorded")
    assert created["stages"]["plan1:final"] in {item["id"] for item in ledger.ready()}
    assert fake_bd.bead(person["id"])["status"] == "open"
    draft_comments = fake_bd.bead(created["stages"]["plan1:draft"])["comments"]
    assert len([row for row in draft_comments if "Critique from" in row["text"]]) == 2
    ledger.comment(person["id"], "Optional person critique: keep the simple baseline opinion")
    final_prompt = stage_prompt(
        engine_settings,
        fake_bd.bead(created["epic"]),
        fake_bd.bead(created["stages"]["plan1:final"]),
        beads=ledger,
    )
    assert "Raise the threshold" in final_prompt
    assert "Optional person critique" in final_prompt
    assert "fixture-pipeline" in final_prompt
    decisions = tmp_path / "decisions.md"
    decisions.write_text(
        "- Accepted: add sensitivity check because DOI:10.1234/fixture\n"
        "- Rejected: higher threshold because fixture opinion\n",
        encoding="utf-8",
    )
    final_report = record_plan_artifacts(
        engine_settings,
        fake_bd.bead(created["stages"]["plan1:final"]),
        tmp_path,
        RunResult(
            summary="final",
            artifacts=[
                {"kind": "plan", "path": str(draft_source)},
                {"kind": "decision-log", "path": str(decisions)},
            ],
        ),
        beads=ledger,
    )
    assert final_report["close"]
    pipeline_dir = engine_settings.runs_dir() / "pipelines" / created["epic"]
    assert (pipeline_dir / "discussion" / "plan-v1" / "ontology.md").is_file()
    assert (pipeline_dir / "discussion" / "plan-v1" / "programmer.md").is_file()
    assert (pipeline_dir / "discussion" / "plan-v1" / "decisions.md").is_file()


def test_stage_prompt_contains_team_catalog_help_rule_and_discussion(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    epic = fake_bd.bead(created["epic"])
    team_prompt = stage_prompt(
        engine_settings,
        epic,
        fake_bd.bead(created["stages"]["team"]),
        beads=ledger,
    )

    assert "agent:ontology" in team_prompt
    assert "person:gus-student" in team_prompt
    assert "role:programmer" in team_prompt
    assert "cube pipeline ask" in team_prompt
    assert "Never contact a person directly" in team_prompt


def test_marshal_subprocess_passes_pipeline_stage_prompt(
    engine_settings: Settings,
    fake_bd: FakeBd,
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    commands: list[list[str]] = []

    def popen(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(pid=1234)

    pid = subprocess_dispatch(engine_settings, popen=popen)(
        "group-leader", created["stages"]["team"], "plan"
    )

    assert pid == 1234
    prompt = commands[0][commands[0].index("--prompt") + 1]
    assert "agent:ontology" in prompt
    assert "smallest team" in prompt
    assert "cube pipeline ask" in prompt


def test_pipeline_ask_delivers_to_agent_and_role_and_records_thread(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    payload = _team_payload(
        {
            "member": "agent:ontology",
            "role": "senior",
            "why": "ontology topic (source: agents/ontology.yaml)",
        },
        {
            "member": "agent:protein-function",
            "role": "senior",
            "why": "protein topic (source: agents/protein-function.yaml)",
        },
        {
            "member": "role:programmer",
            "why": "implementation (source: roles/programmer.yaml)",
        },
    )
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path, payload)

    agent_answer = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="agent:protein-function",
        text="Which protein benchmark should we use?",
        dry_run=False,
        now=datetime(2026, 9, 3, 9, tzinfo=UTC),
    )
    role_answer = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="role:programmer",
        text="Can you estimate the fixture implementation?",
        dry_run=False,
        now=datetime(2026, 9, 3, 10, tzinfo=UTC),
    )

    assert agent_answer["delivered"] and role_answer["delivered"]
    inbox = engine_settings.root / "agents" / "protein-function" / "inbox.jsonl"
    assert "Which protein benchmark" in inbox.read_text(encoding="utf-8")
    help_bead = next(
        item
        for item in fake_bd.beads().values()
        if str(item.get("external_ref") or "").startswith(f"pipe:{created['epic']}:help:")
    )
    assert {"kind:request", "role:programmer"} <= set(help_bead["labels"])
    assert fake_bd.dependencies(help_bead["id"]) == []
    threads = (
        (
            engine_settings.runs_dir()
            / "pipelines"
            / created["epic"]
            / "discussion"
            / "threads.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(threads) == 2
    assert all(json.loads(line)["delivery"] for line in threads)
    assert len(fake_bd.bead(created["epic"])["comments"]) == 2


def test_pipeline_ask_nonmember_recruits_and_person_requires_approval(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    protein_inbox = engine_settings.root / "agents" / "protein-function" / "inbox.jsonl"
    before = protein_inbox.read_text(encoding="utf-8") if protein_inbox.exists() else ""

    request = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="agent:protein-function",
        text="Help interpret this protein-function result",
        dry_run=False,
    )
    approval = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="person:gus-student",
        text="Could you review the benchmark?",
        dry_run=False,
    )

    assert not request["delivered"] and request["recruit_request"]
    recruit_bead = fake_bd.bead(request["recruit_request"])
    assert {"kind:request", "agent:coordinator", "needs:robert"} <= set(recruit_bead["labels"])
    assert "asks to bring agent:protein-function" in recruit_bead["description"]
    after = protein_inbox.read_text(encoding="utf-8") if protein_inbox.exists() else ""
    assert after == before
    assert not approval["delivered"] and approval["approval"]
    approval_bead = fake_bd.bead(approval["approval"])
    assert {"kind:outbound", "needs:robert", "person:gus-student"} <= set(approval_bead["labels"])


def test_recruit_adds_current_round_critique_and_deny_closes_request(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    request = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="agent:protein-function",
        text="We need protein expertise",
        dry_run=False,
    )
    accepted = recruit(
        engine_settings,
        ledger,
        created["epic"],
        member="agent:protein-function",
        role_name="senior",
        why="protein-function topic (source: agents/protein-function.yaml)",
        deny=False,
        dry_run=False,
    )

    assert accepted["added"] and accepted["critique"]
    assert fake_bd.bead(request["recruit_request"])["status"] == "closed"
    assert {"agent:protein-function", "planning-round:1"} <= _labels(fake_bd, accepted["critique"])
    team = yaml.safe_load(
        (engine_settings.runs_dir() / "pipelines" / created["epic"] / "team.yaml").read_text()
    )
    assert "agent:protein-function" in {row["member"] for row in team["team"]}

    second = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="role:editor",
        text="Should an editor join?",
        dry_run=False,
    )
    denied = recruit(
        engine_settings,
        ledger,
        created["epic"],
        member="role:editor",
        role_name=None,
        why="editing is outside this planning round",
        deny=True,
        dry_run=False,
    )
    assert denied["denied"] and fake_bd.bead(second["recruit_request"])["status"] == "closed"
    assert "role:editor" not in {
        row["member"]
        for row in yaml.safe_load(
            (engine_settings.runs_dir() / "pipelines" / created["epic"] / "team.yaml").read_text()
        )["team"]
    }


def test_recruit_person_and_collaborator_are_idempotent_and_nonblocking(
    engine_settings: Settings,
    fake_bd: FakeBd,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fixture_project(engine_settings)
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger, project="fixture-project")
    _record_team(
        engine_settings,
        ledger,
        fake_bd,
        created,
        tmp_path,
        _team_payload(
            {
                "member": "agent:ontology",
                "role": "senior",
                "why": "ontology topic (source: agents/ontology.yaml)",
            },
            {
                "member": "role:programmer",
                "why": "implementation (source: roles/programmer.yaml)",
            },
        ),
    )

    def recruit_json(member: str, role: str, why: str) -> dict:
        rc = main(
            [
                "--root",
                str(engine_settings.root),
                "pipeline",
                "recruit",
                created["epic"],
                "--member",
                member,
                "--role",
                role,
                "--why",
                why,
                "--apply",
                "--json",
            ]
        )
        assert rc == 0
        return json.loads(capsys.readouterr().out)

    person = recruit_json(
        "person:fin-fellow",
        "postdoc",
        "current postdoc roster entry (source: people.yaml)",
    )
    collaborator = recruit_json(
        "collaborator:cole-collaborator",
        "registered lead",
        "fixture project member (source: pa/kg/projects/fixture-project.md)",
    )
    repeat = recruit_json(
        "collaborator:cole-collaborator",
        "registered lead",
        "fixture project member (source: pa/kg/projects/fixture-project.md)",
    )

    assert person["added"] and person["critique"]
    assert collaborator["added"] and collaborator["critique"]
    assert not repeat["added"] and repeat["critique"] == collaborator["critique"]
    team = yaml.safe_load(
        (engine_settings.runs_dir() / "pipelines" / created["epic"] / "team.yaml").read_text()
    )
    by_member = {row["member"]: row for row in team["team"]}
    assert by_member["person:fin-fellow"]["role"] == "postdoc"
    assert by_member["collaborator:cole-collaborator"]["role"] == "registered lead"
    collaborator_bead = fake_bd.bead(collaborator["critique"])
    assert "collaborator:cole-collaborator" in collaborator_bead["labels"]
    assert not any(label.startswith("role:") for label in collaborator_bead["labels"])
    assert fake_bd.dependency_records(collaborator["critique"]) == [
        {"id": created["stages"]["plan1:draft"], "dependency_type": "related"}
    ]
    assert collaborator["critique"] not in fake_bd.dependencies(created["stages"]["plan1:final"])

    approval = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="collaborator:cole-collaborator",
        text="Could you review the challenge constraints?",
        dry_run=False,
    )
    approval_bead = fake_bd.bead(approval["approval"])
    assert not approval["delivered"]
    assert {"kind:outbound", "needs:robert", "collaborator:cole-collaborator"} <= set(
        approval_bead["labels"]
    )

    ledger.close(created["stages"]["collect"], "fixture collected")
    ledger.close(created["stages"]["team"], "fixture team")
    ledger.close(created["stages"]["plan1:draft"], "fixture draft")
    for critique in fake_bd.beads().values():
        if "pipeline-stage:critique" in critique["labels"] and not any(
            label.startswith(("person:", "collaborator:")) for label in critique["labels"]
        ):
            ledger.close(critique["id"], "fixture critique")
    status = pipeline_status(engine_settings, ledger, created["epic"], today=date(2026, 9, 3))
    team_status = {row["member"]: row for row in status["team"]}
    assert team_status["person:fin-fellow"]["kind"] == "person"
    assert not team_status["person:fin-fellow"]["blocking"]
    assert team_status["collaborator:cole-collaborator"] == {
        **by_member["collaborator:cole-collaborator"],
        "kind": "collaborator",
        "blocking": False,
    }
    assert status["stage"] == "plan1:final"
    assert "cole-collaborator" not in status["next"]
    assert "fin-fellow" not in status["next"]

    prompt = stage_prompt(
        engine_settings,
        fake_bd.bead(created["epic"]),
        fake_bd.bead(created["stages"]["team"]),
        beads=ledger,
    )
    assert "collaborator:cole-collaborator" in prompt
    assert (
        "Collaborators are outside the group: never contact them; anything for them becomes an "
        "approval item for Robert."
    ) in prompt


def test_recruitment_autonomy_defaults_to_robert_and_can_route_coordinator(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    default = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="agent:protein-function",
        text="Need domain expertise",
        dry_run=False,
    )
    assert "needs:robert" in _labels(fake_bd, default["recruit_request"])

    engine_settings.pipeline.autonomy.recruit = "coordinator"
    coordinator = ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="role:editor",
        text="Need review help",
        dry_run=False,
    )
    assert "needs:robert" not in _labels(fake_bd, coordinator["recruit_request"])
    assert coordinator["recruit_request"] in {item["id"] for item in ledger.ready()}


def test_progress_review_files_stale_findings_and_status_manager_shape(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    ledger.close(created["stages"]["collect"], "fixture collected")
    ledger.close(created["stages"]["team"], "fixture team")
    ledger.close(created["stages"]["plan1:draft"], "fixture draft")
    critiques = [
        item for item in fake_bd.beads().values() if "pipeline-stage:critique" in item["labels"]
    ]
    for item in critiques:
        if not any(label.startswith("person:") for label in item["labels"]):
            ledger.close(item["id"], "fixture critique")
    manager = review_pipeline_progress(
        engine_settings,
        ledger,
        created["epic"],
        now=datetime(2026, 9, 5, 12, tzinfo=UTC),
        dry_run=False,
    )
    again = review_pipeline_progress(
        engine_settings,
        ledger,
        created["epic"],
        now=datetime(2026, 9, 5, 13, tzinfo=UTC),
        dry_run=False,
    )
    status = pipeline_status(engine_settings, ledger, created["epic"], today=date(2026, 9, 5))

    assert manager["stale"] and again["stale"]
    stale_findings = [
        item
        for item in fake_bd.beads().values()
        if f"pipe:{created['epic']}:stale:" in str(item.get("external_ref") or "")
    ]
    assert len(stale_findings) == 2
    assert any("person-critique-gus-student" in row["stage"] for row in manager["stale"])
    assert status["team"][0]["member"] == "agent:ontology"
    assert set(status["discussion"][0]) == {
        "round",
        "draft",
        "critiques",
        "final",
        "decisions",
    }
    assert status["manager"]["lead"] == "agent:coordinator"
    assert status["manager"]["last_review"].startswith("2026-09-05T13:00:00")
    assert len(status["manager"]["stale"]) == 2


def test_coordinator_workday_reviews_pipelines_and_updates_briefing(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    coordinator_path = engine_settings.root / "agents" / "coordinator.yaml"
    coordinator = yaml.safe_load(coordinator_path.read_text(encoding="utf-8"))
    coordinator["workday"]["max_runs"] = 0
    coordinator_path.write_text(yaml.safe_dump(coordinator, sort_keys=False), encoding="utf-8")

    result = AgentWorkdayPatrol("coordinator", now=datetime(2026, 9, 3, 7, tzinfo=UTC)).run(
        engine_settings, dry_run=False, beads=ledger
    )

    assert result.pipeline_reviews[0]["epic"] == created["epic"]
    briefing = engine_settings.root / str(result.monday_briefing)
    assert f"Pipeline {created['epic']}: collect" in briefing.read_text(encoding="utf-8")
    status = pipeline_status(engine_settings, ledger, created["epic"], today=date(2026, 9, 3))
    assert status["manager"]["last_review"] == "2026-09-03T07:00:00+00:00"


def test_advance_creates_experiments_dependencies_and_gate(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _close_through_replan(engine_settings, ledger, created)
    _plan(engine_settings.runs_dir() / "pipelines" / created["epic"] / "plan-v2.yaml")

    result = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )

    assert len(result["created"]) == 3
    experiments = [
        bead
        for bead in fake_bd.beads().values()
        if "pipeline-stage:experiments" in bead["labels"]
        and not any(label.startswith("revises:") for label in bead["labels"])
    ]
    assert len(experiments) == 2
    by_xid = {bead["external_ref"].rsplit(":", 1)[-1]: bead for bead in experiments}
    assert fake_bd.dependencies(by_xid["evaluate"]["id"]) == [by_xid["prepare"]["id"]]
    gate = next(bead for bead in fake_bd.beads().values() if "gate:1" in bead["labels"])
    assert set(fake_bd.dependencies(gate["id"])) == {bead["id"] for bead in experiments}
    roles, _ = load_all(engine_settings.root)
    assert role_for(by_xid["prepare"], roles) == "programmer"
    assert role_for(gate, roles) == "group-leader"


def test_invalid_plan_files_one_finding_and_flags_epic(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _close_through_replan(engine_settings, ledger, created)
    _plan(
        engine_settings.runs_dir() / "pipelines" / created["epic"] / "plan-v2.yaml",
        valid=False,
    )

    first = advance(engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False)
    second = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )

    assert first["flagged"] and second["created"] == []
    assert "needs:robert" in _labels(fake_bd, created["epic"])
    findings = [b for b in fake_bd.beads().values() if b["external_ref"].endswith(":plan-invalid")]
    assert len(findings) == 1 and "needs:robert" in findings[0]["labels"]


def test_pipeline_patrol_advances_open_epics_and_emits_attention(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _close_through_replan(engine_settings, ledger, created)
    _plan(
        engine_settings.runs_dir() / "pipelines" / created["epic"] / "plan-v2.yaml",
        valid=False,
    )

    report = PipelinePatrol().run(engine_settings, date(2026, 9, 3), False, beads=ledger)

    assert report.data["pipelines"][created["epic"]]["flagged"] == [created["epic"]]
    assert report.events[0]["event"] == "attention"
    assert report.events[0]["data"]["epic"] == created["epic"]


def _prepared_pipeline(engine_settings: Settings, fake_bd: FakeBd) -> tuple[Beads, dict, str]:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _close_through_replan(engine_settings, ledger, created)
    _plan(engine_settings.runs_dir() / "pipelines" / created["epic"] / "plan-v2.yaml")
    advance(engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False)
    for bead in fake_bd.beads().values():
        if "pipeline-stage:experiments" in bead["labels"]:
            ledger.close(bead["id"], "fixture implementation approved")
    gate = next(b["id"] for b in fake_bd.beads().values() if "gate:1" in b["labels"])
    return ledger, created, gate


def test_gate_approve_marks_header_done_and_closes_epic(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger, created, gate = _prepared_pipeline(engine_settings, fake_bd)
    ledger.add_labels(gate, [review_gate.LABEL_APPROVED])
    ledger.close(gate, "approve")

    result = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )

    assert result["closed"] == [created["epic"]]
    epic = fake_bd.bead(created["epic"])
    assert epic["status"] == "closed"
    assert GoalHeader.parse(epic["description"]).status == "done"


def test_gate_revise_uses_review_gate_then_creates_gate_two(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger, created, gate = _prepared_pipeline(engine_settings, fake_bd)
    verdict = review_gate.apply_verdict(
        ledger,
        gate,
        fake_bd.bead(gate),
        verdict="revise",
        summary="repeat both fixture experiments",
        by="group-leader",
        run_id="fixture-gate-1",
    )
    followups = verdict["follow_ups"]
    assert followups
    assert all(
        any(label.startswith("revises:") for label in fake_bd.bead(item)["labels"])
        for item in followups
    )
    waiting = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )
    assert not any("gate:2" in fake_bd.bead(item)["labels"] for item in waiting["created"])
    for item in followups:
        ledger.close(item, "fixture revision approved")

    advanced = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )
    assert len(advanced["created"]) == 1
    assert "gate:2" in _labels(fake_bd, advanced["created"][0])


def test_max_iterations_and_kill_criterion_flag_pipeline(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    engine_settings.pipeline.max_iterations = 1
    ledger, created, gate = _prepared_pipeline(engine_settings, fake_bd)
    ledger.add_labels(gate, [review_gate.LABEL_REVISE])
    ledger.close(gate, "revise")
    experiment = next(
        bead for bead in fake_bd.beads().values() if "pipeline-stage:experiments" in bead["labels"]
    )
    fake_bd.add(
        "revision-one",
        title="Revision",
        labels=[
            f"goal:{created['epic']}",
            "pipeline-stage:experiments",
            "after-gate:1",
            f"revises:{experiment['id']}",
            "stage:implement",
            "role:programmer",
        ],
        status="closed",
    )
    killed = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )
    assert killed["flagged"] == [created["epic"]]
    assert {"needs:robert", "kill:iterations"} <= _labels(fake_bd, created["epic"])

    other_settings = load_settings(engine_settings.root)
    other_settings.pipeline.max_iterations = 3
    ledger2 = _ledger(other_settings.root)
    second = new_pipeline(
        other_settings,
        ledger2,
        title="Kill fixture",
        target=date(2026, 12, 31),
        success=["gate passes"],
        question="Collect the mail I sent about kill fixtures and list the code",
        person="robert",
        provenance=[Provenance(source="fixture", locator="kill request")],
    )
    _close_through_replan(other_settings, ledger2, second)
    _plan(other_settings.runs_dir() / "pipelines" / second["epic"] / "plan-v2.yaml")
    advance(other_settings, ledger2, second["epic"], today=date(2026, 9, 3), dry_run=False)
    kill_exp = next(
        b
        for b in fake_bd.beads().values()
        if f"goal:{second['epic']}" in b["labels"] and "pipeline-stage:experiments" in b["labels"]
    )
    ledger2.comment(kill_exp["id"], "run output\nKILL: fixture score below 0.2")
    criterion = advance(
        other_settings, ledger2, second["epic"], today=date(2026, 9, 3), dry_run=False
    )
    assert second["epic"] in criterion["flagged"]
    assert any(str(b.get("external_ref") or "").endswith(":kill") for b in fake_bd.beads().values())


def test_record_plan_and_survey_artifacts(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source_plan = _plan(run_dir / "plan.yaml")
    plan_result = RunResult(
        summary="planned", artifacts=[{"kind": "plan", "path": str(source_plan)}]
    )

    draft = record_plan_artifacts(
        engine_settings,
        fake_bd.bead(created["stages"]["plan1:draft"]),
        run_dir,
        plan_result,
    )
    decisions = run_dir / "decisions.md"
    decisions.write_text("- Accepted: keep the fixture threshold because fixture opinion\n")
    final_result = RunResult(
        summary="final plan",
        artifacts=[
            {"kind": "plan", "path": str(source_plan)},
            {"kind": "decision-log", "path": str(decisions)},
        ],
    )
    final = record_plan_artifacts(
        engine_settings,
        fake_bd.bead(created["stages"]["plan1:final"]),
        run_dir,
        final_result,
    )
    assert draft["close"] and final["close"]
    pipeline_dir = engine_settings.runs_dir() / "pipelines" / created["epic"]
    assert (pipeline_dir / "plan-v1-draft.yaml").is_file()
    assert (pipeline_dir / "plan-v1.yaml").is_file()
    assert (pipeline_dir / "discussion" / "plan-v1" / "decisions.md").is_file()

    search = run_dir / "search.jsonl"
    from cube.pipeline import write_rehearsal_search_log

    write_rehearsal_search_log(search, today=date(2026, 9, 3))
    reading = run_dir / "reading.bib"
    reading.write_text(
        "@article{fixture, author={A, Researcher}, title={Fixture study}, "
        "journal={Fixtures}, year={2025}, doi={10.1234/fixture}}\n",
        encoding="utf-8",
    )
    survey = RunResult(
        summary="surveyed",
        artifacts=[
            {"kind": "search-log", "path": str(search)},
            {"kind": "reading-list", "path": str(reading)},
        ],
    )
    clean = record_plan_artifacts(
        engine_settings, fake_bd.bead(created["stages"]["survey"]), run_dir, survey
    )
    assert clean["close"] and clean["errors"] == []

    reading_json = run_dir / "reading.json"
    reading_json.write_text(
        json.dumps(
            {
                "identifiers": {
                    "dois": ["10.1234/fixture"],
                    "arxiv": ["2601.00001"],
                    "pmids": ["12345678"],
                }
            }
        ),
        encoding="utf-8",
    )
    json_survey = RunResult(
        summary="surveyed",
        artifacts=[
            {"kind": "search-log", "path": str(search)},
            {"kind": "reading-list", "path": str(reading_json)},
        ],
    )
    clean_json = record_plan_artifacts(
        engine_settings,
        fake_bd.bead(created["stages"]["survey"]),
        run_dir,
        json_survey,
    )
    assert clean_json["close"] and clean_json["errors"] == []

    reading.write_text("@article{broken, title={Missing fields}}\n", encoding="utf-8")
    broken = record_plan_artifacts(
        engine_settings, fake_bd.bead(created["stages"]["survey"]), run_dir, survey
    )
    assert not broken["close"]
    assert any("bib.missing-field" in error for error in broken["errors"])


def test_result_hook_closes_valid_plan_and_flags_bad_survey(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    plan = _plan(tmp_path / "hook-plan.yaml")
    plan_result = RunResult(
        summary="pipeline plan ready",
        artifacts=[{"kind": "plan", "path": str(plan)}],
    )
    planned = execute(
        engine_settings,
        "group-leader",
        bead=created["stages"]["plan1:draft"],
        runner_name="stub",
        runner=StubRunner(result=plan_result),
        beads=ledger,
    )
    assert planned.ok and planned.applied["pipeline"]["close"]  # type: ignore[index]
    assert fake_bd.bead(created["stages"]["plan1:draft"])["status"] == "closed"
    assert "needs:robert" not in _labels(fake_bd, created["stages"]["plan1:draft"])

    search = tmp_path / "hook-search.jsonl"
    from cube.pipeline import write_rehearsal_search_log

    write_rehearsal_search_log(search, today=date(2026, 9, 3))
    reading = tmp_path / "hook-reading.bib"
    reading.write_text("@article{broken, title={Missing fields}}\n", encoding="utf-8")
    survey_result = RunResult(
        summary="pipeline survey needs repair",
        artifacts=[
            {"kind": "search-log", "path": str(search)},
            {"kind": "reading-list", "path": str(reading)},
        ],
    )
    surveyed = execute(
        engine_settings,
        "senior",
        bead=created["stages"]["survey"],
        runner_name="stub",
        runner=StubRunner(result=survey_result),
        beads=ledger,
    )
    assert surveyed.ok and surveyed.applied["pipeline"]["errors"]  # type: ignore[index]
    survey_bead = fake_bd.bead(created["stages"]["survey"])
    assert survey_bead["status"] != "closed"  # parked for Robert, not closed
    assert "needs:robert" in survey_bead["labels"]
    assert any("bib.missing-field" in item["text"] for item in survey_bead["comments"])
    finding = next(
        item
        for item in fake_bd.beads().values()
        if str(item.get("external_ref") or "").endswith(":survey-invalid")
    )
    assert {"kind:finding", "needs:robert"} <= set(finding["labels"])


def test_gate_reject_flags_epic_for_robert(engine_settings: Settings, fake_bd: FakeBd) -> None:
    ledger, created, gate = _prepared_pipeline(engine_settings, fake_bd)
    ledger.add_labels(gate, [review_gate.LABEL_REJECTED])

    result = advance(
        engine_settings, ledger, created["epic"], today=date(2026, 9, 3), dry_run=False
    )

    assert result["flagged"] == [created["epic"]]
    assert "needs:robert" in _labels(fake_bd, created["epic"])


def test_pipeline_cli_new_status_and_advance_json(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "--root",
            str(engine_repo),
            "pipeline",
            "new",
            "--title",
            "CLI fixture",
            "--target",
            "2026-12-31",
            "--success",
            "gate passes",
            "--from-mail",
            "fixture project",
            "--provenance",
            "fixture::CLI test",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    created = json.loads(capsys.readouterr().out)
    assert set(created) >= {"epic", "stages", "dry_run"}
    assert created["dry_run"] is False

    rc = main(["--root", str(engine_repo), "pipeline", "status", created["epic"], "--json"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["epic"] == created["epic"] and status["stage"] == "collect"

    rc = main(["--root", str(engine_repo), "pipeline", "status", "--json"])
    assert rc == 0
    all_status = json.loads(capsys.readouterr().out)
    assert [item["epic"] for item in all_status["pipelines"]] == [created["epic"]]

    rc = main(
        [
            "--root",
            str(engine_repo),
            "pipeline",
            "advance",
            created["epic"],
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    advanced = json.loads(capsys.readouterr().out)
    assert set(advanced) >= {"created", "closed", "flagged", "stage", "iteration"}

    rc = main(
        [
            "--root",
            str(engine_repo),
            "pipeline",
            "new",
            "--title",
            "Invalid CLI fixture",
            "--target",
            "2026-12-31",
            "--from-mail",
            "fixture",
            "--json",
        ]
    )
    assert rc == 2
    assert "at least one --success" in capsys.readouterr().err


def test_pipeline_cli_ask_and_recruit_json(
    engine_settings: Settings,
    fake_bd: FakeBd,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)

    rc = main(
        [
            "--root",
            str(engine_settings.root),
            "pipeline",
            "ask",
            created["epic"],
            "--from",
            "agent:ontology",
            "--to",
            "agent:protein-function",
            "Need protein expertise",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    requested = json.loads(capsys.readouterr().out)
    assert not requested["delivered"] and requested["recruit_request"]

    rc = main(
        [
            "--root",
            str(engine_settings.root),
            "pipeline",
            "recruit",
            created["epic"],
            "--member",
            "agent:protein-function",
            "--role",
            "senior",
            "--why",
            "protein topic (source: agents/protein-function.yaml)",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    recruited = json.loads(capsys.readouterr().out)
    assert recruited["added"] and recruited["critique"]
