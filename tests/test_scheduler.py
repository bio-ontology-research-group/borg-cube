import fcntl
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cube.engine import execute
from cube.resources import FleetLimits
from cube.runners import StubRunner
from cube.scheduler import plan, tick
from tests.helpers_engine import fixtures

globals().update(fixtures())


def issue(bid, *, labels=None, priority=2, **kwargs):
    return {
        "id": bid,
        "status": "open",
        "priority": priority,
        "labels": labels or ["role:senior"],
        **kwargs,
    }


def ledger(rows, ready=None):
    beads = MagicMock()
    beads.list_issues.return_value = rows
    beads.ready.return_value = rows if ready is None else ready
    return beads


@pytest.fixture(autouse=True)
def no_ledger_sync(monkeypatch):
    calls = []

    def fake_sync(settings, beads, direction, *, host, dry_run):
        calls.append(direction)
        return {"direction": direction, "ok": True}

    monkeypatch.setattr("cube.scheduler.sync_ledger", fake_sync)
    return calls


def test_priority_order_review_and_rotation(engine_settings):
    a = issue("cube-a", labels=["role:senior", "schedule:order:2"])
    b = issue("cube-b", labels=["role:programmer", "schedule:order:1"])
    assert plan(engine_settings, ledger([a, b]))["selected"]["bead"] == "cube-b"
    a["priority"] = 1
    assert plan(engine_settings, ledger([a, b]))["selected"]["bead"] == "cube-a"
    a = issue("cube-a")
    b = issue("cube-b", labels=["role:programmer"])
    path = engine_settings.state_dir() / "scheduler.json"
    path.write_text(json.dumps({"agents": {"senior": 1}, "attempts": {}}))
    assert plan(engine_settings, ledger([a, b]))["selected"]["bead"] == "cube-b"
    a["labels"].append("kind:review")
    assert plan(engine_settings, ledger([a, b]))["selected"]["bead"] == "cube-a"


def test_dependency_approval_host_and_restricted_boundaries(engine_settings):
    a = issue("cube-blocked", priority=0)
    rows = [
        a,
        issue("cube-human", labels=["role:senior", "needs:robert"]),
        issue("cube-laptop", labels=["role:senior", "host:laptop"]),
        issue("cube-admin", labels=["role:sysadmin"]),
        issue("cube-go"),
    ]
    result = plan(engine_settings, ledger(rows, rows[1:]))
    assert [r["bead"] for r in result["queue"]] == ["cube-go"]
    assert len(result["waiting"]) == 4


def test_goal_with_child_and_intake_have_dedicated_owners(engine_settings):
    goal = issue("cube-goal", labels=["kind:goal"])
    child = issue("cube-goal.1")
    intake = issue("cube-intake", external_ref="mattermost-goal:abc")
    result = plan(engine_settings, ledger([goal, child, intake]))
    assert [r["bead"] for r in result["queue"]] == ["cube-goal.1"]


def test_central_pause_runtime_clamp_and_cooldown(engine_settings):
    engine_settings.fleet_limits = FleetLimits(local_run_timeout_minutes=30)
    rows = [issue("cube-a", labels=["role:senior", "runtime:minutes:120"])]
    assert plan(engine_settings, ledger(rows))["selected"]["runtime_minutes"] == 30
    engine_settings.fleet_limits.local_workday_concurrency = 0
    assert plan(engine_settings, ledger(rows))["selected"] is None
    engine_settings.fleet_limits.local_workday_concurrency = 1
    now = datetime.now(UTC)
    (engine_settings.state_dir() / "scheduler.json").write_text(
        json.dumps(
            {
                "agents": {},
                "attempts": {"cube-a": {"next_at": (now + timedelta(minutes=5)).isoformat()}},
            }
        )
    )
    assert plan(engine_settings, ledger(rows), now=now)["selected"] is None


