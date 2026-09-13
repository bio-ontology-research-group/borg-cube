from __future__ import annotations

import json
import re
import shlex
import shutil
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cube.agents import (
    AgentError,
    append_inbox,
    file_proposal,
    load_agent,
    read_inbox,
    resource_usage,
)
from cube.beads import Beads
from cube.cli import main
from cube.doctor import check_agents, check_host
from cube.engine.marshal import role_for, tick
from cube.model import BeadHeader, Privacy, Provenance, RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.roles import load_all
from cube.runners import StubRunner
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())


def _json(capsys: pytest.CaptureFixture[str]) -> object:
    return json.loads(capsys.readouterr().out)


def _at_home(repo: Path, name: str, host: str) -> None:
    """Move a fixture agent to ``host`` (the marshal runs an agent only where it lives)."""
    path = repo / "agents" / f"{name}.yaml"
    lines = [
        f"host: {host}" if line.startswith("host:") else line
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _new_agent(repo: Path, capsys: pytest.CaptureFixture[str], name: str = "expert") -> None:
    rc = main(
        [
            "--root",
            str(repo),
            "agent",
            "new",
            name,
            "--kind",
            "expert",
            "--title",
            "Fixture expert",
            "--topic",
            "applied-ontology",
            "--role",
            "senior",
            "--runtime",
            "claude",
            "--apply",
        ]
    )
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()


def _install_liaison(repo: Path) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "liaison"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name)


def _configure_laptop(repo: Path) -> None:
    path = repo / "cube.yaml"
    text = path.read_text(encoding="utf-8").replace("host: testhost", "host: laptop")
    path.write_text(
        text
        + "hosts:\n"
        + "  ws: {role: orchestration, ssh: ws}\n"
        + "  laptop:\n"
        + "    role: personal\n"
        + "    hostname: lc-dell\n"
        + "    ssh: null\n"
        + "    readable: [~/Documents/papers, ~/Public/software]\n"
        + "    unreadable: [~/pa, ~/Public/software/pa, ~/org]\n",
        encoding="utf-8",
    )


def _shell_shim(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _mail_shim(fake_bd: FakeBd, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    log = fake_bd.dir.parent / "notmuch.log"
    monkeypatch.setenv("NOTMUCH_FIXTURE_LOG", str(log))
    search = json.dumps([{"id": "fixture-message"}])
    shown = json.dumps(
        [
            [
                [
                    {
                        "id": "fixture-message",
                        "headers": {
                            "From": "Robert Hoehndorf <robert.hoehndorf@kaust.edu.sa>",
                            "Message-ID": "<fixture-message@local>",
                        },
                        "body": [{"content-type": "text/plain", "content": body}],
                    },
                    [],
                ]
            ]
        ]
    )
    _shell_shim(
        fake_bd.dir / "notmuch",
        'printf \'%s\\n\' "$*" >> "$NOTMUCH_FIXTURE_LOG"\n'
        + 'if [ "$1" = search ]; then\n'
        + f"  printf '%s\\n' {shlex.quote(search)}\n"
        + "else\n"
        + f"  printf '%s\\n' {shlex.quote(shown)}\n"
        + "fi\n",
    )
    return log


def _ssh_shim(fake_bd: FakeBd, monkeypatch: pytest.MonkeyPatch, *, reachable: bool = True) -> Path:
    log = fake_bd.dir.parent / "ssh.log"
    monkeypatch.setenv("SSH_FIXTURE_LOG", str(log))
    ending = (
        "printf '%s\\n' '{\"delivered\": true}'\n"
        if reachable
        else "printf '%s\\n' 'fixture peer unreachable' >&2\nexit 255\n"
    )
    _shell_shim(
        fake_bd.dir / "ssh",
        'printf \'%s\\n\' "$*" >> "$SSH_FIXTURE_LOG"\n' + ending,
    )
    return log


def _request_description() -> str:
    return (
        BeadHeader(
            xid="fixture:liaison-request",
            provenance=[Provenance(source="fixture", locator="request")],
            privacy=Privacy.internal,
        ).render()
        + "\nQuestion: Check the ideas in an email I just sent\n"
    )


def test_agent_new_validation_doctor_and_talk_dry_run(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    assert (engine_repo / "agents" / "expert.yaml").exists()
    assert (engine_repo / "agents" / "expert" / "memory" / "journal.md").exists()
    agent = load_agent(engine_repo, "expert")
    assert (
        agent.role == "senior"
        and check_agents(
            __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)
        )[0].ok
    )

    assert main(["--root", str(engine_repo), "agent", "talk", "expert", "--json"]) == 0
    talk = _json(capsys)
    assert isinstance(talk, dict)
    assert talk["dry_run"] and talk["command"][:2] == ["tmux", "new-session"]
    assert str(talk["context_file"]).endswith("state/agents/expert/context.md")
    assert all(
        section in talk["context"]
        for section in ("## Charter", "## Doctrine", "## Skills", "## Unread inbox")
    )

    text = (engine_repo / "agents" / "expert.yaml").read_text(encoding="utf-8")
    (engine_repo / "agents" / "expert.yaml").write_text(
        text.replace("tier: plan", "tier: implement"), encoding="utf-8"
    )
    assert not check_agents(
        __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)
    )[0].ok


def test_tell_live_session_marks_delivery(
    engine_repo: Path,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _new_agent(engine_repo, capsys)
    sent: list[list[str]] = []

    def tmux(command: list[str]) -> subprocess.CompletedProcess[str]:
        sent.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("cube.commands.agent._tmux", tmux)
    monkeypatch.setattr("cube.commands.agent.TELL_SUBMIT_DELAY", 0)
    assert (
        main(["--root", str(engine_repo), "agent", "tell", "expert", "hello", "--apply", "--json"])
        == 0
    )
    data = _json(capsys)
    assert isinstance(data, dict) and data["delivery"]["delivered"]
    # literal text first, Enter as a separate keystroke so Claude submits it
    assert sent[-2][1:] == ["send-keys", "-t", sent[-2][3], "-l", "hello"]
    assert sent[-1][1:] == ["send-keys", "-t", sent[-1][3], "Enter"]
    inbox = (engine_repo / "agents" / "expert" / "inbox.jsonl").read_text(encoding="utf-8")
    assert json.loads(inbox)["text"] == "hello"

    # --redeliver types the same message again but never duplicates the inbox
    before = len(sent)
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "agent",
                "tell",
                "expert",
                "hello",
                "--apply",
                "--redeliver",
                "--json",
            ]
        )
        == 0
    )
    data = _json(capsys)
    assert isinstance(data, dict) and data["delivery"]["delivered"]
    assert len(sent) == before + 3  # has-session, text, Enter
    inbox = (engine_repo / "agents" / "expert" / "inbox.jsonl").read_text(encoding="utf-8")
    assert inbox.count("\n") == 1


