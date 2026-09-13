from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cube.cli import main
from cube.engine.marshal import role_for
from cube.goals import GoalHeader
from cube.model import BeadHeader, Privacy, Provenance
from cube.roles import load_all
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())


def _goal_description(
    goal_id: str,
    *,
    target: str = "2026-09-11",
    people: list[str] | None = None,
) -> str:
    return GoalHeader(
        xid=f"goal:{goal_id}",
        provenance=[Provenance(source="tests/test_goals.py", locator=goal_id)],
        deadline=date.fromisoformat(target),
        privacy=Privacy.internal,
        target=date.fromisoformat(target),
        success=["At least one result file exists"],
        owner="robert",
        people=people or [],
        status="active",
    ).render()


def _child_description(child_id: str, deadline: str | None = None) -> str:
    return BeadHeader(
        xid=f"child:{child_id}",
        provenance=[Provenance(source="tests/test_goals.py", locator=child_id)],
        deadline=date.fromisoformat(deadline) if deadline else None,
        privacy=Privacy.internal,
    ).render()


def _run_json(repo: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    rc = main(["--root", str(repo), *argv, "--json"])
    return rc, json.loads(capsys.readouterr().out)


def _plan(path: Path, goal: str) -> Path:
    data = {
        "goal": "finish the fixture goal",
        "pattern": "parallel",
        "provenance": [f"bead:{goal}"],
        "review_by": "group-leader",
        "beads": [
            {
                "id": "student-analysis",
                "title": "Analyse the first result",
                "kind": "research",
                "stage": "design",
                "owner": "person:alex-example",
                "why_you": "This analysis advances the student's thesis and trains interpretation.",
                "deadline": "2026-09-08",
                "privacy": "internal",
                "objective": "Interpret the first result against the goal criteria.",
                "output": "A result note at runs/result.md",
                "sources": [f"bead:{goal}"],
                "out_of_scope": "Automation belongs to the agent child.",
                "provenance": [f"bead:{goal}"],
                "acceptance_criteria": [
                    {"check": "runs/result.md exists and contains a Results section"}
                ],
                "depends_on": [],
            },
            {
                "id": "agent-table",
                "title": "Build the result table",
                "kind": "implement",
                "stage": "design",
                "owner": "role:programmer",
                "why": "This repetitive table build is faster and safer for an agent.",
                "deadline": "2026-09-07",
                "privacy": "internal",
                "objective": "Build the input table for the human analysis.",
                "output": "A table at runs/result.tsv",
                "sources": [f"bead:{goal}"],
                "out_of_scope": "Scientific interpretation belongs to student-analysis.",
                "provenance": [f"bead:{goal}"],
                "acceptance_criteria": [
                    {"check": "runs/result.tsv exists and contains at least 2 rows"}
                ],
                "depends_on": [],
            },
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _stub_result(monkeypatch: pytest.MonkeyPatch, plan: Path) -> None:
    monkeypatch.setenv(
        "CUBE_STUB_RESULT",
        json.dumps(
            {
                "summary": "Plan written from tests/test_goals.py fixture.",
                "artifacts": [{"kind": "plan", "path": str(plan)}],
            }
        ),
    )


def test_goal_new_refuses_missing_target_or_success(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(engine_repo), "goal", "new", "--title", "No target"]) == 2
    assert "--target" in capsys.readouterr().err
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "goal",
                "new",
                "--title",
                "No criteria",
                "--target",
                "2026-10-01",
            ]
        )
        == 2
    )
    assert "--success" in capsys.readouterr().err
    assert fake_bd.beads() == {}


