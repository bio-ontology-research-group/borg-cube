from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cube.cli import main
from cube.config import load_settings
from cube.sync.context import SourceContext
from cube.sync.derivers import derive_courses


def _course_repo(tmp_path: Path) -> Path:
    org_dir = tmp_path / "org"
    rkg_dir = tmp_path / "rkg"
    org_dir.mkdir()
    rkg_dir.mkdir()
    (org_dir / "cs999.org").write_text(
        """#+TITLE: Testable Algorithms
#+COURSE_CODE: CS 999
#+SEMESTER: Fall 2026
#+MATERIALS: syllabus.pdf
* Lectures
** Lecture 1: Foundations :lecture:
SCHEDULED: <2026-09-05 Sat>
[[file:slides/01.pdf][Slides]]
** DONE Lecture 2: Applications
:PROPERTIES:
:DATE: 2026-09-12
:MATERIALS: notebooks/02.ipynb
:END:
* Deadlines
** TODO Reading response <2026-08-30 Sun>
** TODO Project proposal
DEADLINE: <2026-09-20 Sun>
""",
        encoding="utf-8",
    )
    (tmp_path / "special.org").write_text(
        """#+TITLE: Special topics
#+COURSE_CODE: CS 888
#+SEMESTER: Spring 2027
* Lectures
** Week 1: Introduction
SCHEDULED: <2027-01-15 Fri>
""",
        encoding="utf-8",
    )
    (rkg_dir / "projects.jsonld").write_text(
        json.dumps(
            {
                "@graph": [
                    {
                        "@id": "borg-id:person/robert-test",
                        "@type": "foaf:Person",
                        "foaf:name": "Robert Test",
                    },
                    {
                        "@id": "borg-id:course/test-2026",
                        "@type": "borg:Course",
                        "schema:name": "RKG title",
                        "borg:courseCode": "CS 999",
                        "borg:year": 2026,
                        "borg:instructor": [{"@id": "borg-id:person/robert-test"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "cube.yaml").write_text(
        f"paths:\n  org: {org_dir}\n  rkg: {rkg_dir}\n"
        "course_files:\n  - special.org\n"
        "beads: {bin: bd-does-not-exist}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_course_deriver_stable_xids_and_provenance(tmp_path: Path) -> None:
    root = _course_repo(tmp_path)
    ctx = SourceContext(load_settings(root), date(2026, 9, 2), github_details=False)
    desired = derive_courses(ctx)
    by_xid = {bead.xid: bead for bead in desired}

    course = by_xid["course:cs999:fall-2026"]
    assert course.type_ == "epic" and course.kind.value == "course"
    assert course.header.deadline == date(2026, 9, 20)
    assert {item.source for item in course.header.provenance} == {
        str(root / "org" / "cs999.org"),
        str(root / "rkg" / "projects.jsonld"),
    }
    lecture = by_xid["lecture:cs999:fall-2026:1"]
    assert lecture.parent_xid == course.xid
    assert lecture.header.deadline == date(2026, 9, 5)
    assert "slides/01.pdf" in lecture.body
    assert by_xid["lecture:cs999:fall-2026:2"].closed
    assert "course:cs888:spring-2027" in by_xid
    assert "lecture:cs888:spring-2027:1" in by_xid


def test_courses_command_json_and_plain_text(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = _course_repo(tmp_path)
    assert main(["--root", str(root), "courses", "--json", "--today", "2026-09-02"]) == 0
    payload = json.loads(capsys.readouterr().out)
    course = next(row for row in payload["courses"] if row["code"] == "CS 999")
    assert course["title"] == "Testable Algorithms"
    assert course["semester"] == "Fall 2026" and course["instructor"] == "Robert Test"
    assert course["lectures"][0] == {
        "number": 1,
        "date": "2026-09-05",
        "topic": "Foundations",
        "materials": ["slides/01.pdf"],
        "source": f"{root / 'org' / 'cs999.org'}:6",
    }
    assert [deadline["title"] for deadline in course["upcoming_deadlines"]] == ["Project proposal"]
    assert [item["xid"] for item in course["work_items"]] == [
        "course:cs999:fall-2026",
        "lecture:cs999:fall-2026:1",
        "lecture:cs999:fall-2026:2",
    ]
    assert "syllabus.pdf" in course["materials"]

    assert main(["--root", str(root), "courses", "--today", "2026-09-02"]) == 0
    output = capsys.readouterr().out
    assert "CS 999: Testable Algorithms [Fall 2026]" in output
    assert "due 2026-09-20  Project proposal" in output