def test_workday_enforces_resources_memory_and_proposals(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    path = engine_repo / "agents" / "expert.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "node005_gpu_hours_per_day: 0", "node005_gpu_hours_per_day: 1"
    )
    # This test exercises a full three-step day, not the one-step hourly tick.
    text = re.sub(r"cron: hourly", 'cron: "07:00"', text)
    text = re.sub(r"^\s*max_runs_per_tick: \d+\n", "", text, flags=re.M)
    text = re.sub(r"max_runs: \d+", "max_runs: 3", text)
    path.write_text(text, encoding="utf-8")
    agent = load_agent(engine_repo, "expert")
    append_inbox(engine_repo, agent, "please investigate")
    steps = [
        {"title": "IBEX analysis", "needs": {"compute_target": "ibex"}},
        {
            "title": "local experiment",
            "needs": {"compute_target": "node005", "gpu_hours": 1},
            "reading": [
                {"identifier": "10.1000/test", "note": "fixture reference", "source": "Crossref"}
            ],
            "proposal": {
                "title": "Test a local model",
                "rationale": "A bounded comparison is warranted.",
                "citations": ["10.1000/test"],
                "resources": "one GPU hour on node005",
                "expected_outcome": "a reproducible comparison",
                "kill_criterion": "stop if the baseline is not exceeded",
            },
        },
        {"title": "too much GPU", "needs": {"compute_target": "node005", "gpu_hours": 1}},
    ]
    patrol = AgentWorkdayPatrol(
        "expert",
        steps=steps,
        runner=StubRunner(RunResult(summary="finished (source: fixture)")),
        now=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    result = patrol.run(engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo))
    assert result.inbox_read == 1 and result.resources["gpu_hours"] == 1
    assert len(result.runs) == 1 and len(result.blocked) == 2 and result.proposals
    assert (
        resource_usage(engine_settings, agent, now=datetime(2026, 9, 2, tzinfo=UTC))["gpu_hours"]
        == 1
    )
    journal = (engine_repo / "agents" / "expert" / "memory" / "journal.md").read_text()
    assert "Sources:" in journal and "agents/expert.yaml" in journal
    assert (
        "10.1000/test" in (engine_repo / "agents" / "expert" / "memory" / "reading.md").read_text()
    )
    assert any(call[0] == "remember" and "agent:expert" in call[1] for call in fake_bd.calls())
    with pytest.raises(AgentError, match="kill_criterion"):
        file_proposal(
            Beads(bin="bd", cwd=engine_repo),
            agent,
            {
                "title": "incomplete",
                "rationale": "x",
                "citations": ["10.1000/test"],
                "resources": "none",
                "expected_outcome": "x",
            },
        )


