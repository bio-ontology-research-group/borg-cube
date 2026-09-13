"""Student research review routing stays local and preserves twin ownership."""

from unittest.mock import MagicMock

import pytest

from cube.beads import Beads
from cube.engine.review_gate import apply_verdict, create_review_bead
from cube.model import Privacy
from cube.roles import load_role
from tests.helpers_engine import REPO_ROOT


def _review() -> dict:
    return {
        "labels": [
            "kind:review",
            "reviews:original",
            "role:student-reviewer",
            "producer:student-researcher",
            "agent:student-supervisor",
            "producer-agent:twin-example",
            "person:example",
            "twin:example",
            "privacy:local-only",
            "tier:local",
        ]
    }


def test_student_review_local_with_supervisor_and_identity():
    beads = MagicMock(spec=Beads)
    beads.create.return_value = "review"
    role = load_role(REPO_ROOT, "programmer").model_copy(
        update={"name": "student-researcher", "review_required_by": "student-reviewer"}
    )
    create_review_bead(
        beads,
        "original",
        {
            "title": "Research draft",
            "labels": [
                "agent:twin-example",
                "person:example",
                "twin:example",
                "twin:milestone",
            ],
        },
        role,
        summary="Draft ready",
        run_id="run-1",
    )
    arguments = beads.create.call_args.kwargs
    assert arguments["header"].privacy == Privacy.local_only
    assert set(_review()["labels"]) <= set(arguments["labels"])
    assert "twin:milestone" not in arguments["labels"]


def test_student_revision_returns_to_twin_not_supervisor():
    beads = MagicMock(spec=Beads)
    beads.create.return_value = "revision"
    review = _review()
    review["labels"].append("twin:milestone")  # legacy reviews must not propagate this marker
    out = apply_verdict(
        beads,
        "review",
        review,
        verdict="revise",
        summary="Check baseline",
        by="student-reviewer",
        run_id="run-2",
    )
    arguments = beads.create.call_args.kwargs
    assert arguments["header"].privacy == Privacy.local_only
    assert {
        "person:example",
        "twin:example",
        "agent:twin-example",
        "privacy:local-only",
        "tier:local",
        "role:student-researcher",
    } <= set(arguments["labels"])
    assert "agent:student-supervisor" not in arguments["labels"]
    assert "twin:milestone" not in arguments["labels"]
    assert out["follow_up"] == "revision"
    assert out["closed"] == ["original", "review"]
    beads.add_labels.assert_any_call("original", ["superseded-by:revision"])
    beads.close.assert_any_call("original", "revision required; superseded by revision (run-2)")
    assert all("review:approved" not in call.args[1] for call in beads.add_labels.call_args_list)


def test_student_rejection_is_scientific_stop_not_approval():
    beads = MagicMock(spec=Beads)
    out = apply_verdict(
        beads,
        "review",
        _review(),
        verdict="reject",
        summary="Unsupported hypothesis",
        by="student-reviewer",
        run_id="run-2",
    )
    assert out["stopped"] is True
    assert out["closed"] == ["original", "review"]
    assert "needs_robert" not in out
    assert all("needs:robert" not in call.args[1] for call in beads.add_labels.call_args_list)
    assert all("review:approved" not in call.args[1] for call in beads.add_labels.call_args_list)
    assert beads.close.call_count == 2


def test_generic_rejection_still_requires_robert():
    beads = MagicMock(spec=Beads)
    out = apply_verdict(
        beads,
        "review",
        {"labels": ["reviews:original", "role:auditor", "producer:programmer"]},
        verdict="reject",
        summary="Unsafe",
        by="auditor",
        run_id="run-2",
    )
    assert out["needs_robert"] is True
    beads.add_labels.assert_any_call("original", ["review:rejected", "needs:robert"])


@pytest.mark.parametrize(
    "verdict,student", [("approve", False), ("approve", True), ("revise", True), ("reject", True)]
)
def test_review_dependency_closed_before_original(verdict, student):
    beads = MagicMock(spec=Beads)
    beads.create.return_value = "revision"
    closed = []

    def close(bead, reason):
        if bead == "original":
            assert "review" in closed, "original blocked by open review"
        closed.append(bead)

    beads.close.side_effect = close
    review = (
        _review()
        if student
        else {"labels": ["reviews:original", "role:auditor", "producer:senior"]}
    )
    apply_verdict(
        beads,
        "review",
        review,
        verdict=verdict,
        summary="Evidence checked",
        by="auditor",
        run_id="run-order",
    )
    assert closed == ["review", "original"]
