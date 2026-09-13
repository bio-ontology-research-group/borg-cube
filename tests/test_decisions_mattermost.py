"""Robert's decisions reach his Mattermost DM through hermes-ws, and his reply answers them.

Robert, 2026-09-07: "can needs:robert run through the agent that has access to
Mattermost, so I can approve (or not) on Mattermost?" The decisions patrol leaves
one inbox message per new pending decision for hermes-ws (the outbox cron posts it,
ADR-0020); `cube decide --reply` turns his DM reply into the answer.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cube.agents import read_inbox
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.decisions import (
    DecisionError,
    announce_pending,
    announced_path,
    decide_from_reply,
    decision_message,
    parse_reply,
    pending_decisions,
)
from cube.patrols import base
from cube.testing.fakebd import FakeBd
from tests.helpers_engine import fixtures
from tests.test_decisions import _install_agent, _seed_one_of_each

globals().update(fixtures())

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _ws(engine_repo: Path, engine_settings: Settings) -> None:
    _install_agent(engine_repo, "hermes-ws", host=engine_settings.host)
    _install_agent(engine_repo, "ontology", host=engine_settings.host)
    _install_agent(engine_repo, "coordinator", host=engine_settings.host)
    _install_agent(engine_repo, "machine-learning", host=engine_settings.host)


def test_pending_decisions_are_announced_once_into_the_hermes_ws_inbox(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _ws(engine_repo, engine_settings)
    _seed_one_of_each(engine_repo, fake_bd)
    beads = Beads(bin="bd", cwd=engine_repo)
    pending = {item["id"] for item in pending_decisions(engine_settings, beads, now=NOW)}
    assert {"cube-101", "cube-102", "cube-103", "cube-104"} <= pending

    dry = announce_pending(engine_settings, beads, dry_run=True, now=NOW)
    assert {row["id"] for row in dry} == pending
    assert not announced_path(engine_settings).exists()
    assert read_inbox(engine_repo, _agent(engine_repo)) == []

    rows = announce_pending(engine_settings, beads, dry_run=False, now=NOW)
    inbox = read_inbox(engine_repo, _agent(engine_repo), unread_only=True)
    assert {row["id"] for row in rows} == pending
    assert len(inbox) == len(pending)
    assert all(row["from"] == "cube" for row in inbox)
    texts = "\n".join(row["text"] for row in inbox)
    assert 'Reply "cube-101 yes" or "cube-101 no"' in texts
    assert 'Reply "cube-102 2025" or "cube-102 2026"' in texts
    assert 'Reply "cube-103 accept" or "cube-103 reject" or "cube-103: <your words>"' in texts
    assert "Decision cube-103 (proposal from agent:machine-learning, 3 day(s) old)" in texts

    # the second pass announces nothing new
    assert announce_pending(engine_settings, beads, dry_run=False, now=NOW) == []
    assert len(read_inbox(engine_repo, _agent(engine_repo), unread_only=True)) == len(pending)
    # an answered decision leaves the announced set, a reopened one would come back
    fake_bd.beads()  # ledger still readable
    recorded = json.loads(announced_path(engine_settings).read_text(encoding="utf-8"))
    assert set(recorded) == pending


def _agent(repo: Path):  # noqa: ANN202 - test helper
    from cube.agents import load_agent

    return load_agent(repo, "hermes-ws", validate_role=False)


def test_no_hermes_ws_on_this_host_means_no_announcement(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _seed_one_of_each(engine_repo, fake_bd)
    assert announce_pending(engine_settings, Beads(bin="bd", cwd=engine_repo), now=NOW) == []
    _install_agent(engine_repo, "hermes-ws", host="elsewhere")
    assert announce_pending(engine_settings, Beads(bin="bd", cwd=engine_repo), now=NOW) == []


def test_decision_message_names_the_answers() -> None:
    item = {
        "id": "apr-20260907-091845-3946",
        "kind": "approval",
        "from": "role:senior",
        "title": "file_change to exec_ibex.py",
        "summary": "Staged diff: anchor the password file default",
        "options": ["approve", "reject"],
        "age": 0,
    }
    text = decision_message(item)
    assert text.splitlines()[0] == (
        "Decision apr-20260907-091845-3946 (approval from role:senior, today): "
        "file_change to exec_ibex.py"
    )
    assert text.endswith(
        'Reply "apr-20260907-091845-3946 approve" or "apr-20260907-091845-3946 reject"'
    )


def test_parse_reply_reads_the_shapes_robert_writes(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _ws(engine_repo, engine_settings)
    _seed_one_of_each(engine_repo, fake_bd)
    beads = Beads(bin="bd", cwd=engine_repo)
    pending = {item["id"]: item for item in pending_decisions(engine_settings, beads, now=NOW)}
    assert parse_reply("cube-101 yes", pending) == {"id": "cube-101", "choice": "yes", "text": None}
    assert parse_reply("approve cube-101", pending)["choice"] == "yes"
    assert parse_reply("Cube-101: no", pending)["choice"] == "no"
    assert parse_reply("cube-102 2026", pending) == {
        "id": "cube-102",
        "choice": "2026",
        "text": None,
    }
    assert parse_reply("cube-103 accept", pending)["choice"] == "accept"
    assert parse_reply("cube-103: only on the test set first", pending) == {
        "id": "cube-103",
        "choice": None,
        "text": "only on the test set first",
    }
    assert parse_reply("reject cube-104.", pending)["choice"] == "no"
    with pytest.raises(DecisionError, match="no decision id"):
        parse_reply("approve", pending)
    with pytest.raises(DecisionError, match="not a pending decision"):
        parse_reply("cube-999 yes", pending)
    with pytest.raises(DecisionError, match="say what to do"):
        parse_reply("cube-101", pending)
    with pytest.raises(DecisionError, match="one of 2025, 2026"):
        parse_reply("cube-102 maybe later", pending)


def test_decide_from_reply_answers_and_routes_like_cube_decide(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _ws(engine_repo, engine_settings)
    _seed_one_of_each(engine_repo, fake_bd)
    beads = Beads(bin="bd", cwd=engine_repo)
    plan = decide_from_reply(engine_settings, beads, "cube-103 accept", dry_run=False, now=NOW)
    assert plan["id"] == "cube-103" and plan["answer"] == "accept" and plan["reply"]
    assert "approved:robert" in fake_bd.bead("cube-103")["labels"]
    plan = decide_from_reply(engine_settings, beads, "cube-102: 2026", dry_run=False, now=NOW)
    assert plan["answer"] == "2026"
    assert fake_bd.bead("cube-102")["status"] == "closed"
    # answered decisions are no longer pending, so the same reply is refused
    with pytest.raises(DecisionError, match="not a pending decision"):
        decide_from_reply(engine_settings, beads, "cube-102: 2026", dry_run=False, now=NOW)


def test_the_decisions_patrol_announces_what_still_waits(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _ws(engine_repo, engine_settings)
    _seed_one_of_each(engine_repo, fake_bd)
    engine_settings.decisions.policy = []
    patrol = base.make("decisions", now=NOW)
    report = base.run_patrol(
        engine_settings,
        patrol,
        today=date(2026, 9, 7),
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
        now=NOW,
    )
    assert set(report.data["announced"]) >= {"cube-101", "cube-102", "cube-103", "cube-104"}
    assert "announced on Mattermost" in report.summary
    assert len(read_inbox(engine_repo, _agent(engine_repo), unread_only=True)) >= 4


def test_cube_decide_reply_cli(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ws(engine_repo, engine_settings)
    _seed_one_of_each(engine_repo, fake_bd)
    code = main(["--root", str(engine_repo), "decide", "--reply", "cube-101 yes", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "cube-101" and payload["choice"] == "yes" and payload["dry_run"]
    assert main(["--root", str(engine_repo), "decide"]) == 2
    assert main(["--root", str(engine_repo), "decide", "--reply", "no id here"]) == 2