def test_marshal_uses_agent_role_and_status_has_agents(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    _at_home(engine_repo, "expert", engine_settings.host)
    roles, _ = load_all(engine_repo)
    assert (
        role_for({"labels": ["agent:expert", "stage:implement"]}, roles, root=engine_repo)
        == "senior"
    )
    fake_bd.add(
        "agent-work",
        title="agent work",
        labels=["agent:expert", "tier:implement"],
        description="---\nxid: fixture:agent-work\nprivacy: internal\n---\n",
    )
    plan = tick(engine_settings, Beads(bin="bd", cwd=engine_repo), dry_run=True)
    assert plan.dispatched == [
        {"bead": "agent-work", "role": "senior", "tier": "plan", "dry_run": True}
    ]
    assert main(["--root", str(engine_repo), "status", "--json"]) == 0
    status = _json(capsys)
    assert isinstance(status, dict)
    assert status["agents"] == [
        {
            "name": "expert",
            "kind": "expert",
            "state": "idle",
            "pending_proposals": 0,
            "inbox_unread": 0,
        }
    ]


def test_worker_filters_explicit_host_labels(
    engine_repo: Path, engine_settings, fake_bd: FakeBd
) -> None:
    for bead_id, labels in (
        ("laptop-work", ["role:senior", "host:laptop"]),
        ("ws-work", ["role:senior", "host:ws"]),
        ("unlabelled-work", ["role:senior"]),
    ):
        fake_bd.add(
            bead_id,
            title=bead_id,
            labels=labels,
            description=BeadHeader(xid=f"fixture:{bead_id}").render(),
        )

    plan = tick(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo),
        dry_run=True,
        host="laptop",
        slots={"plan": 3, "implement": 0, "bulk": 0, "local": 0},
    )

    # A thin client plays only the beads that name it (Robert 2026-09-05: the
    # laptop worker had started the coordinator's plan bead on the laptop).
    assert {row["bead"] for row in plan.dispatched} == {"laptop-work"}
    reasons = {row["bead"]: row["reason"] for row in plan.skipped}
    assert reasons["ws-work"] == "host"
    assert reasons["unlabelled-work"] == "not for laptop"

    plan = tick(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo),
        dry_run=True,
        host=engine_settings.host,
        slots={"plan": 3, "implement": 0, "bulk": 0, "local": 0},
    )
    assert {row["bead"] for row in plan.dispatched} == {"unlabelled-work"}


def test_marshal_runs_an_agent_bead_only_where_the_agent_lives(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    _at_home(engine_repo, "expert", engine_settings.host)
    fake_bd.add(
        "expert-work",
        title="expert-work",
        labels=["role:senior", "agent:expert"],
        description=BeadHeader(xid="fixture:expert-work").render(),
    )
    away = tick(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo),
        dry_run=True,
        host="laptop",
        slots={"plan": 3, "implement": 0, "bulk": 0, "local": 0},
    )
    assert away.dispatched == []
    reasons = {row["bead"]: row["reason"] for row in away.skipped}
    assert reasons["expert-work"] == f"agent:expert lives on {engine_settings.host}"
    home = tick(
        engine_settings,
        Beads(bin="bd", cwd=engine_repo),
        dry_run=True,
        host=engine_settings.host,
        slots={"plan": 3, "implement": 0, "bulk": 0, "local": 0},
    )
    assert [row["bead"] for row in home.dispatched] == ["expert-work"]


