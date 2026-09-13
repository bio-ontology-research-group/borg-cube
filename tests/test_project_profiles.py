from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.config import ProjectRunnerProfile, load_settings
from cube.doctor import check_project_paths
from cube.engine.run import execute
from cube.runners import StubRunner
from cube.runners.base import ExecResult
from tests.helpers_engine import REPO_ROOT, FakeBd, RecordingExec, make_repo


def _configured(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    sandbox: str | None = None,
    cwd: str = "checkout",
) -> tuple[Any, FakeBd, Path]:
    root = make_repo(tmp_path)
    checkout = tmp_path / "project"
    checkout.mkdir()
    settings = load_settings(root)
    settings.host = os.uname().nodename
    settings.projects["demo"] = ProjectRunnerProfile(
        path=checkout,
        runner="codex",
        sandbox=sandbox,
        cwd=cwd,
        env={"CARGO_TARGET_DIR": "$PWD/.work/target", "PROJECT_MARKER": "demo"},
        pre=["./tools/workspace-preflight.sh", "lake build -j 4"],
        worktrees_dir=Path(".work/worktrees"),
    )
    fake_bd = FakeBd(tmp_path)
    fake_bd.install(monkeypatch)
    fake_bd.add(
        "cube-90",
        title="Implement reasoner change",
        labels=["stage:implement", "project:demo"],
        description="---\nxid: test:90\nprivacy: internal\n---\n",
    )
    return settings, fake_bd, checkout


def test_profile_applies_cwd_env_and_ordered_pre_steps(tmp_path: Path, monkeypatch: Any) -> None:
    settings, _, checkout = _configured(tmp_path, monkeypatch)
    runner = StubRunner()
    pre_exec = RecordingExec({"/bin/sh": ExecResult(0, "ok", "")})

    report = execute(
        settings,
        "programmer",
        bead="cube-90",
        runner_name="stub",
        runner=runner,
        exec_fn=pre_exec,
        beads=Beads(bin="bd", cwd=settings.root),
    )

    assert report.ok and report.project == "demo" and report.cwd == str(checkout)
    assert [call["cmd"][-1] for call in pre_exec.calls] == [
        "./tools/workspace-preflight.sh",
        "lake build -j 4",
    ]
    context = runner.calls[0]
    assert context.cwd == checkout
    assert context.env == {
        "CARGO_TARGET_DIR": f"{checkout}/.work/target",
        "PROJECT_MARKER": "demo",
        "CUBE_PRIVACY": "internal",
    }
    assert report.runner_profile and report.runner_profile["effective_cwd"] == str(checkout)


def test_failing_pre_step_aborts_runner_and_writes_error_event(
    tmp_path: Path, monkeypatch: Any
) -> None:
    settings, _, _ = _configured(tmp_path, monkeypatch)
    runner = StubRunner()
    pre_exec = RecordingExec({"/bin/sh": ExecResult(23, "", "preflight rejected checkout")})

    report = execute(
        settings,
        "programmer",
        bead="cube-90",
        runner_name="stub",
        runner=runner,
        exec_fn=pre_exec,
        beads=Beads(bin="bd", cwd=settings.root),
    )

    assert not report.ok and report.state == "error"
    assert "pre-step 1/2 failed with exit 23" in (report.error or "")
    assert runner.calls == []
    events = [
        json.loads(line)
        for line in (settings.state_dir() / "events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == ["start", "error"]
    assert events[-1]["data"]["pre_step"] == "./tools/workspace-preflight.sh"


def test_danger_full_access_command_and_off_host_refusal(tmp_path: Path, monkeypatch: Any) -> None:
    settings, _, _ = _configured(tmp_path, monkeypatch, sandbox="danger-full-access")
    report = execute(
        settings,
        "programmer",
        bead="cube-90",
        resume=True,
        dry_run=True,
        beads=Beads(bin="bd", cwd=settings.root, dry_run=True),
        available=lambda _runner: True,
    )
    assert report.ok and report.command[report.command.index("--sandbox") + 1] == (
        "danger-full-access"
    )
    assert report.runner_profile and report.runner_profile["cwd"] == "checkout"
    assert report.pre_steps == ["./tools/workspace-preflight.sh", "lake build -j 4"]

    settings.host = f"not-{os.uname().nodename}"
    refused = execute(
        settings,
        "programmer",
        bead="cube-90",
        dry_run=True,
        beads=Beads(bin="bd", cwd=settings.root, dry_run=True),
        available=lambda _runner: True,
    )
    assert refused.state == "refused"
    assert "restricted to orchestration host" in (refused.error or "")
    assert refused.command == []


def test_project_worktree_directory_is_used_in_dry_run(tmp_path: Path, monkeypatch: Any) -> None:
    settings, _, checkout = _configured(tmp_path, monkeypatch, cwd="worktree")
    report = execute(
        settings,
        "programmer",
        bead="cube-90",
        runner_name="stub",
        dry_run=True,
        beads=Beads(bin="bd", cwd=settings.root, dry_run=True),
    )
    assert report.ok
    assert report.cwd == str(checkout / ".work" / "worktrees" / "cube-90")


def test_configured_profile_and_doctor_project_path_check(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "cube.yaml").write_text((REPO_ROOT / "cube.yaml").read_text(encoding="utf-8"))
    (site / "cube.local.yaml").write_text(
        "projects:\n"
        "  kobayashi-marust:\n"
        "    path: ~/Public/software/kobayashi-marust\n"
        "    runner: codex\n"
        "    sandbox: danger-full-access\n"
        "    cwd: checkout\n"
        "    env: {CARGO_TARGET_DIR: \"$PWD/.work/target\"}\n"
        "    pre: [\"./tools/workspace-preflight.sh\"]\n"
        "    worktrees_dir: .work/worktrees\n"
        "    budget_usd_per_day: 20.0\n",
        encoding="utf-8",
    )
    configured = load_settings(site).projects["kobayashi-marust"]
    assert configured.model_dump(mode="json", exclude={"remote"}) == {
        "path": "~/Public/software/kobayashi-marust",
        "runner": "codex",
        "sandbox": "danger-full-access",
        "cwd": "checkout",
        "env": {"CARGO_TARGET_DIR": "$PWD/.work/target"},
        "pre": ["./tools/workspace-preflight.sh"],
        "worktrees_dir": ".work/worktrees",
        "budget_usd_per_day": 20.0,
    }

    root = make_repo(tmp_path)
    settings = load_settings(root)
    present = tmp_path / "present"
    present.mkdir()
    settings.projects = {
        "present": ProjectRunnerProfile(path=present, runner="codex"),
        "remote": ProjectRunnerProfile(
            path=tmp_path / "missing-remote", runner="codex", remote=True
        ),
    }
    check = check_project_paths(settings)[0]
    assert check.ok and "marked remote: remote" in check.detail
    settings.projects["missing"] = ProjectRunnerProfile(path=tmp_path / "missing", runner="codex")
    check = check_project_paths(settings)[0]
    assert not check.ok and "missing=" in check.detail
