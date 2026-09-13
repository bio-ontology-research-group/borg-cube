"""Workday hygiene: no duplicate proposals, no hourly re-runs, no repeated inbox rows.

Observed on ws 2026-09-04/05: the hourly coordinator tick filed fifteen copies of
its goal-review proposal, the decisions policy accepted each and delivered the
same answer to the coordinator inbox eleven times, and experts re-ran finished
beads every hour.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.agents import append_inbox, load_agent, mark_inbox_read, read_inbox
from cube.beads import Beads
from cube.config import Settings
from cube.model import RunResult
from cube.patrols.agent_workday import (
    AgentWorkdayPatrol,
    bead_runs,
    waiting_on_review,
    worked_since_update,
)
from cube.runners import StubRunner
from tests.helpers_engine import FakeBd, fixtures
from tests.test_agents import _new_agent
from tests.test_daily_reviews import _real_agent

globals().update(fixtures())

NOW = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


def _stub(text: str = "done (source: bead)") -> StubRunner:
    return StubRunner(RunResult(summary=text))


def test_goal_review_proposal_is_filed_once_per_day(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _real_agent(engine_repo, "coordinator")
    fake_bd.add("cube-g1", title="Goal: ship it", labels=["kind:goal"])
    for hour in (9, 10, 11):
        AgentWorkdayPatrol("coordinator", runner=_stub(), now=NOW.replace(hour=hour)).run(
            engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
        )
    reviews = [
        b for b in fake_bd.beads().values() if str(b.get("title", "")).startswith("Review coord")
    ]
    assert len(reviews) == 1
    assert reviews[0]["external_ref"] == "agent:coordinator:goal-review:2026-09-05"


def test_bead_worked_today_is_not_rerun_until_it_changes(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _new_agent(engine_repo, capsys)
    fake_bd.add("cube-1", title="read the paper", labels=["agent:expert", "kind:task"])
    ledger = Beads(bin="bd", cwd=engine_repo)
    first = AgentWorkdayPatrol("expert", runner=_stub(), now=NOW).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert [run["bead"] for run in first.runs] == ["cube-1"]
    assert bead_runs(engine_settings, "expert")["cube-1"]["run_id"] == first.runs[0]["run_id"]

    again = AgentWorkdayPatrol("expert", runner=_stub(), now=NOW + timedelta(hours=1)).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert again.runs == [] and again.state == "idle"

    # someone changed the bead after the run: it comes back
    fake_bd.add(
        "cube-1",
        title="read the paper",
        labels=["agent:expert", "kind:task"],
        updated_at=(NOW + timedelta(hours=2)).isoformat(),
    )
    changed = AgentWorkdayPatrol("expert", runner=_stub(), now=NOW + timedelta(hours=3)).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert [run["bead"] for run in changed.runs] == ["cube-1"]

    # the change was played; a new day does not start it again on its own
    # (the result waits for its reviewer, Robert 2026-09-06)
    tomorrow = AgentWorkdayPatrol("expert", runner=_stub(), now=NOW + timedelta(days=1)).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert tomorrow.runs == []


def test_worked_since_update_rules() -> None:
    done = {"cube-1": {"run_id": "r-1", "ts": "2026-09-05T08:00:00+00:00"}}
    assert worked_since_update(done, {"id": "cube-1"}, NOW) is True
    assert worked_since_update(done, {"id": "cube-2"}, NOW) is False
    # a finished run holds across days; only a change brings the bead back
    assert worked_since_update(done, {"id": "cube-1"}, NOW + timedelta(days=1)) is True
    later = {"id": "cube-1", "updated_at": "2026-09-05T08:30:00+00:00"}
    assert worked_since_update(done, later, NOW) is False
    earlier = {"id": "cube-1", "updated_at": "2026-09-05T07:30:00+00:00"}
    assert worked_since_update(done, earlier, NOW) is True
    # the stamp read back after the run covers the run's own summary comment
    stamped = {
        "cube-1": {
            "run_id": "r-1",
            "ts": "2026-09-05T08:00:00+00:00",
            "seen": "2026-09-05T08:31:00+00:00",
        }
    }
    assert worked_since_update(stamped, later, NOW) is True
    touched = {"id": "cube-1", "updated_at": "2026-09-05T08:32:00+00:00"}
    assert worked_since_update(stamped, touched, NOW) is False
    # a failed run is retried the next day, not the next hour
    failed = {"cube-1": {"run_id": "r-1", "ts": "2026-09-05T08:00:00+00:00", "ok": False}}
    assert worked_since_update(failed, {"id": "cube-1"}, NOW) is True
    assert worked_since_update(failed, {"id": "cube-1"}, NOW + timedelta(days=1)) is False


def test_waiting_on_review_holds_filed_and_blocked_beads() -> None:
    assert waiting_on_review({"id": "cube-1", "labels": ["review:pending"]}) is True
    assert waiting_on_review({"id": "cube-1", "labels": ["review:revise"]}) is True
    assert waiting_on_review({"id": "cube-1", "labels": ["agent:expert"]}) is False
    blocked = {
        "id": "cube-1",
        "labels": ["agent:expert"],
        "dependencies": [{"id": "cube-9", "status": "open", "dependency_type": "blocks"}],
    }
    assert waiting_on_review(blocked) is True
    released = {
        "id": "cube-1",
        "labels": ["agent:expert"],
        "dependencies": [{"id": "cube-9", "status": "closed", "dependency_type": "blocks"}],
    }
    assert waiting_on_review(released) is False
    related = {
        "id": "cube-1",
        "labels": ["agent:expert"],
        "dependencies": [{"id": "cube-9", "status": "open", "dependency_type": "related"}],
    }
    assert waiting_on_review(related) is False


def test_a_filed_result_waits_for_its_reviewer_not_the_next_tick(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Observed on ws 2026-09-05/06: senior beads ran 6 to 17 times each.

    The run's summary is the result; the engine files the review bead itself
    (the role's reviewer, never the same role), and the hourly tick sees the
    bead labelled review:pending and blocked by that review bead.
    """
    _new_agent(engine_repo, capsys)
    fake_bd.add("cube-1", title="assess the preprint", labels=["agent:expert", "kind:task"])
    ledger = Beads(bin="bd", cwd=engine_repo)
    first = AgentWorkdayPatrol("expert", runner=_stub(), now=NOW).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert [run["bead"] for run in first.runs] == ["cube-1"]
    beads = fake_bd.beads()
    assert "review:pending" in beads["cube-1"]["labels"]
    reviews = [b for b in beads.values() if "reviews:cube-1" in b.get("labels", [])]
    assert len(reviews) == 1
    assert "role:group-leader" in reviews[0]["labels"]  # the senior's reviewer, not the senior
    assert "role:senior" not in reviews[0]["labels"]
    # the run's own comment moved updated_at; the stamp read back covers it
    record = bead_runs(engine_settings, "expert")["cube-1"]
    assert record["ok"] is True
    # the next ticks, today and tomorrow, do not play the bead again
    for later in (NOW + timedelta(hours=1), NOW + timedelta(days=1)):
        again = AgentWorkdayPatrol("expert", runner=_stub(), now=later).run(
            engine_settings, dry_run=False, beads=ledger
        )
        assert again.runs == [], later
        assert "cube-1" not in again.assigned_beads


