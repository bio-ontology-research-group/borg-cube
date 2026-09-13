"""ADR-0026: artifacts leave the laptop by push into the ws drop directory."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cube.beads import Beads
from cube.cli import main
from cube.config import load_settings
from cube.hosts import drop_file
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())


def _configure_hosts(repo: Path, *, drop: str | None = "/mnt/data1/cube-drop") -> None:
    path = repo / "cube.yaml"
    text = path.read_text(encoding="utf-8").replace("host: testhost", "host: laptop")
    ws = "  ws: {role: orchestration, ssh: ws" + (f", drop: {drop}" if drop else "") + "}\n"
    path.write_text(
        text + "hosts:\n" + ws + "  laptop: {role: personal, hostname: lc-dell, ssh: null}\n",
        encoding="utf-8",
    )


class FakeExec:
    """Records every command; answers sha256sum with the configured digest."""

    def __init__(self, remote_sha: str | None = None, fail: str | None = None) -> None:
        self.remote_sha = remote_sha
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if self.fail:
            return subprocess.CompletedProcess(command, 255, "", self.fail)
        if "sha256sum" in command[-1]:
            digest = self.remote_sha or "deadbeef"
            return subprocess.CompletedProcess(command, 0, f"{digest}  /x/y\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")


def _artifact(repo: Path, name: str = "report.md") -> Path:
    path = repo / name
    path.write_text("# Draft report\n\nsource: fixture\n", encoding="utf-8")
    return path


def test_dry_run_lists_the_commands_and_touches_nothing(engine_repo: Path, fake_bd: FakeBd) -> None:
    _configure_hosts(engine_repo)
    fake_bd.add("cube-a1", labels=["kind:request", "privacy:internal"])
    settings = load_settings(engine_repo)
    exec_fn = FakeExec()
    result = drop_file(
        settings,
        "ws",
        "cube-a1",
        _artifact(engine_repo),
        beads=Beads(bin="bd", cwd=engine_repo, dry_run=True),
        dry_run=True,
        exec_fn=exec_fn,
        origin="lc-dell",
    )
    assert not result.delivered and result.error == "dry run"
    assert result.remote_path == "/mnt/data1/cube-drop/cube-a1/report.md"
    assert result.sha256 and len(result.sha256) == 64 and result.bytes
    assert exec_fn.calls == []
    assert [command[0] for command in result.commands] == ["ssh", "rsync", "ssh"]
    assert (
        "install -d -m 700 /mnt/data1/cube-drop /mnt/data1/cube-drop/cube-a1"
        in result.commands[0][-1]
    )
    assert result.commands[1][-1] == "ws:/mnt/data1/cube-drop/cube-a1/report.md"
    assert "--chmod=F600,D700" in result.commands[1]
    assert "comments" not in fake_bd.bead("cube-a1")


def test_apply_pushes_verifies_the_checksum_and_points_the_bead(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _configure_hosts(engine_repo)
    fake_bd.add("cube-a1", labels=["kind:request", "privacy:internal"])
    settings = load_settings(engine_repo)
    artifact = _artifact(engine_repo)
    probe = drop_file(
        settings, "ws", "cube-a1", artifact, beads=Beads(bin="bd", cwd=engine_repo), dry_run=True
    )
    exec_fn = FakeExec(remote_sha=probe.sha256)
    result = drop_file(
        settings,
        "ws",
        "cube-a1",
        artifact,
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=exec_fn,
        origin="lc-dell",
    )
    assert result.delivered and result.error is None
    assert [command[0] for command in exec_fn.calls] == ["ssh", "rsync", "ssh"]
    comments = json.dumps(fake_bd.bead("cube-a1").get("comments"))
    assert "artifact: ws:/mnt/data1/cube-drop/cube-a1/report.md" in comments
    assert f"sha256 {probe.sha256}" in comments and "pushed from lc-dell" in comments


def test_checksum_mismatch_and_unreachable_host_are_errors_without_a_comment(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _configure_hosts(engine_repo)
    fake_bd.add("cube-a1", labels=["privacy:internal"])
    settings = load_settings(engine_repo)
    artifact = _artifact(engine_repo)
    mismatch = drop_file(
        settings,
        "ws",
        "cube-a1",
        artifact,
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=FakeExec(remote_sha="0" * 64),
    )
    assert not mismatch.delivered and "checksum mismatch" in str(mismatch.error)
    down = drop_file(
        settings,
        "ws",
        "cube-a1",
        artifact,
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=FakeExec(fail="ssh: connect to host ws port 22: No route to host"),
    )
    assert not down.delivered and "No route to host" in str(down.error)
    assert "comments" not in fake_bd.bead("cube-a1")


@pytest.mark.parametrize(
    ("labels", "name", "drop", "expected"),
    [
        (["privacy:local-only"], "report.md", "/mnt/data1/cube-drop", "local-only"),
        (["privacy:internal"], ".env", "/mnt/data1/cube-drop", "secret-looking"),
        (["privacy:internal"], "password-list.md", "/mnt/data1/cube-drop", "secret-looking"),
        (["privacy:internal"], "report.md", None, "no drop directory"),
    ],
)
def test_refusals(
    engine_repo: Path,
    fake_bd: FakeBd,
    labels: list[str],
    name: str,
    drop: str | None,
    expected: str,
) -> None:
    _configure_hosts(engine_repo, drop=drop)
    fake_bd.add("cube-a1", labels=labels)
    settings = load_settings(engine_repo)
    exec_fn = FakeExec()
    result = drop_file(
        settings,
        "ws",
        "cube-a1",
        _artifact(engine_repo, name),
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=exec_fn,
    )
    assert not result.delivered and expected in str(result.error)
    assert exec_fn.calls == [] and "comments" not in fake_bd.bead("cube-a1")


def test_cli_drop_dry_run_reports_the_target(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _configure_hosts(engine_repo)
    fake_bd.add("cube-a1", labels=["privacy:internal"])
    artifact = _artifact(engine_repo)
    assert main(["--root", str(engine_repo), "drop", "cube-a1", str(artifact), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["host"] == "ws"
    assert payload["remote_path"] == "/mnt/data1/cube-drop/cube-a1/report.md"
    assert main(["--root", str(engine_repo), "drop", "cube-zzz", str(artifact), "--json"]) == 1


def _git_checkout(root: Path) -> Path:
    """A repository with one commit, one committed-then-modified file, one untracked file."""
    repo = root / "flopoontology"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@x"

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "flopo-2.0-rebuild")
    (repo / "config").mkdir()
    (repo / "config" / "terms.tsv").write_text("id\tlabel\n1\tleaf\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    (repo / "config" / "terms.tsv").write_text("id\tlabel\n1\tleaf\n2\tstem\n", encoding="utf-8")
    (repo / "big.bin").write_bytes(b"\0" * 10)
    return repo


def test_repo_drop_ships_bundle_patch_and_manifest_and_comments_once(
    engine_repo: Path, fake_bd: FakeBd, tmp_path: Path
) -> None:
    """Robert, 2026-09-08: FLOPO lives on the laptop; a ws agent continues from its state."""
    from cube.hosts import drop_repository

    _configure_hosts(engine_repo)
    fake_bd.add("cube-r1", labels=["kind:request", "privacy:internal"])
    settings = load_settings(engine_repo)
    repo = _git_checkout(tmp_path)
    work = tmp_path / "work"

    class ShaExec(FakeExec):
        def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            if "sha256sum" in command[-1]:
                name = command[-1].rsplit("/", 1)[1]
                local = work / name
                digest = __import__("hashlib").sha256(local.read_bytes()).hexdigest()
                return subprocess.CompletedProcess(command, 0, f"{digest}  x\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

    exec_fn = ShaExec()
    result = drop_repository(
        settings,
        "ws",
        "cube-r1",
        repo,
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=exec_fn,
        origin="lc-dell",
        work_dir=work,
    )
    assert result.delivered, result.error
    assert result.remote_path == "/mnt/data1/cube-drop/cube-r1/flopoontology.bundle"
    names = sorted(path.name for path in work.iterdir())
    assert names == [
        "flopoontology.bundle",
        "flopoontology.manifest.txt",
        "flopoontology.uncommitted.patch",
    ]
    subprocess.run(
        ["git", "bundle", "verify", str(work / "flopoontology.bundle")],
        check=True,
        capture_output=True,
    )
    patch = (work / "flopoontology.uncommitted.patch").read_text(encoding="utf-8")
    assert "+2\tstem" in patch
    manifest = (work / "flopoontology.manifest.txt").read_text(encoding="utf-8")
    assert "branch: flopo-2.0-rebuild" in manifest and "big.bin" in manifest
    assert "git fetch flopoontology.bundle flopo-2.0-rebuild" in manifest
    assert [command[0] for command in exec_fn.calls] == ["ssh", "rsync", "ssh"] * 3
    comments = fake_bd.bead("cube-r1")["comments"]
    assert len(comments) == 1
    text = comments[0]["text"]
    assert "repository flopoontology pushed from lc-dell" in text
    assert text.count("artifact: ws:/mnt/data1/cube-drop/cube-r1/") == 3
    # a git-less directory is refused before anything is pushed
    plain = drop_repository(
        settings,
        "ws",
        "cube-r1",
        tmp_path,
        beads=Beads(bin="bd", cwd=engine_repo),
        dry_run=False,
        exec_fn=exec_fn,
        work_dir=tmp_path / "work2",
    )
    assert not plain.delivered and "not a git repository" in str(plain.error)
