"""Triage patrol: Robert sees decisions, not a queue (ADR-0019)."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from cube.config import TriageRule, load_settings
from cube.patrols import base
from cube.patrols.triage import TriagePatrol, title_key
from tests.helpers_engine import REPO_ROOT, FakeBd, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
TODAY = date(2026, 9, 7)


def _rules() -> list[TriageRule]:
    return [
        TriageRule(
            name="infra",
            match={"kind": "finding", "from": ["sysadmin"], "title_regex": "disk|filesystem"},
            action="route",
            to="agent:sysadmin",
            note="sysadmin work",
        ),
        TriageRule(
            name="warn",
            match={
                "kind": "finding",
                "src": ["hermes-infra"],
                "title_regex": "^WARN:",
                "priority_min": 3,
            },
            action="close",
            note="information",
        ),
        TriageRule(
            name="answers",
            match={"kind": "request", "labels_all": ["answer:robert"]},
            action="deliver",
            note="to the inbox",
        ),
        TriageRule(
            name="far milestones",
            match={
                "kind": "finding",
                "src": ["kaust_rules"],
                "title_regex": "due in ([3-9][0-9]|[1-9][0-9][0-9]) day",
            },
            action="defer",
            note="later",
        ),
    ]


def _install_agents(repo: Path) -> None:
    (repo / "agents").mkdir(exist_ok=True)
    for name in ("coordinator", "sysadmin"):
        shutil.copy(REPO_ROOT / "agents" / f"{name}.yaml", repo / "agents" / f"{name}.yaml")
        shutil.copytree(REPO_ROOT / "agents" / name, repo / "agents" / name, dirs_exist_ok=True)
    (repo / "cube.yaml").write_text(
        (repo / "cube.yaml").read_text(encoding="utf-8").replace("host: testhost", "host: ws"),
        encoding="utf-8",
    )


def test_title_key_ignores_numbers() -> None:
    assert title_key("Escalation from sysadmin: ws root disk / at 91% (261G used)") == title_key(
        "Escalation from sysadmin: ws root disk / at 92% (270G used)"
    )
    assert title_key("Escalation from sysadmin: ws root disk") != title_key(
        "Escalation from sysadmin: unimatrix01 root disk"
    )


def test_triage_routes_closes_delivers_and_defers(engine_repo: Path, fake_bd: FakeBd) -> None:
    _install_agents(engine_repo)
    settings = load_settings(engine_repo)
    settings.triage.rules = _rules()
    fake_bd.add(
        "cube-d1",
        title="Escalation from sysadmin: ws root disk / at 91% (261G of 303G used)",
        labels=["kind:finding", "from:sysadmin", "needs:robert"],
        priority=1,
        created_at="2026-09-04T00:00:00+00:00",
    )
    fake_bd.add(
        "cube-d2",
        title="Escalation from sysadmin: ws root disk / at 92% (270G of 303G used)",
        labels=["kind:finding", "from:sysadmin", "needs:robert"],
        priority=1,
        created_at="2026-09-06T00:00:00+00:00",
    )
    fake_bd.add(
        "cube-w1",
        title="WARN: vm-alpha: up 6 days, failed units: dailyaidecheck",
        labels=["kind:finding", "src:hermes-infra"],
        priority=3,
    )
    fake_bd.add(
        "cube-a1",
        title="Robert answered: Escalation from sysadmin: node005 NVML mismatch",
        labels=["kind:request", "role:sysadmin", "answer:robert"],
        description="Question: fix it?\nRobert: yes, via unimatrix01",
    )
    fake_bd.add(
        "cube-a2",
        title="Robert answered: Escalation from senior: charter gap",
        labels=["kind:request", "role:senior", "answer:robert"],
        description="Robert: define the success criteria",
    )
    fake_bd.add(
        "cube-m1",
        title="Milestone warning: thesis application for Eve Sample (due in 139 day(s))",
        labels=["kind:finding", "src:kaust_rules", "needs:robert"],
        priority=3,
    )
    fake_bd.add(
        "cube-q1",
        title="Escalation from group-leader: decision needed from Robert",
        labels=["kind:finding", "from:group-leader", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-p1",
        title="Review coordinator goal decomposition and assignments",
        labels=["kind:proposal", "needs:robert", "review-item", "agent:coordinator"],
        created_at="2026-09-05T00:00:00+00:00",
    )
    fake_bd.add(
        "cube-p2",
        title="Review coordinator goal decomposition and assignments",
        labels=[
            "kind:proposal",
            "needs:robert",
            "review-item",
            "agent:coordinator",
            "approved:robert",
        ],
        created_at="2026-09-06T00:00:00+00:00",
    )

    report = base.run_patrol(settings, TriagePatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    beads = fake_bd.beads()
    # route: the first disk finding becomes sysadmin work, the second is its duplicate
    assert "agent:sysadmin" in beads["cube-d1"]["labels"]
    assert "needs:robert" not in beads["cube-d1"]["labels"]
    assert "triage:routed" in beads["cube-d1"]["labels"]
    assert (
        beads["cube-d2"]["status"] == "closed"
        and "duplicate of cube-d1" in beads["cube-d2"]["close_reason"]
    )
    # close: a monitoring warning is information
    assert beads["cube-w1"]["status"] == "closed"
    # deliver: the sysadmin's answer lands in its inbox, the senior's with the coordinator
    assert beads["cube-a1"]["status"] == "closed"
    assert beads["cube-a2"]["status"] == "closed"
    sysadmin_inbox = (engine_repo / "agents" / "sysadmin" / "inbox.jsonl").read_text(
        encoding="utf-8"
    )
    assert "NVML mismatch" in sysadmin_inbox and "via unimatrix01" in sysadmin_inbox
    coordinator_inbox = (engine_repo / "agents" / "coordinator" / "inbox.jsonl").read_text(
        encoding="utf-8"
    )
    assert "charter gap" in coordinator_inbox
    # defer: a far milestone drops needs:robert but stays open
    assert beads["cube-m1"]["status"] == "open"
    assert "needs:robert" not in beads["cube-m1"]["labels"]
    assert "triage:deferred" in beads["cube-m1"]["labels"]
    # hygiene: the older daily review is superseded, the accepted one closes
    assert beads["cube-p1"]["status"] == "closed"
    assert beads["cube-p2"]["status"] == "closed"
    # a real decision stays Robert's
    assert beads["cube-q1"]["status"] == "open" and "needs:robert" in beads["cube-q1"]["labels"]
    assert report.data["needs_robert_after"] == 1
    assert "1 bead(s) still need Robert" in report.summary

    # idempotent: a second pass changes nothing more
    second = base.run_patrol(settings, TriagePatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    assert second.data["actions"] == []


def test_the_repo_rules_send_unflagged_escalations_to_the_coordinator(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    # Robert, 2026-09-07 (doctrine 7a): only security- and privacy-critical
    # matters, people and integrity stay his; the rest is the coordinator's.
    _install_agents(engine_repo)
    settings = load_settings(engine_repo)
    settings.triage.rules = load_settings(REPO_ROOT).triage.rules
    fake_bd.add(
        "cube-e1",
        title="Escalation from group-leader: decision needed from Robert",
        labels=["kind:finding", "from:group-leader", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-e2",
        title="Escalation from senior: IBEX allocation for the survey",
        labels=["kind:request", "from:senior", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-e3",
        title="Escalation from sysadmin: three sources disagree about node005",
        labels=["kind:conflict", "from:sysadmin", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-e4",
        title="Escalation from sysadmin: restart vm-beta",
        labels=["kind:request", "from:sysadmin", "needs:robert", "critical:security"],
        priority=1,
    )
    fake_bd.add(
        "cube-e5",
        title="Escalation from advisor: a student's progress",
        labels=["kind:finding", "from:advisor", "needs:robert", "people"],
        priority=1,
    )
    fake_bd.add(
        "cube-e6",
        title="Approval: borg-server package upgrades and reboot into the current kernel",
        labels=["kind:approval", "agent:sysadmin", "needs:robert"],
        priority=1,
    )
    # Robert, 2026-09-08 (ADR-0027): a prepared change that names none of the
    # running systems, a laptop read waiting for him, and a question with a flag.
    fake_bd.add(
        "cube-e7",
        title="Approval: human power-on of vm-beta",
        labels=["kind:approval", "agent:sysadmin", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-e8",
        title="Request for Laptop liaison",
        labels=[
            "kind:request",
            "agent:liaison",
            "host:laptop",
            "needs:robert",
            "laptop-read:approval",
        ],
        description="Question: what did I write to the editor in mail last week?",
        priority=1,
    )
    fake_bd.add(
        "cube-e9",
        title="Question from agent:senior: which release should the benchmark use?",
        labels=["kind:question", "agent:senior", "needs:robert"],
        priority=1,
    )
    fake_bd.add(
        "cube-e10",
        title="Question from agent:senior: may the key on ws be rotated?",
        labels=["kind:question", "agent:senior", "needs:robert", "critical:security"],
        priority=1,
    )
    base.run_patrol(settings, TriagePatrol(now=NOW), today=TODAY, dry_run=False, now=NOW)
    beads = fake_bd.beads()
    for ident in ("cube-e1", "cube-e2", "cube-e3", "cube-e7", "cube-e9"):
        assert "agent:coordinator" in beads[ident]["labels"], ident
        assert "needs:robert" not in beads[ident]["labels"], ident
    for ident in ("cube-e4", "cube-e5", "cube-e6", "cube-e8", "cube-e10"):
        assert "needs:robert" in beads[ident]["labels"], ident
        assert "agent:coordinator" not in beads[ident]["labels"], ident


def test_labels_none_excludes_a_bead_that_carries_any_of_them() -> None:
    from cube.patrols.triage import matches

    rule = TriageRule(
        name="x",
        match={"kind": "finding", "labels_none": ["people", "critical:security"]},
        action="route",
        to="agent:coordinator",
    )
    plain = {"id": "a", "labels": ["kind:finding"], "title": "t"}
    flagged = {"id": "b", "labels": ["kind:finding", "critical:security"], "title": "t"}
    assert matches(rule, plain, now=NOW)
    assert not matches(rule, flagged, now=NOW)