def test_dry_run_no_model_no_writes(engine_settings, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("cube.scheduler.execute", run)
    result = tick(engine_settings, ledger([issue("cube-a")]))
    assert result["selected"]["bead"] == "cube-a"
    run.assert_not_called()
    assert not (engine_settings.state_dir() / "scheduler.json").exists()
    assert not (engine_settings.state_dir() / "scheduler.lock").exists()


def test_repeated_incomplete_checkpoints_stop_automatic_retry(engine_settings):
    (engine_settings.state_dir() / "scheduler.json").write_text(
        json.dumps({"attempts": {"cube-a": {"checkpoints": 4}}, "agents": {}})
    )
    result = plan(engine_settings, ledger([issue("cube-a")]))
    assert result["selected"] is None
    assert "4 incomplete turns" in result["waiting"][0]["reason"]
    (engine_settings.state_dir() / "scheduler.json").write_text(
        json.dumps({"attempts": {"cube-a": {"checkpoints": 3}}, "agents": {}})
    )
    assert plan(engine_settings, ledger([issue("cube-a")]))["selected"]["bead"] == "cube-a"


def test_stale_claim_is_released_and_reviewed_work_waits(engine_settings, monkeypatch):
    from cube.engine import lease as leases

    # cube-r1n.3 on 2026-09-09: the run finished with close=false, the bead stayed
    # in_progress, bd ready hid it and the scheduler reported "not ready" for days.
    stuck = issue("cube-a", status="in_progress", assignee="cube/senior")
    human = issue("cube-h", status="in_progress", assignee="robert")
    running = issue("cube-r", status="in_progress", assignee="cube/senior")
    leases.acquire(engine_settings.state_dir(), "cube-r", run_id="run-9", role="senior")
    reviewed = issue("cube-v", labels=["role:senior", "review:pending"])
    b = ledger([stuck, human, running, reviewed], ready=[reviewed])
    result = plan(engine_settings, b)
    reasons = {row["bead"]: row["reason"] for row in result["waiting"]}
    assert reasons["cube-a"].startswith("stale claim")
    assert reasons["cube-r"] == "running"
    assert reasons["cube-h"] == "not ready: dependencies, claim or deferred state"
    assert reasons["cube-v"] == "waiting for review"
    assert result["selected"] is None
    monkeypatch.setattr("cube.scheduler.execute", MagicMock())
    out = tick(engine_settings, b, dry_run=False)
    assert out["released"] == ["cube-a"]
    b.unclaim.assert_called_once_with("cube-a")


def test_tick_syncs_ledger_and_counts_open_finished_turns(
    engine_settings, monkeypatch, no_ledger_sync
):
    from cube.config import TierEntry

    engine_settings.tiers["local"] = [TierEntry(runner="hermes", provider="local", model="qwen")]
    run = MagicMock(
        return_value=SimpleNamespace(
            ok=True,
            state="finished",
            error=None,
            run_id="run-1",
            message="planned",
            applied={"closed": [], "review_bead": None},
        )
    )
    monkeypatch.setattr("cube.scheduler.execute", run)
    b = ledger([issue("cube-a")])
    assert tick(engine_settings, b, dry_run=False)["state"] == "finished"
    assert no_ledger_sync == ["pull", "push"]
    saved = json.loads((engine_settings.state_dir() / "scheduler.json").read_text())
    assert saved["attempts"]["cube-a"]["checkpoints"] == 1
    run.return_value.applied = {"closed": ["cube-a"], "review_bead": None}
    saved["attempts"]["cube-a"].pop("next_at")
    (engine_settings.state_dir() / "scheduler.json").write_text(json.dumps(saved))
    tick(engine_settings, b, dry_run=False)
    saved = json.loads((engine_settings.state_dir() / "scheduler.json").read_text())
    assert saved["attempts"]["cube-a"]["checkpoints"] == 0
    # an idle tick still pushes what the pull merged and this host wrote
    no_ledger_sync.clear()
    assert tick(engine_settings, ledger([]), dry_run=False)["state"] == "idle"
    assert no_ledger_sync == ["pull", "push"]
    # dry runs never touch the remote
    no_ledger_sync.clear()
    tick(engine_settings, ledger([]), dry_run=True)
    assert no_ledger_sync == []


def test_tick_exact_runtime_local_route_and_failure_backoff(engine_settings, monkeypatch):
    from cube.config import TierEntry

    engine_settings.tiers["local"] = [TierEntry(runner="hermes", provider="local", model="qwen")]
    run = MagicMock(
        return_value=SimpleNamespace(
            ok=False, state="error", error="failure", run_id="run-1", message=""
        )
    )
    monkeypatch.setattr("cube.scheduler.execute", run)
    b = ledger([issue("cube-a", labels=["role:senior", "runtime:minutes:12"])])
    assert tick(engine_settings, b, dry_run=False)["state"] == "error"
    assert run.call_args.kwargs["runtime_minutes"] == 12
    assert run.call_args.kwargs["model"] == "qwen"
    assert run.call_args.kwargs["runner_name"] == "hermes@local"
    assert run.call_args.kwargs["respect_project_runner"] is False
    assert tick(engine_settings, b, dry_run=False)["state"] == "idle"
    assert run.call_count == 1


def test_engine_runtime_allocation(engine_settings, fake_bd):
    fake_bd.add(
        "cube-a",
        title="Bounded work",
        labels=["role:senior"],
        description="---\nxid: test:runtime\n---\n",
    )
    report = execute(
        engine_settings,
        "senior",
        bead="cube-a",
        runner=StubRunner(),
        runner_name="stub",
        runtime_minutes=12,
    )
    assert report.ok
    meta = json.loads((Path(report.run_dir) / "meta.json").read_text())
    assert meta["timeout_seconds"] == 720


def test_lock_prevents_second_dispatch(engine_settings, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("cube.scheduler.execute", run)
    with (engine_settings.state_dir() / "scheduler.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert tick(engine_settings, ledger([]), dry_run=False) == {"state": "busy"}
    run.assert_not_called()


def test_engine_exception_records_cooldown(engine_settings, monkeypatch):
    from cube.config import TierEntry

    engine_settings.tiers["local"] = [TierEntry(runner="hermes", provider="local", model="qwen")]
    monkeypatch.setattr("cube.scheduler.execute", MagicMock(side_effect=OSError("private detail")))
    b = ledger([issue("cube-a")])
    result = tick(engine_settings, b, dry_run=False)
    assert result["error"] == "dispatch failed: OSError"
    assert tick(engine_settings, b, dry_run=False)["state"] == "idle"


@pytest.mark.parametrize("minutes", [0, True, 999])
def test_engine_rejects_invalid_allocations(engine_settings, minutes):
    report = execute(engine_settings, "senior", runtime_minutes=minutes)
    assert report.state == "refused"


@pytest.mark.parametrize("respect,expected", [(True, "codex"), (False, "hermes@local")])
def test_scheduler_route_can_override_project_harness(
    engine_settings, fake_bd, monkeypatch, respect, expected
):
    import importlib

    from cube.config import ProjectRunnerProfile
    from cube.router.policy import Queued

    engine_settings.projects["demo"] = ProjectRunnerProfile(
        path=engine_settings.root, runner="codex"
    )
    fake_bd.add(
        "cube-a",
        title="Work",
        labels=["project:demo", "role:senior"],
        description="---\nxid: test:route\n---\n",
    )
    choose = MagicMock(side_effect=Queued("test stops before execution"))
    monkeypatch.setattr(importlib.import_module("cube.engine.run"), "choose", choose)
    report = execute(
        engine_settings,
        "senior",
        bead="cube-a",
        runner_name="hermes@local",
        respect_project_runner=respect,
    )
    assert report.state == "queued"
    assert choose.call_args.kwargs["requested_runner"] == expected


def test_goal_turn_applies_the_returned_plan(engine_settings, monkeypatch):
    import cube.goals as goals
    from cube.scheduler import _apply_goal_plan

    goal = {"id": "cube-g", "labels": ["kind:goal"], "description": "---\nxid: g\n---\n"}
    beads = MagicMock()
    monkeypatch.setattr(goals, "validate_plan", lambda settings, g, plan: plan)
    monkeypatch.setattr(
        goals, "apply_plan", lambda settings, b, g, plan: [{"id": "cube-g.1"}, {"id": "cube-g.2"}]
    )
    report = SimpleNamespace(
        as_dict=lambda: {
            "run_id": "r-1",
            "run_dir": str(engine_settings.root / "runs" / "r-1"),
            "result": {"summary": "beads:\n- id: one\n", "artifacts": []},
        }
    )
    assert _apply_goal_plan(engine_settings, beads, goal, report) == ["cube-g.1", "cube-g.2"]
    assert "created 2 child bead(s)" in beads.comment.call_args.args[1]
    empty = SimpleNamespace(
        as_dict=lambda: {
            "run_id": "r-2",
            "run_dir": "",
            "result": {"summary": "nothing", "artifacts": []},
        }
    )
    assert _apply_goal_plan(engine_settings, beads, goal, empty) == []
    assert "no plan artifact" in beads.comment.call_args.args[1]


def test_goal_in_queue_is_flagged_and_stalled_task_is_handed_to_coordinator(
    engine_settings, monkeypatch
):
    from cube.config import TierEntry

    goal = issue("cube-g", labels=["kind:goal"], priority=1)
    monkeypatch.setattr(
        "cube.scheduler.load_agent",
        lambda root, name: SimpleNamespace(name=name, host=engine_settings.host, charter="none.md"),
    )
    result = plan(engine_settings, ledger([goal]))
    assert result["selected"]["goal"] is True and result["selected"]["role"] == "group-leader"
    assert plan(engine_settings, ledger([issue("cube-a")]))["selected"]["goal"] is False

    engine_settings.tiers["local"] = [TierEntry(runner="hermes", provider="local", model="qwen")]
    (engine_settings.state_dir() / "scheduler.json").write_text(
        json.dumps({"attempts": {"cube-a": {"checkpoints": 3}}, "agents": {}})
    )
    run = MagicMock(
        return_value=SimpleNamespace(
            ok=True,
            state="finished",
            error=None,
            run_id="run-9",
            message="",
            applied={"closed": [], "review_bead": None},
        )
    )
    monkeypatch.setattr("cube.scheduler.execute", run)
    b = ledger([issue("cube-a")])
    tick(engine_settings, b, dry_run=False)
    b.add_labels.assert_called_once_with("cube-a", ["schedule:revise"])
    assert "4 scheduled turns" in b.comment.call_args.args[1]
    inbox = engine_settings.root / "agents" / "coordinator" / "inbox.jsonl"
    assert inbox.exists() and "cube-a" in inbox.read_text()
    assert plan(engine_settings, b)["selected"] is None


def test_local_timeout_floor_applies_to_every_local_harness():
    from cube.engine.run import run_timeout_seconds

    assert run_timeout_seconds(900, "hermes@local", 45, None) == 2700
    assert run_timeout_seconds(900, "claude@local", 45, None) == 2700
    assert run_timeout_seconds(900, "claude@openrouter", 45, None) == 900
    assert run_timeout_seconds(900, "claude@local", 45, 12) == 720
