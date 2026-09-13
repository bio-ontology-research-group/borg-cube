import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cube.agents import load_agent
from cube.beads import Beads
from cube.cli import main
from cube.config import HostEntry, TierEntry
from cube.doctor import check_agent_topics
from cube.engine import execute
from cube.model import Privacy, RunResult, Tier
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.research import exploration_step
from cube.router.policy import Queued, Refused, choose
from cube.runners import StubRunner
from cube.student.twins import current_students, push_sources, sync_twins, twin_members
from tests.helpers_engine import fixtures

globals().update(fixtures())
NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def test_selected_staff_twins_share_private_review_workflow(engine_settings, fake_bd):
    (engine_settings.root / "twins.yaml").write_text(
        "include_members: [fin-fellow, carla-staff, gia-scientist]\n"
    )
    result = sync_twins(engine_settings, dry_run=False)
    assert result["members"] == 14 and result["students"] == 11
    assert len(current_students(engine_settings)) == 11
    ledger = Beads(bin="bd", cwd=engine_settings.root)
    for member in ("fin-fellow", "carla-staff", "gia-scientist"):
        agent = load_agent(engine_settings.root, f"twin-{member}")
        assert agent.privacy_default == Privacy.local_only
        assert agent.runner == "hermes@local"
        charter = (engine_settings.root / f"agents/twin-{member}/charter.md").read_text()
        assert "not a student appointment" in charter
        history = [{"status": "closed", "labels": [f"twin:{member}", "twin:milestone"]}] * 3
        step = exploration_step(engine_settings, ledger, agent, history, NOW, dry_run=False)
        assert step and step["title"] == "research artifact draft"
        assert "not a student" in step["prompt_text"]
        row = fake_bd.beads()[step["bead"]]
        assert "privacy:local-only" in row["labels"]
        assert exploration_step(engine_settings, ledger, agent, [row], NOW, dry_run=True) is None
    assert sync_twins(engine_settings, dry_run=False)["created"] == []


@pytest.mark.parametrize("member", ["typo", "wen-student", "quinn-specialist"])
def test_invalid_additional_members_fail_before_scaffolding(engine_settings, member):
    (engine_settings.root / "twins.yaml").write_text(f"include_members: [{member}]\n")
    with pytest.raises(ValueError, match="unknown, former or pending"):
        sync_twins(engine_settings, dry_run=False)
    assert not (engine_settings.root / "agents").exists()


def test_staff_source_push_uses_same_bounded_transport(engine_settings):
    (engine_settings.root / "twins.yaml").write_text("include_members: [gia-scientist]\n")
    assert len(twin_members(engine_settings)) == 12
    engine_settings.host = "laptop"
    engine_settings.hosts = {
        "laptop": HostEntry(role="personal", readable=[str(engine_settings.root)]),
        "ws": HostEntry(role="orchestration", ssh="ws", drop="/mnt/data1/cube-drop"),
    }
    directory = engine_settings.state_dir() / "agents/liaison/answers/2026-09-08"
    directory.mkdir(parents=True)
    (directory / "gia-scientist.md").write_text("PRIVATE")
    preview = push_sources(engine_settings, MagicMock(spec=Beads), "cube-1")
    assert preview["bundles"][0]["person"] == "gia-scientist"
    assert "PRIVATE" not in json.dumps(preview)


def test_sync_is_private_idempotent_and_excludes_former(engine_settings):
    result = sync_twins(engine_settings)
    assert result["students"] == 11
    assert not (engine_settings.root / "agents").exists()
    assert "twin-wen-student" not in result["agents"]
    sync_twins(engine_settings, dry_run=False)
    agent = load_agent(engine_settings.root, "twin-alex-example")
    assert agent.privacy_default == Privacy.local_only
    assert agent.runner == "hermes@local"
    assert agent.tier == Tier.local
    assert sync_twins(engine_settings, dry_run=False)["created"] == []
    assert all(c.ok for c in check_agent_topics(engine_settings))
    manifest = engine_settings.state_dir() / "twins/alex-example/sources.json"
    assert manifest.stat().st_mode & 0o777 == 0o600
    data = json.loads(manifest.read_text())
    assert any(path.endswith("alex.org") for path in data["sources"])
    assert data["privacy"] == "local-only"


