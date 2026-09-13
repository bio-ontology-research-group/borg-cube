# ruff: noqa: E501
"""Tests for the meeting-scribe skill scripts (org_append.py, actions_extract.py).

Uses a synthetic ~/org tree with header lines, a Notes heading with a property
drawer, a calendar-generated file and an Emacs lock file.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "meeting-scribe"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"ms_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


org_append = load("org_append")
actions_extract = load("actions_extract")

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
** Meeting 16 November 2025
- discussed plan
"""

ENTRY = """\
* 3 September 2026, weekly 1:1
- source: runs/42/notes.txt
- summary: Alex has the embeddings; evaluation is next.
- [ ] run the baseline (Alex Example) <2026-09-10 Thu>
** Details
- more
"""

NOTES = """\
Weekly 1:1 with Alex, 3 Sept 2026.
Alex will run the baseline by 10 September.
- [ ] write the methods section (Alex Example) by 2026-09-20
Robert to send the reviewer comments next week.
Decided: we submit to ISMB, decided by Robert, inform Alex.
Open: which ontology version to use?
TODO update the figure
Is the cluster quota enough?
The weather was nice.
"""


def test_insert_under_notes_keeps_header_and_drawer(tmp_path: Path, capsys) -> None:
    target = tmp_path / "alex.org"
    target.write_text(PERSON_ORG, encoding="utf-8")
    entry = tmp_path / "entry.org"
    entry.write_text(ENTRY, encoding="utf-8")
    rc = org_append.main(["--file", str(target), "--entry", str(entry)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "+** 3 September 2026, weekly 1:1" in out and "dry run" in out
    assert target.read_text(encoding="utf-8") == PERSON_ORG  # nothing written
    rc = org_append.main(["--file", str(target), "--entry", str(entry), "--apply"])
    assert rc == 0
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = lines.index("* Notes")
    assert lines[idx + 1 : idx + 4] == [":PROPERTIES:", ":VISIBILITY: children", ":END:"]
    assert lines[idx + 4] == "** 3 September 2026, weekly 1:1"  # newest first, re-levelled
    assert "*** Details" in lines  # nested heading shifted too
    assert lines.index("** 3 September 2026, weekly 1:1") < lines.index(
        "** Meeting 16 November 2025"
    )
    assert text.startswith("#+STARTUP: overview\n#+TITLE: Alex\n")
    assert "** Disease modules" in text and "- ongoing" in text


def test_insert_top_when_no_notes_heading(tmp_path: Path) -> None:
    target = tmp_path / "bea.org"
    target.write_text("#+STARTUP: overview\n* Todo 4 Nov 2024\n- x\n", encoding="utf-8")
    entry = tmp_path / "entry.org"
    entry.write_text(ENTRY, encoding="utf-8")
    assert org_append.main(["--file", str(target), "--entry", str(entry), "--apply"]) == 0
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#+STARTUP: overview"
    assert lines[2] == "* 3 September 2026, weekly 1:1"
    assert lines.index("* 3 September 2026, weekly 1:1") < lines.index("* Todo 4 Nov 2024")


def test_insert_end_and_heading_mode(tmp_path: Path) -> None:
    target = tmp_path / "todo.org"
    target.write_text("* TODO old\n", encoding="utf-8")
    body = tmp_path / "body.txt"
    body.write_text("DEADLINE: <2026-09-20 Sun>\n", encoding="utf-8")
    rc = org_append.main(
        [
            "--file",
            str(target),
            "--heading",
            "TODO send comments",
            "--body",
            str(body),
            "--anchor",
            "end",
            "--apply",
        ]
    )
    assert rc == 0
    assert (
        target.read_text(encoding="utf-8")
        == "* TODO old\n\n* TODO send comments\nDEADLINE: <2026-09-20 Sun>\n"
    )


def test_refuses_locks_generated_and_bad_entry(tmp_path: Path, capsys) -> None:
    target = tmp_path / "alex.org"
    target.write_text(PERSON_ORG, encoding="utf-8")
    entry = tmp_path / "entry.org"
    entry.write_text(ENTRY, encoding="utf-8")
    (tmp_path / "#alex.org#").write_text("lock", encoding="utf-8")
    assert org_append.main(["--file", str(target), "--entry", str(entry), "--apply"]) == 2
    assert "open in Emacs" in capsys.readouterr().err
    (tmp_path / "#alex.org#").unlink()
    (tmp_path / ".#alex.org").symlink_to("user@host.123:456")
    assert org_append.main(["--file", str(target), "--entry", str(entry), "--apply"]) == 2
    (tmp_path / ".#alex.org").unlink()
    cal = tmp_path / "work.org"
    cal.write_text(
        "* Event\n** COMMENT original iCal entry\nBEGIN:VEVENT\nEND:VEVENT\n", encoding="utf-8"
    )
    assert org_append.main(["--file", str(cal), "--entry", str(entry), "--apply"]) == 2
    assert "generated" in capsys.readouterr().err
    bad = tmp_path / "bad.org"
    bad.write_text("no heading here\n", encoding="utf-8")
    assert org_append.main(["--file", str(target), "--entry", str(bad)]) == 2
    assert org_append.main(["--file", str(target)]) == 2
    assert target.read_text(encoding="utf-8") == PERSON_ORG


def test_actions_extract_owners_dates_and_flags() -> None:
    result = actions_extract.extract(NOTES, dt.date(2026, 9, 3), ["Alex Example", "Robert"])
    actions = {a["text"]: a for a in result["actions"]}
    baseline = next(a for t, a in actions.items() if "baseline" in t)
    assert baseline["owner"] == "Alex Example" and baseline["deadline"] == "2026-09-10"
    methods = next(a for t, a in actions.items() if "methods" in t)
    assert methods["owner"] == "Alex Example" and methods["deadline"] == "2026-09-20"
    assert methods["owner_from"] == "parenthesis"
    reviewer = next(a for t, a in actions.items() if "reviewer" in t)
    assert reviewer["owner"] == "Robert" and reviewer["deadline"] is None
    assert reviewer["deadline_from"] == "relative"
    figure = next(a for t, a in actions.items() if "figure" in t)
    assert figure["owner"] is None and "owner unclear" in figure["flags"]
    assert result["decisions"] == ["we submit to ISMB, decided by Robert, inform Alex"]
    assert result["open"] == ["which ontology version to use?", "Is the cluster quota enough?"]
    assert result["counts"] == {"actions": 4, "without_owner": 1, "without_date": 2}
    assert not any("weather" in a["text"] for a in result["actions"])


def test_actions_extract_org_rendering_and_cli(tmp_path: Path, capsys) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text(NOTES, encoding="utf-8")
    rc = actions_extract.main(
        [
            "--notes",
            str(notes),
            "--date",
            "2026-09-03",
            "--topic",
            "weekly 1:1",
            "--attendees",
            "Alex Example,Robert",
            "--source",
            "runs/42/notes.txt",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "* 3 September 2026, weekly 1:1"
    assert lines[1] == "- source: runs/42/notes.txt"
    assert lines[2] == "- summary: [unclear]"
    assert (
        "- [ ] Alex will run the baseline by 10 September (Alex Example) <2026-09-10 Thu>" in lines
    )
    assert "- [ ] update the figure ([unclear])" in lines
    assert any(
        line.startswith(
            "- [ ] Robert to send the reviewer comments next week (Robert) [unclear: relative date"
        )
        for line in lines
    )
    assert "- Decided: we submit to ISMB, decided by Robert, inform Alex" in lines
    assert "- Open: which ontology version to use?" in lines
    assert "—" not in out
    rc = actions_extract.main(["--notes", str(notes), "--date", "2026-09-03", "--format", "json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["actions"] == 4
    assert actions_extract.main(["--notes", str(tmp_path / "none.txt")]) == 1


def test_parse_deadline_year_rollover() -> None:
    date, how = actions_extract.parse_deadline("finish by 5 January", dt.date(2026, 12, 20))
    assert date == "2027-01-05" and how == "text"
    assert actions_extract.parse_deadline("due Sept 10", dt.date(2026, 9, 3))[0] == "2026-09-10"
    assert (
        actions_extract.parse_deadline("<2026-10-01 Thu>", dt.date(2026, 9, 3))[0] == "2026-10-01"
    )
    assert actions_extract.parse_deadline("no date here", dt.date(2026, 9, 3)) == (None, "none")
