"""The hello-world fleet drill: bead script, inbox routes, and the CLI shapes."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cube.agents import agent_context, append_inbox, load_agent
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.fleet_drill import (
    ANSWER_AGENT,
    ASK_AGENT,
    DRILL_LOCATOR,
    drill_xid,
    start,
)
from cube.fleet_drill import status as drill_status
from cube.model import BeadHeader
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())

DAY = date(2026, 9, 5)
ROSTER = (ASK_AGENT, ANSWER_AGENT, "genomics")


def _real_agent(repo: Path, name: str) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
    if not (repo / "agents" / name).exists():
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name)


def _fleet(repo: Path) -> None:
    for name in ("coordinator", *ROSTER):
        _real_agent(repo, name)


def _tell(repo: Path, to: str, text: str, sender: str) -> None:
    append_inbox(repo, load_agent(repo, to), text, sender=sender)


def _json(capsys: pytest.CaptureFixture[str]) -> object:
    return json.loads(capsys.readouterr().out)


def _started(engine_repo: Path, engine_settings: Settings) -> dict[str, object]:
    return start(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo),
        agents=list(ROSTER),
        today=DAY,
    )


def test_start_creates_the_drill_bead_with_the_whole_script(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fleet(engine_repo)
    data = _started(engine_repo, engine_settings)
    bead_id = str(data["bead"])
    assert data["reused"] is False and data["agents"] == list(ROSTER)
    record = fake_bd.bead(bead_id)
    assert record["labels"] == [
        "kind:task",
        "agent:coordinator",
        "drill:2026-09-05",
        "privacy:internal",
    ]
    assert record["external_ref"] == drill_xid(DAY) == "drill:2026-09-05"
    assert record["title"] == "Fleet drill 2026-09-05: hello world"
    assert record["priority"] == 2 and record["due"] == "2026-09-05"
    header = BeadHeader.parse(record["description"])
    assert header is not None and header.xid == "drill:2026-09-05"
    assert header.provenance[0].source == "cube fleet drill"
    assert header.provenance[0].locator == DRILL_LOCATOR
    body = record["description"]
    # The script quotes the real bead id, not the xid placeholder.
    for name in ROSTER:
        assert f"cube agent tell {name} 'drill {bead_id}: reply to agent:coordinator" in body, name
    assert f"cube agent tell coordinator 'drill {bead_id}: <name>: <one line>'" in body
    assert f"--from agent:{ASK_AGENT} --apply" in body
    assert f"cube agent tell {ANSWER_AGENT} 'drill {bead_id}: which embedding method" in body
    assert f"{ASK_AGENT} relays {ANSWER_AGENT}" in body
    assert f"bd comment {bead_id} " in body
    assert f"bd close {bead_id} --reason 'drill complete'" in body
    assert "This is a drill: no research content is needed" in body
    assert "keep every line under 200 characters, do not create other beads." in body


def test_second_start_reuses_the_open_drill_bead(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fleet(engine_repo)
    first = _started(engine_repo, engine_settings)
    second = _started(engine_repo, engine_settings)
    assert second["reused"] is True and second["bead"] == first["bead"]
    assert len([row for row in fake_bd.beads().values() if row["title"].startswith("Fleet")]) == 1


def _play_partially(engine_repo: Path, bead_id: str) -> None:
    """Coordinator told two agents, one replied, ontology asked, ML answered, no relay."""
    _tell(
        engine_repo, ASK_AGENT, f"drill {bead_id}: reply to agent:coordinator", "agent:coordinator"
    )
    _tell(
        engine_repo,
        ANSWER_AGENT,
        f"drill {bead_id}: reply to agent:coordinator",
        "agent:coordinator",
    )
    _tell(
        engine_repo, "coordinator", f"drill {bead_id}: {ASK_AGENT}: OWL work", f"agent:{ASK_AGENT}"
    )
    _tell(
        engine_repo, ANSWER_AGENT, f"drill {bead_id}: which embedding method", f"agent:{ASK_AGENT}"
    )
    _tell(
        engine_repo,
        ASK_AGENT,
        f"drill {bead_id}: OWL2Vec* keeps the axioms",
        f"agent:{ANSWER_AGENT}",
    )


def test_status_reports_every_missing_route_on_a_partly_played_drill(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fleet(engine_repo)
    bead_id = str(_started(engine_repo, engine_settings)["bead"])
    _play_partially(engine_repo, bead_id)
    data = drill_status(engine_settings, Beads(bin="bd", cwd=engine_repo), bead=bead_id)
    assert data["bead"] == bead_id and data["date"] == "2026-09-05"
    assert sorted(data["agents"]) == sorted(ROSTER)
    assert data["agents"][ASK_AGENT]["told"] and data["agents"][ASK_AGENT]["replied"]
    assert data["agents"][ASK_AGENT]["told_ts"] and data["agents"][ASK_AGENT]["replied_ts"]
    assert data["agents"][ANSWER_AGENT]["told"] and not data["agents"][ANSWER_AGENT]["replied"]
    assert not data["agents"]["genomics"]["told"]
    routes = data["routes"]
    assert routes["coordinator_to_agent"] == {"n": 2, "of": 3}
    assert routes["agent_to_coordinator"] == {"n": 1, "of": 3}
    assert routes["agent_to_agent"] == {"asked": True, "answered": True, "relayed": False}
    assert routes["agent_to_robert"] == {"summary_comment": False, "closed": False}
    assert data["complete"] is False
    assert data["missing"] == [
        f"{ANSWER_AGENT} has not replied to the coordinator",
        "coordinator has not told genomics",
        "genomics has not replied to the coordinator",
        f"{ASK_AGENT} has not relayed the answer to the coordinator",
        f"no drill summary comment on {bead_id}",
        f"{bead_id} is not closed",
    ]


def test_status_is_complete_once_every_route_has_run(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fleet(engine_repo)
    beads = Beads(bin="bd", cwd=engine_repo)
    bead_id = str(_started(engine_repo, engine_settings)["bead"])
    _play_partially(engine_repo, bead_id)
    _tell(engine_repo, "genomics", f"drill {bead_id}: reply to me", "agent:coordinator")
    _tell(engine_repo, "coordinator", f"drill {bead_id}: genomics: variants", "agent:genomics")
    _tell(
        engine_repo,
        "coordinator",
        f"drill {bead_id}: {ANSWER_AGENT}: models",
        f"agent:{ANSWER_AGENT}",
    )
    _tell(
        engine_repo,
        "coordinator",
        f"drill {bead_id}: {ASK_AGENT} relays {ANSWER_AGENT}: OWL2Vec*",
        f"agent:{ASK_AGENT}",
    )
    beads.comment(bead_id, "drill: " + ", ".join(ROSTER) + "; relayed OWL2Vec*")
    beads.close(bead_id, "drill complete")
    data = drill_status(engine_settings, beads, bead=bead_id)
    assert data["missing"] == [] and data["complete"] is True
    assert data["routes"]["agent_to_agent"]["relayed"] is True
    assert data["routes"]["agent_to_robert"] == {"summary_comment": True, "closed": True}


def test_status_without_a_bead_says_so(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _fleet(engine_repo)
    data = drill_status(engine_settings, Beads(bin="bd", cwd=engine_repo), day=DAY)
    assert data["bead"] is None and data["complete"] is False
    assert "no drill bead for 2026-09-05" in data["missing"]


def test_agent_context_tells_an_expert_how_to_reach_the_other_agents(
    engine_repo: Path, engine_settings: Settings
) -> None:
    _fleet(engine_repo)
    text = agent_context(engine_settings, load_agent(engine_repo, ASK_AGENT))
    assert "## Talking to other agents" in text
    assert text.index("## Asking Robert") < text.index("## Talking to other agents")
    assert f"--from agent:{ASK_AGENT} --apply" in text
    assert f"- {ANSWER_AGENT} (" in text and "- coordinator (" in text
    assert f"\n- {ASK_AGENT} (" not in text  # never lists itself
    assert "never a person, never Robert (use cube question new for him)" in text
    assert "Prefix a reply with the id of the bead or drill it answers." in text


def test_cli_fleet_drill_start_and_status_json(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _fleet(engine_repo)
    root = ["--root", str(engine_repo)]
    assert main([*root, "fleet", "drill", "start", "--agents", ",".join(ROSTER), "--json"]) == 0
    dry = _json(capsys)
    assert isinstance(dry, dict)
    assert dry["bead"] is None and dry["dry_run"] is True and dry["xid"].startswith("drill:")
    assert not [row for row in fake_bd.beads().values() if row["title"].startswith("Fleet")]

    assert (
        main([*root, "fleet", "drill", "start", "--agents", ",".join(ROSTER), "--apply", "--json"])
        == 0
    )
    created = _json(capsys)
    assert isinstance(created, dict)
    bead_id = created["bead"]
    assert bead_id and created["reused"] is False and created["agents"] == list(ROSTER)

    assert main([*root, "fleet", "drill", "status", bead_id, "--json"]) == 0
    status = _json(capsys)
    assert isinstance(status, dict)
    assert set(status) == {"bead", "date", "agents", "routes", "complete", "missing"}
    assert set(status["routes"]) == {
        "coordinator_to_agent",
        "agent_to_coordinator",
        "agent_to_agent",
        "agent_to_robert",
    }
    assert status["complete"] is False

    # The text view lists one line per agent and then the routes.
    assert main([*root, "fleet", "drill", "status", bead_id]) == 0
    text = capsys.readouterr().out
    for name in ROSTER:
        assert f"] replied  {name}" in text
    assert "coordinator to agent: 0/3" in text and "agent to Robert:" in text


def test_cli_fleet_without_a_subcommand_is_unchanged(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(engine_repo), "fleet", "--json"]) == 0
    data = _json(capsys)
    assert isinstance(data, dict) and set(data) >= {"sessions", "leases"}


def test_cli_fleet_drill_start_rejects_an_unknown_agent(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _fleet(engine_repo)
    assert main(["--root", str(engine_repo), "fleet", "drill", "start", "--agents", "nobody"]) == 2
    assert "no such agent: nobody" in capsys.readouterr().err


def test_drill_date_defaults_to_today(engine_repo: Path, engine_settings: Settings) -> None:
    assert drill_xid(datetime.now(UTC).date()).startswith("drill:")
