"""Grant work is bounded, private and independently reviewed, without real sends."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.agents import load_agent
from cube.beads import Beads
from cube.engine.review_gate import apply_verdict
from cube.model import Privacy, RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.research import exploration_step, is_researcher
from cube.resources import update_limits
from cube.runners import StubRunner
from tests.helpers_engine import REPO_ROOT, fixtures

globals().update(fixtures())
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def setup_agents(settings):
    for name in ("grants", "student-supervisor"):
        target = settings.root / "agents"
        target.mkdir(exist_ok=True)
        shutil.copy(REPO_ROOT / f"agents/{name}.yaml", target)
        (target / name).mkdir()
        shutil.copy(REPO_ROOT / f"agents/{name}/charter.md", target / name)
    return load_agent(settings.root, "grants")


def test_grant_cycles_are_bounded_and_private(engine_settings, fake_bd):
    agent = setup_agents(engine_settings)
    assert is_researcher(agent)
    assert agent.privacy_default == Privacy.local_only
    ledger = Beads(bin="bd", cwd=engine_settings.root)

    def step(now=NOW, dry=False):
        return exploration_step(
            engine_settings, ledger, agent, list(fake_bd.beads().values()), now, dry_run=dry
        )

    assert "CRG2026" in step(dry=True)["title"]
    assert not fake_bd.beads()
    first = step()
    assert step() is None
    ledger.close(first["bead"], "fixture reviewed")
    second = step()
    assert "funding opportunities" in second["title"]
    ledger.close(second["bead"], "fixture reviewed")
    assert step() is None
    assert "CRG2026" in step(NOW + timedelta(days=1), dry=True)["title"]
    tomorrow = step(NOW + timedelta(days=1))
    ledger.close(tomorrow["bead"], "fixture reviewed")
    assert step(NOW + timedelta(days=1), dry=True) is None
    next_week = NOW + timedelta(days=7)
    proposal = step(next_week)
    ledger.close(proposal["bead"], "fixture reviewed")
    assert "funding opportunities" in step(next_week, dry=True)["title"]
    assert all("privacy:local-only" in b["labels"] for b in fake_bd.beads().values())


@pytest.mark.parametrize("verdict", ["approve", "revise", "reject"])
def test_grant_workday_review_roundtrip(engine_settings, fake_bd, verdict):
    setup_agents(engine_settings)
    engine_settings.host = "ws"
    engine_settings.fleet_enabled = True
    ledger = Beads(bin="bd", cwd=engine_settings.root)
    result = AgentWorkdayPatrol(
        "grants", now=NOW, runner=StubRunner(RunResult(summary="Fixture proposal audit"))
    ).run(engine_settings, dry_run=False, beads=ledger)
    assert len(result.runs) == 1 and result.runs[0]["ok"], result.as_dict()
    meta = json.loads((Path(result.runs[0]["run_dir"]) / "meta.json").read_text())
    assert meta["privacy"] == "local-only"
    review = next(b for b in fake_bd.beads().values() if "kind:review" in b["labels"])
    assert {"agent:student-supervisor", "tier:local", "producer-agent:grants"} <= set(
        review["labels"]
    )
    if verdict == "approve":
        checked = AgentWorkdayPatrol(
            "student-supervisor",
            now=NOW,
            runner=StubRunner(RunResult(summary="Fixture review", verdict="approve")),
        ).run(engine_settings, dry_run=False, beads=ledger)
        assert checked.runs[0]["ok"], checked.as_dict()
        assert all(b["status"] == "closed" for b in fake_bd.beads().values())
    else:
        outcome = apply_verdict(
            ledger,
            review["id"],
            review,
            verdict=verdict,
            summary="Fixture evidence",
            by="student-reviewer",
            run_id="fixture-review",
        )
        assert not outcome.get("needs_robert")
        if verdict == "revise":
            revision = ledger.show(outcome["follow_up"])
            assert {"agent:grants", "tier:local", "privacy:local-only"} <= set(revision["labels"])
            assert (
                exploration_step(
                    engine_settings,
                    ledger,
                    load_agent(engine_settings.root, "grants"),
                    list(fake_bd.beads().values()),
                    NOW,
                    dry_run=True,
                )
                is None
            )


def test_grant_work_respects_fleet_switch(engine_settings, fake_bd):
    setup_agents(engine_settings)
    engine_settings.host = "ws"
    engine_settings.fleet_enabled = False
    runner = StubRunner(RunResult(summary="must not run"))
    AgentWorkdayPatrol("grants", now=NOW, runner=runner).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_settings.root)
    )
    assert not runner.calls


def test_grant_work_respects_central_budget(engine_settings, fake_bd):
    setup_agents(engine_settings)
    engine_settings.host = "ws"
    engine_settings.fleet_enabled = True
    update_limits(engine_settings, {"daily_research_runs": 0}, "test:grant-budget", dry_run=False)
    runner = StubRunner(RunResult(summary="must not run"))
    result = AgentWorkdayPatrol("grants", now=NOW, runner=runner).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_settings.root)
    )
    assert not runner.calls and not result.runs
    assert result.blocked
    assert not fake_bd.beads()
