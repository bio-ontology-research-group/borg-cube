from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.engine import execute, worktree
from cube.engine import lease as leases
from cube.engine.context import build_context, privacy_filter
from cube.model import RunResult
from cube.roles import load_role
from cube.runners import StubRunner
from tests.helpers_engine import (
    REPO_ROOT,
    FakeBd,
    RecordingExec,
    fixtures,
)

globals().update(fixtures())


def header(privacy: str = "internal") -> str:
    return f"---\nxid: test:1\nprivacy: {privacy}\n---\n"


def test_partial_checkpoint_never_applies_actions(engine_settings, fake_bd, monkeypatch):
    import importlib
    from unittest.mock import MagicMock

    from cube.runners.base import RunOutcome

    fake_bd.add("cube-7", title="Unfinished", labels=["role:senior"], description=header())
    runner = StubRunner()
    monkeypatch.setattr(
        runner,
        "run",
        lambda ctx: RunOutcome(
            raw_text='{"summary":"partial",',
            result=RunResult(summary="Partial output"),
            session_id=None,
            usage={},
            exit_code=0,
            stderr="",
            checkpoint_only=True,
        ),
    )
    apply = MagicMock()
    monkeypatch.setattr(importlib.import_module("cube.engine.run"), "apply_result", apply)
    report = execute(engine_settings, "senior", bead="cube-7", runner=runner, runner_name="stub")
    assert report.state == "checkpoint" and not report.ok and report.error is None
    apply.assert_not_called()
    beads = Beads(bin="bd", cwd=engine_settings.root)
    assert beads.show("cube-7")["status"] == "open"


