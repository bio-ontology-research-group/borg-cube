"""Escalation kinds decide who sees a run's escalation, and Robert sees few.

Robert, 2026-09-07: only a security-critical or privacy-critical matter reaches
him (``critical`` set, or kind ``people`` and ``integrity``). A `decision`,
`permission` or `conflict` without the flag is the coordinator's; `blocked`
goes to the group; `note` is recorded and closed on arrival. The same subject
from the same role is one bead, however often it is raised.
"""

from __future__ import annotations

from pathlib import Path

from cube.config import Settings
from cube.engine.results import blocked_owner, escalation_labels
from cube.model import ESCALATION_KINDS, Escalation, RunResult
from cube.roles import load_role
from cube.runners.stub import StubRunner
from tests.helpers_engine import REPO_ROOT, FakeBd, RecordingExec, fixtures
from tests.test_engine import execute, header

globals().update(fixtures())


def _esc(kind: str, summary: str = "something happened", to: str = "robert") -> Escalation:
    return Escalation(condition=f"{kind} condition", to=to, summary=summary, kind=kind)


def test_every_kind_maps_onto_its_labels() -> None:
    labels = {kind: escalation_labels(_esc(kind), "editor") for kind in ESCALATION_KINDS}
    # without a critical flag the coordinator decides, not Robert
    assert labels["decision"] == ["kind:finding", "from:editor", "agent:coordinator"]
    assert labels["permission"] == ["kind:request", "from:editor", "agent:coordinator"]
    assert labels["conflict"] == ["kind:conflict", "from:editor", "agent:coordinator"]
    # a person and suspected fabrication are always Robert's
    assert labels["integrity"] == ["kind:finding", "from:editor", "needs:robert", "integrity"]
    assert labels["people"] == ["kind:finding", "from:editor", "needs:robert", "people"]
    assert labels["note"] == ["kind:note", "from:editor"]
    # blocked never carries needs:robert, whoever it names
    assert "needs:robert" not in labels["blocked"]
    assert "blocked" in labels["blocked"]
    for kind in ESCALATION_KINDS:
        if kind not in ("integrity", "people"):
            assert "needs:robert" not in labels[kind], kind


def test_a_critical_escalation_is_roberts_whatever_its_kind() -> None:
    for kind in ("decision", "permission", "conflict"):
        for critical in ("security", "privacy"):
            esc = Escalation(condition="c", summary="s", kind=kind, critical=critical)
            labels = escalation_labels(esc, "sysadmin")
            assert "needs:robert" in labels, (kind, critical)
            assert f"critical:{critical}" in labels
            assert "agent:coordinator" not in labels
    # the flag travels with an escalation to another role too
    esc = Escalation(condition="c", summary="s", to="agent:sysadmin", critical="security")
    assert escalation_labels(esc, "senior") == [
        "kind:finding",
        "from:senior",
        "agent:sysadmin",
        "critical:security",
    ]


