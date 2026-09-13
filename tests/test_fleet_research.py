from datetime import UTC, date, datetime

from cube.agents import load_agent, read_inbox
from cube.beads import Beads
from cube.cli import main
from cube.engine.run import RunReport
from cube.goals import GoalHeader
from cube.model import BeadHeader, Provenance, RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.research import exploration_step, literature_handoffs
from cube.resources import update_limits
from cube.runners import StubRunner
from tests.helpers_engine import fixtures

globals().update(fixtures())
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def researcher(repo, name="expert"):
    assert (
        main(
            [
                "--root",
                str(repo),
                "agent",
                "new",
                name,
                "--kind",
                "expert",
                "--title",
                "Ontology researcher",
                "--topic",
                "applied-ontology",
                "--role",
                "senior",
                "--runtime",
                "claude",
                "--apply",
            ]
        )
        == 0
    )
    return load_agent(repo, name)


def goal(fake_bd, state="active"):
    fake_bd.add(
        "cube-goal",
        title="Reproduce ontology evaluation",
        labels=["kind:goal"],
        description=GoalHeader(
            xid="goal:fixture",
            target=date(2026, 12, 1),
            status=state,
            success=["Measured reproducible ontology evaluation"],
            provenance=[Provenance(source="tests/test_fleet_research.py")],
        ).render(),
    )


def test_exploration_requires_active_goal(engine_repo, engine_settings, fake_bd):
    agent = researcher(engine_repo)
    ledger = Beads(bin="bd", cwd=engine_repo)
    assert exploration_step(engine_settings, ledger, agent, [], NOW, dry_run=False) is None
    goal(fake_bd, "proposed")
    assert (
        exploration_step(
            engine_settings, ledger, agent, list(fake_bd.beads().values()), NOW, dry_run=False
        )
        is None
    )


def test_exploration_is_sourced_scoped_and_idempotent(engine_repo, engine_settings, fake_bd):
    agent = researcher(engine_repo)
    goal(fake_bd)
    ledger = Beads(bin="bd", cwd=engine_repo)
    step = exploration_step(
        engine_settings, ledger, agent, list(fake_bd.beads().values()), NOW, dry_run=False
    )
    bead = ledger.show(step["bead"])
    header = BeadHeader.parse(bead["description"])
    assert header is not None
    assert any(source.source == agent.charter for source in header.provenance)
    assert any(source.locator == "cube-goal" for source in header.provenance)
    assert "Choose only a goal that fits your expertise" in step["prompt_text"]
    assert "failed reproduction" in step["prompt_text"]
    same = exploration_step(
        engine_settings, ledger, agent, list(fake_bd.beads().values()), NOW, dry_run=False
    )
    assert same["bead"] == step["bead"]
    assert len(fake_bd.beads()) == 2
    fake_bd.add(step["bead"], **{**bead, "status": "closed", "id": step["bead"]})
    assert (
        exploration_step(
            engine_settings, ledger, agent, list(fake_bd.beads().values()), NOW, dry_run=False
        )
        is None
    )


def test_literature_handoff_reaches_named_researchers(engine_repo, engine_settings, fake_bd):
    first = researcher(engine_repo)
    second = researcher(engine_repo, "second")
    literature_handoffs(
        engine_settings,
        [
            {
                "agent": first.name,
                "identifier": "doi:10.example/ontology",
                "note": "Replicable baseline",
                "source": "https://example.org/paper",
            },
        ],
    )
    inbox = read_inbox(engine_repo, first, unread_only=True)
    assert len(inbox) == 1
    assert "https://example.org/paper" in str(inbox)
    assert "measured results" in str(inbox)
    assert "agent:literature" in str(inbox)
    assert not read_inbox(engine_repo, second, unread_only=True)


def test_idle_goal_runs_and_queues_documentation(engine_repo, engine_settings, fake_bd):
    researcher(engine_repo)
    goal(fake_bd)
    engine_settings.fleet_enabled = True
    runner = StubRunner(RunResult(summary="Baseline reproduced; source: tests/fixture.csv"))
    result = AgentWorkdayPatrol("expert", runner=runner, now=NOW).run(
        engine_settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )
    assert len(result.runs) == 1
    assert len(runner.calls) == 1
    assert "literature" in str(runner.calls)
    pending = list((engine_settings.state_dir() / "fleet-github").glob("*.json"))
    assert len(pending) == 1
    assert "Baseline reproduced" in pending[0].read_text()


def test_central_budget_stops_idle_research_before_runner(engine_repo, engine_settings, fake_bd):
    researcher(engine_repo)
    goal(fake_bd)
    engine_settings.fleet_enabled = True
    update_limits(engine_settings, {"daily_research_runs": 0}, "test:budget", dry_run=False)
    runner = StubRunner(RunResult(summary="Must never execute"))
    result = AgentWorkdayPatrol("expert", runner=runner, now=NOW).run(
        engine_settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )
    assert not runner.calls
    assert not result.runs
    assert any("research" in str(item) for item in result.blocked)


def test_queued_admission_does_not_spend_research_budget(
    engine_repo, engine_settings, fake_bd, monkeypatch
):
    import json

    researcher(engine_repo)
    goal(fake_bd)
    engine_settings.fleet_enabled = True
    monkeypatch.setattr(
        "cube.patrols.agent_workday.execute",
        lambda *args, **kwargs: RunReport(
            ok=False,
            run_id="fixture-queued",
            role="senior",
            bead=None,
            state="queued",
            error="local inference capacity full",
        ),
    )
    AgentWorkdayPatrol("expert", runner=StubRunner(), now=NOW).run(
        engine_settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )
    records = json.loads((engine_settings.state_dir() / "fleet-research.json").read_text())
    assert len(records) == 1
    assert records[0]["cancelled_before_start"] == "local inference capacity full"


def test_research_run_ceilings_can_be_disabled(engine_settings):
    from cube.resources import reserve_research_run, update_limits

    update_limits(
        engine_settings,
        {"daily_research_runs": None, "per_agent_daily_research_runs": None},
        "user:free-local-inference",
        dry_run=False,
    )
    for _ in range(3):
        reserve_research_run(engine_settings, "ontology", dry_run=False)