def test_request_uses_agent_host_and_agent_list_exposes_it(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_liaison(engine_repo)

    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "request",
                "liaison",
                "Check the ideas in an email I just sent",
                "--due",
                "2026-09-04",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = _json(capsys)
    bead = fake_bd.bead(str(payload["bead"]))
    assert payload["host"] == "laptop"
    assert {"kind:request", "agent:liaison", "host:laptop", "privacy:internal"} <= set(
        bead["labels"]
    )
    header = BeadHeader.parse(bead["description"])
    assert header is not None and header.deadline == datetime(2026, 9, 4).date()

    assert main(["--root", str(engine_repo), "agent", "list", "--json"]) == 0
    rows = _json(capsys)
    assert isinstance(rows, list)
    assert {row["name"]: row["host"] for row in rows} == {
        "coordinator": "ws",
        "liaison": "laptop",
    }


def test_liaison_answers_mail_fixture_with_message_id_and_closes(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_liaison(engine_repo)
    _configure_laptop(engine_repo)
    mail_log = _mail_shim(
        fake_bd,
        monkeypatch,
        "Here are my ideas:\n\n1. Compare the two ontology mappings.\n\n"
        "2. Add a fixture-backed regression test.",
    )
    ssh_log = _ssh_shim(fake_bd, monkeypatch)
    fake_bd.add(
        "liaison-request",
        title="Email ideas",
        labels=[
            "kind:request",
            "agent:liaison",
            "host:laptop",
            "privacy:internal",
            "approved:robert",
        ],
        description=_request_description(),
    )
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)

    result = AgentWorkdayPatrol("liaison").run(
        settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )

    stored = fake_bd.bead("liaison-request")
    assert stored["status"] == "closed"
    assert "Compare the two ontology mappings" in stored["description"]
    assert "Add a fixture-backed regression test" in stored["description"]
    assert "<fixture-message@local>" in stored["description"]
    assert "paragraph: 2" in stored["description"] and "paragraph: 3" in stored["description"]
    assert "Here are my ideas" not in stored["description"]
    assert result.answers[0]["privacy"] == "internal"
    notmuch_calls = mail_log.read_text(encoding="utf-8")
    assert "search --format=json --sort=newest-first" in notmuch_calls
    assert "from:robert.hoehndorf@kaust.edu.sa" in notmuch_calls
    assert "show --format=json --body=true id:fixture-message" in notmuch_calls
    assert "ConnectTimeout=10" in ssh_log.read_text(encoding="utf-8")
    assert "agent tell coordinator" in ssh_log.read_text(encoding="utf-8")


def test_liaison_collects_links_identifiers_and_matching_local_repositories(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_liaison(engine_repo)
    _configure_laptop(engine_repo)
    software = engine_repo / "software"
    for name in ("PhysioMap", "mOWL", "time"):
        (software / name).mkdir(parents=True)
    git = software / "PhysioMap" / ".git"
    git.mkdir()
    (git / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:borg/PhysioMap.git\n',
        encoding="utf-8",
    )
    config = engine_repo / "cube.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "    ssh: null\n",
            f"    ssh: null\n    software_dirs: [{software}]\n",
        ),
        encoding="utf-8",
    )
    _mail_shim(
        fake_bd,
        monkeypatch,
        "Use https://github.com/borg/PhysioMap, DOI 10.1234/Fixture.1, "
        "and https://pubmed.ncbi.nlm.nih.gov/12345678/.\n\n"
        "Compare PhysioMap with mOWL. Time is only a common word.",
    )
    _ssh_shim(fake_bd, monkeypatch)
    fake_bd.add(
        "collect-request",
        title="Collect mail",
        labels=[
            "kind:request",
            "agent:liaison",
            "host:laptop",
            "privacy:internal",
            "approved:robert",
        ],
        description=(
            BeadHeader(
                xid="fixture:collect-request",
                provenance=[Provenance(source="fixture", locator="request")],
                privacy=Privacy.internal,
            ).render()
            + "\nQuestion: Collect the papers and code from the mail I sent\n"
        ),
    )
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)

    result = AgentWorkdayPatrol("liaison").run(
        settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )

    answer = result.answers[0]
    assert {item["kind"] for item in answer["links"]} >= {"github", "doi", "pubmed"}
    assert answer["identifiers"] == {
        "dois": ["10.1234/Fixture.1"],
        "arxiv": [],
        "pmids": ["12345678"],
    }
    repos = {item["name"]: item for item in answer["local_repos"]}
    assert set(repos) == {"PhysioMap", "mOWL"}
    assert repos["PhysioMap"]["remote"] == "git@github.com:borg/PhysioMap.git"
    assert repos["mOWL"]["remote"] is None
    stored = fake_bd.bead("collect-request")["description"]
    assert "https://doi.org/10.1234/Fixture.1" in stored
    assert str(software / "PhysioMap") in stored

    from cube.agents.liaison import subject_words

    assert subject_words(
        "Collect the email I sent about Alpha Project: extract the ideas, list the papers "
        "and the code I already have (links, DOIs, local repositories)"
    ) == ["alpha", "project"]


def test_liaison_keeps_grade_answer_local_and_only_points_from_bead(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_liaison(engine_repo)
    _configure_laptop(engine_repo)
    grade_sentence = "The student's grade should be reviewed before the meeting."
    _mail_shim(fake_bd, monkeypatch, "Here are my ideas:\n\n" + grade_sentence)
    _ssh_shim(fake_bd, monkeypatch, reachable=False)
    fake_bd.add(
        "private-request",
        title="Email ideas",
        labels=[
            "kind:request",
            "agent:liaison",
            "host:laptop",
            "privacy:internal",
            "approved:robert",
        ],
        description=_request_description(),
    )
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)

    result = AgentWorkdayPatrol("liaison").run(
        settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )

    answer = result.answers[0]
    stored = fake_bd.bead("private-request")
    assert stored["status"] == "closed"
    assert "privacy: local-only" in stored["description"]
    assert "privacy:local-only" in stored["labels"]
    assert "privacy:internal" not in stored["labels"]
    assert grade_sentence not in stored["description"]
    assert "ideas" not in answer and answer["relay"]["queued"]
    pointer = engine_repo / str(answer["pointer"])
    assert pointer.is_file() and grade_sentence in pointer.read_text(encoding="utf-8")
    assert grade_sentence not in (engine_repo / "state" / "events.jsonl").read_text(
        encoding="utf-8"
    )