def test_decompose_review_then_approve_creates_mixed_children(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_bd.add(
        "goal-1",
        title="Fixture goal",
        issue_type="epic",
        labels=["kind:goal"],
        description=_goal_description("goal-1", people=["alex-example"]),
        created_at="2026-09-01T09:00:00+00:00",
    )
    plan = _plan(engine_repo / "plan.yaml", "goal-1")
    _stub_result(monkeypatch, plan)
    rc, proposed = _run_json(engine_repo, capsys, "goal", "decompose", "goal-1", "--runner", "stub")
    assert rc == 0 and not proposed["applied"] and proposed["children"] == []
    assert proposed["review"]["status"] == "pending"
    assert set(fake_bd.beads()) == {"goal-1"}

    rc, approved = _run_json(engine_repo, capsys, "approve", proposed["review"]["id"])
    assert rc == 0 and approved["result"] == "applied"
    assert {child["owner"] for child in approved["children"]} == {
        "person:alex-example",
        "role:programmer",
    }
    create_calls = [call for call in fake_bd.calls() if call[0] == "create"]
    assert len(create_calls) == 2
    assert all(call[call.index("--parent") + 1] == "goal-1" for call in create_calls)
    labels = [call[call.index("--labels") + 1].split(",") for call in create_calls]
    assert all("goal:goal-1" in item for item in labels)
    human = next(item for item in labels if "person:alex-example" in item)
    assert not any(label.startswith("role:") for label in human)


def test_decompose_apply_uses_stub_offline(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bd.add(
        "goal-stub",
        title="Offline goal",
        labels=["kind:goal"],
        description=_goal_description("goal-stub"),
    )
    rc, output = _run_json(
        engine_repo,
        capsys,
        "goal",
        "decompose",
        "goal-stub",
        "--runner",
        "stub",
        "--apply",
    )
    assert rc == 0 and output["applied"] and len(output["children"]) == 1
    assert output["review"]["status"] == "approved"


def test_goals_compute_track_state_blockers_and_next_owners(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    for goal_id in ("goal-true", "goal-false", "goal-empty"):
        fake_bd.add(
            goal_id,
            title=goal_id,
            labels=["kind:goal"],
            description=_goal_description(goal_id, people=["alex-example"]),
            created_at="2026-09-01T00:00:00+00:00",
            updated_at="2026-09-02T00:00:00+00:00",
        )
    fake_bd.add(
        "true-closed",
        title="closed",
        labels=["goal:goal-true", "role:programmer"],
        parent="goal-true",
        status="closed",
        description=_child_description("true-closed"),
    )
    fake_bd.add(
        "true-agent",
        title="agent",
        labels=["goal:goal-true", "role:programmer"],
        parent="goal-true",
        priority=1,
        description=_child_description("true-agent", "2026-09-10"),
    )
    fake_bd.add(
        "true-person",
        title="human analysis",
        labels=["goal:goal-true", "person:alex-example"],
        parent="goal-true",
        description=_child_description("true-person", "2026-09-09"),
    )
    fake_bd.add(
        "true-overdue",
        title="overdue",
        labels=["goal:goal-true", "role:editor"],
        parent="goal-true",
        blocked=True,
        description=_child_description("true-overdue", "2026-09-04"),
    )
    for suffix in ("a", "b"):
        fake_bd.add(
            f"false-{suffix}",
            title=f"false {suffix}",
            labels=["goal:goal-false", "role:programmer"],
            parent="goal-false",
            description=_child_description(f"false-{suffix}"),
        )
    rc, output = _run_json(engine_repo, capsys, "goals", "--today", "2026-09-06")
    assert rc == 0
    rows = {row["id"]: row for row in output["goals"]}
    assert rows["goal-true"]["progress"] == {
        "total": 4,
        "closed": 1,
        "in_progress": 0,
        "blocked": 1,
        "pct": 25,
    }
    assert rows["goal-true"]["on_track"] is False
    assert rows["goal-true"]["status"] == "at-risk"
    assert rows["goal-true"]["blockers"][0]["bead"] == "true-overdue"
    assert rows["goal-true"]["next"]["people"][0]["person"] == "alex-example"
    assert next(
        item for item in rows["goal-true"]["next"]["agents"] if item["bead"] == "true-agent"
    )["ready"]
    assert rows["goal-false"]["on_track"] is False
    assert rows["goal-empty"]["on_track"] is None

    fake_bd.add(
        "true-closed-2",
        title="closed 2",
        labels=["goal:goal-true", "role:programmer"],
        parent="goal-true",
        status="closed",
        description=_child_description("true-closed-2"),
    )
    rc, output = _run_json(engine_repo, capsys, "goals", "--today", "2026-09-06")
    row = next(item for item in output["goals"] if item["id"] == "goal-true")
    assert rc == 0 and row["on_track"] is True


def test_people_gains_owed_work_and_agenda(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bd.add(
        "goal-people",
        title="People goal",
        labels=["kind:goal"],
        description=_goal_description("goal-people", people=["alex-example"]),
    )
    fake_bd.add(
        "human-work",
        title="Interpret the table",
        labels=["goal:goal-people", "person:alex-example"],
        parent="goal-people",
        description=_child_description("human-work", "2026-09-09"),
    )
    rc, output = _run_json(engine_repo, capsys, "people", "--today", "2026-09-06")
    person = next(row for row in output["people"] if row["slug"] == "alex-example")
    assert rc == 0 and person["goals"] == ["goal-people"]
    assert person["owed"] == [
        {"bead": "human-work", "title": "Interpret the table", "due": "2026-09-09"}
    ]
    assert any("Interpret the table" in item for item in person["next_meeting_agenda"])


def test_spin_dry_run_selects_priority_and_runs_nothing(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bd.add(
        "goal-spin",
        title="Spin goal",
        labels=["kind:goal"],
        description=_goal_description("goal-spin"),
    )
    for child_id, priority, deadline in (
        ("later", 2, "2026-09-07"),
        ("first", 0, "2026-09-10"),
    ):
        fake_bd.add(
            child_id,
            title=child_id,
            labels=["goal:goal-spin", "role:programmer"],
            parent="goal-spin",
            priority=priority,
            description=_child_description(child_id, deadline),
        )
    before = fake_bd.beads()
    rc, output = _run_json(engine_repo, capsys, "goal", "spin", "goal-spin", "--runner", "stub")
    assert rc == 0 and output["selected"]["bead"] == "first"
    assert output["run"]["state"] == "dry-run" and output["assignment_commands"] == []
    assert fake_bd.beads() == before
    assert not any(call[0] in {"update", "comment", "close", "label"} for call in fake_bd.calls())


def test_marshal_requires_explicit_agent_role_for_goal_children(engine_repo: Path) -> None:
    roles, _ = load_all(engine_repo)
    labels = ["goal:goal-1", "person:alex-example", "stage:design"]
    assert role_for({"labels": labels}, roles) is None
    assert (
        role_for({"labels": ["goal:goal-1", "role:programmer", "stage:design"]}, roles)
        == "programmer"
    )
    assert role_for({"labels": ["kind:goal", "stage:design"]}, roles) is None
