"""Stage beads inherit the epic labels from bd; they must never be listed as epics."""

from __future__ import annotations

from cube.pipeline import is_pipeline_epic

EPIC_DESC = (
    "---\nxid: pipeline:x:2026-12-15\nprovenance:\n- source: cli\n  locator: test\n"
    "deadline: '2026-12-15'\nprivacy: internal\ntarget: '2026-12-15'\nsuccess:\n- done\n"
    "owner: robert\npeople: []\nstatus: active\n---\n"
)


def test_epic_is_recognised_and_inherited_children_are_not() -> None:
    epic = {"id": "cube-1", "labels": ["kind:goal", "pipeline:research"], "description": EPIC_DESC}
    child = {
        "id": "cube-1.5",
        "labels": ["kind:goal", "pipeline:research", "kind:request", "pipeline-stage:collect"],
        "description": "---\nxid: pipe:cube-1:collect\nprovenance: []\n---\nQuestion: x",
    }
    stray = {
        "id": "cube-2",
        "labels": ["kind:goal", "pipeline:research"],
        "description": "no header",
    }
    assert is_pipeline_epic(epic)
    assert not is_pipeline_epic(child)
    assert not is_pipeline_epic(stray)


def test_marshal_dispatches_stage_beads_that_inherit_kind_goal() -> None:
    from pathlib import Path

    from cube.engine.marshal import role_for
    from cube.roles.loader import load_all

    roles, _errors = load_all(Path(__file__).resolve().parents[1])
    stage = {
        "id": "cube-1.2",
        "labels": [
            "kind:goal",
            "pipeline:research",
            "kind:design",
            "stage:design",
            "role:group-leader",
            "pipeline-stage:team",
            "goal:cube-1",
        ],
    }
    epic = {"id": "cube-1", "labels": ["kind:goal", "pipeline:research"]}
    assert role_for(stage, roles) == "group-leader"
    assert role_for(epic, roles) is None
