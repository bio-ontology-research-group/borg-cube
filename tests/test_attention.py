from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.approvals import ApprovalStore, Intent
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.engine import lease as leases
from cube.engine.attention import build_attention
from cube.engine.fleet import fleet
from cube.engine.marshal import tick
from cube.notify import append_event, make_event
from cube.runners.base import ExecResult
from tests.helpers_engine import (
    FakeBd,
    RecordingExec,
    fixtures,
)

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def test_attention_aggregates_and_sorts(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    state = engine_repo / "state"
    store = ApprovalStore(state)
    store.create(
        Intent(kind="email", person="alex-example", subject="reminder"),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor",
        now=NOW - timedelta(minutes=20),
    )
    fake_bd.add(
        "cube-233",
        title="Milestone risk: Gus",
        labels=["needs:robert"],
        created_at=(NOW - timedelta(hours=2)).isoformat(),
    )
    fake_bd.add("cube-240", title="blocked thing", labels=[], status="blocked")
    leases.acquire(
        state, "cube-5", run_id="r-dead", role="senior", pid=2**22 - 1, now=NOW - timedelta(hours=3)
    )
    append_event(
        state, make_event("error", title="senior cube-9: error: boom", run_id="r-9", bead="cube-9")
    )
    append_event(state, make_event("finished", title="fine", run_id="r-10"))
    beads = Beads(bin="bd", cwd=engine_repo, dry_run=True)
    items = build_attention(engine_settings, beads, now=NOW + timedelta(seconds=5))
    kinds = [(i["kind"], i["severity"]) for i in items]
    assert kinds[0][1] == "high" and {k for k, _ in kinds} == {
        "approval",
        "needs_robert",
        "finding",
        "session",
        "error",
    }
    assert [i["severity"] for i in items] == sorted(
        (i["severity"] for i in items), key={"high": 0, "normal": 1, "low": 2}.get
    )
    approval = next(i for i in items if i["kind"] == "approval")
    assert approval["age"] >= 1200 and approval["actions"] == ["approve", "reject", "open"]
    needs = next(i for i in items if i["kind"] == "needs_robert")
    assert needs["target"] == {"type": "bead", "id": "cube-233"} and needs["age"] >= 7200
    lease_item = next(i for i in items if i["kind"] == "session")
    assert "cube-5" in lease_item["title"]
    written = json.loads((state / "attention.json").read_text())
    assert len(written["items"]) == len(items)


def test_attention_cli_and_fleet(
    engine_repo: Path, engine_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(engine_repo), "attention", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"] == [] and "generated" in out
    state = engine_repo / "state"
    leases.acquire(
        state, "cube-1", run_id="r-1", role="programmer", pid=os.getpid(), tier="implement"
    )
    append_event(
        state, make_event("start", session="run-r-1", run_id="r-1", bead="cube-1", resume_id="sess")
    )
    ex = RecordingExec(
        {"tmux": ExecResult(0, "cube/run-r-1\t1756800000\t1\t2\nother\t1756800000\t0\t1\n", "")}
    )
    data = fleet(engine_settings, exec_fn=ex)
    assert ex.calls[0]["cmd"][:3] == ["tmux", "ls", "-F"]
    assert data["sessions"][0]["tmux"] == "cube/run-r-1" and data["sessions"][0]["kind"] == "run"
    assert (
        data["sessions"][0]["last_event"] == "start" and data["sessions"][0]["resume_id"] == "sess"
    )
    assert data["sessions"][1]["kind"] == "other"
    assert data["leases"][0]["bead"] == "cube-1" and data["leases"][0]["last_event"] == "start"
    ex = RecordingExec({"tmux": ExecResult(1, "", "no server running")})
    assert fleet(engine_settings, exec_fn=ex)["sessions"] == []
    assert main(["--root", str(engine_repo), "fleet", "--json"]) == 0
    assert "leases" in json.loads(capsys.readouterr().out)


def test_worker_respects_kill_slots_and_leases(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    state = engine_repo / "state"
    for i in range(4):
        fake_bd.add(f"cube-{i}", title=f"impl {i}", labels=["stage:implement"])
    fake_bd.add("cube-d", title="design", labels=["stage:design"])
    fake_bd.add("cube-r", title="robert", labels=["stage:design", "needs:robert"])
    fake_bd.add("cube-x", title="no role", labels=[])
    fake_bd.add("cube-p", title="python", labels=["role:marshal"])
    fake_bd.add(
        "cube-l",
        title="local-only",
        labels=["stage:implement"],
        description="---\nxid: t\nprivacy: local-only\n---\n",
    )
    leases.acquire(
        state, "cube-0", run_id="r-live", role="programmer", pid=os.getpid(), tier="implement"
    )
    beads = Beads(bin="bd", cwd=engine_repo, dry_run=True)
    dispatched: list[tuple[str, str, str]] = []

    def dispatch(role: str, bead: str, tier: str) -> int:
        dispatched.append((role, bead, tier))
        return 4242

    plan = tick(engine_settings, beads, dispatch=dispatch, now=NOW)
    assert not plan.killed
    # implement slots = 2, one taken by the live lease -> one dispatch;
    # plan slot 1 -> senior on cube-d; local-only bead -> local tier
    assert sorted(dispatched) == [
        ("programmer", "cube-1", "implement"),
        ("programmer", "cube-l", "local"),
        ("senior", "cube-d", "plan"),
    ]
    reasons = {s["bead"]: s["reason"] for s in plan.skipped if "bead" in s}
    assert reasons["cube-0"] == "leased" and reasons["cube-r"] == "needs:robert"
    assert reasons["cube-2"] == "no free implement slot" and reasons["cube-x"].startswith("no role")
    assert "python" in reasons["cube-p"]
    assert plan.slots["implement"] == {"limit": 2, "used": 2}
    audit = [json.loads(x) for x in (state / "audit.jsonl").read_text().splitlines()]
    assert [a["action"] for a in audit].count("marshal.dispatch") == 3 and audit[0][
        "child_pid"
    ] == 4242
    # dry-run plans but does not dispatch; max_dispatch caps
    dispatched.clear()
    plan = tick(engine_settings, beads, dispatch=dispatch, dry_run=True, max_dispatch=1, now=NOW)
    assert dispatched == [] and len(plan.dispatched) == 1 and plan.dispatched[0]["dry_run"]
    # KILL stops everything
    (state / "KILL").write_text("x")
    plan = tick(engine_settings, beads, dispatch=dispatch, now=NOW)
    assert plan.killed and plan.dispatched == []


def test_worker_expires_dead_leases_and_cli(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    state = engine_repo / "state"
    leases.acquire(state, "cube-9", run_id="r-dead", role="senior", pid=2**22 - 1, tier="plan")
    assert main(["--root", str(engine_repo), "worker", "--once", "--dry-run", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["last"]["expired"] == ["cube-9"] and out["last"]["dispatched"] == []
    (state / "KILL").write_text("x")
    assert main(["--root", str(engine_repo), "worker", "--once", "--json"]) == 6
    assert json.loads(capsys.readouterr().out)["last"]["killed"] is True


def test_attention_ack_dismisses_an_item(
    engine_repo: Path, engine_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """An acknowledged error leaves attention; unknown ids are rejected."""
    from cube.engine.attention import acknowledge, acknowledged

    state = engine_repo / "state"
    append_event(
        state,
        make_event("error", title="group-leader: out of usage credits", run_id="r-old"),
    )
    items = build_attention(engine_settings, None)
    assert [item["id"] for item in items] == ["att-error-r-old"]
    assert main(["--root", str(engine_repo), "attention", "ack", "att-error-r-old"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert build_attention(engine_settings, None)
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "attention",
                "ack",
                "att-error-r-old",
                "--reason",
                "Claude no longer routed",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["ack"]["reason"] == "Claude no longer routed"
    assert build_attention(engine_settings, None) == []
    assert "att-error-r-old" in acknowledged(state)
    assert main(["--root", str(engine_repo), "attention", "ack", "att-nope", "--apply"]) == 2
    acknowledge(state, "att-stale", now=NOW - timedelta(days=8))
    acknowledge(state, "att-new", now=NOW)
    assert set(acknowledged(state)) >= {"att-new"} and "att-stale" not in acknowledged(state)
