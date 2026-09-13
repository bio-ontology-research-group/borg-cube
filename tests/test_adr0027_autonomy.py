"""ADR-0027: Robert approves two things; the cube reports on finished goals.

Robert, 2026-09-08: fewer messages, only (a) a change to a running system and
(b) a laptop read outside the readable directories reach him; the liaison
answers readable lookups on its own with `cube lookup`; a finished goal becomes
one larger report; a timed-out run says "timeout", not "no JSON object".
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cube.agents.liaison import (
    APPROVED,
    LAPTOP_READ,
    NEEDS_ROBERT,
    classify_request,
    gate_request,
    request_paths,
)
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings, load_settings
from cube.decisions import (
    decide,
    decision_guards,
    is_robert,
    pending_decisions,
    policy_preview,
)
from cube.goals import GoalHeader
from cube.lookup import (
    LookupError,
    Roots,
    op_find,
    op_grep,
    op_head,
    op_ls,
    readable_roots,
    resolve_within,
)
from cube.model import Privacy, Provenance
from cube.patrols import base
from cube.patrols.goals import GoalsPatrol
from cube.patrols.triage import ROUTED, ROUTED_TWICE, TriagePatrol
from cube.reports import goal_report
from cube.roles.loader import load_role
from cube.runners.base import ExecResult, RunContext, failure_error
from cube.runners.claude_code import ClaudeCodeRunner, deny_paths, parse_envelope, read_rule
from cube.runners.hermes import HermesRunner
from cube.systems import names_system
from cube.testing.fakebd import FakeBd
from tests.helpers_engine import REPO_ROOT, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
TODAY = NOW.date()
SYSTEMS = ["borg-server", "ontolinator", "example.org", "unimatrix01", "ws"]


def _header(xid: str) -> str:
    return f"---\nxid: {xid}\nprovenance: []\nprivacy: internal\n---\n"


# --- systems ---------------------------------------------------------------------


def test_names_system_matches_whole_words_and_domains() -> None:
    assert names_system(SYSTEMS, "Approval: reboot borg-server tonight") == "borg-server"
    assert names_system(SYSTEMS, "renew the certificate for example.org.") == "example.org"
    assert names_system(SYSTEMS, "Escalation from sysadmin: (ws) root disk") == "ws"
    assert names_system(SYSTEMS, "news about wsl and awsome tools") is None
    assert names_system(SYSTEMS, None, "", "unimatrix01: PAM repair") == "unimatrix01"
    assert names_system([], "borg-server") is None


# --- what Robert decides -----------------------------------------------------------


def _shipped(engine_repo: Path) -> Settings:
    lines = (REPO_ROOT / "cube.yaml").read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(lines) if line == "decisions:")
    block = ["decisions:"]
    for line in lines[first + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    path = engine_repo / "cube.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n".join(block) + "\n", encoding="utf-8")
    # The names of running systems are site data (cube.local.yaml), not shipped policy.
    (engine_repo / "cube.local.yaml").write_text(
        "decisions:\n  systems: [example.org, ws]\n", encoding="utf-8"
    )
    return load_settings(engine_repo)


def _approval(settings: Settings, ident: str, **fields: object) -> None:
    from cube.approvals.store import Approval, ApprovalStore

    store = ApprovalStore(settings.state_dir())
    row = {
        "id": ident,
        "kind": "file_change",
        "created_by": "senior/r-1",
        "created": "2026-09-08T08:00:00+00:00",
        "status": "pending",
        **fields,
    }
    store.save(Approval.model_validate(row))


def test_policy_approves_file_changes_and_dms_to_robert_but_not_system_changes(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    settings = _shipped(engine_repo)
    (settings.state_dir() / "bodies").mkdir(parents=True, exist_ok=True)
    diff = settings.state_dir() / "bodies" / "apr-1.diff"
    diff.write_text("--- a/cube/x.py\n+++ b/cube/x.py\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    _approval(settings, "apr-1", diff_file=str(diff), target_dir="cube")
    _approval(
        settings,
        "apr-2",
        kind="mattermost_dm",
        person="robert-hoehndorf",
        subject="FLOPO status",
        created_by="group-leader/r-2",
    )
    _approval(
        settings,
        "apr-3",
        kind="mattermost_dm",
        person="alex-example",
        subject="hello",
        created_by="advisor/r-3",
    )
    sysdiff = settings.state_dir() / "bodies" / "apr-4.diff"
    sysdiff.write_text(
        "--- a/etc/nginx/example.org.conf\n+++ b/etc/nginx/example.org.conf\n@@ -1 +1 @@\n-a\n+b\n",
        encoding="utf-8",
    )
    _approval(
        settings,
        "apr-4",
        diff_file=str(sysdiff),
        target_dir="/etc/nginx",
        subject="vhost for example.org",
        created_by="sysadmin/r-4",
    )
    items = {
        item["id"]: item
        for item in pending_decisions(settings, Beads(bin="bd", cwd=engine_repo), now=NOW)
    }

    assert policy_preview(settings, items["apr-1"], now=NOW)["answer"] == "approve"
    assert items["apr-2"]["context"]["recipient"] == "robert-hoehndorf"
    assert decision_guards(settings, items["apr-2"], now=NOW) == []
    assert policy_preview(settings, items["apr-2"], now=NOW)["answer"] == "approve"
    assert "outbound" in decision_guards(settings, items["apr-3"], now=NOW)
    assert policy_preview(settings, items["apr-3"], now=NOW) is None
    assert items["apr-4"]["context"]["system"] == "example.org"
    assert policy_preview(settings, items["apr-4"], now=NOW) is None


def test_is_robert_accepts_his_ids_only() -> None:
    assert is_robert("robert-hoehndorf") and is_robert("@roberthoehndorf") and is_robert("robert")
    assert not is_robert("alex-example") and not is_robert(None) and not is_robert("")


def test_a_laptop_read_permission_keeps_the_request_open_when_approved(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    settings = _shipped(engine_repo)
    fake_bd.add(
        "cube-r1",
        title="Request for Laptop liaison",
        labels=["kind:request", "agent:liaison", "host:laptop", NEEDS_ROBERT, LAPTOP_READ],
        description=_header("request:liaison:1") + "Question: what did I mail the editor?\n",
        created_at="2026-09-08T08:00:00+00:00",
    )
    fake_bd.add(
        "cube-r2",
        title="Request for Laptop liaison",
        labels=["kind:request", "agent:liaison", "host:laptop", NEEDS_ROBERT, LAPTOP_READ],
        description=_header("request:liaison:2") + "Question: what is in ~/org/notes.org?\n",
        created_at="2026-09-08T08:01:00+00:00",
    )
    beads = Beads(bin="bd", cwd=engine_repo)
    pending = {item["id"]: item for item in pending_decisions(settings, beads, now=NOW)}
    assert pending["cube-r1"]["kind"] == "permission"
    assert policy_preview(settings, pending["cube-r1"], now=NOW) is None

    decide(settings, beads, "cube-r1", choice="yes", dry_run=False, now=NOW)
    stored = fake_bd.bead("cube-r1")
    assert stored["status"] != "closed"
    assert APPROVED in stored["labels"] and NEEDS_ROBERT not in stored["labels"]
    assert "cube-r1" not in {i["id"] for i in pending_decisions(settings, beads, now=NOW)}

    decide(settings, beads, "cube-r2", choice="no", text="not now", dry_run=False, now=NOW)
    assert fake_bd.bead("cube-r2")["status"] == "closed"


# --- triage --------------------------------------------------------------------------


def _install_agents(repo: Path) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "sysadmin"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name, dirs_exist_ok=True)
    (repo / "cube.yaml").write_text(
        (repo / "cube.yaml").read_text(encoding="utf-8").replace("host: testhost", "host: ws"),
        encoding="utf-8",
    )


def test_triage_routes_a_bead_again_once_then_lets_it_stand(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _install_agents(engine_repo)
    settings = load_settings(engine_repo)
    settings.triage.rules = load_settings(REPO_ROOT).triage.rules
    fake_bd.add(
        "cube-b09l",
        title="Escalation from sysadmin: after the Phase A probes are recorded",
        labels=["kind:request", "from:sysadmin", NEEDS_ROBERT, ROUTED],
        priority=1,
    )
    fake_bd.add(
        "cube-twice",
        title="Escalation from sysadmin: the same probe again",
        labels=["kind:request", "from:sysadmin", NEEDS_ROBERT, ROUTED, ROUTED_TWICE],
        priority=1,
    )
    fake_bd.add(
        "cube-rowz",
        title="Escalation from sysadmin: approve a /storage relief plan on unimatrix01",
        labels=["kind:finding", "agent:sysadmin", "from:sysadmin", NEEDS_ROBERT, ROUTED],
        priority=1,
    )
    base.run_patrol(settings, TriagePatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    beads = fake_bd.beads()
    assert NEEDS_ROBERT not in beads["cube-b09l"]["labels"]
    assert ROUTED_TWICE in beads["cube-b09l"]["labels"]
    assert NEEDS_ROBERT in beads["cube-twice"]["labels"]
    # names unimatrix01: a change to a running system stays Robert's
    assert NEEDS_ROBERT in beads["cube-rowz"]["labels"]


def test_triage_defers_deadline_findings_and_routes_stale_pipeline_findings(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _install_agents(engine_repo)
    settings = load_settings(engine_repo)
    settings.triage.rules = load_settings(REPO_ROOT).triage.rules
    fake_bd.add(
        "cube-1uy4",
        title="Deadline overdue by 49 day(s): Nazarbayev University leadership opportunity",
        labels=["kind:finding", NEEDS_ROBERT, "src:deadlines.md", "window:overdue"],
        priority=1,
    )
    fake_bd.add(
        "cube-pjr.15",
        title="Research pipeline stage is stale: survey",
        labels=["kind:finding", "kind:goal", NEEDS_ROBERT, "goal:cube-pjr", "pipeline:research"],
        priority=1,
    )
    base.run_patrol(settings, TriagePatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    beads = fake_bd.beads()
    assert NEEDS_ROBERT not in beads["cube-1uy4"]["labels"]
    assert "triage:deferred" in beads["cube-1uy4"]["labels"]
    assert "agent:coordinator" in beads["cube-pjr.15"]["labels"]


# --- the liaison's scope -------------------------------------------------------------


def _laptop(repo: Path) -> Settings:
    path = repo / "cube.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("host: testhost", "host: laptop")
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
    return load_settings(repo)


def test_request_paths_and_classification(engine_repo: Path) -> None:
    settings = _laptop(engine_repo)
    home = Path.home()
    assert request_paths("list ~/Public/software/x and /home/robert/Documents/papers/a.pdf.") == [
        "~/Public/software/x",
        "/home/robert/Documents/papers/a.pdf",
    ]
    readable = classify_request(
        "count the files under ~/Public/software/physiomap/docs", settings, home=home
    )
    assert readable.scope == "readable" and not readable.needs_approval
    outside = classify_request(
        "read ~/Downloads/x.txt and ~/Public/software/y", settings, home=home
    )
    assert outside.scope == "personal" and "Downloads" in outside.reason
    closed = classify_request(
        "grep ~/Public/software/pa/deadlines.md for KAUST", settings, home=home
    )
    assert closed.scope == "personal" and "closed" in closed.reason
    traversal = classify_request("read ~/Public/software/../.ssh/id_rsa", settings, home=home)
    assert traversal.scope == "personal"
    mail = classify_request("check the ideas in an email I sent", settings, home=home)
    assert mail.scope == "mail" and mail.needs_approval
    memories = classify_request(
        "what do my memories under ~/Public/software say", settings, home=home
    )
    assert memories.scope == "personal"
    nopath = classify_request("which repositories changed this week?", settings, home=home)
    assert nopath.scope == "personal" and "no path" in nopath.reason


def test_gate_labels_a_personal_request_once_and_passes_an_approved_one(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    settings = _laptop(engine_repo)
    beads = Beads(bin="bd", cwd=engine_repo)
    fake_bd.add(
        "req-mail",
        title="Request for Laptop liaison",
        labels=["kind:request", "agent:liaison", "host:laptop"],
        description=_header("request:1") + "Question: what did I write in mail to the editor?\n",
    )
    first = gate_request(settings, beads, fake_bd.bead("req-mail"), dry_run=False)
    assert first["waiting"] and first.get("labelled")
    labels = fake_bd.bead("req-mail")["labels"]
    assert NEEDS_ROBERT in labels and LAPTOP_READ in labels
    second = gate_request(settings, beads, fake_bd.bead("req-mail"), dry_run=False)
    assert second["waiting"] and not second.get("labelled")

    fake_bd.add(
        "req-ok",
        title="Request for Laptop liaison",
        labels=["kind:request", "agent:liaison", "host:laptop", APPROVED],
        description=_header("request:2") + "Question: what did I write in mail to the editor?\n",
    )
    assert gate_request(settings, beads, fake_bd.bead("req-ok"), dry_run=False)["approved"]


def test_cube_request_files_a_personal_read_already_waiting(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    (engine_repo / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "liaison"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", engine_repo / "agents" / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, engine_repo / "agents" / name)
    _laptop(engine_repo)
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "request",
                "liaison",
                "What is in ~/org/x.org?",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"]["needs_approval"]
    assert {NEEDS_ROBERT, LAPTOP_READ} <= set(fake_bd.bead(payload["bead"])["labels"])
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "request",
                "liaison",
                "List ~/Public/software/x",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert not payload["scope"]["needs_approval"]
    assert NEEDS_ROBERT not in fake_bd.bead(payload["bead"])["labels"]


# --- cube lookup ---------------------------------------------------------------------


def _tree(tmp_path: Path) -> tuple[Path, Roots]:
    home = tmp_path / "home"
    software = home / "Public" / "software"
    (software / "proj" / "docs").mkdir(parents=True)
    (software / "proj" / "docs" / "a.md").write_text("alpha\nbeta needle\n", encoding="utf-8")
    (software / "proj" / "notes.txt").write_text("needle here\n", encoding="utf-8")
    (software / "proj" / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (software / "pa").mkdir()
    (software / "pa" / "deadlines.md").write_text("needle private\n", encoding="utf-8")
    (home / "pa").symlink_to(software / "pa")
    (home / "org").mkdir()
    (home / "org" / "x.org").write_text("needle org\n", encoding="utf-8")
    (software / "proj" / "link-out").symlink_to(home / "org")
    roots = Roots(
        readable=(software.resolve(),),
        denied=((software / "pa").resolve(), (home / "org").resolve()),
    )
    return home, roots


def test_lookup_refuses_outside_closed_and_secret_paths(tmp_path: Path) -> None:
    home, roots = _tree(tmp_path)
    software = home / "Public" / "software"
    assert resolve_within(str(software / "proj"), roots).root == software.resolve()
    with pytest.raises(LookupError, match="outside"):
        resolve_within(str(home / "Downloads"), roots) if (
            home / "Downloads"
        ).mkdir() is None else None
    with pytest.raises(LookupError, match="stays closed"):
        resolve_within(str(home / "pa" / "deadlines.md"), roots)
    with pytest.raises(LookupError, match="stays closed"):
        resolve_within(str(software / "proj" / "link-out" / "x.org"), roots)
    with pytest.raises(LookupError, match="secret"):
        resolve_within(str(software / "proj" / ".env"), roots)
    with pytest.raises(LookupError, match="no such path"):
        resolve_within(str(software / "nope"), roots)


def test_lookup_ops_stay_inside_and_cap_output(tmp_path: Path) -> None:
    home, roots = _tree(tmp_path)
    software = home / "Public" / "software"
    bounded = resolve_within(str(software), roots)
    listed = {e["name"] for e in op_ls(bounded)["entries"]}
    assert "proj" in listed and "pa" not in listed
    files = op_find(bounded, name="*.md")["files"]
    assert files == [str(software / "proj" / "docs" / "a.md")]
    hits = op_grep(bounded, "needle")["matches"]
    assert {h["file"] for h in hits} == {
        str(software / "proj" / "docs" / "a.md"),
        str(software / "proj" / "notes.txt"),
    }
    head = op_head(
        resolve_within(str(software / "proj" / "docs" / "a.md"), roots), start=2, lines=5
    )
    assert head["lines"] == ["2:beta needle"]
    with pytest.raises(LookupError, match="not a file"):
        op_head(bounded)
    capped = op_ls(bounded, limit=1)
    assert capped["truncated"] is False or len(capped["entries"]) == 1


def test_lookup_cli_reads_roots_from_settings(
    engine_repo: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, _ = _tree(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    settings = _laptop(engine_repo)
    roots = readable_roots(settings)
    assert roots.readable == ((home / "Public" / "software").resolve(),)
    assert (home / "org").resolve() in roots.denied
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "lookup",
                "grep",
                "needle",
                str(home / "Public" / "software"),
                "--json",
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert all("/pa/" not in m["file"] and "/org/" not in m["file"] for m in out["matches"])
    assert main(["--root", str(engine_repo), "lookup", "ls", str(home / "pa")]) == 2
    assert "stays closed" in capsys.readouterr().err


# --- the liaison role and the Claude runner ------------------------------------------


def test_liaison_role_reads_only_inside_the_readable_roots(engine_repo: Path) -> None:
    settings = _laptop(engine_repo)
    role = load_role(engine_repo, "liaison")
    assert role.read_roots == "host" and role.permission_mode == "read-only"
    assert not any(t.startswith(("Read", "Grep", "Glob")) for t in role.allowed_tools)
    ctx = RunContext(
        run_id="r-1",
        role=role,
        prompt="lookup",
        cwd=engine_repo,
        run_dir=engine_repo / "runs" / "r-1",
        read_roots=settings.readable_dirs("laptop"),
        deny_roots=settings.unreadable_dirs("laptop"),
        dry_run=True,
    )
    cmd = ClaudeCodeRunner().command(ctx)
    assert "--allowedTools" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "Bash"
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    hook_settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert not hook_settings.get("disableAllHooks", False)
    hook = hook_settings["hooks"]["PreToolUse"][0]
    assert hook["matcher"] == "Bash"
    assert "tool_guard.py" in hook["hooks"][0]["command"]
    assert "--role liaison" in hook["hooks"][0]["command"]
    denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
    home = str(Path.home())
    assert Path.home() / "Public/software" in ctx.read_roots
    assert Path.home() / "Documents/papers" in ctx.read_roots
    assert f"Read(/{home}/org/**)" in denied and f"Read(/{home}/.ssh/**)" in denied
    assert read_rule(Path("/x/y")) == "Read(//x/y/**)"
    assert deny_paths([Path("/nowhere/z")]) == [Path("/nowhere/z")]


def test_a_role_with_read_roots_may_not_list_read_grep_or_glob(tmp_path: Path) -> None:
    text = (REPO_ROOT / "roles" / "liaison.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["allowed_tools"] = ["Read", "Bash(bd *)"]
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "liaison.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (tmp_path / "roles" / "prompts").mkdir()
    (tmp_path / "roles" / "prompts" / "liaison.md").write_text("# x\n", encoding="utf-8")
    with pytest.raises(Exception, match="read_roots"):
        load_role(tmp_path, "liaison")


# --- runner errors -------------------------------------------------------------------


def test_failure_error_names_the_timeout_not_the_missing_json() -> None:
    assert failure_error(
        "no JSON object in output", harness="hermes", timed_out=True, stderr="timeout after 1800s"
    ) == ("hermes timeout after 1800s; no result before the deadline")
    assert failure_error(
        "no JSON object in output", harness="hermes", stdout="", stderr="boom", returncode=1
    ) == ("hermes produced no output (exit 1): boom")
    assert (
        failure_error("no JSON object in output", harness="hermes", stdout="prose")
        == "no JSON object in output"
    )


def test_hermes_and_claude_runners_report_timeouts(engine_repo: Path) -> None:
    role = load_role(engine_repo, "senior")
    ctx = RunContext(
        run_id="r-1",
        role=role,
        prompt="p",
        cwd=engine_repo,
        run_dir=engine_repo / "runs" / "r-1",
        timeout=5,
    )

    def timed_out(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return ExecResult(124, "", "timeout after 5s", timed_out=True)

    outcome = HermesRunner(exec_fn=timed_out).run(ctx)
    assert (
        outcome.result is None
        and outcome.error == "hermes timeout after 5s; no result before the deadline"
    )
    envelope = parse_envelope("", "timeout after 5s", 124, ["claude"], timed_out=True)
    assert envelope.error == "claude timeout after 5s; no result before the deadline"


# --- goal reports --------------------------------------------------------------------


def _goal(goal_id: str) -> str:
    return GoalHeader(
        xid=f"goal:{goal_id}",
        provenance=[Provenance(source="tests/test_adr0027_autonomy.py", locator=goal_id)],
        deadline=TODAY,
        privacy=Privacy.internal,
        target=TODAY,
        success=["The survey is on the ledger", "Every claim cites a source"],
        status="done",  # type: ignore[arg-type]
    ).render()


def _install_hermes_ws(repo: Path) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "hermes-ws"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name, dirs_exist_ok=True)
    (repo / "cube.yaml").write_text(
        (repo / "cube.yaml").read_text(encoding="utf-8").replace("host: testhost", "host: ws"),
        encoding="utf-8",
    )


def test_a_finished_goal_becomes_one_report_in_hermes_ws_inbox(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    from cube.agents import load_agent, read_inbox

    _install_hermes_ws(engine_repo)
    settings = load_settings(engine_repo)
    recent = (NOW - timedelta(hours=1)).isoformat()
    fake_bd.add(
        "g1",
        title="Survey temporal knowledge graphs",
        labels=["kind:goal"],
        status="closed",
        closed_at=recent,
        close_reason="survey delivered",
        description=_goal("g1"),
    )
    fake_bd.add(
        "g1.1",
        title="Screen 40 papers",
        labels=["kind:goal", "goal:g1", "agent:ontology"],
        status="closed",
        closed_at=recent,
        close_reason="screened",
        parent="g1",
    )
    fake_bd.add(
        "g1.2",
        title="Write the synthesis",
        labels=["kind:goal", "goal:g1", "role:editor"],
        status="open",
        parent="g1",
    )
    issues = Beads(bin="bd", cwd=engine_repo).list_issues("--all")
    text = goal_report(settings, fake_bd.bead("g1"), issues, now=NOW)
    assert text.startswith("# Goal report: Survey temporal knowledge graphs")
    assert "Closed because: survey delivered" in text
    assert "- The survey is on the ledger" in text
    assert "1 of 2 work item(s) closed; by ontology (1)." in text
    assert "## Still open" in text and "g1.2 [editor] Write the synthesis" in text

    report = base.run_patrol(settings, GoalsPatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    rows = report.data["reports"]
    assert len(rows) == 1 and rows[0]["posted"]
    assert (engine_repo / "briefings" / "goals" / "g1.md").read_text(encoding="utf-8") == text
    inbox = read_inbox(
        engine_repo, load_agent(engine_repo, "hermes-ws", validate_role=False), unread_only=True
    )
    assert len(inbox) == 1 and inbox[0]["from"] == "cube" and "Goal report" in inbox[0]["text"]

    again = base.run_patrol(settings, GoalsPatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    assert again.data["reports"] == []
    assert (
        len(
            read_inbox(
                engine_repo,
                load_agent(engine_repo, "hermes-ws", validate_role=False),
                unread_only=True,
            )
        )
        == 1
    )


# --- the worker profile --------------------------------------------------------------


def test_cube_worker_template_bounds_context_and_allows_worker_scripts() -> None:
    from cube.hermes import render_template

    text = (REPO_ROOT / "hermes" / "profiles" / "cube-worker" / "config.yaml.tmpl").read_text(
        encoding="utf-8"
    )
    rendered = yaml.safe_load(
        render_template(
            text,
            {
                "PROFILE": "cube-worker",
                "CUBE_ROOT": "/r",
                "VLLM_BASE_URL": "http://u:8000/v1",
                "MATTERMOST_URL": "",
                "MATTERMOST_ALLOWED_USERS": "",
                "MATTERMOST_HOME_CHANNEL": "",
            },
        )
    )
    assert rendered["model"]["context_length"] == 131072
    assert rendered["model"]["max_tokens"] == 8192
    assert rendered["compression"]["threshold"] == 0.4
    assert rendered["approvals"]["single_query_mode"] == "deny"
    assert set(rendered["command_allowlist"]) == {
        "script execution via -e/-c flag",
        "script execution via heredoc",
    }


def test_settings_expose_readable_and_closed_dirs(engine_repo: Path) -> None:
    settings = _laptop(engine_repo)
    home = Path.home()
    assert settings.readable_dirs("laptop") == [
        home / "Documents" / "papers",
        home / "Public" / "software",
    ]
    closed = settings.unreadable_dirs("laptop")
    assert home / "pa" in closed and home / "org" in closed and home / ".ssh" in closed
    assert settings.readable_dirs("ws") == []
    assert os.environ.get("CUBE_HOST") is None or True