def test_relay_degrades_when_peer_is_unreachable(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_laptop(engine_repo)
    ssh_log = _ssh_shim(fake_bd, monkeypatch, reachable=False)

    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "relay",
                "--json",
                "ws",
                "agent",
                "tell",
                "coordinator",
                "answer ready",
                "--apply",
            ]
        )
        == 0
    )
    payload = _json(capsys)
    assert payload["reachable"] is False and payload["queued"] is True
    command = ssh_log.read_text(encoding="utf-8")
    assert "ConnectTimeout=10" in command and "BatchMode=yes" in command
    # Non-interactive ssh has no login PATH: the remote command must carry the
    # same PATH the systemd units use so bd and the runners resolve.
    assert "PATH=$HOME/.local/bin:" in command
    assert command.index("PATH=$HOME/.local/bin:") < command.index("/.venv/bin/cube")


def test_status_includes_peer_payload(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_laptop(engine_repo)
    log = fake_bd.dir.parent / "ssh.log"
    monkeypatch.setenv("SSH_FIXTURE_LOG", str(log))
    _shell_shim(
        fake_bd.dir / "ssh",
        "printf '%s\\n' \"$*\" >> \"$SSH_FIXTURE_LOG\"\nprintf '%s\\n' abc123 2\n",
    )

    assert main(["--root", str(engine_repo), "status", "--json"]) == 0
    payload = _json(capsys)
    assert payload["host"] == "laptop"
    assert payload["peers"] == [
        {"name": "ws", "reachable": True, "sha": "abc123", "lag_commits": 2, "route": "ssh"}
    ]


def test_peer_without_ssh_route_is_pull_only_not_unreachable(engine_repo: Path) -> None:
    from cube.doctor import check_host
    from cube.hosts import probe_peer

    _configure_laptop(engine_repo)
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)
    peer = probe_peer("laptop", settings.hosts["laptop"], engine_repo)
    assert peer.route == "none" and peer.reachable is False
    settings = settings.model_copy(update={"host": "ws"})
    checks = {check.name: check for check in check_host(settings)}
    assert checks["host:peer:laptop"].ok
    assert checks["host:peer:laptop"].severity == "info"
    assert "pulls and relays" in checks["host:peer:laptop"].detail


def test_doctor_matches_current_host_and_warns_for_unreachable_peer(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_laptop(engine_repo)
    _ssh_shim(fake_bd, monkeypatch, reachable=False)
    monkeypatch.setattr("cube.doctor.os.uname", lambda: SimpleNamespace(nodename="lc-dell"))
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)

    checks = {check.name: check for check in check_host(settings)}

    assert checks["host:configured"].ok
    assert not checks["host:peer:ws"].ok
    assert checks["host:peer:ws"].severity == "warn"
    assert "next Beads sync" in checks["host:peer:ws"].detail


def test_agent_talk_attach_starts_session_then_execs_tmux_attach(
    engine_repo: Path,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cube.commands import agent as agent_cmd

    _new_agent(engine_repo, capsys)
    tmux_calls: list[list[str]] = []
    execs: list[list[str]] = []

    def fake_tmux(command: list[str]) -> SimpleNamespace:
        tmux_calls.append(command)
        # has-session says "not live" until new-session has run
        live = any(c[1] == "new-session" for c in tmux_calls)
        return SimpleNamespace(
            returncode=0 if command[1] != "has-session" or live else 1, stderr=""
        )

    monkeypatch.setattr(agent_cmd, "_tmux", fake_tmux)
    monkeypatch.setattr(agent_cmd.os, "execvp", lambda prog, argv: execs.append(list(argv)))

    assert main(["--root", str(engine_repo), "agent", "talk", "expert", "--apply", "--attach"]) == 0
    assert [c[1] for c in tmux_calls] == ["has-session", "new-session"]
    assert execs == [["tmux", "attach-session", "-t", "cube/agent-expert"]]

    # dry run never execs and reports the attach command it would use
    execs.clear()
    capsys.readouterr()
    assert main(["--root", str(engine_repo), "agent", "talk", "expert", "--attach", "--json"]) == 0
    talk = _json(capsys)
    assert isinstance(talk, dict)
    assert talk["attach_command"] == ["tmux", "attach-session", "-t", "cube/agent-expert"]
    assert execs == []


def test_workday_keeps_inbox_unread_when_no_step_succeeds(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """A model outage must not swallow Robert's message: the inbox stays unread."""
    _new_agent(engine_repo, capsys)
    agent = load_agent(engine_repo, "expert")
    append_inbox(engine_repo, agent, "please read this")
    steps = [{"title": "answer the inbox", "needs": {"compute_target": "ws"}}]
    failing = AgentWorkdayPatrol(
        "expert",
        steps=steps,
        runner=StubRunner(fail="out of usage credits"),
        now=datetime(2026, 9, 4, 4, 20, tzinfo=UTC),
    )
    result = failing.run(engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo))
    assert result.inbox_read == 1 and not any(run["ok"] for run in result.runs)
    assert any(item.get("step") == "inbox" for item in result.blocked)
    assert len(read_inbox(engine_repo, agent, unread_only=True)) == 1

    ok = AgentWorkdayPatrol(
        "expert",
        steps=steps,
        runner=StubRunner(RunResult(summary="answered (source: inbox)")),
        now=datetime(2026, 9, 4, 5, 0, tzinfo=UTC),
    )
    ok.run(engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo))
    assert read_inbox(engine_repo, agent, unread_only=True) == []


