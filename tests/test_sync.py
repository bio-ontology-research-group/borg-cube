import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from cube.beads import Beads
from cube.cli import main
from cube.config import Settings, load_settings
from cube.model import BeadHeader
from cube.sync.context import SourceContext
from cube.sync.derivers import (
    DesiredBead,
    derive_all,
    derive_conflicts,
    derive_deadlines,
    derive_kg_stale,
    derive_meetings,
    derive_papers,
    derive_programs,
)
from cube.sync.reconcile import apply, index_existing, plan, summarize

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 2)


@pytest.fixture
def data_repo(tmp_path: Path) -> Path:
    """A repo root whose ~/pa, ~/org, KG and website paths point at the fixtures."""
    org = tmp_path / "org"
    pa = tmp_path / "pa"
    rkg = tmp_path / "rkg"
    web = tmp_path / "web" / "people"
    for d in (org, pa / "kg" / "projects", pa / "contacts", rkg, web, tmp_path / "state"):
        d.mkdir(parents=True)
    shutil.copy(FIX / "staff.org", org / "staff.org")
    shutil.copy(FIX / "papers.org", org / "papers.org")
    shutil.copy(FIX / "person.org", org / "alex.org")
    shutil.copy(FIX / "work.cal", org / "work.cal")
    shutil.copy(FIX / "deadlines.md", pa / "deadlines.md")
    for f in (FIX / "kg" / "projects").glob("*.md"):
        shutil.copy(f, pa / "kg" / "projects" / f.name)
    for f in (FIX / "contacts").glob("*.md"):
        shutil.copy(f, pa / "contacts" / f.name)
    shutil.copy(FIX / "projects.jsonld", rkg / "projects.jsonld")
    shutil.copy(FIX / "roster.md", web / "roster.md")
    shutil.copy(FIX / "people.yaml", tmp_path / "people.yaml")
    (tmp_path / "contacts.yaml").write_text("grants: {}\n", encoding="utf-8")
    (tmp_path / "cube.yaml").write_text(
        "host: testhost\n"
        "beads: {bin: bd-does-not-exist}\n"
        f"paths:\n  pa: {pa}\n  org: {org}\n  rkg: {rkg}\n  website: {tmp_path / 'web'}\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def ctx(data_repo: Path) -> SourceContext:
    return SourceContext(load_settings(data_repo), TODAY, github_details=False)


def _xids(beads: list[DesiredBead]) -> set[str]:
    return {b.xid for b in beads}


def test_programs_and_milestones(ctx: SourceContext) -> None:
    beads = derive_programs(ctx)
    xids = _xids(beads)
    assert "program:alex-example" in xids and "program:vic-visitor" not in xids
    assert "program:carla-staff" not in xids
    prog = next(b for b in beads if b.xid == "program:alex-example")
    assert prog.type_ == "epic" and prog.kind.value == "program"
    assert prog.header.deadline == date(2029, 1, 1)
    sources = {p.source for p in prog.header.provenance}
    assert any(s.endswith("people.yaml") for s in sources)
    assert any(s.endswith("staff.org") for s in sources)
    assert any(s.endswith("roster.md") for s in sources)
    qe = next(b for b in beads if b.xid == "milestone:alex-example:qualifying-exam")
    assert qe.parent_xid == "program:alex-example" and qe.header.deadline == date(2026, 5, 31)
    assert "status:unknown" in qe.labels
    assert any("kaust_rules" in p.source for p in qe.header.provenance)
    assert any("Preproposal: Jan 2026" in (p.locator or "") for p in qe.header.provenance)
    prop = next(b for b in beads if b.xid == "milestone:alex-example:proposal-defense")
    assert prop.deps == ["milestone:alex-example:qualifying-exam"]
    # Bea: proposal completed -> closed milestone; no start date -> estimates only
    bea_prop = next(b for b in beads if b.xid == "milestone:bea-sample:proposal-defense")
    assert bea_prop.closed and bea_prop.close_reason == "done on 2025-05-31"
    assert "milestone:bea-sample:qualifying-exam" not in xids
    # Dan: MS estimate must not leak into the PhD clock
    dan = [b for b in beads if b.xid.startswith("milestone:dan-doe:")]
    assert {b.xid.rsplit(":", 1)[1] for b in dan} == {
        "qualifying-exam",
        "proposal-defense",
        "dissertation-defense",
        "extension-limit",
    }
    assert "kind:milestone" in qe.all_labels() and "privacy:internal" in qe.all_labels()


def test_deadlines_papers_kg_conflicts(ctx: SourceContext) -> None:
    dl = derive_deadlines(ctx)
    by = {b.xid: b for b in dl}
    assert by["pa:aaaa1111"].kind.value == "service"
    assert (
        by["pa:bbbb2222"].kind.value == "paper"
        and "person:alex-example" in by["pa:bbbb2222"].labels
    )
    assert by["pa:bbbb2222"].header.deadline == date(2026, 9, 10)
    assert by["pa:cccc3333"].closed
    bare = [b for b in dl if b.xid.startswith("pa:deadline:2026-09-05:")]
    assert len(bare) == 1 and bare[0].kind.value == "service"
    assert all(
        p.locator and p.locator.endswith(("md:5", "md:6", "md:7", "md:8"))
        for b in dl
        for p in b.header.provenance
    )

    papers = derive_papers(ctx)
    pb = {b.xid: b for b in papers}
    assert (
        pb["paper:nanobodies"].closed and "paper-state:published" in pb["paper:nanobodies"].labels
    )
    assert pb["paper:enzymes"].parent_xid == "paper:empty-quarter"
    assert "person:alex-example" in pb["paper:enzymes"].labels
    assert (
        pb["paper:inductive-gda"].type_ == "epic"
        and "paper-state:revising" in pb["paper:inductive-gda"].labels
    )
    assert pb["paper:metabolic-reconstruction"].labels[1] == "paper-state:none"

    stale = derive_kg_stale(ctx)
    assert _xids(stale) == {"finding:kg-stale:test-project"}
    assert "person:alex-example" in stale[0].labels  # contact slug equals the people.yaml id
    assert "32 days ago" in stale[0].body

    conflicts = derive_conflicts(ctx)
    assert _xids(conflicts) == {"conflict:bea-sample:status"}
    assert "needs:robert" in conflicts[0].labels


def test_meetings_tomorrow(ctx: SourceContext) -> None:
    beads = derive_meetings(ctx)
    xids = _xids(beads)
    assert xids == {"meeting-note:2026-09-03:alex-example", "meeting-note:2026-09-03:bea-sample"}
    alex = next(b for b in beads if b.xid.endswith("alex-example"))
    assert alex.parent_xid == "program:alex-example" and alex.type_ == "chore"
    assert alex.header.deadline == date(2026, 9, 3) and "10:00" in alex.title


def test_derive_all_dedups_and_survives_bad_source(ctx: SourceContext) -> None:
    beads = derive_all(ctx, ["people", "people", "nope", "papers"])
    xids = [b.xid for b in beads]
    assert len(xids) == len(set(xids))
    assert any(w.startswith("unknown source") for w in ctx.warnings)
    assert any(w.startswith("duplicate xid") for w in ctx.warnings)


class FakeBeads(Beads):
    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__(bin="bd", dry_run=False)
        self.issues = issues
        self.writes: list[list[str]] = []

    def available(self) -> bool:
        return True

    def list_issues(self, *filters: str) -> list[dict[str, Any]]:
        return self.issues

    def _run(self, *args: str, write: bool = False, check: bool = True):  # type: ignore[no-untyped-def]
        self.log.append(list(args))
        if write:
            self.writes.append(list(args))
        from cube.beads import BdResult

        return BdResult(list(args), 0, "cube-new" if args[0] == "create" else "", "")


def _desired(
    xid: str, closed: bool = False, labels: list[str] | None = None, parent: str | None = None
) -> DesiredBead:
    from cube.model import WorkKind

    return DesiredBead(
        xid=xid,
        title=f"T {xid}",
        kind=WorkKind.milestone,
        labels=labels or [],
        parent_xid=parent,
        header=BeadHeader(xid=xid),
        closed=closed,
    )


def test_reconcile_plan_and_apply() -> None:
    existing_issues = [
        {
            "id": "cube-1",
            "external_ref": "a",
            "status": "open",
            "labels": ["kind:milestone", "privacy:internal"],
        },
        {
            "id": "cube-2",
            "description": BeadHeader(xid="b").render(),
            "status": "open",
            "labels": [],
        },
        {"id": "cube-3", "external_ref": "c", "status": "closed", "labels": []},
        {"id": "cube-4", "external_ref": "d", "status": "open", "labels": []},
    ]
    beads = FakeBeads(existing_issues)
    existing, warning = index_existing(beads)
    assert warning is None and set(existing) == {"a", "b", "c", "d"}
    desired = [
        _desired("a"),  # up to date
        _desired("b", labels=["person:x"]),  # labels drifted
        _desired("c"),  # closed in bd, open at source -> conflict
        _desired("d", closed=True),  # closed at source -> close
        _desired("e", parent="p"),  # new child, parent created first
        _desired("p"),  # new parent
        _desired("z", closed=True),  # closed and absent -> noop
    ]
    actions = plan(desired, existing)
    ops = {a.xid: a.op for a in actions}
    assert ops == {
        "a": "noop",
        "b": "update-labels",
        "c": "conflict",
        "d": "close",
        "e": "create",
        "p": "create",
        "z": "noop",
    }
    creates = [a.xid for a in actions if a.op == "create"]
    assert creates == ["p", "e"]
    assert next(a for a in actions if a.xid == "b").labels_add == [
        "kind:milestone",
        "privacy:internal",
        "person:x",
    ]
    summary = summarize(actions)
    assert summary["by_op"] == {
        "noop": 2,
        "update-labels": 1,
        "conflict": 1,
        "close": 1,
        "create": 2,
    }
    results = apply(actions, desired, beads, existing)
    assert all(r["ok"] for r in results)
    create_cmds = [w for w in beads.writes if w[0] == "create"]
    assert len(create_cmds) == 2
    child = create_cmds[1]
    assert child[child.index("--parent") + 1] == "cube-new"  # parent id threaded through
    assert any(w[:2] == ["close", "cube-4"] for w in beads.writes)
    assert any(w[:3] == ["label", "add", "cube-2"] for w in beads.writes)
    assert not any(w[0] == "update" for w in beads.writes)  # conflicts never reopen


def test_index_existing_without_bd(data_repo: Path) -> None:
    settings: Settings = load_settings(data_repo)
    existing, warning = index_existing(Beads(bin=settings.beads.bin, dry_run=True))
    assert existing == {} and warning is not None and "not found" in warning


def test_cli_sync_dry_run_json(data_repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    rc = main(
        [
            "--root",
            str(data_repo),
            "sync",
            "--dry-run",
            "--json",
            "--today",
            "2026-09-02",
            "--source",
            "people",
            "--source",
            "papers",
            "--source",
            "deadlines",
            "--source",
            "kg",
            "--source",
            "calendar",
            "--source",
            "conflicts",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["existing"] == 0
    assert out["summary"]["by_op"]["create"] > 10
    kinds = set(out["summary"]["by_kind"])
    assert {
        "program",
        "milestone",
        "paper",
        "service",
        "finding",
        "meeting-note",
        "conflict",
    } <= kinds
    assert all(a["op"] != "noop" for a in out["actions"])
    assert any("not found" in w for w in out["warnings"])


def test_cli_read_commands(data_repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--root", str(data_repo), "people", "--json", "--today", "2026-09-02"]) == 0
    people = json.loads(capsys.readouterr().out)["people"]
    alex = next(p for p in people if p["slug"] == "alex-example")
    assert alex["role"] == "phd" and alex["org_file"] == "~/org/alex.org"
    assert alex["last_meeting"] == "2026-04-16" and alex["program"] is None
    assert alex["next_milestone"]["name"] == "proposal defense"
    assert alex["contact"] == {"mattermost_dm": False, "email": False, "dossier_read": False}
    assert next(p for p in people if p["slug"] == "carla-staff")["role"] == "staff"
    assert next(p for p in people if p["slug"] == "vic-visitor")["role"] == "visitor"

    assert (
        main(
            ["--root", str(data_repo), "student", "alex-example", "--json", "--today", "2026-09-02"]
        )
        == 0
    )
    dossier = json.loads(capsys.readouterr().out)
    assert dossier["slug"] == "alex-example" and dossier["program"]["started"] == "2025-01-01"
    assert [m["name"] for m in dossier["milestones"]][:2] == ["qualifying exam", "proposal defense"]
    assert dossier["evidence"]["org_notes_last"] == "2026-04-16"
    assert dossier["kg_projects"][0]["slug"] == "test-project"
    assert len(dossier["deadlines"]) == 1 and dossier["deadlines"][0]["id"] == "bbbb2222"
    assert {p["slug"] for p in dossier["papers"]} >= {"metabolic-reconstruction", "enzymes"}
    assert dossier["research_kg"]["position"] == "PhD (current)"
    assert main(["--root", str(data_repo), "student", "nobody", "--json"]) == 2
    capsys.readouterr()

    assert main(["--root", str(data_repo), "papers", "--json"]) == 0
    papers = json.loads(capsys.readouterr().out)
    states = {p["slug"]: p["state"] for p in papers["papers"]}
    assert states["nanobodies"] == "PUBLISHED" and states["inductive-gda"] == "REVISING"
    assert next(p for p in papers["papers"] if p["slug"] == "enzymes")["lead"] == "alex-example"
    assert papers["kg_papers"][0]["paper"] == "pa-id:paper/test-2026"

    assert main(["--root", str(data_repo), "conflicts", "--json"]) == 0
    conflicts = json.loads(capsys.readouterr().out)["conflicts"]
    assert [c["xid"] for c in conflicts] == ["conflict:bea-sample:status"]
    assert conflicts[0]["provenance"][0]["source"].endswith("people.yaml")


def test_cli_repos_without_gh(data_repo: Path, capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import cube.sources.github as ghmod

    def broken(args: list[str]) -> str:
        raise ghmod.GhUnavailableError("gh CLI not installed")

    monkeypatch.setattr(ghmod, "gh_runner", broken)
    assert main(["--root", str(data_repo), "repos", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["repos"] == [] and any("gh CLI" in w for w in out["warnings"])


def test_stale_overdue_deadlines_fold_into_one_weekly_digest(ctx: SourceContext) -> None:
    from datetime import timedelta

    from cube.patrols.deadlines import STALE_OVERDUE_DAYS, derive, digest_xid

    later = SourceContext(
        ctx.settings, TODAY + timedelta(days=STALE_OVERDUE_DAYS + 10), github_details=False
    )
    beads, _, events, counts = derive(later)
    by_xid = {b.xid: b for b in beads}
    digest = by_xid[digest_xid(later.today)]
    assert digest.closed is False and "needs:robert" in digest.labels
    assert "2 item(s)" in digest.title
    assert "Alex Example" in digest.body and "Committee meeting" in digest.body
    stale = [b for b in beads if b.closed and "weekly overdue digest" in (b.close_reason or "")]
    assert len(stale) == 2 and counts["stale"] == 2
    assert not [e for e in events if "overdue" in str(e.get("title"))]
    # inside the two-week window the items stay individual findings for Robert
    fresh, _, _, _ = derive(
        SourceContext(ctx.settings, TODAY + timedelta(days=4), github_details=False)
    )
    assert digest_xid(TODAY + timedelta(days=4)) not in {b.xid for b in fresh}
    assert any("needs:robert" in b.labels and not b.closed and "overdue" in b.title for b in fresh)
