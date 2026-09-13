"""The goals patrol tells Robert once when a goal is complete."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from cube.config import Settings
from cube.goals import GoalHeader
from cube.model import Privacy, Provenance
from cube.patrols import base
from cube.patrols.goals import GoalsPatrol, completed_goals
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
TODAY = date(2026, 9, 7)


def _goal(goal_id: str, status: str = "active") -> str:
    return GoalHeader(
        xid=f"goal:{goal_id}",
        provenance=[Provenance(source="tests/test_goals_patrol.py", locator=goal_id)],
        deadline=TODAY,
        privacy=Privacy.internal,
        target=TODAY,
        success=["The report exists"],
        status=status,  # type: ignore[arg-type]
    ).render()


def test_completed_goals_need_a_header_and_a_recent_close() -> None:
    recent = (NOW - timedelta(hours=2)).isoformat()
    old = (NOW - timedelta(days=3)).isoformat()
    issues = [
        {
            "id": "g1",
            "title": "done",
            "labels": ["kind:goal"],
            "status": "closed",
            "closed_at": recent,
            "description": _goal("g1"),
        },
        {
            "id": "g1.1",
            "title": "child",
            "labels": ["kind:goal"],
            "status": "closed",
            "closed_at": recent,
            "description": "no header",
            "parent": "g1",
        },
        {
            "id": "g2",
            "title": "old",
            "labels": ["kind:goal"],
            "status": "closed",
            "closed_at": old,
            "description": _goal("g2"),
        },
        {
            "id": "g3",
            "title": "open",
            "labels": ["kind:goal"],
            "status": "open",
            "updated_at": recent,
            "description": _goal("g3"),
        },
        {
            "id": "d1",
            "title": "duplicate",
            "labels": ["kind:goal"],
            "status": "closed",
            "closed_at": recent,
            "close_reason": "duplicate of g1; Robert 2026-09-07",
            "description": _goal("d1"),
        },
        {
            "id": "d2",
            "title": "dropped",
            "labels": ["kind:goal"],
            "status": "closed",
            "closed_at": recent,
            "description": _goal("d2", status="dropped"),
        },
        {
            "id": "s1",
            "title": "stage",
            "labels": ["kind:goal", "pipeline-stage:draft"],
            "status": "closed",
            "closed_at": recent,
            "description": _goal("s1"),
        },
    ]
    assert [g["id"] for g in completed_goals(issues, now=NOW)] == ["g1"]


def test_goals_patrol_emits_one_goal_event_per_goal(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    fake_bd.add(
        "cube-g1",
        title="Student reports delivered",
        labels=["kind:goal"],
        status="closed",
        closed_at=(NOW - timedelta(hours=1)).isoformat(),
        close_reason="all eleven reports in place",
        description=_goal("cube-g1"),
    )
    events_path = engine_settings.root / "state" / "events.jsonl"
    base.run_patrol(engine_settings, GoalsPatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    base.run_patrol(engine_settings, GoalsPatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    events = [json.loads(x) for x in events_path.read_text().splitlines()]
    goal_events = [e for e in events if e["event"] == "goal"]
    assert len(goal_events) == 1
    assert goal_events[0]["title"] == "Goal complete: Student reports delivered"
    assert goal_events[0]["severity"] == "info"
    assert goal_events[0]["data"]["bead"] == "cube-g1"
    assert goal_events[0]["data"]["xid"] == "goal:complete:cube-g1"
    assert "all eleven reports" in goal_events[0]["data"]["body"]
