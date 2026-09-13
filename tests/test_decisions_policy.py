"""`decisions.policy`: the answers Robert would give anyway, given automatically.

Every rule is checked on its own, the guards are checked against the decisions
they must protect, and the patrol, the doctor check, the payload preview and the
digest line are checked against the same policy.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from cube.beads import Beads
from cube.cli import main
from cube.config import DecisionRule, Settings, load_settings
from cube.decisions import (
    apply_policy,
    decide,
    decision_guards,
    decisions_payload,
    pending_decisions,
    policy_digest_lines,
    policy_preview,
    within_budget,
)
from cube.doctor import check_decisions_policy
from cube.patrols import base
from cube.testing.fakebd import FakeBd
from tests.helpers_engine import REPO_ROOT, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
TODAY = date(2026, 9, 4)


def _shipped_policy() -> str:
    """The `decisions:` block of the repo's own cube.yaml, verbatim."""
    lines = (REPO_ROOT / "cube.yaml").read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(lines) if line == "decisions:")
    rest: list[str] = []
    for line in lines[first + 1 :]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        rest.append(line)
    return "\n".join(["decisions:", *rest]).rstrip() + "\n"


POLICY = _shipped_policy()


def _with_policy(repo: Path, extra: str = POLICY) -> Settings:
    path = repo / "cube.yaml"
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return load_settings(repo)


def _beads(repo: Path) -> Beads:
    return Beads(bin="bd", cwd=repo)


def _header(xid: str) -> str:
    return f"---\nxid: {xid}\nprovenance: []\nprivacy: internal\n---\n"


def _decision(settings: Settings, repo: Path, ident: str) -> dict[str, Any]:
    items = {str(item["id"]): item for item in pending_decisions(settings, _beads(repo), now=NOW)}
    return items[ident]


def _seed(fake_bd: FakeBd) -> None:
    """One bead per rule, plus the ones the guards must protect."""
    fake_bd.add(
        "cube-201",
        title="Approve Ontology expert resource step: run the benchmark",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
        description=_header("agent:ontology:resource:1")
        + "Agent: ontology\nResource class: gpu\nReason: node005 GPU allowance exhausted\n"
        "Declared needs:\ncompute_target: node005\ngpu_hours: 2\n",
        created_at="2026-09-04T08:00:00+00:00",
    )
    fake_bd.add(
        "cube-202",
        title="Decide recruitment of role:programmer",
        labels=["kind:request", "agent:coordinator", "pipeline-stage:recruit", "needs:robert"],
        description=_header("pipe:cube-1:recruit:role-programmer:1")
        + "From: agent:ontology\nCandidate: role:programmer\nQuestion: bring them in\n",
        created_at="2026-09-04T08:05:00+00:00",
    )
    fake_bd.add(
        "cube-203",
        title="Decide recruitment of person:alex-example",
        labels=["kind:request", "agent:coordinator", "pipeline-stage:recruit", "needs:robert"],
        description=_header("pipe:cube-1:recruit:person-alex-example:1")
        + "From: agent:ontology\nCandidate: person:alex-example\nQuestion: bring them in\n",
        created_at="2026-09-04T08:06:00+00:00",
    )
    fake_bd.add(
        "cube-204",
        title="Review coordinator goal decomposition and assignments",
        labels=["kind:proposal", "needs:robert", "review-item", "agent:coordinator"],
        description=_header("agent:coordinator:goal-review:2026-09-04")
        + "Rationale: Coordinator review of current goals.\n",
        created_at="2026-09-04T08:10:00+00:00",
    )
    fake_bd.add(
        "cube-205",
        title="Escalation from senior: the manuscript source is missing",
        labels=["kind:finding", "blocked", "role:sysadmin", "from:senior", "needs:robert"],
        description=_header("esc:r-1:0") + "The pandoc binary is not on PATH.\n",
        created_at="2026-09-04T08:15:00+00:00",
    )


