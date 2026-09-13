from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cube.cli import main
from cube.commands import doctor_cockpit
from cube.commands.doctor_cockpit import GitVersion, cockpit_check, update_command


def test_cockpit_check_reports_exact_remote_update(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor_cockpit, "git_version", lambda root: GitVersion("abc123", False))
    monkeypatch.setattr(
        doctor_cockpit,
        "remote_git_version",
        lambda host, root: GitVersion("def456", True),
    )

    check = cockpit_check(tmp_path, "ws")

    assert not check.ok
    assert check.name == "cockpit:version-skew"
    assert check.severity == "warn"
    assert "laptop abc123" in check.detail
    assert "ws def456 dirty" in check.detail
    assert update_command("ws", tmp_path) in check.detail
    assert "git -C" in check.detail and "pull --ff-only" in check.detail


def test_remote_git_version_uses_bounded_noninteractive_ssh(monkeypatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_run(
        command: list[str], *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        assert cwd is None
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="abc123\n M changed\n", stderr="")

    monkeypatch.setattr(doctor_cockpit, "_run", fake_run)

    assert doctor_cockpit.remote_git_version("ws", tmp_path) == GitVersion("abc123", True)
    assert seen == [
        [
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "ws",
            "--",
            f"git -C {tmp_path} rev-parse --short HEAD && git -C {tmp_path} status --porcelain",
        ]
    ]


def test_status_advertises_checkout_and_parser_commands(repo: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from cube.commands import status_fleet

    monkeypatch.setattr(status_fleet, "git_version", lambda root: GitVersion("abc123", False))

    assert main(["--root", str(repo), "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["version"]["git"] == "abc123"
    assert payload["version"]["dirty"] is False
    assert isinstance(payload["version"]["git"], str)
    assert isinstance(payload["version"]["dirty"], bool)
    assert {"status", "goals", "agent", "doctor"} <= set(payload["version"]["commands"])


def test_doctor_cockpit_option_includes_skew_check(repo: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        doctor_cockpit,
        "cockpit_check",
        lambda root, host: doctor_cockpit.Check("cockpit:version-skew", False, f"{host} behind"),
    )

    main(["--root", str(repo), "doctor", "--cockpit", "--host", "ws", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert {check["name"] for check in payload["checks"]} >= {"cockpit:version-skew"}