def test_a_failed_run_is_retried_tomorrow_not_hourly(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _new_agent(engine_repo, capsys)
    fake_bd.add("cube-1", title="read the paper", labels=["agent:expert", "kind:task"])
    ledger = Beads(bin="bd", cwd=engine_repo)
    broken = StubRunner(RunResult(summary="x"), fail="runner crashed")
    first = AgentWorkdayPatrol("expert", runner=broken, now=NOW).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert first.runs and not first.runs[0]["ok"]
    assert bead_runs(engine_settings, "expert")["cube-1"]["ok"] is False
    again = AgentWorkdayPatrol("expert", runner=broken, now=NOW + timedelta(hours=1)).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert again.runs == []
    tomorrow = AgentWorkdayPatrol("expert", runner=broken, now=NOW + timedelta(days=1)).run(
        engine_settings, dry_run=False, beads=ledger
    )
    assert [run["bead"] for run in tomorrow.runs] == ["cube-1"]


def test_inbox_keeps_one_copy_of_an_unread_message(
    engine_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    agent = load_agent(engine_repo, "expert")
    first = append_inbox(engine_repo, agent, "Robert answered: policy: advisory")
    second = append_inbox(engine_repo, agent, "Robert answered: policy: advisory")
    assert second.get("duplicate") is True and second["ts"] == first["ts"]
    assert len(read_inbox(engine_repo, agent)) == 1
    # a different sender or text is a new message
    append_inbox(engine_repo, agent, "Robert answered: policy: advisory", sender="agent:ontology")
    assert len(read_inbox(engine_repo, agent)) == 2
    # once read, the same text may arrive again
    mark_inbox_read(engine_repo, agent)
    append_inbox(engine_repo, agent, "Robert answered: policy: advisory")
    assert len(read_inbox(engine_repo, agent)) == 3


def test_parent_link_and_unknown_status_do_not_block_a_child_bead() -> None:
    # Real `bd list --json` dependency records: type/depends_on_id, no status.
    child = {
        "id": "cube-dwv.1",
        "labels": ["agent:liaison"],
        "dependencies": [
            {"issue_id": "cube-dwv.1", "depends_on_id": "cube-dwv", "type": "parent-child"}
        ],
    }
    assert waiting_on_review(child) is False
    blocked = {
        "id": "cube-dwv.3",
        "labels": ["agent:ontology"],
        "dependencies": [
            {"issue_id": "cube-dwv.3", "depends_on_id": "cube-dwv.1", "type": "blocks"}
        ],
    }
    # without the ledger the status is unknown: bd ready decides, not this filter
    assert waiting_on_review(blocked) is False
    issues = [child, blocked, {"id": "cube-dwv.1", "status": "open"}]
    assert waiting_on_review(blocked, issues) is True
    issues[-1]["status"] = "closed"
    assert waiting_on_review(blocked, issues) is False