def test_each_match_key_selects_its_own_decision(engine_repo: Path, fake_bd: FakeBd) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    previews = {
        ident: policy_preview(settings, _decision(settings, engine_repo, ident), now=NOW)
        for ident in ("cube-201", "cube-202", "cube-203", "cube-204", "cube-205")
    }
    # resource_class and within_budget
    assert previews["cube-201"]["rule"] == 0 and previews["cube-201"]["answer"] == "yes"
    # member_kind: a role joins, a person never does
    assert previews["cube-202"]["rule"] == 1
    assert previews["cube-203"] is None
    # from plus title_prefix
    assert previews["cube-204"]["rule"] == 2 and previews["cube-204"]["answer"] == "accept"
    # labels_all
    assert previews["cube-205"]["rule"] == 4 and previews["cube-205"]["answer"] == "reject"


def test_first_matching_rule_wins(engine_repo: Path, fake_bd: FakeBd) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    settings.decisions.policy.insert(
        0,
        DecisionRule(
            kind="permission",
            match={"resource_class": ["gpu"]},  # type: ignore[arg-type]
            answer="no",
            note="first rule wins",
        ),
    )
    preview = policy_preview(settings, _decision(settings, engine_repo, "cube-201"), now=NOW)
    assert (
        preview["rule"] == 0 and preview["answer"] == "no" and preview["note"] == "first rule wins"
    )


def test_a_resource_step_over_budget_is_never_automatic(engine_repo: Path, fake_bd: FakeBd) -> None:
    fake_bd.add(
        "cube-210",
        title="Approve Ontology expert resource step: rent a big model",
        labels=["agent:ontology", "needs:robert", "resource:approval"],
        description=_header("agent:ontology:resource:2")
        + "Agent: ontology\nResource class: ws_cpu\nReason: spend allowance exhausted\n"
        "Declared needs:\ncompute_target: ws\nspend_usd: 500\n",
        created_at="2026-09-04T08:20:00+00:00",
    )
    settings = _with_policy(
        engine_repo, POLICY + "budget:\n  daily_total_usd: 60\n  weekly_total_usd: 300\n"
    )
    decision = _decision(settings, engine_repo, "cube-210")
    assert decision["context"]["spend_usd"] == 500.0
    assert not within_budget(settings, 500.0, now=NOW)
    assert "spend_over_budget" in decision_guards(settings, decision, now=NOW)
    assert policy_preview(settings, decision, now=NOW) is None


