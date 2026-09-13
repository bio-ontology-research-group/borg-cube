from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cube.cli import main
from cube.orgwrite import append_dated
from tests.helpers_engine import fixtures

globals().update(fixtures())


ORG_TEXT = """#+TITLE: Alex notes

* Notes
:PROPERTIES:
:ID: alex-notes
:END:
** 2026-08-20 Earlier entry
- [ ] Existing task

* Milestones
- Proposal
"""


def _org_file(engine_repo: Path) -> Path:
    path = engine_repo / "org" / "alex.org"
    path.write_text(ORG_TEXT, encoding="utf-8")
    return path


def test_org_append_preserves_drawer_newest_first_and_emits_event(engine_repo, capsys) -> None:
    target = _org_file(engine_repo)
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "append",
                "alex-example",
                "--heading",
                "Research plan",
                "--date",
                "2026-09-02",
                "--item",
                "Review figures",
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    text = target.read_text(encoding="utf-8")
    assert payload["applied"] is True and payload["action"] == "append"
    assert ":ID: alex-notes\n:END:\n\n** 2026-09-02 Research plan" in text
    assert text.index("2026-09-02") < text.index("2026-08-20")
    assert "- [ ] Review figures" in text
    event = json.loads((engine_repo / "state" / "events.jsonl").read_text(encoding="utf-8"))
    assert event["event"] == "org-write" and event["data"]["action"] == "append"


def test_org_refuses_lock_path_escape_ambiguous_and_private_content(engine_repo, capsys) -> None:
    target = _org_file(engine_repo)
    lock = target.parent / "#alex.org#"
    lock.touch()
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "append",
                "alex-example",
                "--heading",
                "Research",
            ]
        )
        == 2
    )
    assert "open in Emacs" in capsys.readouterr().err
    lock.unlink()
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "todo",
                "../outside.org",
                "--heading-match",
                "Notes",
                "--item",
                "anything",
            ]
        )
        == 2
    )
    assert "outside org root" in capsys.readouterr().err
    target.write_text("* Notes\n* Notes\n", encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "property",
                "alex.org",
                "--heading-match",
                "Notes",
                "--set",
                "OWNER=Robert",
            ]
        )
        == 2
    )
    assert "ambiguous" in capsys.readouterr().err
    target.write_text(ORG_TEXT, encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "append",
                "alex-example",
                "--heading",
                "Contract discussion",
            ]
        )
        == 2
    )
    assert "private content" in capsys.readouterr().err


def test_org_atomic_apply_todo_toggle_and_property(engine_repo, monkeypatch, capsys) -> None:
    target = _org_file(engine_repo)
    calls: list[tuple[str, Path]] = []
    from cube import orgwrite

    real_replace = orgwrite.os.replace

    def record_replace(source: str, destination: Path) -> None:
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(orgwrite.os, "replace", record_replace)
    result = append_dated(
        target,
        engine_repo / "org",
        heading="Atomic entry",
        day=date(2026, 9, 2),
        apply=True,
        state_dir=engine_repo / "state",
    )
    assert result.applied and calls and calls[0][1] == target
    assert not list(target.parent.glob(".alex.org.*.tmp"))

    assert (
        main(
            [
                "--root",
                str(engine_repo),
                "org",
                "todo",
                "alex.org",
                "--heading-match",
                "Earlier entry",
                "--item",
                "Existing task",
                "--done",
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
                str(engine_repo),
                "org",
                "property",
                "alex.org",
                "--heading-match",
                "Earlier entry",
                "--set",
                "OWNER=Robert",
                "--apply",
            ]
        )
        == 0
    )
    capsys.readouterr()
    updated = target.read_text(encoding="utf-8")
    assert "- [X] Existing task" in updated
    assert ":PROPERTIES:\n:OWNER: Robert\n:END:" in updated