def test_hourly_agent_idles_without_work_and_answers_inbox_per_tick(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 24/7 agent checks its inbox every tick, spends nothing when idle."""
    from cube.agents import last_workday_start

    _new_agent(engine_repo, capsys)
    path = engine_repo / "agents" / "expert.yaml"
    text = path.read_text(encoding="utf-8")
    assert "cron: hourly" in text  # agents work 24/7 by default
    text = re.sub(r"max_runs: \d+", "max_runs: 48", text)
    text = re.sub(r"max_runs_per_tick: \d+", "max_runs_per_tick: 1", text)
    path.write_text(text, encoding="utf-8")
    agent = load_agent(engine_repo, "expert")
    assert agent.workday.hourly and agent.workday.runs_per_tick == 1
    runner = StubRunner(RunResult(summary="answered (source: inbox)"))
    tick = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    idle = AgentWorkdayPatrol("expert", runner=runner, now=tick).run(
        engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert idle.state == "idle" and not idle.runs and not runner.calls
    assert last_workday_start(engine_settings, agent) == tick
    append_inbox(engine_repo, agent, "status please")
    busy = AgentWorkdayPatrol(
        "expert", runner=runner, now=datetime(2026, 9, 4, 13, 0, tzinfo=UTC)
    ).run(engine_settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo))
    assert busy.state == "finished" and len(busy.runs) == 1 and busy.inbox_read == 1
    assert read_inbox(engine_repo, agent, unread_only=True) == []


def test_agent_inbox_lists_reads_now_and_relays_to_the_agent_host(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """`cube agent inbox` lists, plans, applies an inbox-only pass, and relays off-host."""
    _new_agent(engine_repo, capsys)
    # The fixture host is testhost; make the agent local so the pass runs here.
    path = engine_repo / "agents" / "expert.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("host: ws", "host: testhost")
        .replace("max_runs_per_tick: 1", "max_runs_per_tick: 3"),
        encoding="utf-8",
    )
    agent = load_agent(engine_repo, "expert")
    fake_bd.add("cube-11", title="Named in the message", labels=["agent:expert"], status="open")
    fake_bd.add("cube-12", title="Not named", labels=["agent:expert"], status="open")
    append_inbox(engine_repo, agent, "please finish cube-11 today")

    rc = main(["--root", str(engine_repo), "agent", "inbox", "expert", "--json"])
    assert rc == 0, capsys.readouterr().err
    listed = _json(capsys)
    assert isinstance(listed, dict)
    assert listed["unread"] == 1 and len(listed["messages"]) == 1
    assert listed["workday"] is None

    rc = main(
        ["--root", str(engine_repo), "agent", "inbox", "expert", "--now", "--dry-run", "--json"]
    )
    assert rc == 0, capsys.readouterr().err
    plan = _json(capsys)
    assert isinstance(plan, dict)
    assert plan["dry_run"] is True
    assert plan["workday"]["dry_run"] is True
    assert len(read_inbox(engine_repo, agent, unread_only=True)) == 1

    rc = main(
        [
            "--root",
            str(engine_repo),
            "agent",
            "inbox",
            "expert",
            "--now",
            "--runner",
            "stub",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0, capsys.readouterr().err
    applied = _json(capsys)
    assert isinstance(applied, dict)
    workday = applied["workday"]
    # The inbox step plus the one assigned bead the message names, and no
    # default reading step and no bead the message did not mention.
    assert workday["state"] == "finished"
    assert len(workday["runs"]) == 2
    assert [run["bead"] for run in workday["runs"]] == [None, "cube-11"]
    assert read_inbox(engine_repo, agent, unread_only=True) == []

    path.write_text(
        path.read_text(encoding="utf-8").replace("host: testhost", "host: ws"), encoding="utf-8"
    )
    rc = main(["--root", str(engine_repo), "agent", "inbox", "expert", "--now", "--json"])
    assert rc == 3
    relay = _json(capsys)
    assert isinstance(relay, dict)
    assert relay["relay"] == "ws"
    assert relay["command"] == ["cube", "agent", "inbox", "expert", "--now", "--dry-run", "--json"]


def test_agent_inbox_pass_is_idle_without_unread_mail(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """An inbox-only pass never falls back to the default reading step."""
    _new_agent(engine_repo, capsys)
    path = engine_repo / "agents" / "expert.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("host: ws", "host: testhost"), encoding="utf-8"
    )
    rc = main(
        [
            "--root",
            str(engine_repo),
            "agent",
            "inbox",
            "expert",
            "--now",
            "--runner",
            "stub",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0, capsys.readouterr().err
    data = _json(capsys)
    assert isinstance(data, dict)
    assert data["workday"]["state"] == "idle"
    assert data["workday"]["runs"] == []


def test_zero_spend_allowance_defers_to_the_global_budget(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """spend_usd_per_day 0 no longer asks Robert for every step once spend was measured."""
    from cube.agents import step_decision

    _new_agent(engine_repo, capsys)
    agent = load_agent(engine_repo, "expert")
    assert agent.resources.spend_usd_per_day == 0
    usage = {"gpu_hours": 0.0, "runs": 3, "spend_usd": 0.42}
    assert step_decision(agent, {"compute_target": "ws"}, usage).allowed
    assert step_decision(agent, {"compute_target": "ws", "spend_usd": 2}, usage).allowed
    limited = agent.model_copy(
        update={"resources": agent.resources.model_copy(update={"spend_usd_per_day": 1.0})}
    )
    assert step_decision(limited, {"compute_target": "ws"}, usage).allowed
    blocked = step_decision(limited, {"compute_target": "ws", "spend_usd": 2}, usage)
    assert not blocked.allowed and blocked.resource_class == "approval"


def test_workday_never_works_on_beads_waiting_for_robert(
    engine_repo: Path, engine_settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _new_agent(engine_repo, capsys)
    fake_bd.add(
        "cube-77",
        title="Review expert goal decomposition",
        labels=["agent:expert", "kind:proposal", "needs:robert"],
    )
    fake_bd.add("cube-78", title="real work", labels=["agent:expert", "kind:design"])
    runner = StubRunner(RunResult(summary="done (source: fixture)"))
    result = AgentWorkdayPatrol("expert", runner=runner).run(
        engine_settings, dry_run=True, beads=Beads(bin="bd", cwd=engine_repo, dry_run=True)
    )
    assert result.assigned_beads == ["cube-78"]


def test_inbox_drain_previews_until_explicit_id_acknowledgement(
    engine_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Previewing preserves unread messages until their delivery is acknowledged."""
    from cube.agents import mark_inbox_read

    _install_liaison(engine_repo)
    _at_home(engine_repo, "coordinator", "testhost")
    root = str(engine_repo)
    tell = ["--root", root, "agent", "tell", "coordinator", "reply for Robert"]
    assert main([*tell, "--from", "sysadmin", "--apply"]) == 0
    capsys.readouterr()
    drain = ["--root", root, "agent", "inbox", "coordinator", "--drain", "--apply"]
    assert main(drain) == 0
    out = capsys.readouterr().out
    assert "sysadmin: reply for Robert" in out
    assert main(drain) == 0
    assert "sysadmin: reply for Robert" in capsys.readouterr().out
    assert main(["--root", root, "agent", "inbox", "coordinator", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["unread"] == 1
    mark_inbox_read(
        engine_repo, load_agent(engine_repo, "coordinator"), ids=[preview["messages"][0]["id"]]
    )
    assert main(drain) == 0
    assert capsys.readouterr().out.strip() == ""
    assert main(["--root", root, "agent", "inbox", "coordinator", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["unread"] == 0 and len(data["messages"]) == 1


def test_hermes_ws_is_a_declared_fleet_agent_the_cube_never_plays() -> None:
    from cube.agents import load_agent

    agent = load_agent(REPO_ROOT, "hermes-ws")
    assert agent.role == "concierge" and agent.runtime == "hermes" and agent.host == "ws"
    assert agent.workday.max_runs == 0


def _plain_request_description(ask: str) -> str:
    return (
        BeadHeader(
            xid="fixture:liaison-plain-request",
            provenance=[Provenance(source="fixture", locator="request")],
            privacy=Privacy.internal,
        ).render()
        + "\n"
        + ask
        + "\n"
    )


def test_liaison_request_without_question_field_becomes_a_model_step(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cube-p91d (2026-09-07) blocked on 'missing Question field' and nobody answered it.

    A plain ask after the header is the question (ADR-0025). One that names only a
    readable path is a lookup: the `liaison` role runs it with the lookup protocol
    and no approval (ADR-0027).
    """
    from cube.patrols.agent_workday import LIAISON_LOOKUP_PROMPT

    _install_liaison(engine_repo)
    _configure_laptop(engine_repo)
    _ssh_shim(fake_bd, monkeypatch, reachable=False)
    fake_bd.add(
        "plain-request",
        title="Request for Laptop liaison: validate two local directories",
        labels=["kind:request", "agent:liaison", "host:laptop", "privacy:internal"],
        description=_plain_request_description(
            "Ask, read-only on the laptop: list the files under ~/Public/software/x."
        ),
    )
    settings = __import__("cube.config", fromlist=["load_settings"]).load_settings(engine_repo)
    runner = StubRunner(RunResult(summary="answered on the bead (source: bd comment)"))

    result = AgentWorkdayPatrol("liaison", runner=runner).run(
        settings,
        dry_run=False,
        beads=Beads(bin="bd", cwd=engine_repo),
    )

    assert result.answers == []
    assert not [item for item in result.blocked if "Question" in str(item.get("reason"))]
    assert result.gates[0]["scope"]["scope"] == "readable" and not result.gates[0]["waiting"]
    assert len(result.runs) == 1 and result.runs[0]["bead"] == "plain-request"
    assert result.runs[0]["role"] == "liaison"
    prompt = runner.calls[0].prompt
    assert LIAISON_LOOKUP_PROMPT in prompt
    assert "Readable directories:" in prompt and "Public/software" in prompt
    assert "bd close" in prompt and "cube lookup" in prompt


def test_liaison_pins_local_claude_for_private_sources(
    engine_repo: Path,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0030: the endpoint is reachable; private liaison memory stays local."""
    from cube.config import load_settings
    from cube.model import Tier
    from cube.patrols import agent_workday
    from cube.router import Refused, choose

    _install_liaison(engine_repo)
    _configure_laptop(engine_repo)
    _ssh_shim(fake_bd, monkeypatch, reachable=False)
    agent = load_agent(engine_repo, "liaison")
    assert (agent.runner, agent.model) == ("claude@local", "qwen3.8-27b")
    fake_bd.add(
        "plain-request",
        title="Request for Laptop liaison",
        labels=["kind:request", "agent:liaison", "host:laptop", "privacy:internal"],
        description=_plain_request_description(
            "Ask: which repositories under ~/Public/software changed this week?"
        ),
    )
    seen: list[dict[str, object]] = []

    def fake_execute(settings, role_name, **kwargs):  # type: ignore[no-untyped-def]
        seen.append({"role": role_name, **kwargs})
        return agent_workday.RunReport(
            ok=True,
            run_id="r-test",
            role=role_name,
            bead=kwargs.get("bead"),
            state="finished",
            started="2026-09-07T19:00:00+00:00",
        )

    monkeypatch.setattr(agent_workday, "execute", fake_execute)
    settings = load_settings(engine_repo)
    result = AgentWorkdayPatrol("liaison").run(
        settings, dry_run=False, beads=Beads(bin="bd", cwd=engine_repo)
    )
    assert len(result.runs) == 1 and len(seen) == 1
    assert seen[0]["role"] == "liaison"
    assert seen[0]["runner_name"] == "claude@local"
    assert seen[0]["model"] == "qwen3.8-27b"
    assert seen[0]["needs_tools"] is True

    shipped = load_settings(REPO_ROOT)
    route = choose(
        shipped,
        Tier.plan,
        privacy=Privacy.local_only,
        requested_runner="claude@local",
        requested_model="qwen3.8-27b",
        available=lambda _target: True,
        role="senior",
        needs_tools=True,
        agent="liaison",
    )
    assert (route.runner, route.model) == ("claude@local", "qwen3.8-27b")
    with pytest.raises(Refused, match="local-only"):
        choose(
            shipped,
            Tier.plan,
            privacy=Privacy.local_only,
            requested_runner="claude@openrouter",
            requested_model="z-ai/glm-5.3-flash",
            available=lambda _target: True,
            role="senior",
            needs_tools=True,
            agent="liaison",
        )


def test_agent_runner_must_be_the_runtime_harness(engine_repo: Path) -> None:
    _install_liaison(engine_repo)
    path = engine_repo / "agents" / "liaison.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("runner: claude@local", "runner: codex@local"),
        encoding="utf-8",
    )
    with pytest.raises(AgentError, match="not the claude harness"):
        load_agent(engine_repo, "liaison")
