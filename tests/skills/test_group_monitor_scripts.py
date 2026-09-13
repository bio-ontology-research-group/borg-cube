# ruff: noqa: E501
"""Tests for the group-monitor skill scripts.

Covers papers_state.py, repos_state.py, students_state.py, diff_state.py and
briefing_render.py with a synthetic org tree (including an Emacs lock file), a
synthetic git repository and hand-written snapshots.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "group-monitor"
SCRIPTS = SKILL / "scripts"
THRESHOLDS = SKILL / "assets" / "thresholds.yaml"
TEMPLATE = SKILL / "assets" / "briefing-template.md"
TODAY = dt.date(2026, 9, 2)


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"gm_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


papers_state = load("papers_state")
repos_state = load("repos_state")
students_state = load("students_state")
diff_state = load("diff_state")
briefing_render = load("briefing_render")

PAPERS_ORG = """\
#+TODO: READY_TO_SUBMIT SUBMITTED REVISING PAUSED TODO | PUBLISHED CANCELED
#+OPTIONS: toc:1

* In preparation

** Metabolic reconstruction
- Alex

* Pipeline

** SUBMITTED Genome-scale evaluation
- submitted <2026-03-01 Sun>
** REVISING Inductive GDA
- reviews back [2026-08-20 Thu]
** READY_TO_SUBMIT Nanobody design                                  :PAPER:
** PUBLISHED Saudi Pangenome
CLOSED: [2026-06-01 Mon]
** TODO New idea
"""

PERSON_ORG = """\
#+STARTUP: overview
* 3 September 2026, weekly 1:1
- [ ] send draft (alex) <2026-09-10 Thu>
* Notes
** Meeting 16 November 2025
- discussed plan
** Group meeting 15 Feb 2025
* Projects
*** Meeting with Paul <2025-10-26 Sun>
"""

STALE_ORG = """\
* Final-year plan
- chapters
* Notes
** Discussion 6 November 2025
- things
"""

PEOPLE = """\
people:
  alex-example: {name: Alex Example, role: student, program: PhD-Bioeng, start: 2025-01-01, org_file: alex.org}  # noqa: E501
  bea-sample: {name: Bea Sample, role: student, program: PhD-CS, start: 2022-08-21, org_file: bea.org}  # noqa: E501
  nobody: {name: No File, role: student, program: MS-CS}
  carla: {name: Carla, role: staff, org_file: carla.org}
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x",
            "GIT_AUTHOR_DATE": "2026-01-15T10:00:00",
            "GIT_COMMITTER_DATE": "2026-01-15T10:00:00",
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = tmp_path / "toolrepo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("# tool\n", encoding="utf-8")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    git(r, "tag", "v0.1.0")
    return r


# --------------------------------------------------------------------------- papers


def test_papers_state_uses_file_todo_sequence(tmp_path: Path) -> None:
    path = tmp_path / "papers.org"
    path.write_text(PAPERS_ORG, encoding="utf-8")
    state = papers_state.build_state(path, use_mtime=False, today=TODAY)
    assert state["todo_sequence"] == ["READY_TO_SUBMIT", "SUBMITTED", "REVISING", "PAUSED", "TODO"]
    assert state["done_states"] == ["PUBLISHED", "CANCELED"]
    by_title = {p["title"]: p for p in state["papers"]}
    assert "Metabolic reconstruction" not in by_title  # no keyword, not a paper
    assert by_title["Genome-scale evaluation"]["state"] == "SUBMITTED"
    assert by_title["Genome-scale evaluation"]["last_touched"] == "2026-03-01"
    assert by_title["Genome-scale evaluation"]["days_since_touch"] == 185
    assert by_title["Inductive GDA"]["last_touched"] == "2026-08-20"
    assert by_title["Nanobody design"]["tags"] == ["PAPER"]
    assert by_title["Nanobody design"]["last_touched"] is None
    assert by_title["Saudi Pangenome"]["done"] is True
    assert by_title["Saudi Pangenome"]["last_touched"] == "2026-06-01"
    assert state["counts"]["SUBMITTED"] == 1
    assert by_title["New idea"]["source"].endswith("papers.org:18")


