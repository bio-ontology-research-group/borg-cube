# ruff: noqa: E501
"""Tests for the mentoring-session script org_meeting_entry.py.

Uses a synthetic org tree with header lines, a Notes heading with a property
drawer, an Emacs lock file, a calendar-generated file, and session inputs in
both YAML and Markdown.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "mentoring-session"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"mse_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ome = load("org_meeting_entry")

PERSON_ORG = """\
#+STARTUP: overview
#+TITLE: Alex

* Projects
** Disease modules
- ongoing

* Notes
:PROPERTIES:
:VISIBILITY: children
:END:
** 20 August 2026, weekly 1:1
- summary: earlier meeting
"""

SESSION_YAML = """\
person: alex
date: 2026-09-03
topic: weekly 1:1
summary: Embeddings reproduce the published numbers; the split is open.
agenda:
  - point: baseline reproduces the numbers
    evidence: repo borg-embed, commits 2026-08-25..2026-09-02
  - plain point without evidence
actions:
  - text: rerun the baseline with the grouped split
    owner: Alex
    due: 2026-09-10
  - text: send comments on the methods draft
    owner: Robert
decisions:
  - grouped split is primary
open:
  - which ontology version to use
skills:
  - practised writing a methods section
notes:
  - discussed the workshop rejection
flags:
  - no commits for 14 days (repo borg-embed)
"""

SESSION_MD = """\
person: alex
date: 2026-09-04
topic: draft review

## Summary
Methods draft read, argument is the problem.

## Actions
- [ ] restructure the methods section (Alex) due 2026-09-11
- [ ] send the annotated draft (Robert)

