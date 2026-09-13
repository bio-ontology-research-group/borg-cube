"""`cube work`: the one call that answers what the cube is working on."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.cli import main
from cube.commands.work import build_work, work_text
from cube.engine import lease as leases
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())


def _json(capsys: pytest.CaptureFixture[str]) -> object:
    return json.loads(capsys.readouterr().out)


def _install_agent(repo: Path, name: str = "coordinator") -> None:
    (repo / "agents").mkdir(exist_ok=True)
    shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
    shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name, dirs_exist_ok=True)


def _run_meta(repo: Path, run_id: str, **fields: object) -> None:
    run_dir = repo / "runs" / "2026-09-04" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps({"run_id": run_id, **fields}), encoding="utf-8")


def test_work_reports_agents_tasks_and_running_first(
    engine_repo: Path, engine_settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo)
    fake_bd.add(
        "cube-1",
        title="Final plan v1",
        labels=["agent:coordinator", "pipeline-stage:plan1:final", "goal:cube-9", "kind:design"],
        status="in_progress",
        due="2026-09-10",
    )
    fake_bd.add(
        "cube-2",
        title="Survey the literature",
        labels=["role:senior", "goal:cube-9"],
        status="open",
        due="2026-09-01",
    )
    fake_bd.add("cube-3", title="Unlabelled chore", labels=[], status="open")
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    leases.acquire(
        engine_settings.state_dir(),
        "cube-1",
        run_id="r-1",
        role="group-leader",
        now=now - timedelta(minutes=3),
    )
    _run_meta(engine_repo, "r-1", runner="openrouter", model="z-ai/glm-5.3-flash")

    from cube.beads import Beads

    data = build_work(engine_settings, Beads(bin="bd", cwd=engine_repo, dry_run=True), now=now)

    assert [row["name"] for row in data["agents"]] == ["coordinator"]
    agent = data["agents"][0]
    assert agent["kind"] == "coordinator"
    assert agent["host"] == "ws"
    assert agent["cron"] == agent["next_tick"] == "hourly"
    assert agent["state"] == "running"
    assert agent["current"]["bead"] == "cube-1"
    assert agent["current"]["title"] == "Final plan v1"
    assert agent["current"]["run_id"] == "r-1"
    assert agent["current"]["runner"] == "openrouter"
    assert agent["current"]["model"] == "z-ai/glm-5.3-flash"
    assert [row["bead"] for row in agent["assigned"]] == ["cube-1"]
    assert agent["assigned"][0]["stage"] == "plan1:final"
    assert agent["assigned"][0]["epic"] == "cube-9"
    assert agent["inbox_unread"] == 0
    assert agent["last_workday"] is None
    assert agent["today"] == {"runs": 0, "spend_usd": 0.0}

    # cube-3 carries none of the work labels and no kind:goal, so it is not a task.
    assert [row["bead"] for row in data["tasks"]] == ["cube-1", "cube-2"]
    first, second = data["tasks"]
    assert first["running"] is True and first["owner"] == "agent:coordinator"
    assert first["stage"] == "plan1:final" and first["kind"] == "design"
    assert first["deadline"] == "2026-09-10"
    # cube-2 has the earlier deadline but is not running, so it sorts second.
    assert second["running"] is False and second["owner"] == "role:senior"


def test_work_sorts_in_progress_before_open_and_then_by_deadline(
    engine_repo: Path, engine_settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo)
    fake_bd.add(
        "cube-a", title="Later open", labels=["role:senior"], status="open", due="2026-12-01"
    )
    fake_bd.add(
        "cube-b", title="Earlier open", labels=["role:senior"], status="open", due="2026-10-01"
    )
    fake_bd.add("cube-c", title="Claimed", labels=["role:senior"], status="in_progress")

    from cube.beads import Beads

    data = build_work(engine_settings, Beads(bin="bd", cwd=engine_repo, dry_run=True))
    assert [row["bead"] for row in data["tasks"]] == ["cube-c", "cube-b", "cube-a"]


def test_work_resolves_current_by_role_when_the_agent_is_the_only_one(
    engine_repo: Path, engine_settings, fake_bd: FakeBd
) -> None:
    """An unlabelled running bead still belongs to the sole agent holding that role."""
    _install_agent(engine_repo)
    from cube.agents import load_agent

    role = load_agent(engine_repo, "coordinator").role
    fake_bd.add("cube-7", title="Unassigned run", labels=["kind:goal"], status="in_progress")
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    leases.acquire(engine_settings.state_dir(), "cube-7", run_id="r-7", role=role, now=now)

    from cube.beads import Beads

    data = build_work(engine_settings, Beads(bin="bd", cwd=engine_repo, dry_run=True), now=now)
    assert data["agents"][0]["current"]["bead"] == "cube-7"
    assert data["agents"][0]["state"] == "running"
    assert data["tasks"][0]["running"] is True


def test_work_lists_pipeline_epics_with_stage_and_next(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_agent(engine_repo)
    rc = main(
        [
            "--root",
            str(engine_repo),
            "pipeline",
            "new",
            "--title",
            "Work fixture pipeline",
            "--target",
            "2030-01-01",
            "--success",
            "the cockpit shows it",
            "--from-mail",
            "fixture mail",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0, capsys.readouterr().err
    epic = _json(capsys)
    assert isinstance(epic, dict)
    epic_id = str(epic["epic"])

    rc = main(["--root", str(engine_repo), "work", "--json"])
    assert rc == 0, capsys.readouterr().err
    data = _json(capsys)
    assert isinstance(data, dict)
    epics = {row["bead"]: row for row in data["epics"]}
    assert epic_id in epics
    assert epics[epic_id]["stage"]
    assert epics[epic_id]["next"]
    assert epics[epic_id]["open"] >= 1


def test_work_text_view_has_one_table_per_block(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_agent(engine_repo)
    fake_bd.add("cube-1", title="Final plan v1", labels=["agent:coordinator"], status="open")
    rc = main(["--root", str(engine_repo), "work"])
    assert rc == 0, capsys.readouterr().err
    text = capsys.readouterr().out
    assert "Agents\n" in text and "Tasks\n" in text and "Epics\n" in text
    assert "coordinator" in text and "cube-1" in text

    from cube.beads import Beads

    rendered = work_text(
        build_work(engine_settings, Beads(bin="bd", cwd=engine_repo, dry_run=True))
    )
    assert rendered.count("Agents") == 1


def test_work_marks_a_paused_agent(engine_repo: Path, engine_settings, fake_bd: FakeBd) -> None:
    _install_agent(engine_repo)
    marker = engine_settings.state_dir() / "agents" / "coordinator"
    marker.mkdir(parents=True, exist_ok=True)
    (marker / "PAUSED").write_text("paused\n", encoding="utf-8")

    from cube.beads import Beads

    data = build_work(engine_settings, Beads(bin="bd", cwd=engine_repo, dry_run=True))
    assert data["agents"][0]["state"] == "paused"
