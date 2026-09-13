"""The summarising half of the literature watch: prompt, validation, digest, delivery."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cube import literature as lit
from cube.agents.scaffold import AgentScaffoldSpec, scaffold_agent
from cube.beads import Beads
from cube.cli import main
from cube.config import Settings, load_settings
from cube.model import Artifact, RunResult
from cube.patrols.agent_workday import AgentWorkdayPatrol, digest_artifact
from cube.runners import StubRunner
from tests.helpers_engine import FakeBd, fixtures, make_repo

globals().update(fixtures())

TODAY = date(2026, 9, 4)
NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)

PROJECTS = {
    "@context": {},
    "@graph": [
        {"@id": "borg-id:topic/phenotype-informatics", "@type": "borg:Topic"},
        {
            "@id": "borg-id:project/nih-temporal-kg",
            "@type": "borg:Project",
            "schema:name": "Temporal knowledge graphs for cohorts",
            "borg:startYear": 2025,
            "borg:hasMember": [
                {"@id": "gus-student", "borg:roleOnProject": "student"},
            ],
            "borg:topic": [{"@id": "borg-id:topic/phenotype-informatics"}],
        },
    ],
}

CANDIDATES = [
    {
        "id": "arxiv:2609.01234v1",
        "source": "arxiv",
        "title": "Temporal knowledge graph embeddings for phenotype trajectories",
        "abstract": "We extend a knowledge graph embedding model with time.",
        "authors": ["G Student"],
        "categories": ["cs.AI"],
        "published": "2026-09-04",
        "url": "https://arxiv.org/abs/2609.01234v1",
        "doi": None,
        "matched": ["knowledge graph"],
        "summarised": False,
    },
    {
        "id": "biorxiv:10.1101/2026.09.03.611222",
        "source": "biorxiv",
        "title": "A protein function benchmark for metagenome-assembled genomes",
        "abstract": "A benchmark pairing MAGs with curated protein function annotations.",
        "authors": ["F Fellow"],
        "categories": ["bioinformatics"],
        "published": "2026-09-04",
        "url": "https://www.biorxiv.org/content/10.1101/2026.09.03.611222v1",
        "doi": "10.1101/2026.09.03.611222",
        "matched": ["protein function"],
        "summarised": False,
    },
]

ARTIFACT = {
    "kind": "literature-digest",
    "entries": [
        {
            "id": "arxiv:2609.01234v1",
            "source": "arxiv",
            "url": "https://arxiv.org/abs/2609.01234v1",
            "title": "Temporal knowledge graph embeddings for phenotype trajectories",
            "one_paragraph_summary": "A temporal extension of a knowledge graph embedding model.",
            "relevance": [
                {
                    "kind": "goal",
                    "ref": "Ship the temporal cohort model",
                    "why": "the goal 'Ship the temporal cohort model' needs exactly this model.",
                },
                {
                    "kind": "topic",
                    "ref": "phenotype-informatics",
                    "why": "matched term 'knowledge graph' sits inside phenotype informatics.",
                },
            ],
            "priority": "high",
        },
        {
            "id": "biorxiv:10.1101/2026.09.03.611222",
            "source": "biorxiv",
            "url": "https://www.biorxiv.org/content/10.1101/2026.09.03.611222v1",
            "title": "A protein function benchmark for metagenome-assembled genomes",
            "one_paragraph_summary": "A benchmark for protein function prediction on MAGs.",
            "relevance": [
                {
                    "kind": "student",
                    "ref": "gus-student",
                    "why": "matched term 'protein function' is the core of his project work.",
                }
            ],
            "priority": "normal",
        },
    ],
}


@pytest.fixture
def lit_repo(tmp_path: Path) -> Path:
    root = make_repo(tmp_path)
    (root / "rkg" / "projects.jsonld").write_text(json.dumps(PROJECTS), encoding="utf-8")
    return root


@pytest.fixture
def lit_settings(lit_repo: Path) -> Settings:
    return load_settings(lit_repo)


def _seed_candidates(settings: Settings) -> None:
    lit.write_candidates(settings, TODAY, [dict(row) for row in CANDIDATES])


def _context(settings: Settings, *, deadline: str | None = "2026-09-20") -> lit.LiteratureContext:
    ctx = lit.build_context(settings, beads=None)
    ctx.goals = [
        {"id": "cube-900", "title": "Ship the temporal cohort model", "deadline": deadline}
    ]
    return ctx


# --- context and prompt ------------------------------------------------------------------


def test_context_reads_topics_projects_students_and_goals(lit_settings: Settings) -> None:
    ctx = lit.build_context(lit_settings, beads=None)
    assert {t["slug"] for t in ctx.topics} == {"phenotype-informatics"}
    assert ctx.projects[0]["slug"] == "nih-temporal-kg"
    assert ctx.projects[0]["topics"] == ["phenotype-informatics"]
    student = next(s for s in ctx.students if s["id"] == "gus-student")
    assert student["program"] == "MS-CS"
    assert student["expertise"] == ["phenotype-informatics"]
    assert any("projects.jsonld" in source for source in ctx.sources)


def test_summary_prompt_carries_the_context_blocks_and_the_candidate_list(
    lit_settings: Settings,
) -> None:
    prompt = lit.summary_prompt(lit_settings, CANDIDATES, _context(lit_settings))
    for heading in (
        "### Topics",
        "### Active projects",
        "### Current students and postdocs",
        "### Open goals",
        "## Candidate preprints",
    ):
        assert heading in prompt
    assert "phenotype-informatics" in prompt
    assert "nih-temporal-kg" in prompt
    assert "gus-student" in prompt
    assert "Ship the temporal cohort model" in prompt
    assert "arxiv:2609.01234v1" in prompt
    assert "https://www.biorxiv.org/content/10.1101/2026.09.03.611222v1" in prompt
    assert "literature-digest" in prompt
    assert f"At most {lit_settings.literature_watch.max_summaries_per_day} entries" in prompt
    assert "—" not in prompt


# --- validation --------------------------------------------------------------------------


def test_validation_accepts_the_fixture_artifact(lit_settings: Settings) -> None:
    entries, errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    assert errors == []
    assert [e["id"] for e in entries] == [c["id"] for c in CANDIDATES]
    assert entries[0]["priority"] == "high"
    assert entries[0]["matched"] == ["knowledge graph"]
    assert entries[1]["doi"] == "10.1101/2026.09.03.611222"


def test_validation_rejects_a_paper_outside_the_candidate_list() -> None:
    artifact = {"entries": [{**ARTIFACT["entries"][0], "id": "arxiv:9999.99999"}]}
    entries, errors = lit.validate_digest(artifact, CANDIDATES, limit=25)
    assert entries == []
    assert errors == ["arxiv:9999.99999: not in today's candidate list"]


def test_validation_rejects_a_relevance_without_a_why_and_a_duplicate() -> None:
    first = {
        **ARTIFACT["entries"][0],
        "relevance": [{"kind": "topic", "ref": "phenotype-informatics", "why": "  "}],
    }
    entries, errors = lit.validate_digest({"entries": [first]}, CANDIDATES, limit=25)
    assert entries == []
    assert any("without a why" in e for e in errors)

    duplicate = {"entries": [ARTIFACT["entries"][0], ARTIFACT["entries"][0]]}
    entries, errors = lit.validate_digest(duplicate, CANDIDATES, limit=25)
    assert len(entries) == 1
    assert any("duplicate entry" in e for e in errors)


def test_validation_honours_the_daily_limit_and_rejects_junk() -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=1)
    assert len(entries) == 1
    with pytest.raises(lit.LiteratureError):
        lit.validate_digest({"nope": []}, CANDIDATES, limit=5)
    with pytest.raises(lit.LiteratureError):
        lit.parse_artifact("not json")
    assert lit.parse_artifact('```json\n{"entries": []}\n```') == {"entries": []}


# --- rendering ---------------------------------------------------------------------------


def test_digest_markdown_and_json_render_from_the_fixture(lit_settings: Settings) -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    md_path, json_path = lit.write_digest(lit_settings, TODAY, entries, {"candidates": 2})
    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# Literature watch 2026-09-04")
    assert "## For students" in md
    assert "## For goals" in md
    assert "https://arxiv.org/abs/2609.01234v1" in md
    assert "the goal 'Ship the temporal cohort model' needs exactly this model." in md
    assert "—" not in md
    # every entry cites its url
    for line in md.splitlines():
        if line.startswith("- ["):
            assert "(" in line
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["date"] == "2026-09-04"
    assert payload["counts"]["candidates"] == 2
    assert [e["id"] for e in payload["entries"]] == [c["id"] for c in CANDIDATES]


def test_empty_digest_says_so(lit_settings: Settings) -> None:
    md_path, _json_path = lit.write_digest(lit_settings, TODAY, [], {})
    assert "Nothing relevant" in md_path.read_text(encoding="utf-8")


def test_grouping_puts_each_entry_under_its_first_target() -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    grouped = dict(lit.group_entries(entries))
    assert [e["id"] for e in grouped["For goals"]] == ["arxiv:2609.01234v1"]
    assert [e["id"] for e in grouped["For students"]] == ["biorxiv:10.1101/2026.09.03.611222"]
    topic_only = [{**entries[0], "relevance": [entries[0]["relevance"][1]]}]
    assert dict(lit.group_entries(topic_only))["Other relevant"]


# --- delivery ----------------------------------------------------------------------------


def test_brief_block_lists_high_priority_entries_and_the_path(lit_settings: Settings) -> None:
    assert lit.brief_block(lit_settings, TODAY) == [
        "## Literature",
        "- no literature digest for today",
    ]
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    lit.write_digest(lit_settings, TODAY, entries, {})
    block = lit.brief_block(lit_settings, TODAY)
    assert block[0] == "## Literature"
    assert "Temporal knowledge graph embeddings" in block[1]
    assert "https://arxiv.org/abs/2609.01234v1" in block[1]
    assert block[-1].endswith("briefings/literature/2026-09-04.md")
    # normal priority entries stay out of the brief
    assert not any("protein function benchmark" in line for line in block)


def test_brief_command_includes_the_literature_block(
    lit_repo: Path, lit_settings: Settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    lit.write_digest(lit_settings, TODAY, entries, {})
    assert main(["--root", str(lit_repo), "brief", "--today", "2026-09-04"]) == 0
    out = capsys.readouterr().out
    assert "## Literature" in out
    assert "Temporal knowledge graph embeddings" in out


def test_needs_robert_only_for_a_goal_deadline_inside_the_horizon(
    lit_settings: Settings,
) -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    assert lit.needs_robert(entries, _context(lit_settings, deadline="2026-09-20"), TODAY)
    assert not lit.needs_robert(entries, _context(lit_settings, deadline="2026-12-31"), TODAY)
    assert not lit.needs_robert(entries, _context(lit_settings, deadline=None), TODAY)
    # a goal relevance that is not high priority never wakes Robert
    quiet = [{**entries[0], "priority": "normal"}]
    assert not lit.needs_robert(quiet, _context(lit_settings), TODAY)


def test_reading_list_bead_carries_the_digest_as_provenance(
    lit_repo: Path, lit_settings: Settings, fake_bd: FakeBd
) -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    _md, json_path = lit.write_digest(lit_settings, TODAY, entries, {})
    ledger = Beads(bin="bd", cwd=lit_repo)
    bead_id = lit.reading_list_bead(ledger, TODAY, entries, digest_json=json_path, attention=True)
    assert bead_id
    created = fake_bd.bead(bead_id)
    assert "kind:reading-list" in created["labels"]
    assert "needs:robert" in created["labels"]
    assert f"xid: {lit.reading_list_xid(TODAY)}" in created["description"]
    assert str(json_path) in created["description"]
    quiet = lit.reading_list_bead(ledger, TODAY, entries, digest_json=json_path, attention=False)
    assert "needs:robert" not in fake_bd.bead(quiet)["labels"]
    assert lit.reading_list_bead(ledger, TODAY, [], digest_json=json_path, attention=True) is None


def test_reading_records_target_the_expert_that_owns_the_topic() -> None:
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    records = lit.reading_records(entries, {"phenotype-informatics": ["rare-disease"]})
    assert records == [
        {
            "agent": "rare-disease",
            "identifier": "arXiv:2609.01234v1",
            "note": (
                "Temporal knowledge graph embeddings for phenotype trajectories: "
                "matched term 'knowledge graph' sits inside phenotype informatics."
            ),
            "source": "https://arxiv.org/abs/2609.01234v1",
        }
    ]
    assert lit.reading_records(entries, {}) == []
    assert lit.reading_identifier(CANDIDATES[1]) == "10.1101/2026.09.03.611222"


# --- read view ---------------------------------------------------------------------------


def test_literature_payload_and_text(lit_settings: Settings) -> None:
    _seed_candidates(lit_settings)
    payload = lit.literature_payload(lit_settings, TODAY)
    assert payload["counts"] == {"fetched": 0, "matched": 2, "summarised": 0, "pending": 2}
    assert payload["digest_exists"] is False

    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    lit.write_digest(lit_settings, TODAY, entries, {"arxiv": {"fetched": 3}})
    lit.mark_summarised(lit_settings, TODAY, [c["id"] for c in CANDIDATES])
    payload = lit.literature_payload(lit_settings, TODAY)
    assert payload["counts"] == {"fetched": 3, "matched": 2, "summarised": 2, "pending": 0}
    text = lit.literature_text(payload)
    assert "[high] Temporal knowledge graph embeddings" in text
    assert "for: goal Ship the temporal cohort model, topic phenotype-informatics" in text


def test_literature_command_emits_json(
    lit_repo: Path, lit_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_candidates(lit_settings)
    assert main(["--root", str(lit_repo), "literature", "--today", "2026-09-04", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["date"] == "2026-09-04"
    assert payload["counts"]["pending"] == 2
    assert payload["entries"] == []


# --- the standing agent's workday --------------------------------------------------------


def _make_agents(settings: Settings) -> None:
    """Scaffold the literature agent and one expert that owns the matched topic."""
    scaffold_agent(
        settings,
        AgentScaffoldSpec(
            name="literature",
            kind="functional",
            title="Literature watch",
            topics=["phenotype-informatics"],
            role="scribe",
            runtime="hermes",
            skills=["literature-review"],
        ),
    )
    scaffold_agent(
        settings,
        AgentScaffoldSpec(
            name="rare-disease",
            kind="expert",
            title="Rare disease expert",
            topics=["phenotype-informatics"],
            role="senior",
            runtime="claude",
        ),
    )


def _stub(artifact: dict | None = None) -> StubRunner:
    payload = json.dumps(ARTIFACT if artifact is None else artifact)
    return StubRunner(
        RunResult(
            summary="digest ready (source: state/literature)",
            artifacts=[
                Artifact(kind="literature-digest", path="literature-digest.json", content=payload)
            ],
        )
    )


def test_workday_summarises_pending_candidates_and_files_the_reading_list(
    lit_repo: Path,
    lit_settings: Settings,
    fake_bd: FakeBd,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _make_agents(lit_settings)
    _seed_candidates(lit_settings)
    runner = _stub()
    result = AgentWorkdayPatrol("literature", runner=runner, now=NOW).run(
        lit_settings, dry_run=False, beads=Beads(bin="bd", cwd=lit_repo)
    )
    assert result.state == "finished"
    assert len(result.runs) == 1 and result.runs[0]["ok"]
    # One JSON digest, no shell: the bulk tier's chat models must stay eligible
    # even though the scribe role may write in the workspace (ADR-0016).
    assert result.runs[0]["needs_tools"] is False
    prompt = runner.calls[0].prompt
    assert "## Candidate preprints" in prompt
    assert "### Open goals" in prompt
    assert "arxiv:2609.01234v1" in prompt

    assert result.literature is not None
    assert result.literature["entries"] == 2
    assert result.literature["errors"] == []

    md_path, json_path = lit.digest_paths(lit_settings, NOW.date())
    assert md_path.exists() and json_path.exists()
    assert lit.pending_candidates(lit_settings, NOW.date()) == []

    bead_id = result.literature["bead"]
    assert bead_id and "kind:reading-list" in fake_bd.bead(bead_id)["labels"]
    # no goal is due, so nothing wakes Robert
    assert "needs:robert" not in fake_bd.bead(bead_id)["labels"]

    reading = (lit_repo / "agents" / "rare-disease" / "memory" / "reading.md").read_text(
        encoding="utf-8"
    )
    assert "arXiv:2609.01234v1" in reading
    assert "https://arxiv.org/abs/2609.01234v1" in reading
    assert result.literature["reading"] == 1


def test_workday_idles_when_nothing_is_pending(
    lit_repo: Path, lit_settings: Settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_agents(lit_settings)
    runner = _stub()
    result = AgentWorkdayPatrol("literature", runner=runner, now=NOW).run(
        lit_settings, dry_run=False, beads=Beads(bin="bd", cwd=lit_repo)
    )
    assert result.state == "idle"
    assert result.runs == [] and runner.calls == []
    assert result.literature is None
    assert not lit.digest_paths(lit_settings, NOW.date())[0].exists()


def test_workday_blocks_when_the_artifact_names_an_unknown_paper(
    lit_repo: Path, lit_settings: Settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_agents(lit_settings)
    _seed_candidates(lit_settings)
    bad = {"entries": [{**ARTIFACT["entries"][0], "id": "arxiv:0000.00000"}]}
    result = AgentWorkdayPatrol("literature", runner=_stub(bad), now=NOW).run(
        lit_settings, dry_run=False, beads=Beads(bin="bd", cwd=lit_repo)
    )
    assert result.literature is not None
    assert result.literature["entries"] == 0
    assert result.literature["errors"] == ["arxiv:0000.00000: not in today's candidate list"]
    # a rejected paper still closes the day so the same candidates are not retried forever
    assert lit.pending_candidates(lit_settings, NOW.date()) == []


def test_workday_reports_a_missing_artifact(
    lit_repo: Path, lit_settings: Settings, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_agents(lit_settings)
    _seed_candidates(lit_settings)
    runner = StubRunner(RunResult(summary="nothing to report (source: fixture)"))
    result = AgentWorkdayPatrol("literature", runner=runner, now=NOW).run(
        lit_settings, dry_run=False, beads=Beads(bin="bd", cwd=lit_repo)
    )
    assert result.literature is not None
    assert result.literature["errors"] == ["no literature-digest artifact returned"]
    assert any(b["step"] == "literature digest" for b in result.blocked)
    assert lit.pending_candidates(lit_settings, NOW.date())


def test_digest_artifact_picks_the_last_inline_digest() -> None:
    assert digest_artifact([]) is None
    assert digest_artifact([{"result": {"artifacts": [{"kind": "plan", "content": "x"}]}}]) is None
    runs = [
        {"result": {"artifacts": [{"kind": "literature-digest", "content": "first"}]}},
        {"result": {"artifacts": [{"kind": "literature-digest", "content": "second"}]}},
    ]
    assert digest_artifact(runs) == "second"


def test_student_digest_lines_appear_only_for_a_named_student(lit_settings: Settings) -> None:
    assert lit.student_digest_lines(lit_settings, "gus-student", TODAY) == []
    entries, _errors = lit.validate_digest(ARTIFACT, CANDIDATES, limit=25)
    lit.write_digest(lit_settings, TODAY, entries, {})
    lines = lit.student_digest_lines(lit_settings, "gus-student", TODAY)
    assert lines[1] == "## Literature"
    assert "protein function benchmark" in lines[3]
    assert "https://www.biorxiv.org/content/10.1101/2026.09.03.611222v1" in lines[3]
    assert lines[-1].endswith("briefings/literature/2026-09-04.json")
    assert lit.student_digest_lines(lit_settings, "alex-example", TODAY) == []


def test_digest_artifact_reads_a_saved_digest_file(tmp_path) -> None:
    run_dir = tmp_path / "runs" / "r-1"
    run_dir.mkdir(parents=True)
    (run_dir / "literature-digest.json").write_text('{"entries": []}', encoding="utf-8")
    runs = [
        {
            "run_dir": str(run_dir),
            "result": {
                "artifacts": [{"kind": "digest", "path": str(run_dir / "literature-digest.json")}]
            },
        }
    ]
    assert digest_artifact(runs) is None  # no root: never read arbitrary paths
    assert digest_artifact(runs, tmp_path) == '{"entries": []}'
    outside = [{"result": {"artifacts": [{"kind": "digest", "path": "/etc/hostname"}]}}]
    assert digest_artifact(outside, tmp_path) is None
    relative = [
        {
            "run_dir": str(run_dir),
            "result": {"artifacts": [{"kind": "file", "path": "literature-digest.json"}]},
        }
    ]
    assert digest_artifact(relative, tmp_path) == '{"entries": []}'