def test_guards_hold_back_outbound_people_integrity_conflict_and_questions(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    from cube.approvals import ApprovalStore, Intent
    from cube.contact import ContactPolicy

    fake_bd.add(
        "cube-220",
        title="Escalation from advisor: two missed check-ins",
        labels=["kind:finding", "needs:robert", "people", "from:advisor"],
        description=_header("esc:r-2:0") + "Two check-ins missed.\n",
        created_at="2026-09-04T08:25:00+00:00",
    )
    fake_bd.add(
        "cube-221",
        title="Escalation from editor: suspected fabricated reference",
        labels=["kind:finding", "needs:robert", "integrity", "from:editor"],
        description=_header("esc:r-3:0") + "The reference could not be verified.\n",
        created_at="2026-09-04T08:26:00+00:00",
    )
    fake_bd.add(
        "cube-222",
        title="Escalation from group-leader: source conflict",
        labels=["kind:conflict", "needs:robert", "from:group-leader"],
        description=_header("esc:r-4:0") + "Two sources disagree.\n",
        created_at="2026-09-04T08:27:00+00:00",
    )
    fake_bd.add(
        "cube-223",
        title="Question from agent:ontology: which release?",
        labels=["kind:question", "needs:robert", "agent:ontology"],
        description=_header("question:agent:ontology:abc")
        + "Question: which release?\nOptions: 2025 | 2026\n",
        created_at="2026-09-04T08:28:00+00:00",
    )
    ApprovalStore(engine_settings.state_dir()).create(
        Intent(kind="email", person="alex-example", subject="reminder"),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor/r-9",
        run_id="r-9",
        now=NOW,
    )
    settings = _with_policy(engine_repo)
    # a rule that would happily answer each of them
    settings.decisions.policy = [
        DecisionRule(kind=kind, answer=answer, note="would answer")
        for kind, answer in (
            ("finding", "reject"),
            ("conflict", "reject"),
            ("question", "free"),
            ("approval", "approve"),
        )
    ]
    guards = {}
    for ident in ("cube-220", "cube-221", "cube-222", "cube-223"):
        decision = _decision(settings, engine_repo, ident)
        guards[ident] = decision_guards(settings, decision, now=NOW)
        assert policy_preview(settings, decision, now=NOW) is None
    assert guards["cube-220"] == ["people"]
    assert guards["cube-221"] == ["integrity"]
    assert guards["cube-222"] == ["conflict"]
    assert guards["cube-223"] == ["question"]
    approval = next(
        item
        for item in pending_decisions(settings, _beads(engine_repo), now=NOW)
        if item["source"] == "approval"
    )
    assert decision_guards(settings, approval, now=NOW) == ["outbound"]
    assert policy_preview(settings, approval, now=NOW) is None


def test_a_file_change_under_runs_is_answered_and_a_deletion_is_not(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    from cube.approvals import ApprovalStore, Intent
    from cube.contact import ContactPolicy

    store = ApprovalStore(engine_settings.state_dir())
    keep = engine_repo / "state" / "keep.diff"
    keep.write_text("--- a/runs/x.md\n+++ b/runs/x.md\n+one line\n", encoding="utf-8")
    drop = engine_repo / "state" / "drop.diff"
    drop.write_text(
        "deleted file mode 100644\n--- a/runs/y.md\n+++ /dev/null\n-one line\n", encoding="utf-8"
    )
    for name, path in (("keep", keep), ("drop", drop)):
        store.create(
            Intent(kind="file_change", diff_file=str(path), subject=name),
            policy=ContactPolicy(engine_repo / "contacts.yaml"),
            created_by="programmer/r-1",
            run_id="r-1",
            now=NOW,
        )
    settings = _with_policy(engine_repo)
    items = {
        str(item["title"]): item
        for item in pending_decisions(settings, _beads(engine_repo), now=NOW)
        if item["source"] == "approval"
    }
    keep_item = next(item for title, item in items.items() if "keep" in title)
    drop_item = next(item for title, item in items.items() if "drop" in title)
    assert keep_item["context"]["targets"] == ["runs/x.md"]
    preview = policy_preview(settings, keep_item, now=NOW)
    assert preview["rule"] == 3 and preview["answer"] == "approve"
    assert drop_item["context"]["deletes"] is True
    assert decision_guards(settings, drop_item, now=NOW) == ["deletion"]
    assert policy_preview(settings, drop_item, now=NOW) is None


def test_apply_policy_dry_run_changes_nothing_and_apply_records_who_answered(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    rows = apply_policy(settings, _beads(engine_repo), dry_run=True, now=NOW)
    assert [row["id"] for row in rows if row["answered"]] == [
        "cube-201",
        "cube-204",
        "cube-205",
    ]
    # the recruit rule matched but the request names no epic; the failure is reported,
    # not swallowed, and the decision stays open
    recruit = next(row for row in rows if row["id"] == "cube-202")
    assert recruit["policy"]["rule"] == 1 and "no goal:" in recruit["error"]
    assert fake_bd.bead("cube-201")["status"] == "open"
    assert not (engine_repo / "state" / "decisions.jsonl").exists()

    rows = apply_policy(settings, _beads(engine_repo), dry_run=False, now=NOW)
    answered = [row for row in rows if row["answered"]]
    assert len(answered) == 3
    log = [
        json.loads(line)
        for line in (engine_repo / "state" / "decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    by = {row["id"]: row for row in log}
    assert by["cube-201"]["by"] == "policy:0"
    assert by["cube-201"]["text"].startswith("policy: compute inside")
    assert by["cube-205"]["by"] == "policy:4"
    assert fake_bd.bead("cube-201")["status"] == "closed"
    # a policy answer is not an attention event
    events_file = engine_repo / "state" / "events.jsonl"
    events = [
        json.loads(line)
        for line in (
            events_file.read_text(encoding="utf-8").splitlines() if events_file.exists() else []
        )
    ]
    assert not [ev for ev in events if (ev.get("data") or {}).get("kind") == "answered"]


def test_robert_still_answers_a_blocked_finding_by_hand(engine_repo: Path, fake_bd: FakeBd) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    plan = decide(
        settings, _beads(engine_repo), "cube-205", choice="accept", dry_run=False, now=NOW
    )
    assert plan["by"] == "robert" and plan["closed"] == "cube-205"
    log = [
        json.loads(line)
        for line in (engine_repo / "state" / "decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert log[0]["by"] == "robert"


def test_patrol_summary_counts_both_sides(engine_repo: Path, fake_bd: FakeBd) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    import cube.patrols  # noqa: F401 - registers the patrol

    assert "decisions" in base.names()
    patrol = base.make("decisions", now=NOW)
    report = base.run_patrol(
        settings, patrol, today=TODAY, dry_run=True, beads=_beads(engine_repo), now=NOW
    )
    assert report.summary.startswith("auto-answered 3, 2 wait for Robert")
    notes = {note.title.split(" ")[0] for note in report.notes()}
    assert notes == {"cube-201", "cube-204", "cube-205"}
    assert "compute inside the declared allowances" in report.text()
    assert any("cube-202" in warning for warning in report.warnings)


def test_the_payload_previews_what_the_next_tick_would_answer(
    engine_repo: Path, fake_bd: FakeBd
) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    payload = decisions_payload(settings, _beads(engine_repo), now=NOW)
    previews = {item["id"]: item["policy_preview"] for item in payload["decisions"]}
    assert previews["cube-201"]["answer"] == "yes"
    assert previews["cube-203"] is None


def test_the_brief_names_what_the_policy_answered_today(engine_repo: Path, fake_bd: FakeBd) -> None:
    _seed(fake_bd)
    settings = _with_policy(engine_repo)
    apply_policy(settings, _beads(engine_repo), dry_run=False, now=NOW)
    lines = policy_digest_lines(settings.state_dir(), TODAY)
    assert lines[0] == "## Policy"
    assert lines[-1].startswith("- Policy answered 3 decisions: cube-201 yes (compute inside")
    assert policy_digest_lines(settings.state_dir(), date(2026, 9, 3)) == []


def test_doctor_rejects_a_rule_that_is_guarded_or_answers_off_the_options(
    engine_repo: Path,
) -> None:
    settings = _with_policy(engine_repo)
    assert check_decisions_policy(settings)[0].ok
    settings.decisions.policy.append(
        DecisionRule(kind="conflict", answer="reject", note="never allowed")
    )
    check = check_decisions_policy(settings)[0]
    assert not check.ok and "never_automatic" in check.detail
    settings.decisions.policy = [
        DecisionRule(kind="permission", answer="maybe", note="not an option")
    ]
    check = check_decisions_policy(settings)[0]
    assert not check.ok and "not one of yes, no" in check.detail
    settings.decisions.policy = [DecisionRule(kind="permission", answer="yes", note="  ")]
    assert "needs a note" in check_decisions_policy(settings)[0].detail


def test_the_shipped_policy_is_legal_and_typed() -> None:
    settings = load_settings(Path(__file__).resolve().parents[1])
    assert check_decisions_policy(settings)[0].ok
    kinds = [rule.kind for rule in settings.decisions.policy]
    # Robert, 2026-09-08 (ADR-0027): three more automatic answers, and the list of
    # running systems whose changes stay his.
    assert kinds == [
        "permission",
        "recruit",
        "proposal",
        "approval",
        "finding",
        "approval",
        "approval",
        "proposal",
    ]
    assert {"borg-server", "ontolinator", "leechuck.de"} <= set(settings.decisions.systems)
    assert settings.patrols["decisions"] == "15min"


def test_an_unknown_guard_is_refused(engine_repo: Path) -> None:
    path = engine_repo / "cube.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "decisions:\n  never_automatic: [weather]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown never_automatic guards: weather"):
        load_settings(engine_repo)


def test_cli_apply_policy_is_dry_run_by_default(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    _seed(fake_bd)
    _with_policy(engine_repo)
    monkeypatch.setenv("CUBE_ROOT", str(engine_repo))
    assert main(["decisions", "apply-policy", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True and len(data["answered"]) == 3
    assert fake_bd.bead("cube-201")["status"] == "open"


def test_the_shipped_cube_yaml_policy_block_is_the_documented_one() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = yaml.safe_load((root / "cube.yaml").read_text(encoding="utf-8"))["decisions"]
    assert raw["digest"] == "daily"
    assert raw["never_automatic"] == [
        "outbound",
        "people",
        "integrity",
        "conflict",
        "question",
        "deletion",
        "spend_over_budget",
    ]