def test_twins_cli_dry_run(engine_repo, capsys):
    assert main(["--root", str(engine_repo), "twins", "sync", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


def test_twin_milestone_waits_for_review(engine_settings, fake_bd):
    sync_twins(engine_settings, dry_run=False)
    agent = load_agent(engine_settings.root, "twin-alex-example")
    ledger = Beads(bin="bd", cwd=engine_settings.root)
    step = exploration_step(engine_settings, ledger, agent, [], NOW, dry_run=False)
    assert step and step["bead"]
    rows = list(fake_bd.beads().values())
    assert "privacy:local-only" in rows[0]["labels"]
    assert exploration_step(engine_settings, ledger, agent, rows, NOW, dry_run=False) is None
    ledger.close(step["bead"], "review approved")
    step2 = exploration_step(
        engine_settings, ledger, agent, list(fake_bd.beads().values()), NOW, dry_run=False
    )
    assert step2 and step2["title"] == "literature synthesis"


def test_private_tool_route_cannot_fall_back_to_cloud(engine_settings):
    engine_settings.tiers["local"] = [
        TierEntry(runner="hermes", provider="local", model="fixture"),
        TierEntry(runner="claude", provider="openrouter", model="fixture"),
        TierEntry(runner="local"),
    ]
    route = choose(
        engine_settings,
        Tier.local,
        privacy=Privacy.local_only,
        needs_tools=True,
        available=lambda _: True,
    )
    assert route.runner == "hermes@local"
    with pytest.raises(Queued):
        choose(
            engine_settings,
            Tier.local,
            privacy=Privacy.local_only,
            needs_tools=True,
            available=lambda runner: runner != "hermes@local",
        )
    with pytest.raises(Refused):
        choose(
            engine_settings,
            Tier.local,
            privacy=Privacy.local_only,
            requested_runner="claude@openrouter",
            available=lambda _: True,
        )


def test_private_agent_inbox_run_has_privacy_floor(engine_settings, fake_bd):
    sync_twins(engine_settings, dry_run=False)
    report = execute(
        engine_settings,
        "student-researcher",
        agent="twin-alex-example",
        runner_name="stub",
        runner=StubRunner(result=RunResult(summary="checkpoint")),
        now=NOW,
    )
    assert report.ok, report.error
    meta = json.loads((Path(report.run_dir) / "meta.json").read_text())
    assert meta["privacy"] == "local-only"


def test_private_labelled_agent_keeps_floor(engine_settings, fake_bd):
    sync_twins(engine_settings, dry_run=False)
    fake_bd.add(
        "cube-1",
        labels=["agent:twin-alex-example"],
        description="---\nxid: fixture:private-floor\nprivacy: internal\n---\nResearch",
    )
    report = execute(
        engine_settings,
        "student-researcher",
        bead="cube-1",
        runner_name="stub",
        runner=StubRunner(result=RunResult(summary="checkpoint")),
        now=NOW,
    )
    assert report.ok, report.error
    assert json.loads((Path(report.run_dir) / "meta.json").read_text())["privacy"] == "local-only"


def test_private_interactive_talk_is_refused(engine_settings, capsys):
    sync_twins(engine_settings, dry_run=False)
    root = str(engine_settings.root)
    assert main(["--root", root, "agent", "talk", "twin-alex-example", "--dry-run"]) == 2
    assert "routed tools" in capsys.readouterr().err


def test_roster_is_not_duplicated(engine_settings):
    assert len(current_students(engine_settings)) == 11
    sync_twins(engine_settings, dry_run=False)
    charter = (engine_settings.root / "agents/twin-alex-example/charter.md").read_text()
    assert "state/twins/alex-example/sources.json" in charter
    assert "source-backed" in charter


def test_source_push_is_inbound_current_student_only(engine_settings, monkeypatch):
    engine_settings.host = "laptop"
    engine_settings.hosts = {
        "laptop": HostEntry(role="personal", readable=[str(engine_settings.root)]),
        "ws": HostEntry(role="orchestration", ssh="ws", drop="/mnt/data1/cube-drop"),
    }
    source_dir = engine_settings.state_dir() / "agents/liaison/answers/2026-09-08"
    source_dir.mkdir(parents=True)
    (source_dir / "alex-example.md").write_text("PRIVATE SOURCE MUST NEVER BE PRINTED")
    (source_dir / "wen-student.md").write_text("former member")
    ledger = MagicMock(spec=Beads)
    pushed = MagicMock(remote_path="/mnt/data1/cube-drop/cube-1/alex-example.md", sha256="abc")
    transfer = MagicMock(return_value=pushed)
    monkeypatch.setattr("cube.student.twins._push_one", transfer)
    preview = push_sources(engine_settings, ledger, "cube-1")
    assert len(preview["bundles"]) == 1
    transfer.assert_not_called()
    result = push_sources(engine_settings, ledger, "cube-1", dry_run=False)
    assert "PRIVATE SOURCE" not in json.dumps(result)
    assert "PRIVATE SOURCE" not in str(ledger.comment.call_args)
    transfer.assert_called_once()
    (source_dir / "alex-example.md").unlink()
    unrelated = engine_settings.root / "private.org"
    unrelated.write_text("UNRELATED")
    (source_dir / "alex-example.md").symlink_to(unrelated)
    with pytest.raises(ValueError, match="symlinks"):
        push_sources(engine_settings, ledger, "cube-1", dry_run=False)
    engine_settings.host = "ws"
    with pytest.raises(ValueError, match="never a ws pull"):
        push_sources(engine_settings, ledger, "cube-1", dry_run=False)


def test_twin_workday_and_independent_review_roundtrip(engine_settings, fake_bd):
    engine_settings.host = "ws"
    engine_settings.fleet_enabled = True
    sync_twins(engine_settings, dry_run=False)
    ledger = Beads(bin="bd", cwd=engine_settings.root)
    producer = AgentWorkdayPatrol(
        "twin-alex-example", now=NOW, runner=StubRunner(RunResult(summary="Fixture research plan"))
    )
    produced = producer.run(engine_settings, dry_run=False, beads=ledger)
    assert len(produced.runs) == 1 and produced.runs[0]["ok"], produced.as_dict()
    rows = list(fake_bd.beads().values())
    review = next(row for row in rows if "kind:review" in row["labels"])
    assert "agent:student-supervisor" in review["labels"]
    reviewed = AgentWorkdayPatrol(
        "student-supervisor",
        now=NOW,
        runner=StubRunner(RunResult(summary="Fixture reviewed", verdict="approve")),
    ).run(engine_settings, dry_run=False, beads=ledger)
    assert len(reviewed.runs) == 1 and reviewed.runs[0]["ok"], reviewed.as_dict()
    assert all(row["status"] == "closed" for row in fake_bd.beads().values())
