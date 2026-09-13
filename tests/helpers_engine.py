"""Shared fixtures for the engine tests: a temp repo with real roles and a fake `bd`."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from cube.config import Settings, load_settings
from cube.runners.base import ExecResult
from cube.testing.fakebd import FakeBd

REPO_ROOT = Path(__file__).resolve().parents[1]

CUBE_YAML = """\
host: testhost
paths: {pa: pa, org: org, rkg: rkg, runs: runs, state: state, skills_library: skills-lib}
slots: {plan: 1, implement: 2, bulk: 4, local: 1}
tiers:
  plan:
    - {runner: claude, model: fable}
    - {runner: claude, model: opus}
  implement:
    - {runner: codex, profile: cube-chatgpt}
    - {runner: claude, model: sonnet}
    - {runner: openrouter, model: qwen/qwen3-coder}
  bulk:
    - {runner: openrouter, model: z-ai/glm-5.3-flash}
    - {runner: local}
  local:
    - {runner: local}
budget: {plan_runs_per_day: 2, implement_runs_per_day: 3}
decisions: {systems: [borg-server, ontolinator, leechuck.de, unimatrix01, ws]}
"""


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "cube.yaml").write_text(CUBE_YAML, encoding="utf-8")
    (root / ".gitignore").write_text(".env\nruns/\nstate/\n", encoding="utf-8")
    (root / "contacts.yaml").write_text("grants: {}\n", encoding="utf-8")
    for d in ("pa", "org", "rkg", "state", "runs", "skills-lib", "brain"):
        (root / d).mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "roles", root / "roles")
    shutil.copy(REPO_ROOT / "brain" / "doctrine.md", root / "brain" / "doctrine.md")
    # Synthetic roster: the engine tests never read the real people.yaml.
    shutil.copy(REPO_ROOT / "tests" / "fixtures" / "people-fleet.yaml", root / "people.yaml")
    shutil.copy(
        REPO_ROOT / "tests" / "fixtures" / "projects.jsonld",
        root / "rkg" / "projects.jsonld",
    )
    return root


def _engine_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def _engine_settings(engine_repo: Path) -> Settings:
    return load_settings(engine_repo)


def _fake_bd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeBd:
    bd = FakeBd(tmp_path)
    bd.install(monkeypatch)
    return bd


def fixtures() -> dict[str, Any]:
    """Register the shared fixtures in a test module: ``globals().update(fixtures())``."""
    return {
        "engine_repo": pytest.fixture(name="engine_repo")(_engine_repo),
        "engine_settings": pytest.fixture(name="engine_settings")(_engine_settings),
        "fake_bd": pytest.fixture(name="fake_bd")(_fake_bd),
    }


class RecordingExec:
    """Injectable exec_fn: records calls, returns canned results per command name."""

    def __init__(self, responses: dict[str, ExecResult] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.responses = responses or {}

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        stdin_devnull: bool = True,
        stdin_text: str | None = None,
    ) -> ExecResult:
        self.calls.append(
            {
                "cmd": cmd,
                "cwd": cwd,
                "env": env,
                "timeout": timeout,
                "stdin_devnull": stdin_devnull,
                "stdin_text": stdin_text,
            }
        )
        return self.responses.get(cmd[0], ExecResult(0, "", ""))