## Open
- which baseline goes in the appendix
"""


def write_session(tmp_path: Path, text: str, name: str = "session.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def org_root(tmp_path: Path) -> Path:
    root = tmp_path / "org"
    root.mkdir(exist_ok=True)
    (root / "alex.org").write_text(PERSON_ORG, encoding="utf-8")
    return root


def test_dry_run_prints_entry_and_writes_nothing(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    session = write_session(tmp_path, SESSION_YAML)
    rc = ome.main(["--input", str(session), "--org-root", str(root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "* 3 September 2026, weekly 1:1" in out
    assert "- [ ] rerun the baseline with the grouped split (Alex) <2026-09-10 Thu>" in out
    assert "- [ ] send comments on the methods draft (Robert)\n" in out
    assert "- Decided: grouped split is primary" in out
    assert "- Open: which ontology version to use" in out
    assert "- Skill practised: practised writing a methods section" in out
    assert "** Agenda" in out and "(evidence: repo borg-embed" in out
    assert "** Notes" in out
    assert "dry run, nothing written" in out
    assert (root / "alex.org").read_text(encoding="utf-8") == PERSON_ORG


def test_flags_are_reported_but_never_written(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    session = write_session(tmp_path, SESSION_YAML)
    assert ome.main(["--input", str(session), "--org-root", str(root), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "for Robert only, not written" in out
    assert "flag: no commits for 14 days (repo borg-embed)" in out
    text = (root / "alex.org").read_text(encoding="utf-8")
    assert "no commits for 14 days" not in text
    assert "flag" not in text.split("- source:")[0]


def test_apply_inserts_newest_first_under_notes(tmp_path: Path) -> None:
    root = org_root(tmp_path)
    session = write_session(tmp_path, SESSION_YAML)
    assert ome.main(["--input", str(session), "--org-root", str(root), "--apply"]) == 0
    text = (root / "alex.org").read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = lines.index("* Notes")
    assert lines[idx + 1 : idx + 4] == [":PROPERTIES:", ":VISIBILITY: children", ":END:"]
    assert lines[idx + 4] == "** 3 September 2026, weekly 1:1"
    assert lines.index("** 3 September 2026, weekly 1:1") < lines.index(
        "** 20 August 2026, weekly 1:1"
    )
    assert "*** Agenda" in lines and "*** Notes" in lines  # subheadings shifted too
    assert text.startswith("#+STARTUP: overview\n#+TITLE: Alex\n")
    assert "** Disease modules" in text and "- ongoing" in text


def test_markdown_input_and_default_top_anchor(tmp_path: Path) -> None:
    root = tmp_path / "org"
    root.mkdir()
    target = root / "bea.org"
    target.write_text("#+STARTUP: overview\n* 1 August 2026, kickoff\n- x\n", encoding="utf-8")
    session = write_session(tmp_path, SESSION_MD, name="session.md")
    rc = ome.main(
        ["--input", str(session), "--file", str(target), "--org-root", str(root), "--apply"]
    )
    assert rc == 0
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#+STARTUP: overview"
    assert lines[2] == "* 4 September 2026, draft review"
    assert "- summary: Methods draft read, argument is the problem." in lines
    assert "- [ ] restructure the methods section (Alex) <2026-09-11 Fri>" in lines
    assert "- [ ] send the annotated draft (Robert)" in lines
    assert "- Open: which baseline goes in the appendix" in lines
    assert lines.index("* 4 September 2026, draft review") < lines.index("* 1 August 2026, kickoff")


def test_refuses_emacs_lock_files(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    session = write_session(tmp_path, SESSION_YAML)
    for lock in ("#alex.org#", ".#alex.org"):
        path = root / lock
        path.write_text("lock", encoding="utf-8")
        rc = ome.main(["--input", str(session), "--org-root", str(root), "--apply"])
        err = capsys.readouterr().err
        assert rc == 2 and "open in Emacs" in err
        path.unlink()
    assert (root / "alex.org").read_text(encoding="utf-8") == PERSON_ORG


def test_refuses_target_outside_org_root(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    outside = tmp_path / "elsewhere.org"
    outside.write_text("* old\n", encoding="utf-8")
    session = write_session(tmp_path, SESSION_YAML)
    rc = ome.main(
        ["--input", str(session), "--file", str(outside), "--org-root", str(root), "--apply"]
    )
    assert rc == 2
    assert "outside the org root" in capsys.readouterr().err
    assert outside.read_text(encoding="utf-8") == "* old\n"


def test_refuses_duplicate_date_and_topic(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    session = write_session(tmp_path, SESSION_YAML)
    assert ome.main(["--input", str(session), "--org-root", str(root), "--apply"]) == 0
    capsys.readouterr()
    rc = ome.main(["--input", str(session), "--org-root", str(root), "--apply"])
    assert rc == 2
    assert "already has an entry for this date and topic" in capsys.readouterr().err
    assert (root / "alex.org").read_text(encoding="utf-8").count(
        "3 September 2026, weekly 1:1"
    ) == 1


def test_refuses_generated_calendar_file(tmp_path: Path, capsys) -> None:
    root = tmp_path / "org"
    root.mkdir()
    target = root / "work.org"
    target.write_text("* COMMENT original iCal\nBEGIN:VEVENT\nEND:VEVENT\n", encoding="utf-8")
    session = write_session(tmp_path, SESSION_YAML)
    rc = ome.main(
        ["--input", str(session), "--file", str(target), "--org-root", str(root), "--apply"]
    )
    assert rc == 2 and "VEVENT" in capsys.readouterr().err


def test_refuses_private_content(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    for bad in (
        "summary: his visa expires in December\n",
        "summary: discussed the contract renewal\n",
        "notes:\n  - grades for the course are late\n",
    ):
        session = write_session(
            tmp_path, "person: alex\ndate: 2026-09-05\ntopic: 1:1\n" + bad, name="bad.yaml"
        )
        rc = ome.main(["--input", str(session), "--org-root", str(root), "--apply"])
        assert rc == 2
        assert "never enter a meeting record" in capsys.readouterr().err
    assert (root / "alex.org").read_text(encoding="utf-8") == PERSON_ORG


def test_refuses_unclassifiable_and_extended_health_content(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    cases = (
        ("summary: The student is recovering from surgery\n", "health"),
        ("personal_context: a private matter\n", "cannot classify"),
    )
    for payload, message in cases:
        session = write_session(
            tmp_path,
            "person: alex\ndate: 2026-09-05\ntopic: 1:1\n" + payload,
            name="unclassifiable.yaml",
        )
        assert ome.main(["--input", str(session), "--org-root", str(root), "--apply"]) == 2
        assert message in capsys.readouterr().err
        assert (root / "alex.org").read_text(encoding="utf-8") == PERSON_ORG


def test_refuses_action_item_without_owner(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    session = write_session(
        tmp_path,
        "person: alex\ndate: 2026-09-06\ntopic: 1:1\nactions:\n  - rerun the baseline\n",
        name="noowner.yaml",
    )
    rc = ome.main(["--input", str(session), "--org-root", str(root), "--apply"])
    assert rc == 2
    assert "has no owner" in capsys.readouterr().err
    assert (root / "alex.org").read_text(encoding="utf-8") == PERSON_ORG


def test_rejects_bad_due_date_and_accepts_inline_owner(tmp_path: Path, capsys) -> None:
    assert ome.parse_action("write the intro (Alex) due 2026-09-10") == {
        "text": "write the intro",
        "owner": "Alex",
        "due": "2026-09-10",
    }
    root = org_root(tmp_path)
    session = write_session(
        tmp_path,
        "person: alex\ndate: 2026-09-07\ntopic: 1:1\nactions:\n  - text: x\n    owner: Alex\n    due: next week\n",
        name="baddue.yaml",
    )
    rc = ome.main(["--input", str(session), "--org-root", str(root)])
    assert rc == 2 and "use YYYY-MM-DD" in capsys.readouterr().err


def test_heading_and_stamp_helpers() -> None:
    day = dt.date(2026, 9, 3)
    assert ome.heading_text(day, "weekly 1:1") == "3 September 2026, weekly 1:1"
    assert ome.org_stamp(day) == "<2026-09-03 Thu>"


def test_help_exits_zero(capsys) -> None:
    try:
        ome.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "org file" in capsys.readouterr().out


def test_reads_the_shipped_example_asset(tmp_path: Path, capsys) -> None:
    root = org_root(tmp_path)
    example = SKILL / "assets" / "session.yaml.example"
    rc = ome.main(["--input", str(example), "--org-root", str(root)])
    assert rc == 0  # a .yaml.example suffix is still YAML, not Markdown
    out = capsys.readouterr().out
    assert "* 3 September 2026, weekly 1:1" in out
    assert "flag: no commits and no draft change for 14 days" in out