def test_papers_state_cli(tmp_path: Path, capsys) -> None:
    path = tmp_path / "papers.org"
    path.write_text(PAPERS_ORG, encoding="utf-8")
    out = tmp_path / "papers.json"
    assert (
        papers_state.main(
            ["--papers", str(path), "--out", str(out), "--mtime", "--today", "2026-09-02"]
        )
        == 0
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    nano = next(p for p in data["papers"] if p["title"] == "Nanobody design")
    assert nano["last_touched_from"] == "mtime"
    assert papers_state.main(["--papers", str(tmp_path / "none.org")]) == 1


def test_parse_todo_line_variants() -> None:
    assert papers_state.parse_todo_line("TODO(t) NEXT | DONE(d)") == (["TODO", "NEXT"], ["DONE"])
    assert papers_state.parse_todo_line("TODO DONE") == (["TODO"], ["DONE"])


# --------------------------------------------------------------------------- repos


def test_repos_state_reads_git_facts(repo: Path, tmp_path: Path) -> None:
    state = repos_state.repo_state(repo, TODAY, use_gh=False)
    assert state["last_commit"] == "2026-01-15"
    assert state["days_since_commit"] == 230
    assert state["default_branch"] == "main"
    assert state["ci_config"] == [".github/workflows"]
    assert state["last_tag"] == "v0.1.0"
    assert state["release_lag_days"] == 0
    assert state["dirty"] is False
    assert state["open_issues"] is None
    missing = repos_state.repo_state(tmp_path / "nope", TODAY, use_gh=False)
    assert missing["error"] == "not a git repository"
    assert repos_state.github_slug("git@github.com:borg/tool.git") == "borg/tool"
    assert repos_state.github_slug("https://gitlab.com/x/y.git") is None


def test_repos_state_cli(repo: Path, tmp_path: Path, capsys) -> None:
    listing = tmp_path / "repos.txt"
    listing.write_text(f"# repos\n{repo}\n", encoding="utf-8")
    out = tmp_path / "repos.json"
    assert (
        repos_state.main(["--repos-file", str(listing), "--out", str(out), "--today", "2026-09-02"])
        == 0
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["kind"] == "repos" and data["repos"][0]["name"] == "toolrepo"
    assert repos_state.main([]) == 1


# --------------------------------------------------------------------------- students


@pytest.fixture
def org_tree(tmp_path: Path) -> tuple[Path, Path]:
    org = tmp_path / "org"
    org.mkdir()
    (org / "alex.org").write_text(PERSON_ORG, encoding="utf-8")
    (org / "bea.org").write_text(STALE_ORG, encoding="utf-8")
    (org / "#bea.org#").write_text("lock", encoding="utf-8")  # open in Emacs
    (org / "carla.org").write_text("* Notes\n", encoding="utf-8")
    people = tmp_path / "people.yaml"
    people.write_text(PEOPLE, encoding="utf-8")
    return org, people


def test_students_state_finds_meetings_and_locks(org_tree, tmp_path: Path) -> None:
    org, people = org_tree
    ms_dir = tmp_path / "milestones"
    ms_dir.mkdir()
    (ms_dir / "bea-sample.json").write_text(
        json.dumps(
            {
                "milestones": [
                    {
                        "id": "qualifier",
                        "label": "Qualifying exam",
                        "deadline": "2023-12-15",
                        "status": "passed",
                        "days_left": -992,
                    },
                    {
                        "id": "defense",
                        "label": "Dissertation defense",
                        "deadline": "2027-08-21",
                        "status": "upcoming",
                        "days_left": 353,
                    },
                ],
                "flags": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "students.json"
    rc = students_state.main(
        [
            "--org-dir",
            str(org),
            "--people",
            str(people),
            "--milestones-dir",
            str(ms_dir),
            "--out",
            str(out),
            "--today",
            "2026-09-02",
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["privacy"] == "local-only"
    by = {s["slug"]: s for s in data["students"]}
    assert set(by) == {"alex-example", "bea-sample", "nobody"}  # staff excluded
    assert by["alex-example"]["last_meeting"] == "2026-09-03"
    assert by["alex-example"]["meeting_entries"] == 4
    assert by["alex-example"]["org_locked"] is False
    assert by["bea-sample"]["last_meeting"] == "2025-11-06"
    assert by["bea-sample"]["days_since_meeting"] == 300
    assert by["bea-sample"]["org_locked"] is True
    assert by["bea-sample"]["final_year_plan"] is True
    assert by["bea-sample"]["next_milestone"]["id"] == "defense"
    assert by["bea-sample"]["expected_defense"] == "2027-08-21"
    assert by["nobody"]["error"] == "no org_file in people.yaml"


def test_heading_date_forms() -> None:
    hd = students_state.heading_date
    assert hd("Meeting 16 November 2023", None) == dt.date(2023, 11, 16)
    assert hd("Group meeting 15 Feb 2024", None) == dt.date(2024, 2, 15)
    assert hd("Meeting with Paul <2023-10-26 Thu>", None) == dt.date(2023, 10, 26)
    assert hd("21 April, practice talk", 2026) == dt.date(2026, 4, 21)
    assert hd("Projects", 2026) is None


# --------------------------------------------------------------------------- diff and render


def snapshots(tmp_path: Path):
    prev_papers = {
        "kind": "papers",
        "generated": "2026-08-26",
        "source": "papers.org",
        "done_states": ["PUBLISHED", "CANCELED"],
        "papers": [
            {
                "title": "Genome-scale evaluation",
                "state": "SUBMITTED",
                "days_since_touch": 178,
                "last_touched": "2026-03-01",
                "source": "papers.org:8",
            },
            {
                "title": "Inductive GDA",
                "state": "REVISING",
                "days_since_touch": 40,
                "last_touched": "2026-07-17",
                "source": "papers.org:10",
            },
            {
                "title": "Saudi Pangenome",
                "state": "SUBMITTED",
                "days_since_touch": 10,
                "last_touched": "2026-08-16",
                "source": "papers.org:12",
            },
        ],
    }
    cur_papers = {
        "kind": "papers",
        "generated": "2026-09-02",
        "source": "papers.org",
        "done_states": ["PUBLISHED", "CANCELED"],
        "papers": [
            {
                "title": "Genome-scale evaluation",
                "state": "SUBMITTED",
                "days_since_touch": 185,
                "last_touched": "2026-03-01",
                "source": "papers.org:8",
            },
            {
                "title": "Inductive GDA",
                "state": "REVISING",
                "days_since_touch": 13,
                "last_touched": "2026-08-20",
                "source": "papers.org:10",
            },
            {
                "title": "Saudi Pangenome",
                "state": "PUBLISHED",
                "days_since_touch": 1,
                "last_touched": "2026-09-01",
                "source": "papers.org:12",
            },
            {
                "title": "Nanobody design",
                "state": "READY_TO_SUBMIT",
                "days_since_touch": None,
                "last_touched": None,
                "source": "papers.org:14",
            },
        ],
    }
    cur_repos = {
        "kind": "repos",
        "generated": "2026-09-02",
        "repos": [
            {
                "name": "idle-tool",
                "source": "/r/idle-tool",
                "days_since_commit": 200,
                "open_issues": 3,
                "last_commit_hash": "aaa",
                "last_tag": "v1",
                "release_lag_days": 400,
                "ci_status": "failing",
            },
            {
                "name": "busy-tool",
                "source": "/r/busy-tool",
                "days_since_commit": 2,
                "open_issues": 9,
                "last_commit_hash": "ccc",
                "last_tag": "v2.1",
                "release_lag_days": 3,
            },
        ],
    }
    prev_repos = {
        "kind": "repos",
        "generated": "2026-08-26",
        "repos": [
            {
                "name": "idle-tool",
                "source": "/r/idle-tool",
                "days_since_commit": 193,
                "open_issues": 3,
                "last_commit_hash": "aaa",
                "last_tag": "v1",
                "release_lag_days": 400,
                "ci_status": "failing",
            },
            {
                "name": "busy-tool",
                "source": "/r/busy-tool",
                "days_since_commit": 1,
                "open_issues": 9,
                "last_commit_hash": "bbb",
                "last_tag": "v2.0",
                "release_lag_days": 3,
            },
        ],
    }
    cur_students = {
        "kind": "students",
        "generated": "2026-09-02",
        "privacy": "local-only",
        "students": [
            {
                "slug": "alex-example",
                "org_file": "alex.org",
                "last_meeting": "2026-09-01",
                "last_meeting_source": "alex.org:1",
                "days_since_meeting": 1,
                "new_member": False,
            },
            {
                "slug": "bea-sample",
                "org_file": "bea.org",
                "last_meeting": "2025-11-06",
                "last_meeting_source": "bea.org:4",
                "days_since_meeting": 300,
                "new_member": False,
                "next_milestone": {
                    "id": "defense",
                    "label": "Dissertation defense",
                    "deadline": "2026-10-15",
                    "days_left": 43,
                    "status": "due-soon",
                },
                "milestone_flags": [
                    {
                        "kind": "overdue",
                        "milestone": "proposal",
                        "message": "proposal was due 2025-12-15",
                    }
                ],
                "expected_defense": "2026-10-15",
                "final_year_plan": False,
            },
        ],
    }
    services = {
        "kind": "services",
        "generated": "2026-09-01T06:00:00",
        "interval_minutes": 60,
        "checks": [
            {"name": "vllm", "status": "fail", "detail": "no /v1/models"},
            {"name": "web", "status": "ok"},
        ],
    }
    teaching = {
        "kind": "teaching",
        "deadlines": [
            {
                "course": "CS249",
                "item": "syllabus",
                "due": "2026-09-10",
                "artifact": None,
                "source": "teaching.org:5",
            },
            {"course": "CS321", "item": "grades", "due": "2026-09-05", "artifact": "grades.csv"},
        ],
    }
    files = {}
    for name, data in [
        ("prev_papers", prev_papers),
        ("cur_papers", cur_papers),
        ("cur_repos", cur_repos),
        ("prev_repos", prev_repos),
        ("cur_students", cur_students),
        ("services", services),
        ("teaching", teaching),
    ]:
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        files[name] = p
    return files


def test_diff_state_signals(tmp_path: Path) -> None:
    f = snapshots(tmp_path)
    out = tmp_path / "signals.json"
    rc = diff_state.main(
        [
            "--current",
            str(f["cur_papers"]),
            "--current",
            str(f["cur_repos"]),
            "--current",
            str(f["cur_students"]),
            "--current",
            str(f["services"]),
            "--current",
            str(f["teaching"]),
            "--previous",
            str(f["prev_papers"]),
            "--previous",
            str(f["prev_repos"]),
            "--previous",
            str(tmp_path / "absent.json"),
            "--thresholds",
            str(THRESHOLDS),
            "--out",
            str(out),
            "--today",
            "2026-09-02",
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    ids = {s["id"]: s for s in data["signals"]}
    assert ids["papers:submitted_max_days:Genome-scale evaluation"]["severity"] == "attention"
    assert "papers:revising_idle_days:Inductive GDA" not in ids
    assert ids["cleared:papers:revising_idle_days:Inductive GDA"]["severity"] == "cleared"
    assert ids["papers:transition:Saudi Pangenome"]["severity"] == "positive"
    assert ids["papers:new:Nanobody design"]["severity"] == "change"
    assert ids["papers:waiting:Nanobody design"]["severity"] == "waiting"
    assert ids["repos:idle_days_with_open_issues:idle-tool"]["severity"] == "attention"
    assert ids["repos:release_lag_days:idle-tool"]["severity"] == "attention"
    assert ids["repos:ci_failing:idle-tool"]["severity"] == "attention"
    assert ids["repos:commits:busy-tool"]["severity"] == "change"
    assert ids["repos:release:busy-tool"]["severity"] == "positive"
    assert ids["students:meeting_gap_days:bea-sample"]["privacy"] == "local-only"
    assert ids["students:milestone_window_days:bea-sample:defense"]["deadline"] == "2026-10-15"
    assert ids["students:overdue:bea-sample:proposal"]["severity"] == "attention"
    assert ids["students:final_year_plan_months:bea-sample"]["severity"] == "attention"
    assert "students:meeting_gap_days:alex-example" not in ids
    assert ids["services:vllm"]["severity"] == "attention"
    assert ids["services:stale"]["severity"] == "attention"
    assert ids["teaching:deadline_window_days:CS249 syllabus"]["deadline"] == "2026-09-10"
    assert ids["teaching:ready:CS321 grades"]["severity"] == "positive"
    assert data["unchanged"]["papers"] == 2
    assert data["thresholds_version"] == "2026-09-02"
    assert data["previous_present"] == ["papers", "repos"]


def test_briefing_render_separates_students(tmp_path: Path, capsys) -> None:
    f = snapshots(tmp_path)
    signals = tmp_path / "signals.json"
    diff_state.main(
        [
            "--current",
            str(f["cur_papers"]),
            "--current",
            str(f["cur_repos"]),
            "--current",
            str(f["cur_students"]),
            "--previous",
            str(f["prev_papers"]),
            "--thresholds",
            str(THRESHOLDS),
            "--out",
            str(signals),
            "--today",
            "2026-09-02",
        ]
    )
    capsys.readouterr()
    out = tmp_path / "group.md"
    students = tmp_path / "students.md"
    args = [
        "--signals",
        str(signals),
        "--template",
        str(TEMPLATE),
        "--out",
        str(out),
        "--students-out",
        str(students),
        "--today",
        "2026-09-02",
    ]
    assert briefing_render.main(args) == 0  # dry run
    text = capsys.readouterr().out
    assert not out.exists() and not students.exists()
    assert text.startswith("# Group briefing - 2026-09-02 (Wednesday)")
    assert "bea-sample" not in text  # local-only never in the group briefing
    assert "student signal(s) need attention" in text
    assert "Genome-scale evaluation" in text and "Saudi Pangenome" in text
    assert "unchanged: 2 papers" in text
    assert "thresholds 2026-09-02" in text
    assert "—" not in text
    assert briefing_render.main([*args, "--apply"]) == 0
    assert out.exists() and students.exists()
    st = students.read_text(encoding="utf-8")
    assert "bea-sample" in st and "local-only" in st
    assert len(out.read_text(encoding="utf-8").splitlines()) <= 60


def test_briefing_render_style_gate(tmp_path: Path) -> None:
    with pytest.raises(briefing_render.RenderError):
        briefing_render.check_style("# Group Briefing Today\n", 60)
    with pytest.raises(briefing_render.RenderError):
        briefing_render.check_style("# ok\nline — dash\n", 60)
    briefing_render.check_style("# Group briefing - 2026-09-02\n## Waiting on Robert\n", 60)