def test_the_same_subject_from_the_same_role_is_one_bead(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    fake_bd.add("cube-40", title="ws disk", labels=["kind:finding"], description=header())
    first = RunResult(
        summary="disk at 91% (source: df)",
        escalations=[_esc("decision", "ws root disk / at 91%", to="robert")],
    )
    first.escalations[0].condition = "ws root disk / at 91% (261G used)"
    report = execute(
        engine_settings,
        "sysadmin",
        bead="cube-40",
        runner=StubRunner(result=first),
        runner_name="stub",
        exec_fn=RecordingExec(),
    )
    assert report.ok, report.error
    (filed,) = (report.applied or {})["escalations"]
    again = RunResult(
        summary="disk at 92% (source: df)",
        escalations=[_esc("decision", "x", to="robert")],
    )
    again.escalations[0].condition = "ws root disk / at 92% (263G used)"
    fake_bd.add("cube-41", title="ws disk again", labels=["kind:finding"], description=header())
    report = execute(
        engine_settings,
        "sysadmin",
        bead="cube-41",
        runner=StubRunner(result=again),
        runner_name="stub",
        exec_fn=RecordingExec(),
    )
    assert report.ok, report.error
    assert (report.applied or {})["escalations"] == []
    beads = fake_bd.beads()
    assert filed in beads
    assert any("repeated" in c["text"] for c in beads[filed]["comments"])
    assert not any(
        b["title"].startswith("Escalation from sysadmin") and ident != filed
        for ident, b in beads.items()
    )


def test_a_finding_closes_when_its_result_is_filed(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    # Robert, 2026-09-07: a diagnosis is done when it is on the ledger; the
    # review gate is for designs and implementations.
    fake_bd.add(
        "cube-50",
        title="Escalation from sysadmin: x",
        labels=["kind:finding"],
        description=header(),
    )
    report = execute(
        engine_settings,
        "sysadmin",
        bead="cube-50",
        runner=StubRunner(result=RunResult(summary="diagnosed (source: journalctl)")),
        runner_name="stub",
        exec_fn=RecordingExec(),
    )
    assert report.ok, report.error
    bead = fake_bd.beads()["cube-50"]
    assert bead["status"] == "closed"
    assert (report.applied or {})["review_bead"] is None
    assert "needs:robert" not in bead["labels"]


def test_a_blocked_escalation_goes_to_the_group_not_robert() -> None:
    tooling = _esc("blocked", "pandoc is not on PATH in this run")
    other = _esc("blocked", "the survey has no candidate papers yet")
    assert blocked_owner(tooling) == "role:sysadmin"
    assert blocked_owner(other) == "agent:coordinator"
    assert escalation_labels(tooling, "editor") == [
        "kind:finding",
        "from:editor",
        "blocked",
        "role:sysadmin",
    ]
    assert escalation_labels(other, "editor")[-1] == "agent:coordinator"
    # an explicit role still wins over the guess
    named = Escalation(condition="c", to="senior", summary="no network", kind="blocked")
    assert escalation_labels(named, "programmer")[-1] == "role:senior"


def test_an_escalation_to_another_role_keeps_its_kind_label() -> None:
    esc = Escalation(condition="c", to="group-leader", summary="s", kind="decision")
    assert escalation_labels(esc, "senior") == ["kind:finding", "from:senior", "role:group-leader"]


def test_a_note_is_filed_and_closed_and_a_blocked_finding_never_asks_robert(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    fake_bd.add(
        "cube-30", title="Write the survey", labels=["stage:implement"], description=header()
    )
    result = RunResult(
        summary="drafted the survey (source: runs/x)",
        escalations=[
            _esc("note", "the charter names no success criterion yet"),
            _esc("blocked", "pandoc is not on PATH in this run"),
            _esc("integrity", "the reference could not be verified"),
        ],
    )
    report = execute(
        engine_settings,
        "programmer",
        bead="cube-30",
        runner=StubRunner(result=result),
        runner_name="stub",
        exec_fn=RecordingExec(),
    )
    assert report.ok, report.error
    filed = (report.applied or {})["escalations"]
    beads = fake_bd.beads()
    note, blocked, integrity = (beads[ident] for ident in filed)
    assert "kind:note" in note["labels"] and "needs:robert" not in note["labels"]
    assert note["status"] == "closed"
    assert note["comments"][-1]["text"] == "the charter names no success criterion yet"
    assert "needs:robert" not in blocked["labels"]
    assert {"blocked", "role:sysadmin"} <= set(blocked["labels"])
    assert blocked["status"] == "open"
    assert {"needs:robert", "integrity"} <= set(integrity["labels"])


def test_the_default_kind_is_decision_and_the_role_yamls_are_typed() -> None:
    assert Escalation(condition="c", summary="s").kind == "decision"
    for name in ("group-leader", "senior", "editor", "advisor", "programmer"):
        role = load_role(REPO_ROOT, name)
        assert role.escalation, name
        assert all(entry.kind in ESCALATION_KINDS for entry in role.escalation), name
    editor = load_role(REPO_ROOT, "editor")
    assert editor.escalation[0].kind == "integrity"
    advisor = load_role(REPO_ROOT, "advisor")
    assert {entry.kind for entry in advisor.escalation} == {"people"}
    # no role escalates "no actionable work item" any more
    for path in sorted((REPO_ROOT / "roles").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "no actionable work" not in text, path


def test_every_role_prompt_says_what_to_escalate() -> None:
    for path in sorted((REPO_ROOT / "roles" / "prompts").glob("*.md")):
        # Robert, 2026-09-07: the prompts were shortened; the rule set stays, the
        # wording is the prompt's own. Every prompt names the seven escalation
        # kinds and the idle rule.
        text = " ".join(path.read_text(encoding="utf-8").split()).lower()
        for kind in (
            "decision",
            "permission",
            "integrity",
            "people",
            "conflict",
            "blocked",
            "note",
        ):
            assert kind in text, (path, kind)
        assert "no work assigned" in text or "idle" in text, path
        # and every prompt says who decides: Robert only security and privacy
        assert "security" in text and "privacy" in text, path


def test_the_run_result_schema_carries_the_new_fields() -> None:
    schema = RunResult.model_json_schema()
    escalation = schema["$defs"]["Escalation"]["properties"]
    assert set(escalation) == {"condition", "to", "summary", "kind", "options", "critical"}


def test_a_null_or_bare_finished_at_does_not_invalidate_the_result() -> None:
    # 2026-09-08: two group-leader runs were dropped as "Input should be a valid
    # datetime or date, input is too short" over finished_at: "null"
    assert RunResult.model_validate({"summary": "s", "finished_at": "null"}).finished_at is None
    assert RunResult.model_validate({"summary": "s", "finished_at": ""}).finished_at is None
    assert RunResult.model_validate({"summary": "s", "finished_at": "soon"}).finished_at is None
    parsed = RunResult.model_validate({"summary": "s", "finished_at": "2026-09-08T10:00:00Z"})
    assert parsed.finished_at is not None and parsed.finished_at.year == 2026
