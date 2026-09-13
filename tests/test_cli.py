import json
from pathlib import Path

from cube.cli import main


def test_doctor_json(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    rc = main(["--root", str(repo), "doctor", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert "checks" in out and isinstance(rc, int)


def test_contact_flow(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "--root",
                str(repo),
                "contact",
                "check",
                "alex-example",
                "mattermost_dm",
                "weekly-checkin",
            ]
        )
        == 3
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(repo),
                "contact",
                "grant",
                "alex-example",
                "mattermost_dm",
                "--scope",
                "weekly-checkin",
            ]
        )
        == 0
    )
    assert "DRY-RUN" in capsys.readouterr().out
    assert (
        main(
            [
                "--root",
                str(repo),
                "contact",
                "check",
                "alex-example",
                "mattermost_dm",
                "weekly-checkin",
            ]
        )
        == 3
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(repo),
                "contact",
                "grant",
                "alex-example",
                "mattermost_dm",
                "--scope",
                "weekly-checkin",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "--root",
                str(repo),
                "contact",
                "check",
                "alex-example",
                "mattermost_dm",
                "weekly-checkin",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--root", str(repo), "contact", "allowlist", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["people"] == ["alex-example"]


def test_kill_switch(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    main(["--root", str(repo), "kill", "on"])
    assert (repo / "state" / "KILL").exists()
    main(["--root", str(repo), "kill", "off"])
    assert not (repo / "state" / "KILL").exists()


def test_notify_hook_stdin(repo: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    import io
    import sys

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"hook_event_name": "Stop", "cwd": "/a/b", "session_id": "s1"})),
    )
    assert main(["--root", str(repo), "notify", "--hook", "--session", "x", "--json"]) == 0
    ev = json.loads(capsys.readouterr().out)
    assert ev["event"] == "stop" and ev["session"] == "x" and ev["resume_id"] == "s1"
    assert (repo / "state" / "events.jsonl").exists()


def test_cli_puts_user_bin_dirs_on_path(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A non-login ssh shell has no ~/.local/bin, so bd was never found from the cockpit."""
    from cube.cli import ensure_user_bin_on_path

    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    env = {"PATH": "/usr/bin:/bin"}
    path = ensure_user_bin_on_path(env)
    assert path.split(":") == [str(home / ".local" / "bin"), "/usr/bin", "/bin"]
    assert ensure_user_bin_on_path(env) == path  # idempotent
    assert ensure_user_bin_on_path({"PATH": ""}).split(":") == [str(home / ".local" / "bin")]


def test_github_comment_placeholders_do_not_shadow_login():
    from cube.config import clean_github_environment

    env = {"GH_TOKEN": "  # example comment", "GITHUB_TOKEN": "", "OTHER": "untouched"}
    clean_github_environment(env)
    assert env == {"OTHER": "untouched"}
    scoped = {"GH_TOKEN": "real-scoped-token"}
    clean_github_environment(scoped)
    assert scoped == {"GH_TOKEN": "real-scoped-token"}
