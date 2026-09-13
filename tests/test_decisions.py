"""`cube decisions`, `cube question new` and `cube decide`: one answer path."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cube.agents import load_agent, resource_approval_title, resource_usage, step_decision
from cube.approvals import ApprovalStore, Intent
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.decisions import (
    DecisionError,
    decide,
    decisions_payload,
    pending_decisions,
)
from cube.engine.attention import acknowledged, build_attention
from cube.model import BeadHeader, Privacy, Provenance, RunResult
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures
from tests.test_agents import _new_agent
from tests.test_pipeline import _ledger, _new, _record_team

globals().update(fixtures())

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)


def _json(capsys: pytest.CaptureFixture[str]) -> dict:
    return json.loads(capsys.readouterr().out)


def _beads(repo: Path) -> Beads:
    return Beads(bin="bd", cwd=repo)


def _install_agent(repo: Path, name: str, *, host: str) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
    if not (repo / "agents" / name).exists():
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name)
    path = repo / "agents" / f"{name}.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(
            f"host: {host}" if line.startswith("host:") else line for line in text.splitlines()
        )
        + "\n",
        encoding="utf-8",
    )


def _header(xid: str) -> BeadHeader:
    return BeadHeader(
        xid=xid,
        provenance=[Provenance(source="runs/r-1", locator="result.json")],
        privacy=Privacy.internal,
    )


def _seed_one_of_each(repo: Path, fake_bd: FakeBd) -> None:
    fake_bd.add(
        "cube-101",
        title="Approve Ontology expert resource step: run the benchmark",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
        description="---\nxid: agent:ontology:resource:1\n---\nAgent: ontology\n"
        "Resource class: approval\nReason: IBEX use requires Robert approval\n"
        "Declared needs:\ncompute_target: ibex\n",
        created_at="2026-09-04T08:00:00+00:00",
    )
    fake_bd.add(
        "cube-102",
        title="Question from agent:ontology: which ontology release?",
        labels=["kind:question", "needs:robert", "agent:ontology"],
        description="---\nxid: question:agent:ontology:abc\n---\n"
        "Question: Which ontology release should the benchmark use?\nOptions: 2025 | 2026\n",
        created_at="2026-09-04T08:30:00+00:00",
    )
    fake_bd.add(
        "cube-103",
        title="Use the new embedding model",
        labels=["kind:proposal", "needs:robert", "agent:machine-learning"],
        description="---\nxid: agent:machine-learning:proposal:1\n---\nRationale: it is better\n",
        created_at="2026-09-04T08:45:00+00:00",
    )
    fake_bd.add(
        "cube-104",
        title="Decide recruitment of role:programmer",
        labels=["kind:request", "agent:coordinator", "pipeline-stage:recruit", "needs:robert"],
        description="---\nxid: pipe:cube-1:recruit:role-programmer:1\n---\n"
        "From: agent:ontology\nCandidate: role:programmer\nQuestion: bring them in\n",
        created_at="2026-09-04T08:50:00+00:00",
    )
    fake_bd.add(
        "cube-105",
        title="Weekly report from the ontology expert",
        labels=["kind:report", "needs:robert", "agent:ontology"],
        created_at="2026-09-04T08:55:00+00:00",
    )


def test_decisions_list_normalises_every_channel(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _seed_one_of_each(engine_repo, fake_bd)
    ApprovalStore(engine_settings.state_dir()).create(
        Intent(kind="email", person="alex-example", subject="reminder"),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor/r-9",
        run_id="r-9",
        now=NOW,
    )
    items = pending_decisions(engine_settings, _beads(engine_repo), now=NOW)
    by_id = {item["id"]: item for item in items}

    # a kind:report bead needs Robert but is not a decision
    assert "cube-105" not in by_id
    assert by_id["cube-101"]["kind"] == "permission"
    assert by_id["cube-101"]["options"] == ["yes", "no"]
    assert by_id["cube-101"]["from"] == "agent:ontology"
    assert by_id["cube-101"]["answer_command"] == ["decide", "cube-101", "--choice", "yes"]
    assert by_id["cube-102"]["kind"] == "question"
    assert by_id["cube-102"]["options"] == ["2025", "2026"]
    assert by_id["cube-102"]["question"].startswith("Which ontology release")
    assert by_id["cube-102"]["context"]["run_id"] is None
    assert by_id["cube-103"]["kind"] == "proposal"
    assert by_id["cube-103"]["options"] == ["accept", "reject", "free"]
    assert by_id["cube-104"]["kind"] == "recruit"
    approval = next(item for item in items if item["source"] == "approval")
    assert approval["kind"] == "approval"
    assert approval["options"] == ["approve", "reject"]
    assert approval["from"] == "role:advisor"
    assert approval["context"]["run_id"] == "r-9"
    # newest last
    assert [item["age"] for item in items] == sorted((item["age"] for item in items), reverse=True)


def test_decisions_cli_payload_and_answered_list(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_one_of_each(engine_repo, fake_bd)
    assert main(["--root", str(engine_repo), "decisions", "--json"]) == 0
    payload = _json(capsys)
    assert payload["answered"] == []
    assert {row["id"] for row in payload["decisions"]} == {
        "cube-101",
        "cube-102",
        "cube-103",
        "cube-104",
    }
    assert "generated" in payload


def test_question_new_is_idempotent_and_source_backed(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CUBE_RUN_ID", "r-42")
    argv = [
        "--root",
        str(engine_repo),
        "question",
        "new",
        "--from",
        "agent:ontology",
        "--text",
        "Should the benchmark use the 2026 release?",
        "--options",
        "yes,no",
        "--json",
    ]
    # Robert, 2026-09-08 (ADR-0027): without a critical flag the coordinator
    # answers; the bead never carries needs:robert and is not a pending decision.
    assert main([*argv, "--apply"]) == 0
    first = _json(capsys)
    assert first["created"] and first["bead"] and first["decider"] == "coordinator"
    bead = fake_bd.bead(first["bead"])
    assert {"kind:question", "agent:coordinator", "agent:ontology"} <= set(bead["labels"])
    assert "needs:robert" not in bead["labels"]
    assert "Question: Should the benchmark use the 2026 release?" in bead["description"]
    assert "Options: yes | no" in bead["description"]
    assert "runs/r-42" in bead["description"]
    assert bead["external_ref"] == first["xid"]

    assert main([*argv, "--apply"]) == 0
    second = _json(capsys)
    assert not second["created"] and second["bead"] == first["bead"]
    assert first["bead"] not in {
        item["id"] for item in pending_decisions(engine_settings, _beads(engine_repo))
    }

    # With --critical the question is Robert's: needs:robert, the flag, the event.
    critical = [*argv[:-1], "--critical", "security", "--json"]
    critical[critical.index("--text") + 1] = "May the sysadmin reboot borg-server tonight?"
    assert main([*critical, "--apply"]) == 0
    asked_robert = _json(capsys)
    assert asked_robert["created"] and asked_robert["decider"] == "robert"
    bead = fake_bd.bead(asked_robert["bead"])
    assert {"kind:question", "needs:robert", "critical:security"} <= set(bead["labels"])
    events = (engine_settings.state_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert '"needs_robert"' in events

    items = pending_decisions(engine_settings, _beads(engine_repo))
    asked = next(item for item in items if item["id"] == asked_robert["bead"])
    assert asked["options"] == ["yes", "no"] and asked["from"] == "agent:ontology"
    assert asked["context"]["system"] == "borg-server"

    # The coordinator never asks Robert without saying what makes it his.
    own = [*argv[:-1], "--json"]
    own[own.index("--from") + 1] = "agent:coordinator"
    assert main([*own, "--apply"]) == 2


def test_question_new_rejects_an_unknown_sender(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "--root",
            str(engine_repo),
            "question",
            "new",
            "--from",
            "somebody",
            "--text",
            "hello",
            "--apply",
        ]
    )
    assert rc == 2
    assert "--from must be" in capsys.readouterr().err


def test_decide_approval_uses_the_approval_store_path(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    store = ApprovalStore(engine_settings.state_dir())
    approval = store.create(
        Intent(kind="mattermost_dm", person="alex-example", subject="reminder"),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor/r-9",
        now=NOW,
    )
    plan = decide(
        engine_settings,
        _beads(engine_repo),
        approval.id,
        choice="approve",
        dry_run=False,
        now=NOW,
    )
    assert plan["route"] == "approval"
    assert plan["result"]["action"] == "approve"
    assert plan["result"]["result"] == "queued_for_send"
    assert store.get(approval.id).status == "approved"
    assert f"att-{approval.id}" in acknowledged(engine_settings.state_dir())


def test_decide_permission_writes_a_grant_step_decision_honours_once(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo, "ontology", host="testhost")
    agent = load_agent(engine_repo, "ontology")
    needs = {"compute_target": "ibex"}
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        resource_approval_title(agent, "run the IBEX benchmark"),
        header=_header("agent:ontology:resource:1"),
        body="Agent: ontology\nResource class: approval\n"
        "Reason: IBEX use requires Robert approval\nDeclared needs:\ncompute_target: ibex\n",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
    )
    assert bead_id
    assert not step_decision(agent, needs, resource_usage(engine_settings, agent)).allowed

    plan = decide(engine_settings, ledger, bead_id, choice="yes", dry_run=False, now=NOW)
    assert plan["route"] == "permission" and plan["closed"] == bead_id
    assert plan["grant"]["step_title"] == "run the IBEX benchmark"
    assert plan["grant"]["needs"] == needs
    assert fake_bd.bead(bead_id)["status"] == "closed"
    assert fake_bd.bead(bead_id)["close_reason"].startswith("robert: yes")

    granted = step_decision(agent, needs, resource_usage(engine_settings, agent))
    assert granted.allowed and granted.resource_class == "granted"
    # single use: the next identical step asks again
    assert not step_decision(agent, needs, resource_usage(engine_settings, agent)).allowed


def test_decide_permission_no_closes_without_a_grant(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo, "ontology", host="testhost")
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Approve the ontology expert resource step: run the IBEX benchmark",
        header=_header("agent:ontology:resource:2"),
        body="Declared needs:\ncompute_target: ibex\n",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
    )
    assert bead_id
    plan = decide(engine_settings, ledger, bead_id, choice="no", dry_run=False, now=NOW)
    assert plan["grant"] is None
    assert fake_bd.bead(bead_id)["close_reason"].startswith("robert: no")
    assert not (engine_settings.state_dir() / "agents" / "ontology" / "grants.json").exists()


def test_decide_question_reaches_the_agent_inbox(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo, "ontology", host="testhost")
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Question from agent:ontology: which release?",
        header=_header("question:agent:ontology:abc"),
        body="Question: Which ontology release should the benchmark use?\nOptions: 2025 | 2026",
        labels=["kind:question", "needs:robert", "agent:ontology"],
    )
    assert bead_id
    plan = decide(engine_settings, ledger, bead_id, choice="2026", dry_run=False, now=NOW)
    assert plan["delivery"] == "inbox:agent:ontology"
    assert plan["closed"] == bead_id
    comments = [row["text"] for row in fake_bd.bead(bead_id)["comments"]]
    assert comments == ["Robert: 2026"]
    inbox = (engine_repo / "agents" / "ontology" / "inbox.jsonl").read_text(encoding="utf-8")
    assert "Robert answered: 2026" in inbox

    log = (engine_settings.state_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    row = json.loads(log.splitlines()[-1])
    assert row["id"] == bead_id and row["choice"] == "2026" and row["kind"] == "question"
    answered = decisions_payload(engine_settings, ledger)["answered"]
    assert answered[-1]["id"] == bead_id and answered[-1]["choice"] == "2026"


def test_decide_rejects_a_choice_outside_the_options(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Question from role:senior: which release?",
        header=_header("question:role:senior:abc"),
        body="Question: which release?\nOptions: 2025 | 2026",
        labels=["kind:question", "needs:robert", "role:senior"],
    )
    assert bead_id
    with pytest.raises(DecisionError):
        decide(engine_settings, ledger, bead_id, choice="2027", dry_run=False)
    with pytest.raises(DecisionError):
        decide(engine_settings, ledger, "cube-nope", choice="yes", dry_run=False)


def test_decide_question_from_a_role_files_a_follow_up_bead(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Question from role:senior: rerun the failing test?",
        header=_header("question:role:senior:def"),
        body="Question: Should I rerun the failing test?",
        labels=["kind:question", "needs:robert", "role:senior"],
    )
    assert bead_id
    plan = decide(
        engine_settings, ledger, bead_id, text="Yes, rerun it twice.", dry_run=False, now=NOW
    )
    follow_up = fake_bd.bead(plan["delivery"].split(":", 1)[1])
    assert follow_up["title"] == f"Robert answered: {fake_bd.bead(bead_id)['title']}"
    assert {"kind:request", "role:senior", "answer:robert"} <= set(follow_up["labels"])
    assert "Robert: Yes, rerun it twice." in follow_up["description"]
    # The answer is work for the role, never a new decision for Robert.
    pending = {d["id"] for d in pending_decisions(engine_settings, ledger, now=NOW)}
    assert plan["delivery"].split(":", 1)[1] not in pending


def test_decide_proposal_accept_keeps_it_open_and_labels_it(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Use the new embedding model",
        header=_header("agent:ontology:proposal:1"),
        body="Rationale: it is better",
        labels=["kind:proposal", "needs:robert", "agent:ontology"],
    )
    assert bead_id
    _install_agent(engine_repo, "ontology", host="testhost")
    plan = decide(engine_settings, ledger, bead_id, choice="accept", dry_run=False, now=NOW)
    assert plan["closed"] is None
    bead = fake_bd.bead(bead_id)
    assert bead["status"] == "open" and "approved:robert" in bead["labels"]


def test_decide_relays_to_the_agent_host_and_records_locally(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_agent(engine_repo, "liaison", host="laptop")
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Question from agent:liaison: which mailbox?",
        header=_header("question:agent:liaison:abc"),
        body="Question: Which mailbox should I read?",
        labels=["kind:question", "needs:robert", "agent:liaison"],
    )
    assert bead_id
    rc = main(
        [
            "--root",
            str(engine_repo),
            "decide",
            bead_id,
            "--text",
            "the KAUST one",
            "--apply",
            "--json",
        ]
    )
    assert rc == 3
    payload = _json(capsys)
    assert payload["relay"] == "laptop"
    assert payload["command"][:4] == ["cube", "agent", "tell", "liaison"]
    assert "Robert answered: the KAUST one" in payload["command"]
    assert "--apply" in payload["command"]
    assert payload["decision"]["context"]["host"] == "laptop"
    # the answer is recorded here even though delivery happens on the laptop
    log = (engine_settings.state_dir() / "decisions.jsonl").read_text(encoding="utf-8")
    assert json.loads(log.splitlines()[-1])["id"] == bead_id


def test_decide_dry_run_changes_nothing(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo, "ontology", host="testhost")
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Approve the ontology expert resource step: run the IBEX benchmark",
        header=_header("agent:ontology:resource:3"),
        body="Declared needs:\ncompute_target: ibex\n",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
    )
    assert bead_id
    plan = decide(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo, dry_run=True),
        bead_id,
        choice="yes",
        dry_run=True,
        now=NOW,
    )
    assert plan["dry_run"] and plan["grant"]["step_title"] == "run the IBEX benchmark"
    assert fake_bd.bead(bead_id)["status"] == "open"
    assert not (engine_settings.state_dir() / "decisions.jsonl").exists()
    assert not (engine_settings.state_dir() / "agents" / "ontology" / "grants.json").exists()
    assert acknowledged(engine_settings.state_dir()) == {}


def test_decide_acknowledges_the_attention_item(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    _install_agent(engine_repo, "ontology", host="testhost")
    ledger = _beads(engine_repo)
    bead_id = ledger.create(
        "Question from agent:ontology: which release?",
        header=_header("question:agent:ontology:ghi"),
        body="Question: which release?",
        labels=["kind:question", "needs:robert", "agent:ontology"],
    )
    assert bead_id
    before = build_attention(engine_settings, ledger, now=NOW)
    assert f"att-{bead_id}" in {item["id"] for item in before}
    decide(engine_settings, ledger, bead_id, text="the 2026 one", dry_run=False, now=NOW)
    after = build_attention(engine_settings, ledger, now=NOW)
    assert f"att-{bead_id}" not in {item["id"] for item in after}


def test_decide_recruit_yes_and_no_go_through_pipeline_recruit(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    ledger = _ledger(engine_settings.root)
    created = _new(engine_settings, ledger)
    _record_team(engine_settings, ledger, fake_bd, created, tmp_path)
    from cube.pipeline import ask as pipeline_ask

    request = pipeline_ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="agent:protein-function",
        text="Help interpret this result",
        dry_run=False,
    )
    request_id = request["recruit_request"]
    listed = {item["id"]: item for item in pending_decisions(engine_settings, ledger, now=NOW)}
    assert listed[request_id]["kind"] == "recruit"
    assert listed[request_id]["context"]["epic"] == created["epic"]

    plan = decide(
        engine_settings, ledger, request_id, choice="yes", text="topic match", dry_run=False
    )
    assert plan["route"] == "recruit" and plan["member"] == "agent:protein-function"
    assert plan["result"]["added"]
    assert fake_bd.bead(request_id)["status"] == "closed"

    second = pipeline_ask(
        engine_settings,
        ledger,
        created["epic"],
        from_member="agent:ontology",
        to_member="role:editor",
        text="Please edit the report",
        dry_run=False,
    )
    denial = decide(
        engine_settings,
        ledger,
        second["recruit_request"],
        choice="no",
        text="not needed yet",
        dry_run=False,
    )
    assert denial["result"]["denied"]
    assert fake_bd.bead(second["recruit_request"])["status"] == "closed"


def test_grant_matches_the_step_title_and_survives_a_dry_run() -> None:
    """A grant unlocks only the step it was given for, and only on an applied run."""
    from cube.agents import matching_grant

    grants = [
        {"step_title": "IBEX benchmark", "needs": {"compute_target": "ibex"}, "used_at": None}
    ]
    needs = {"compute_target": "ibex"}
    assert matching_grant(grants, needs, "IBEX benchmark") is grants[0]
    assert matching_grant(grants, needs, "another ibex job") is None
    assert matching_grant(grants, needs) is grants[0]
    assert (
        matching_grant(grants, {"compute_target": "ibex", "gpu_hours": 1}, "IBEX benchmark") is None
    )


def test_workday_dry_run_does_not_consume_a_grant(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cube.agents import add_grant, grants_path, load_grants
    from cube.patrols.agent_workday import AgentWorkdayPatrol
    from cube.runners import StubRunner

    _new_agent(engine_repo, capsys)
    path = grants_path(engine_settings, "expert")
    add_grant(path, step_title="IBEX benchmark", needs={"compute_target": "ibex"})
    steps = [{"title": "IBEX benchmark", "needs": {"compute_target": "ibex"}}]
    runner = StubRunner(RunResult(summary="ran (source: fixture)"))
    dry = AgentWorkdayPatrol("expert", steps=steps, runner=runner).run(
        engine_settings, dry_run=True, beads=Beads(bin="bd", cwd=engine_repo, dry_run=True)
    )
    assert dry.runs and load_grants(path)[0]["used_at"] is None
    applied = AgentWorkdayPatrol("expert", steps=steps, runner=runner).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert applied.runs and load_grants(path)[0]["used_at"]
    again = AgentWorkdayPatrol("expert", steps=steps, runner=runner).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert again.blocked and not again.runs


def test_decisions_carry_the_request_body_and_fold_duplicates(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    """Robert sees the request text, and identical asks show once and close together."""
    from cube.decisions import decide, decision_body, pending_decisions

    header = "---\nxid: t\nprovenance: []\n---\n"
    body = "Rationale: needs IBEX.\nResources requested: 4 node hours.\nKill criterion: none."
    for ident in ("cube-801", "cube-802"):
        fake_bd.add(
            ident,
            title="Approve X resource step: IBEX benchmark",
            labels=["needs:robert", "resource:approval", "agent:coordinator"],
            description=header + body,
        )
    fake_bd.add(
        "cube-803",
        title="Escalation from senior: charter gap",
        labels=["needs:robert", "kind:finding", "role:senior"],
        description=header + "Finding: no active projects.\n" + "x" * 5000,
    )
    beads = Beads(bin="bd", cwd=engine_repo, dry_run=True)
    items = {item["id"]: item for item in pending_decisions(engine_settings, beads)}
    assert "cube-802" not in items and items["cube-801"]["duplicates"] == ["cube-802"]
    assert items["cube-801"]["body"] == body
    assert items["cube-803"]["body"].startswith("Finding: no active projects.")
    assert items["cube-803"]["body"].endswith("[truncated; RET opens the full bead]")
    assert decision_body("") == ""
    plan = decide(engine_settings, beads, "cube-801", choice="no", dry_run=True)
    assert plan["duplicates"] == ["cube-802"]
    # A duplicate can also be answered directly.
    assert decide(engine_settings, beads, "cube-802", choice="no", dry_run=True)["id"] == "cube-802"


def test_decision_summary_is_short_and_prefers_labelled_lines() -> None:
    from cube.decisions import SUMMARY_CHARS, decision_summary

    body = (
        "# Heading\n\nSome long preamble that goes on.\n"
        "Rationale: needs IBEX.\nResources requested: 4 node hours.\n"
        "Expected outcome: a table.\nKill criterion: none.\nMore text.\n"
    )
    summary = decision_summary(body)
    lines = summary.splitlines()
    assert lines[:2] == ["Rationale: needs IBEX.", "Resources requested: 4 node hours."]
    assert len(lines) <= 4 and "# Heading" not in summary
    assert len(decision_summary("word " * 500)) <= SUMMARY_CHARS + 4
    assert decision_summary("") == ""


def test_accepted_proposal_leaves_the_pending_list(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    from cube.decisions import pending_decisions

    fake_bd.add(
        "cube-900",
        title="Review coordinator goal decomposition and assignments",
        labels=["needs:robert", "kind:proposal", "agent:coordinator", "approved:robert"],
        description="---\nxid: p\nprovenance: []\n---\nRationale: advisory.",
    )
    beads = Beads(bin="bd", cwd=engine_repo, dry_run=True)
    assert [d["id"] for d in pending_decisions(engine_settings, beads)] == []


def test_an_approval_bead_is_a_pending_decision_with_accept_and_reject() -> None:
    from cube.decisions import _bead_kind, _options_for

    labels = ["kind:approval", "agent:sysadmin", "needs:robert", "privacy:internal"]
    assert _bead_kind(labels) == "proposal"
    assert _options_for("proposal", "") == ["accept", "reject", "free"]
