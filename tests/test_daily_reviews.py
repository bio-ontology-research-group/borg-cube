"""The coordinator's daily management review and the sysadmin's daily server review."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.agents import load_agent
from cube.agents.coordinator import (
    IDLE_STEP_TITLE,
    last_management_review,
    management_context,
    management_due,
    management_facts,
    record_management_review,
)
from cube.agents.sysadmin import SERVER_REVIEW_TITLE, server_review_context
from cube.beads import Beads
from cube.config import Settings
from cube.model import RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.runners import StubRunner
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures
from tests.test_agents import _new_agent

globals().update(fixtures())

NOW = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


def _real_agent(repo: Path, name: str) -> None:
    import shutil

    (repo / "agents").mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
    if not (repo / "agents" / name).exists():
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name)


def test_management_facts_show_idle_agents_people_deadlines_and_seeds(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _real_agent(engine_repo, "coordinator")
    _new_agent(engine_repo, capsys)  # "expert", idle
    fake_bd.add("cube-1", title="busy work", labels=["agent:coordinator", "kind:task"])
    fake_bd.add("cube-2", title="thesis chapter", labels=["person:gus-student", "kind:task"])
    (engine_repo / "pa" / "deadlines.md").write_text(
        "# Deadlines\n- 2026-09-20 - NIH phase 1 concept paper\n- 2027-01-01 - far away\n",
        encoding="utf-8",
    )
    digest_dir = engine_settings.literature_watch.digest_path(engine_repo)
    digest_dir.mkdir(parents=True, exist_ok=True)
    (digest_dir / "2026-09-05.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "title": "Semantic Bayesian World Models",
                        "url": "https://arxiv.org/abs/2609.03834v1",
                        "priority": "high",
                        "relevance": [{"kind": "topic", "ref": "neuro-symbolic-ai", "why": "x"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    beads = Beads(bin="bd", cwd=engine_repo, dry_run=True)
    facts = management_facts(engine_settings, beads, now=NOW)
    assert facts["agents"]["busy"] == ["coordinator"] and "expert" in facts["agents"]["idle"]
    assert "gus-student" in facts["people"]["busy"]
    assert facts["people"]["idle"] and "gus-student" not in facts["people"]["idle"]
    assert [row["text"] for row in facts["deadlines"]] == ["NIH phase 1 concept paper"]
    assert facts["deadlines"][0]["days"] == 15
    assert facts["literature"][0]["title"] == "Semantic Bayesian World Models"
    text = management_context(engine_settings, beads, now=NOW)
    assert "agents idle: " in text and "expert" in text
    assert "2026-09-20 (15 days): NIH phase 1 concept paper" in text
    assert "cube create --title" in text and "Never contact them yourself" in text


def test_management_review_runs_every_few_hours_through_the_workday(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    # Robert, 2026-09-07: the coordinator reviews every coordination.review_every_hours.
    _real_agent(engine_repo, "coordinator")
    agent = load_agent(engine_repo, "coordinator")
    every = engine_settings.coordination.review_every_hours
    assert every == 4
    assert management_due(engine_settings, agent, NOW)
    runner = StubRunner(RunResult(summary="reviewed (source: management context)"))
    first = AgentWorkdayPatrol("coordinator", runner=runner, now=NOW).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert first.management_review == IDLE_STEP_TITLE and len(first.runs) == 1
    assert last_management_review(engine_settings, agent) == NOW
    assert not management_due(engine_settings, agent, NOW + timedelta(hours=every - 1))
    second = AgentWorkdayPatrol(
        "coordinator", runner=runner, now=NOW + timedelta(hours=every - 1)
    ).run(engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo))
    assert second.management_review is None and second.state == "idle"
    assert management_due(engine_settings, agent, NOW + timedelta(hours=every))
    # A dry run reviews but does not consume the slot.
    record_management_review(engine_settings, agent, NOW - timedelta(days=1))
    dry = AgentWorkdayPatrol("coordinator", runner=runner, now=NOW).run(
        engine_settings, dry_run=True, beads=Beads(bin="bd", cwd=engine_repo, dry_run=True)
    )
    assert dry.management_review == IDLE_STEP_TITLE
    assert last_management_review(engine_settings, agent) == NOW - timedelta(days=1)
    # A bare date written before 2026-09-07 still reads as that day's midnight.
    path = engine_repo / "state" / "agents" / "coordinator" / "management.json"
    path.write_text('{"last": "2026-09-04"}\n', encoding="utf-8")
    assert last_management_review(engine_settings, agent) == datetime(2026, 9, 4, tzinfo=UTC)
    assert management_due(engine_settings, agent, NOW)


def test_management_facts_show_assignments_stale_work_and_quiet_projects(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Robert, 2026-09-07: the coordinator distributes and makes sure work is done.
    _real_agent(engine_repo, "coordinator")
    _new_agent(engine_repo, capsys)  # "expert"
    old = (NOW - timedelta(hours=30)).isoformat()
    fresh = (NOW - timedelta(hours=2)).isoformat()
    fake_bd.add(
        "cube-10",
        title="never touched",
        labels=["agent:expert", "kind:task", "project:crg-explainable-ml-ontologies"],
        created_at=old,
        updated_at=old,
    )
    fake_bd.add(
        "cube-11",
        title="ran this morning",
        labels=["agent:expert", "kind:task"],
        created_at=old,
        updated_at=fresh,
    )
    fake_bd.add(
        "cube-12",
        title="filed, waits for review",
        labels=["agent:expert", "kind:task", "review:pending"],
        created_at=old,
        updated_at=old,
    )
    fake_bd.add("cube-13", title="a review", labels=["kind:review", "role:senior"])
    runs_file = engine_repo / "state" / "agents" / "expert" / "bead-runs.json"
    runs_file.parent.mkdir(parents=True, exist_ok=True)
    runs_file.write_text(
        json.dumps({"cube-11": {"run_id": "r-1", "ts": fresh, "ok": True}}), encoding="utf-8"
    )
    facts = management_facts(engine_settings, Beads(bin="bd", cwd=engine_repo), now=NOW)
    rows = {row["id"]: row for row in facts["assignments"]["expert"]}
    assert rows["cube-10"]["stale"] and rows["cube-10"]["last_run_hours"] is None
    assert not rows["cube-11"]["stale"] and rows["cube-11"]["last_run_hours"] == 2.0
    assert rows["cube-12"]["waiting"] and not rows["cube-12"]["stale"]
    assert [row["id"] for row in facts["stale"]] == ["cube-10"]
    assert facts["reviews_pending"] == 1
    assert facts["assignments"]["coordinator"] == []
    text = management_context(engine_settings, Beads(bin="bd", cwd=engine_repo), now=NOW)
    assert "cube-10 (open, never ran STALE) never touched" in text
    assert "cube-12 (open, never ran waiting)" in text
    assert "- coordinator: nothing assigned" in text
    assert "review beads open: 1" in text
    assert "Distribute." in text and "Chase." in text and "Decide." in text
    assert "critical" in text and "Robert sees only security-critical" in text


def test_sysadmin_server_review_is_read_only_and_daily(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _real_agent(engine_repo, "sysadmin")
    text = server_review_context(engine_settings, None, now=NOW)
    assert text.startswith("# Daily server review 2026-09-05")
    assert "you never restart, delete,\nedit or install anything" in text
    # Robert, 2026-09-07: logs, upgrades and robustness fixes, bundled into one
    # approval bead per host; a change to a running system is the one thing that waits.
    assert "kind:approval" in text and "nvidia-smi" in text and "systemctl --user --failed" in text
    assert "apt list --upgradable" in text and "dmesg" in text and "failed password" in text
    assert "--xid sysadmin:<host>:<topic>" in text and "rollback" in text
    runner = StubRunner(RunResult(summary="checked (source: uptime on ws)"))
    result = AgentWorkdayPatrol("sysadmin", runner=runner, now=NOW).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert result.management_review == SERVER_REVIEW_TITLE and len(result.runs) == 1
    assert "Daily server review" in runner.calls[0].prompt


def test_fleet_sysadmin_review_uses_only_guarded_tools(engine_settings: Settings) -> None:
    engine_settings.fleet_enabled = True
    text = server_review_context(engine_settings, None, now=NOW)
    assert "cube boundary inspect" in text and "cube boundary propose" in text
    assert "inodes" in text and "postchecks" in text
    assert "cube create" not in text and "ssh -o" not in text


def test_daily_reviews_demand_a_tool_capable_harness(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    """Both daily reviews plan and then act, so they never route to a chat runner."""
    from cube.patrols.agent_workday import TOOL_STEPS

    assert TOOL_STEPS == {IDLE_STEP_TITLE, SERVER_REVIEW_TITLE}
    for name in ("coordinator", "sysadmin"):
        _real_agent(engine_repo, name)
        runner = StubRunner(RunResult(summary=f"done (source: {name} review)"))
        result = AgentWorkdayPatrol(name, runner=runner, now=NOW).run(
            engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
        )
        assert len(result.runs) == 1
        assert result.runs[0]["needs_tools"] is True


def test_charters_are_robert_reviewed_not_placeholders() -> None:
    for name in ("coordinator", "sysadmin"):
        text = (REPO_ROOT / "agents" / name / "charter.md").read_text(encoding="utf-8")
        assert "example charter text" not in text.lower()
        assert "reviewed_by: Robert Hoehndorf" in text
        assert "## Success in 6 months" in text


def test_workday_is_skipped_while_another_run_holds_the_lock(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    """The hourly timer and a manual `--now` must never run the same review twice."""
    import fcntl

    from cube.patrols.agent_workday import workday_lock, workday_lock_path

    _real_agent(engine_repo, "sysadmin")
    holder = workday_lock(engine_settings, "sysadmin")
    assert holder is not None
    runner = StubRunner(RunResult(summary="done (source: sysadmin review)"))
    try:
        result = AgentWorkdayPatrol("sysadmin", runner=runner, now=NOW).run(
            engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
        )
        assert result.state == "busy"
        assert result.runs == []
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
    assert workday_lock_path(engine_settings, "sysadmin").exists()
    result = AgentWorkdayPatrol("sysadmin", runner=runner, now=NOW).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert result.state == "finished" and len(result.runs) == 1