def run_json(repo: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    rc = main(["--root", str(repo), *argv, "--json"])
    return rc, json.loads(capsys.readouterr().out)


def test_full_stub_run_on_bead(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bd.add(
        "cube-1",
        title="Design the widget",
        labels=["stage:design", "person:alex-example", "project:foo"],
        description=header() + "Make a spec.",
    )
    rc, out = run_json(engine_repo, capsys, "run", "senior", "--bead", "cube-1", "--runner", "stub")
    assert rc == 0 and out["ok"] and out["state"] == "finished"
    assert out["runner"] == "stub" and out["bead"] == "cube-1"
    run_dir = Path(out["run_dir"])
    assert {p.name for p in run_dir.iterdir()} >= {
        "prompt.md",
        "stdout.jsonl",
        "result.json",
        "meta.json",
    }
    prompt = (run_dir / "prompt.md").read_text()
    assert "FAKE PRIME CONTEXT" in prompt and "Make a spec." in prompt
    assert "person:alex-example: name=Alex Example" in prompt  # resolved from people.yaml
    assert "project:foo" in prompt
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["state"] == "finished" and meta["session_id"].startswith("stub-")
    cmds = [c[0] for c in fake_bd.calls()]
    assert "prime" in cmds and "show" in cmds and "update" in cmds and "comment" in cmds
    claim = next(c for c in fake_bd.calls() if c[0] == "update")
    assert claim[1:3] == ["cube-1", "--claim"]
    # lease released, session stored, events and audit written
    assert not (engine_repo / "state" / "leases" / "cube-1.json").exists()
    assert (
        json.loads((engine_repo / "state" / "sessions" / "cube-1.json").read_text())["runner"]
        == "stub"
    )
    events = [
        json.loads(x) for x in (engine_repo / "state" / "events.jsonl").read_text().splitlines()
    ]
    assert [e["event"] for e in events] == ["start", "finished"]
    assert events[0]["run_id"] == out["run_id"] and events[0]["bead"] == "cube-1"
    audit = [
        json.loads(x) for x in (engine_repo / "state" / "audit.jsonl").read_text().splitlines()
    ]
    assert [a["action"] for a in audit] == ["run.start", "run.finish"]
    budget = json.loads((engine_repo / "state" / "budget.json").read_text())
    assert next(iter(budget.values()))["plan"]["runs"] == 1
    rc, runs = run_json(engine_repo, capsys, "runs")
    assert runs["runs"][0]["run_id"] == out["run_id"]


def test_dry_run_prints_command_and_writes_nothing(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_bd.add("cube-2", title="Implement", labels=["stage:implement"], description=header())
    rc, out = run_json(
        engine_repo, capsys, "run", "programmer", "--bead", "cube-2", "--dry-run", "--show-prompt"
    )
    assert rc == 0 and out["state"] == "dry-run"
    assert out["command"][:2] == ["codex", "exec"] and "cube-chatgpt" in out["command"]
    assert "Worktree" in out["prompt"] and ".cube/wt/cube-2" in out["prompt"]
    assert not (engine_repo / "runs").exists() or not list((engine_repo / "runs").glob("*/*"))
    assert not (engine_repo / "state" / "leases").exists()
    assert all(c[0] not in ("update", "comment", "close") for c in fake_bd.calls())


def test_needs_tools_flags_reach_the_run_report(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--needs-tools` / `--no-needs-tools` override the value derived from the role."""
    fake_bd.add("cube-9", title="Implement", labels=["stage:implement"], description=header())
    rc, derived = run_json(
        engine_repo, capsys, "run", "programmer", "--bead", "cube-9", "--dry-run"
    )
    assert rc == 0 and derived["needs_tools"] is True

    rc, forced = run_json(
        engine_repo,
        capsys,
        "run",
        "programmer",
        "--bead",
        "cube-9",
        "--dry-run",
        "--no-needs-tools",
    )
    assert rc == 0 and forced["needs_tools"] is False

    rc, asked = run_json(
        engine_repo, capsys, "run", "programmer", "--bead", "cube-9", "--dry-run", "--needs-tools"
    )
    assert rc == 0 and asked["needs_tools"] is True
    assert asked["runner"] == "codex"


def test_review_gate_and_escalations(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    fake_bd.add(
        "cube-3", title="Implement the parser", labels=["stage:implement"], description=header()
    )
    result = RunResult(
        summary="implemented; tests pass (source: runs/x)",
        bead_updates=[
            {
                "bead": "cube-3",
                "comment": "diff in branch",
                "close": True,
                "labels_add": ["has:diff"],
            }
        ],  # type: ignore[list-item]
        escalations=[
            {
                "condition": "task requires credentials",
                "to": "robert",
                "summary": "needs a token",
                # Robert, 2026-09-07: a secret is privacy-critical, so this one is his
                "critical": "privacy",
            }
        ],  # type: ignore[list-item]
    )
    report = execute(
        engine_settings,
        "programmer",
        bead="cube-3",
        runner=StubRunner(result=result),
        runner_name="stub",
        exec_fn=RecordingExec(),
    )
    assert report.ok, report.error
    applied = report.applied or {}
    assert applied["closed"] == [] and applied["review_bead"] and "has:diff" in applied["labels"]
    beads = fake_bd.beads()
    review = beads[applied["review_bead"]]
    assert {"kind:review", "tier:plan", "role:senior", "reviews:cube-3"} <= set(review["labels"])
    assert "review:pending" in beads["cube-3"]["labels"]
    assert (
        beads["cube-3"]["status"] == "in_progress"
    )  # claimed at dispatch, awaiting its review bead
    esc = beads[applied["escalations"][0]]
    assert "needs:robert" in esc["labels"] and esc["title"].startswith("Escalation from programmer")
    assert "critical:privacy" in esc["labels"]
    events = [
        json.loads(x)["event"]
        for x in (engine_repo / "state" / "events.jsonl").read_text().splitlines()
    ]
    assert "attention" in events
    # worktree was attempted through the injected exec (git) and reported, not fatal
    assert any("worktree" in w for w in report.warnings) or report.ok


def test_verdict_closes_original(engine_settings: Settings, fake_bd: FakeBd) -> None:
    fake_bd.add(
        "cube-3", title="work", labels=["stage:implement", "review:pending"], description=header()
    )
    fake_bd.add(
        "cube-9",
        title="Review cube-3",
        labels=["kind:review", "tier:plan", "role:senior", "reviews:cube-3", "producer:programmer"],
        description=header(),
    )
    result = RunResult(summary="looks right (diff hunk 1-20)", verdict="approve")
    report = execute(
        engine_settings,
        "senior",
        bead="cube-9",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok and report.applied["verdict"]["closed"] == ["cube-3", "cube-9"]  # type: ignore[index]
    beads = fake_bd.beads()
    assert beads["cube-3"]["status"] == "closed" and "review:approved" in beads["cube-3"]["labels"]
    # revise spawns a follow-up implement bead for the producer
    fake_bd.add("cube-4", title="work2", labels=["stage:implement"], description=header())
    fake_bd.add(
        "cube-10",
        title="Review cube-4",
        labels=["kind:review", "role:senior", "reviews:cube-4", "producer:programmer"],
        description=header(),
    )
    result = RunResult(summary="tests missing", verdict="revise")
    report = execute(
        engine_settings,
        "senior",
        bead="cube-10",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    follow = report.applied["verdict"]["follow_up"]  # type: ignore[index]
    assert {"stage:implement", "role:programmer", "revises:cube-4"} <= set(
        fake_bd.bead(follow)["labels"]
    )


def test_group_leader_close_is_its_own(engine_settings: Settings, fake_bd: FakeBd) -> None:
    # Robert, 2026-09-07: the top of the review chain closes; nothing waits for
    # him but security and privacy matters.
    fake_bd.add("cube-5", title="plan", labels=["stage:design"], description=header())
    result = RunResult(summary="planned", bead_updates=[{"bead": "cube-5", "close": True}])  # type: ignore[list-item]
    report = execute(
        engine_settings,
        "group-leader",
        bead="cube-5",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok and "needs:robert" not in fake_bd.bead("cube-5")["labels"]
    assert fake_bd.bead("cube-5")["status"] == "closed"


def test_outbound_artifact_becomes_approval(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    fake_bd.add("cube-6", title="remind alex", labels=["kind:mentoring"], description=header())
    draft = engine_repo / "draft.md"
    draft.write_text(
        "---\nto: alex@example.org\nperson: alex-example\nchannel: email\n"
        "action: milestone-reminder\nsubject: Proposal defense\n---\nDear Alex, ...\n"
    )
    result = RunResult(
        summary="drafted reminder", artifacts=[{"kind": "outbound", "path": str(draft)}]
    )  # type: ignore[list-item]
    report = execute(
        engine_settings,
        "advisor",
        bead="cube-6",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok
    apr_id = report.applied["approvals"][0]  # type: ignore[index]
    data = json.loads((engine_repo / "state" / "approvals" / f"{apr_id}.json").read_text())
    assert data["status"] == "pending" and data["kind"] == "email"
    assert data["person"] == "alex-example"
    assert "no grants" in data["policy"]["reason"]
    assert any(c[0] == "comment" and apr_id in c[2] for c in fake_bd.calls())


def test_invalid_result_no_state_change(engine_settings: Settings, fake_bd: FakeBd) -> None:
    fake_bd.add("cube-7", title="x", labels=["stage:design"], description=header())
    report = execute(
        engine_settings,
        "senior",
        bead="cube-7",
        runner=StubRunner(fail="model said nothing"),
        runner_name="stub",
    )
    assert not report.ok and report.state == "error"
    assert all(c[0] not in ("close", "label") for c in fake_bd.calls())
    # the failed run gives the claim back so the marshal can retry it
    assert ["update", "cube-7", "--status", "open"] in [c[:4] for c in fake_bd.calls()]
    assert fake_bd.bead("cube-7")["status"] == "open"
    comments = [c for c in fake_bd.calls() if c[0] == "comment"]
    assert comments and "no state change" in comments[-1][2]


def test_privacy_rules(engine_settings: Settings, fake_bd: FakeBd) -> None:
    fake_bd.add(
        "cube-8",
        title="check-in transcript",
        labels=["kind:mentoring"],
        description=header("local-only"),
    )
    report = execute(engine_settings, "senior", bead="cube-8", runner_name="stub")
    assert report.state == "refused" and "privacy_max" in (report.error or "")
    # scribe may see local-only, but only on the local runner; none is available here -> queued
    report = execute(engine_settings, "scribe", bead="cube-8", available=lambda r: r != "local")
    assert report.state == "queued" and "never goes to cloud" in (report.error or "")
    events = [
        json.loads(x)
        for x in (engine_settings.root / "state" / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["event"] == "queued"


def test_kill_switch_and_leases(engine_settings: Settings, fake_bd: FakeBd) -> None:
    state = engine_settings.state_dir()
    (state / "KILL").write_text("stop")
    report = execute(engine_settings, "senior", runner_name="stub")
    assert report.state == "killed"
    (state / "KILL").unlink()
    fake_bd.add("cube-11", title="x", labels=["stage:design"], description=header())
    leases.acquire(state, "cube-11", run_id="r-other", role="senior", pid=os.getpid())
    report = execute(engine_settings, "senior", bead="cube-11", runner_name="stub")
    assert report.state == "leased" and "r-other" in (report.error or "")
    # a lease whose process is gone is not live; expire_dead removes it
    dead = leases.acquire(state, "cube-12", run_id="r-dead", role="senior", pid=2**22 - 1)
    assert not dead.live()
    old = leases.acquire(
        state,
        "cube-13",
        run_id="r-old",
        role="senior",
        ttl_seconds=1,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    assert old.expired()
    gone = {x.bead for x in leases.expire_dead(state)}
    assert gone == {"cube-12", "cube-13"} and leases.load(state, "cube-11") is not None
    assert leases.release(state, "cube-11", "wrong-run") is False
    assert leases.release(state, "cube-11", "r-other") is True


def test_python_role_and_unknown_role(engine_settings: Settings) -> None:
    assert execute(engine_settings, "marshal").state == "refused"
    assert execute(engine_settings, "nobody").state == "refused"


def test_context_privacy_filter_and_no_bd(engine_settings: Settings) -> None:
    text, hits = privacy_filter("fine line\nGPA 3.9 this term\nvisa expires soon")
    assert hits == 2 and "GPA" not in text and "fine line" in text
    beads = Beads(bin="definitely-not-a-binary", dry_run=True)
    ctx = build_context(
        engine_settings, beads, load_role(REPO_ROOT, "senior"), "cube-1", prompt_text="hi"
    )
    assert "### Instruction" in ctx.text and "hi" in ctx.text


def test_worktree_helpers(engine_settings: Settings) -> None:
    ex = RecordingExec()
    ex.responses["git"] = __import__("cube.runners.base", fromlist=["ExecResult"]).ExecResult(
        1, "", "no branch"
    )
    prog = load_role(REPO_ROOT, "programmer")
    assert worktree.needs_worktree(prog, [])
    assert not worktree.needs_worktree(load_role(REPO_ROOT, "senior"), ["kind:program"])
    assert worktree.needs_worktree(load_role(REPO_ROOT, "lecturer"), ["kind:program"])
    with pytest.raises(worktree.WorktreeError):
        worktree.create(engine_settings.root, "cube-1", ex)
    assert ex.calls[-1]["cmd"][:3] == ["git", "worktree", "add"] and ex.calls[-1]["cmd"][-2:] == [
        "-b",
        "cube/cube-1",
    ]
    assert worktree.remove(engine_settings.root, "cube-1", ex) is False


def test_resume_uses_stored_session(engine_settings: Settings, fake_bd: FakeBd) -> None:
    fake_bd.add("cube-14", title="x", labels=["stage:implement"], description=header())
    stub = StubRunner()
    execute(engine_settings, "programmer", bead="cube-14", runner=stub, runner_name="stub")
    stub2 = StubRunner()
    execute(
        engine_settings, "programmer", bead="cube-14", runner=stub2, runner_name="stub", resume=True
    )
    assert stub.calls[0].resume_id is None
    assert stub2.calls[0].resume_id == f"stub-{stub.calls[0].run_id}"


def test_inline_artifact_content_is_written_to_disk(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    """A read-only role returns the file as content; the engine materialises it.

    On 2026-09-05 the coordinator's per-student report existed only inside
    result.json because nothing wrote artifact content anywhere.
    """
    fake_bd.add("cube-8", title="student report", labels=["kind:task"], description=header())
    result = RunResult(
        summary="report compiled",
        artifacts=[
            {
                "kind": "report",
                "path": "state/agents/coordinator/student-progress-report-2026-09-05.md",
                "content": "# Report\n\nprivacy: local-only\n",
            },
            {"kind": "note", "path": "/etc/passwd", "content": "never"},
            {"kind": "note", "path": "roles/senior.yaml", "content": "tier: bulk\n"},
        ],  # type: ignore[list-item]
    )
    report = execute(
        engine_settings,
        "group-leader",
        bead="cube-8",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok
    target = (
        engine_repo / "state" / "agents" / "coordinator" / "student-progress-report-2026-09-05.md"
    )
    assert target.read_text(encoding="utf-8").startswith("# Report")
    run_dir = Path(report.run_dir)
    assert (run_dir / "student-progress-report-2026-09-05.md").exists()
    assert (run_dir / "passwd").read_text(encoding="utf-8") == "never"
    assert not Path("/etc/passwd").read_text(encoding="utf-8").startswith("never")
    assert "tier: bulk" not in (engine_repo / "roles" / "senior.yaml").read_text(encoding="utf-8")
    written = report.applied["artifacts"]["written"]  # type: ignore[index]
    assert str(target) in written
    notes = report.applied["notes"]  # type: ignore[index]
    assert any("outside the repo" in n for n in notes)
    assert any("roles/senior.yaml" in n for n in notes)


def test_execute_marks_open_data_runs_for_the_runner(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    """Only a privacy.open_endpoints_for agent runs with open_data (ADR-0018)."""
    from cube.runners import StubRunner

    engine_settings.privacy.open_endpoints_for = ["literature"]
    runner = StubRunner(RunResult(summary="ok"))
    for agent in ("literature", "ontology", None):
        report = execute(
            engine_settings,
            "scribe",
            runner=runner,
            runner_name="stub",
            prompt_text="x",
            agent=agent,
        )
        assert report.ok, report.error
    assert [ctx.open_data for ctx in runner.calls] == [True, False, False]


def test_finished_run_that_leaves_its_bead_open_releases_the_claim(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    # cube-r1n.3, 2026-09-09: close=false with a checkpoint comment, then two days
    # parked in_progress because nothing gave the claim back (cube-in1).
    fake_bd.add("cube-9", title="map twins", labels=["role:group-leader"], description=header())
    result = RunResult(
        summary="checkpoint",
        bead_updates=[{"bead": "cube-9", "comment": "half done", "close": False}],  # type: ignore[list-item]
    )
    report = execute(
        engine_settings,
        "group-leader",
        bead="cube-9",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok and report.state == "finished"
    bead = fake_bd.bead("cube-9")
    assert bead["status"] == "open" and "assignee" not in bead
    assert any("checkpoint, task stays open" in n for n in report.applied["notes"])


def test_goal_is_not_closed_by_a_planning_turn(engine_settings: Settings, fake_bd: FakeBd) -> None:
    # cube-ihu, cube-7hb, cube-dze, cube-up7 (2026-09-09): one decomposition turn
    # each, no child beads, all four P1 goals closed as done.
    fake_bd.add(
        "cube-g",
        title="Reproduce one method paper per agent",
        labels=["kind:goal"],
        issue_type="epic",
        description=header(),
    )
    report = execute(
        engine_settings, "group-leader", bead="cube-g", runner=StubRunner(), runner_name="stub"
    )
    assert report.ok and fake_bd.bead("cube-g")["status"] == "open"
    assert any("goal stays open" in n for n in report.applied["notes"])
    # an explicit close with no children is refused too
    result = RunResult(summary="done", bead_updates=[{"bead": "cube-g", "close": True}])  # type: ignore[list-item]
    report = execute(
        engine_settings,
        "group-leader",
        bead="cube-g",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert fake_bd.bead("cube-g")["status"] == "open"
    assert any("no child work yet" in n for n in report.applied["notes"])
    # with an open child the goal still waits; once the child is closed it may close
    fake_bd.add("cube-g.1", title="child", labels=["kind:goal", "role:senior"], parent="cube-g")
    report = execute(
        engine_settings,
        "group-leader",
        bead="cube-g",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert fake_bd.bead("cube-g")["status"] == "open"
    assert any("open child work (cube-g.1)" in n for n in report.applied["notes"])
    fake_bd.add("cube-g.1", title="child", labels=["role:senior"], parent="cube-g", status="closed")
    execute(
        engine_settings,
        "group-leader",
        bead="cube-g",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert fake_bd.bead("cube-g")["status"] == "closed"


def test_intake_child_does_not_close_as_a_request(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    # cube-r1n.2 inherited kind:request from its Mattermost intake parent and was
    # closed as "result filed, no review" although no repository existed.
    fake_bd.add(
        "cube-i.2",
        title="bootstrap fleet repo",
        labels=["kind:request", "intake:goal", "role:senior"],
        parent="cube-i",
        description=header(),
    )
    report = execute(
        engine_settings, "senior", bead="cube-i.2", runner=StubRunner(), runner_name="stub"
    )
    assert report.ok
    bead = fake_bd.bead("cube-i.2")
    assert bead["status"] != "closed"
    assert "review:pending" in bead["labels"] and report.applied["review_bead"]
    # a genuine request without an intake parent still closes on its answer
    fake_bd.add(
        "cube-q", title="which path?", labels=["kind:request", "role:liaison"], description=header()
    )
    execute(engine_settings, "liaison", bead="cube-q", runner=StubRunner(), runner_name="stub")
    assert fake_bd.bead("cube-q")["status"] == "closed"


def test_local_only_privacy_ignores_the_project_harness(
    engine_settings: Settings, fake_bd: FakeBd, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The laptop liaison on project:flopo was refused every five minutes:
    # "privacy local-only allows only runner 'local', not 'codex'" (2026-09-12).
    import importlib
    from unittest.mock import MagicMock

    from cube.config import ProjectRunnerProfile
    from cube.router.policy import Queued

    engine_settings.projects["demo"] = ProjectRunnerProfile(
        path=engine_settings.root, runner="codex"
    )
    fake_bd.add(
        "cube-p",
        title="push the source",
        labels=["project:demo", "role:liaison"],
        description=header("local-only"),
    )
    choose = MagicMock(side_effect=Queued("stop before execution"))
    monkeypatch.setattr(importlib.import_module("cube.engine.run"), "choose", choose)
    report = execute(engine_settings, "liaison", bead="cube-p", runner_name="claude@local")
    assert report.state == "queued", report.error
    assert choose.call_args.kwargs["requested_runner"] == "claude@local"


def test_design_brief_hands_the_bead_to_the_programmer(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    # cube-r1n.6: the senior wrote the worker brief, returned close=false, and then
    # re-verified its own brief for three more turns because nothing ran a programmer.
    fake_bd.add(
        "cube-d",
        title="publication spec",
        labels=["stage:design", "agent:research-software", "intake:goal"],
        description=header(),
    )
    result = RunResult(
        summary="brief written",
        artifacts=[{"kind": "brief", "path": "runs/x/r1n.6-spec.md", "summary": "worker brief"}],  # type: ignore[list-item]
        bead_updates=[{"bead": "cube-d", "comment": "handoff", "close": False}],  # type: ignore[list-item]
    )
    report = execute(
        engine_settings,
        "senior",
        bead="cube-d",
        runner=StubRunner(result=result),
        runner_name="stub",
    )
    assert report.ok
    labels = set(fake_bd.bead("cube-d")["labels"])
    assert {"stage:implement", "role:programmer", "designed-by:research-software"} <= labels
    assert "stage:design" not in labels and "agent:research-software" not in labels
    assert fake_bd.bead("cube-d")["status"] == "open"
    assert any("design handed to programmer" in n for n in report.applied["notes"])
    # a partial checkpoint without a brief keeps the design stage
    fake_bd.add(
        "cube-e", title="spec", labels=["stage:design", "role:senior"], description=header()
    )
    partial = RunResult(
        summary="notes only",
        bead_updates=[{"bead": "cube-e", "close": False}],  # type: ignore[list-item]
    )
    execute(
        engine_settings,
        "senior",
        bead="cube-e",
        runner=StubRunner(result=partial),
        runner_name="stub",
    )
    assert "stage:design" in fake_bd.bead("cube-e")["labels"]
