from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.commands.adopt import AdoptError, adopt_session
from cube.config import load_settings
from cube.engine.fleet import fleet
from cube.engine.run import execute
from cube.runners.base import ExecResult
from tests.helpers_engine import FakeBd, RecordingExec, make_repo


class TmuxExec(RecordingExec):
    def __init__(self, checkout: Path, *, command: str = "codex", git_ok: bool = True):
        super().__init__()
        self.checkout = checkout
        self.command = command
        self.git_ok = git_ok
        self.session_name = "legacy"

    def __call__(self, cmd: list[str], **kwargs: Any) -> ExecResult:
        super().__call__(cmd, **kwargs)
        if cmd[:2] == ["tmux", "display-message"]:
            return ExecResult(0, f"{self.command}\t{self.checkout}\n", "")
        if cmd[:2] == ["git", "rev-parse"]:
            return (
                ExecResult(0, f"{self.checkout}\n", "")
                if self.git_ok
                else ExecResult(128, "", "not a git repository")
            )
        if cmd[:2] == ["tmux", "rename-session"]:
            self.session_name = cmd[-1]
            return ExecResult(0, "", "")
        if cmd[:3] == ["tmux", "ls", "-F"]:
            return ExecResult(0, f"{self.session_name}\t1756800000\t1\t1\n", "")
        return ExecResult(0, "", "")


def _rollout(
    sessions: Path,
    name: str,
    *,
    session_id: str,
    cwd: Path,
    source: str,
    mtime: int,
) -> Path:
    path = sessions / "2026" / "09" / "02" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "session_id": session_id,
                    "cwd": str(cwd),
                    "originator": f"codex_{source}",
                    "source": source,
                },
            }
        )
        + "\n"
        + json.dumps({"type": "response_item", "payload": {"cwd": "ignore me"}})
        + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_adopt_renames_records_and_prefers_matching_tui(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    settings = load_settings(root)
    checkout = tmp_path / "project"
    checkout.mkdir()
    sessions = tmp_path / ".codex" / "sessions"
    tui = _rollout(sessions, "tui", session_id="tui-session", cwd=checkout, source="tui", mtime=100)
    _rollout(sessions, "exec", session_id="newer-exec", cwd=checkout, source="exec", mtime=200)
    other = tmp_path / "other"
    other.mkdir()
    _rollout(sessions, "other", session_id="wrong-cwd", cwd=other, source="tui", mtime=300)
    ex = TmuxExec(checkout)

    report = adopt_session(
        settings,
        "legacy",
        project="demo",
        bead="cube-44",
        dry_run=False,
        exec_fn=ex,
        codex_sessions_root=sessions,
    )

    assert report.session == "cube/demo-codex" and report.resume_id == "tui-session"
    assert report.rollout == str(tui)
    assert [item["resume_id"] for item in report.alternatives] == ["newer-exec"]
    assert any(call["cmd"][:2] == ["tmux", "rename-session"] for call in ex.calls)
    stored = json.loads((root / "state" / "sessions.json").read_text())
    assert stored["sessions"][0]["session"] == "cube/demo-codex"
    bead_session = json.loads((root / "state" / "sessions" / "cube-44.json").read_text())
    assert bead_session["resume_id"] == "tui-session"
    event = json.loads((root / "state" / "events.jsonl").read_text().splitlines()[-1])
    assert event["event"] == "adopted" and event["resume_id"] == "tui-session"

    session = fleet(settings, exec_fn=ex)["sessions"][0]
    assert (
        session
        | {
            "project": "demo",
            "cwd": str(checkout),
            "resume_id": "tui-session",
            "adopted": True,
        }
        == session
    )


def test_adopt_without_match_and_refusals(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    settings = load_settings(root)
    checkout = tmp_path / "project"
    checkout.mkdir()
    ex = TmuxExec(checkout)
    report = adopt_session(
        settings,
        "cube/already-codex",
        project="demo",
        dry_run=True,
        exec_fn=ex,
        codex_sessions_root=tmp_path / "empty",
    )
    assert report.resume_id is None and report.commands == []
    assert "adopting without one" in report.message
    assert not (root / "state" / "sessions.json").exists()

    try:
        adopt_session(
            settings,
            "legacy",
            project="demo",
            exec_fn=TmuxExec(checkout, git_ok=False),
        )
    except AdoptError as exc:
        assert "not a git checkout" in str(exc)
    else:
        raise AssertionError("non-git pane path was accepted")


def test_adopted_bead_resume_appears_in_codex_dry_run(tmp_path: Path, monkeypatch: Any) -> None:
    root = make_repo(tmp_path)
    checkout = tmp_path / "project"
    checkout.mkdir()
    with (root / "cube.yaml").open("a", encoding="utf-8") as stream:
        stream.write(
            f"\nprojects:\n  demo:\n    path: {checkout}\n    runner: codex\n    cwd: checkout\n"
        )
    settings = load_settings(root)
    fake_bd = FakeBd(tmp_path)
    fake_bd.install(monkeypatch)
    fake_bd.add(
        "cube-45",
        title="Continue session",
        labels=["stage:implement", "project:demo"],
        description="---\nxid: test:45\nprivacy: internal\n---\n",
    )
    sessions = tmp_path / ".codex" / "sessions"
    _rollout(sessions, "resume", session_id="resume-this", cwd=checkout, source="tui", mtime=100)
    adopt_session(
        settings,
        "legacy",
        project="demo",
        bead="cube-45",
        dry_run=False,
        exec_fn=TmuxExec(checkout),
        codex_sessions_root=sessions,
    )

    report = execute(
        settings,
        "programmer",
        bead="cube-45",
        resume=True,
        dry_run=True,
        beads=Beads(bin="bd", cwd=root, dry_run=True),
        available=lambda _runner: True,
    )
    assert report.ok and report.command[:4] == ["codex", "exec", "resume", "resume-this"]
