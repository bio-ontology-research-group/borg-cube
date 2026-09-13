from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from deploy import hermes_remote_dir, main, parse_hermes


def args_for(repo, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--skills-dir",
        str(repo.skills),
        "--manifest",
        str(repo.manifest),
        "--distilled",
        str(repo.distilled),
        "--tests-dir",
        str(repo.tests),
        "--claude-dir",
        str(tmp_path / "claude"),
        "--codex-dir",
        str(tmp_path / "codex"),
        *extra,
    ]


def test_dry_run_is_default_and_writes_nothing(skill_repo, tmp_path: Path, capsys) -> None:
    assert main(args_for(skill_repo, tmp_path, "--json")) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "dry-run"
    assert [a["kind"] for a in data["actions"]] == ["symlink", "rsync"]
    assert not (tmp_path / "claude").exists() and not (tmp_path / "codex").exists()


def test_hermes_plan(skill_repo, tmp_path: Path, capsys) -> None:
    assert main(args_for(skill_repo, tmp_path, "--hermes", "ws:advisor", "--json")) == 0
    actions = json.loads(capsys.readouterr().out)["actions"]
    assert actions[2]["argv"] == [
        "ssh",
        "ws",
        "mkdir",
        "-p",
        "~/.hermes/profiles/advisor/skills/infra/demo-skill",
    ]
    assert actions[3]["argv"][-1] == "ws:~/.hermes/profiles/advisor/skills/infra/demo-skill/"
    assert hermes_remote_dir(None, "infra", "x") == "~/.hermes/skills/infra/x"
    assert parse_hermes("ws") == ("ws", None) and parse_hermes(None) is None


def test_refuses_when_lint_fails(skill_repo, tmp_path: Path, capsys) -> None:
    skill_repo.write_skill_md(skill_repo.skill_md().replace("category: infra", "category: misc"))
    assert main(args_for(skill_repo, tmp_path, "--apply")) == 1
    assert "refusing" in capsys.readouterr().err
    assert not (tmp_path / "claude").exists()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_apply_symlinks_and_copies(skill_repo, tmp_path: Path, capsys) -> None:
    assert main(args_for(skill_repo, tmp_path, "--apply")) == 0
    capsys.readouterr()
    link = tmp_path / "claude" / "demo-skill"
    assert link.is_symlink() and link.resolve() == skill_repo.skill.resolve()
    assert (tmp_path / "codex" / "demo-skill" / "SKILL.md").read_text() == skill_repo.skill_md()
    # second run: symlink is reported as skip, rsync still planned
    assert main(args_for(skill_repo, tmp_path, "--json")) == 0
    kinds = [a["kind"] for a in json.loads(capsys.readouterr().out)["actions"]]
    assert kinds == ["skip", "rsync"]


def test_existing_directory_blocks_symlink(skill_repo, tmp_path: Path, capsys) -> None:
    (tmp_path / "claude" / "demo-skill").mkdir(parents=True)
    assert main(args_for(skill_repo, tmp_path)) == 1
    assert "not a symlink" in capsys.readouterr().err


def test_unknown_skill(skill_repo, tmp_path: Path) -> None:
    assert main(args_for(skill_repo, tmp_path, "--skill", "ghost")) == 1
