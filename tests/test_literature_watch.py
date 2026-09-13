"""The deterministic half of the literature watch: fetch, dedupe, match, write.

No test here reaches the network: every fetch goes through an injected ``http_get``
that answers from ``tests/fixtures/literature/``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pytest
import yaml

from cube.config import LiteratureWatch, Settings, load_settings
from cube.doctor import check_literature_watch
from cube.patrols import base
from cube.patrols import literature_watch as lw
from tests.helpers_engine import fixtures, make_repo

globals().update(fixtures())

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "literature"
TODAY = date(2026, 9, 4)

PROJECTS = {
    "@context": {},
    "@graph": [
        {"@id": "borg-id:topic/phenotype-informatics", "@type": "borg:Topic"},
        {"@id": "borg-id:topic/protein-function-prediction", "@type": "borg:Topic"},
        {
            "@id": "borg-id:project/nih-temporal-kg",
            "@type": "borg:Project",
            "schema:name": "temporal knowledge graph cohorts",
            "borg:startYear": 2025,
            "borg:hasMember": [
                {"@id": "borg-id:person/alex-example", "borg:roleOnProject": "student"}
            ],
            "borg:topic": [{"@id": "borg-id:topic/phenotype-informatics"}],
        },
        {
            "@id": "borg-id:project/old-one",
            "@type": "borg:Project",
            "schema:name": "sparse linear solves",
            "borg:startYear": 2015,
            "borg:endYear": 2018,
        },
    ],
}


class FakeHttp:
    """Answers arXiv and bioRxiv from fixtures; a named source can be made to fail."""

    def __init__(self, *, fail: str | None = None, status: int = 500) -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.status = status

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        self.calls.append(url)
        assert "User-Agent" in headers
        if url.startswith(lw.ARXIV_API):
            if self.fail == "arxiv":
                return self.status, b""
            return 200, (FIXTURES / "arxiv.atom").read_bytes()
        if url.startswith(lw.BIORXIV_API):
            if self.fail == "biorxiv":
                return self.status, b""
            return 200, (FIXTURES / "biorxiv.json").read_bytes()
        if url.startswith(lw.MEDRXIV_API):
            # the same fixture; none of its categories is a medRxiv one, so no row
            return 200, (FIXTURES / "biorxiv.json").read_bytes()
        raise AssertionError(f"unexpected url {url}")


@pytest.fixture
def lit_repo(tmp_path: Path) -> Path:
    root = make_repo(tmp_path)
    (root / "rkg" / "projects.jsonld").write_text(json.dumps(PROJECTS), encoding="utf-8")
    config = yaml.safe_load((root / "cube.yaml").read_text(encoding="utf-8"))
    config["literature_watch"] = {
        "arxiv": {"categories": ["cs.AI"], "max_per_day": 20},
        "biorxiv": {"categories": ["bioinformatics", "genomics"], "max_per_day": 20},
        "keywords": ["knowledge graph", "protein function"],
        "max_summaries_per_day": 5,
    }
    (root / "cube.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return root


@pytest.fixture
def lit_settings(lit_repo: Path) -> Settings:
    return load_settings(lit_repo)


def _patrol(http: FakeHttp) -> lw.LiteratureWatchPatrol:
    return lw.LiteratureWatchPatrol(http_get=http, pause=lambda _s: None)


# --- parsing -----------------------------------------------------------------------------


def test_arxiv_atom_parses_into_the_normal_shape() -> None:
    rows = lw.parse_arxiv_atom((FIXTURES / "arxiv.atom").read_bytes())
    assert [row["id"] for row in rows] == [
        "arxiv:2609.01234v1",
        "arxiv:2609.00987v2",
        "arxiv:2608.55555v1",
    ]
    first = rows[0]
    assert first["source"] == "arxiv"
    assert first["url"] == "https://arxiv.org/abs/2609.01234v1"
    assert first["authors"] == ["G Student", "A Example"]
    assert first["categories"] == ["cs.AI", "cs.LG"]
    assert first["published"] == "2026-09-04"
    assert first["doi"] is None
    assert "phenotype trajectories" in first["abstract"]
    assert rows[2]["doi"] == "10.1000/older"


def test_arxiv_malformed_feed_is_a_fetch_error() -> None:
    with pytest.raises(lw.FetchError):
        lw.parse_arxiv_atom(b"<feed>not closed")


def test_biorxiv_details_parse_and_filter_by_category() -> None:
    rows = lw.parse_biorxiv_details(
        (FIXTURES / "biorxiv.json").read_bytes(), ["bioinformatics", "genomics"]
    )
    assert [row["id"] for row in rows] == [
        "biorxiv:10.1101/2026.09.03.611222",
        "biorxiv:10.1101/2026.09.03.611999",
    ]
    first = rows[0]
    assert first["url"] == "https://www.biorxiv.org/content/10.1101/2026.09.03.611222v1"
    assert first["authors"] == ["Fellow, F.", "Former, Z."]
    assert first["doi"] == "10.1101/2026.09.03.611222"
    assert rows[1]["url"].endswith("v2")


def test_biorxiv_malformed_json_is_a_fetch_error() -> None:
    with pytest.raises(lw.FetchError):
        lw.parse_biorxiv_details(b"not json", [])


def test_arxiv_query_url_is_the_documented_api_call() -> None:
    url = lw.arxiv_query_url("q-bio.QM", 40)
    assert url.startswith(lw.ARXIV_API + "?")
    assert "search_query=cat%3Aq-bio.QM" in url
    assert "sortBy=submittedDate" in url
    assert "sortOrder=descending" in url
    assert "max_results=40" in url
    # 2026-09-08: nine per-category calls were rate limited (HTTP 429); one OR query
    both = lw.arxiv_query_url(["cs.AI", "cs.LO"], 200, start=200)
    assert "search_query=cat%3Acs.AI+OR+cat%3Acs.LO" in both and "start=200" in both


def test_arxiv_is_one_paged_query_and_a_failure_is_retried_once() -> None:
    http = FakeHttp()
    config = LiteratureWatch(arxiv={"categories": ["cs.AI", "cs.LO", "q-bio.QM"]})
    rows, warnings = lw.fetch_arxiv(config, http_get=http, pause=lambda _s: None)
    assert len(rows) == 3 and not warnings
    assert len(http.calls) == 1 and "cat%3Acs.AI+OR+cat%3Acs.LO+OR+cat%3Aq-bio.QM" in http.calls[0]

    pauses: list[float] = []
    failing = FakeHttp(fail="arxiv", status=429)
    rows, warnings = lw.fetch_arxiv(config, http_get=failing, pause=pauses.append)
    assert rows == [] and warnings == [
        f"arxiv cs.AI, cs.LO, q-bio.QM: {failing.calls[0]}: HTTP 429"
    ]
    assert len(failing.calls) == 2 and pauses == [lw.RETRY_PAUSE_SECONDS]


def test_arxiv_stops_paging_once_past_the_window() -> None:
    pages: list[str] = []

    def http(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        pages.append(url)
        return 200, (FIXTURES / "arxiv.atom").read_bytes()

    config = LiteratureWatch(arxiv={"categories": ["cs.AI"], "max_per_day": 9})
    # the fixture holds 3 entries: page size 3, the oldest is 2026-08-30, window 09-03/09-04
    lw.ARXIV_PAGE, saved = 3, lw.ARXIV_PAGE
    try:
        rows, _warnings = lw.fetch_arxiv(
            config, http_get=http, pause=lambda _s: None, window={"2026-09-03", "2026-09-04"}
        )
    finally:
        lw.ARXIV_PAGE = saved
    assert len(pages) == 1 and len(rows) == 3


def test_medrxiv_rows_name_medrxiv() -> None:
    rows = lw.parse_medrxiv_details((FIXTURES / "biorxiv.json").read_bytes(), ["bioinformatics"])
    assert [row["id"] for row in rows] == ["medrxiv:10.1101/2026.09.03.611222"]
    assert rows[0]["source"] == "medrxiv"
    assert rows[0]["url"] == "https://www.medrxiv.org/content/10.1101/2026.09.03.611222v1"


def test_details_api_pages_by_cursor_until_total() -> None:
    def page(cursor: int, count: int, total: int) -> bytes:
        rows = [
            {
                "doi": f"10.1101/x{cursor + i}",
                "title": f"t{cursor + i}",
                "abstract": "",
                "date": "2026-09-04",
                "version": "1",
                "category": "genomics",
                "authors": "A",
            }
            for i in range(count)
        ]
        return json.dumps(
            {"messages": [{"count": count, "total": total}], "collection": rows}
        ).encode()

    calls: list[str] = []

    def http(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
        calls.append(url)
        cursor = int(url.rsplit("/", 1)[-1])
        return 200, page(cursor, 100 if cursor == 0 else 40, 140)

    config = LiteratureWatch(biorxiv={"categories": ["genomics"], "max_per_day": 400})
    rows, warnings = lw.fetch_biorxiv(
        config, since=date(2026, 9, 3), until=date(2026, 9, 4), http_get=http, pause=lambda _s: None
    )
    assert not warnings and len(rows) == 140
    assert [c.rsplit("/", 1)[-1] for c in calls] == ["0", "100"]


# --- matching ----------------------------------------------------------------------------


def test_keyword_and_auto_terms_match_a_project_name_and_a_goal_title(
    lit_settings: Settings,
) -> None:
    auto, sources = lw.auto_terms(lit_settings, beads=None)
    assert "temporal knowledge graph cohorts" in auto
    assert "sparse linear solves" not in auto  # the project ended before this year
    assert "phenotype informatics" in auto and "phenotype-informatics" in auto
    assert sources["topics"] == ["phenotype-informatics", "protein-function-prediction"]

    terms = lw.all_terms(lit_settings.literature_watch, [*auto, "Ship the phenotype benchmark"])
    row = {
        "title": "Temporal knowledge graph cohorts and the phenotype benchmark",
        "abstract": "We ship the phenotype benchmark for protein function work.",
    }
    hits = lw.match_terms(row, terms)
    assert "knowledge graph" in hits
    assert "protein function" in hits
    assert "temporal knowledge graph cohorts" in hits
    assert "Ship the phenotype benchmark" in hits


def test_slug_terms_keeps_the_slug_and_its_phrase() -> None:
    assert lw.slug_terms("rare-disease") == ["rare-disease", "rare disease"]
    assert lw.slug_terms("genomics") == ["genomics"]


# --- patrol ------------------------------------------------------------------------------


def test_patrol_writes_the_days_candidates_and_updates_the_cursor(
    lit_settings: Settings,
) -> None:
    http = FakeHttp()
    report = base.run_patrol(lit_settings, _patrol(http), today=TODAY, dry_run=False, beads=None)
    assert not report.failed and not report.warnings
    assert http.calls[0].startswith(lw.ARXIV_API)
    assert http.calls[1] == f"{lw.BIORXIV_API}/2026-09-03/2026-09-04/0"

    rows = [
        json.loads(line)
        for line in (lit_settings.state_dir() / "literature" / "2026-09-04.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    ids = [row["id"] for row in rows]
    # the unrelated GPU solver, the out-of-window paper and the off-topic
    # organoid preprint are all dropped
    assert ids == ["arxiv:2609.01234v1", "biorxiv:10.1101/2026.09.03.611222"]
    assert rows[0]["matched"] == ["knowledge graph"]
    assert rows[0]["summarised"] is False
    assert rows[1]["matched"] == ["protein function"]
    assert report.data["counts"]["arxiv"] == {"fetched": 3, "new": 2, "matched": 1}
    assert report.data["counts"]["biorxiv"]["matched"] == 1

    from cube.patrols.cursors import load_cursor

    cursor = load_cursor(lit_settings.state_dir(), "literature_watch")
    assert cursor["candidates"] == 2
    assert cursor["today"] == "2026-09-04"
    assert cursor["seen"] == 4


def test_dry_run_writes_nothing(lit_settings: Settings) -> None:
    report = base.run_patrol(lit_settings, _patrol(FakeHttp()), today=TODAY, dry_run=True)
    assert "would go" in report.summary
    assert not (lit_settings.state_dir() / "literature" / "2026-09-04.jsonl").exists()
    assert not lw.seen_path(lit_settings).exists()


def test_ids_already_seen_are_not_offered_twice(lit_settings: Settings) -> None:
    lw.save_seen(lit_settings, {"arxiv:2609.01234v1": "2026-09-01"})
    base.run_patrol(lit_settings, _patrol(FakeHttp()), today=TODAY, dry_run=False)
    from cube.literature import load_candidates

    ids = [row["id"] for row in load_candidates(lit_settings, TODAY)]
    assert ids == ["biorxiv:10.1101/2026.09.03.611222"]


def test_seen_ledger_forgets_after_sixty_days() -> None:
    kept = lw.prune_seen(
        {"a": "2026-09-01", "b": "2026-06-01", "c": "not-a-date"}, date(2026, 9, 4)
    )
    assert kept == {"a": "2026-09-01"}


def test_a_failed_source_is_a_warning_not_a_crash(lit_settings: Settings) -> None:
    report = base.run_patrol(
        lit_settings, _patrol(FakeHttp(fail="arxiv")), today=TODAY, dry_run=False
    )
    assert not report.failed
    assert any("arxiv cs.AI: " in w and "HTTP 500" in w for w in report.warnings)
    assert report.data["counts"]["arxiv"]["fetched"] == 0
    from cube.literature import load_candidates

    assert [row["source"] for row in load_candidates(lit_settings, TODAY)] == ["biorxiv"]


def test_a_failed_biorxiv_source_is_reported_separately(lit_settings: Settings) -> None:
    report = base.run_patrol(
        lit_settings, _patrol(FakeHttp(fail="biorxiv")), today=TODAY, dry_run=True
    )
    assert any(w.startswith("biorxiv: ") for w in report.warnings)
    assert report.data["counts"]["arxiv"]["matched"] == 1


def test_patrol_is_registered_under_both_spellings() -> None:
    assert "literature_watch" in base.names()
    assert base.normalise("literature-watch") == "literature_watch"


# --- configuration -----------------------------------------------------------------------


def test_config_defaults_and_rejection_of_unknown_keys(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from cube.config import LiteratureWatch

    default = LiteratureWatch()
    assert "cs.AI" in default.arxiv.categories
    assert "bioinformatics" in default.biorxiv.categories
    assert "knowledge graph" in default.keywords
    assert default.max_summaries_per_day == 25
    assert default.digest_path(tmp_path) == tmp_path / "briefings" / "literature"
    with pytest.raises(ValidationError):
        LiteratureWatch.model_validate({"arxiv": {"categories": ["cs.AI"], "typo": 1}})
    with pytest.raises(ValidationError):
        LiteratureWatch.model_validate({"digest_dir": "/etc"})
    with pytest.raises(ValidationError):
        LiteratureWatch.model_validate({"keywords": ["ok", "  "]})


def test_doctor_reports_the_literature_watch_configuration(lit_settings: Settings) -> None:
    (check,) = check_literature_watch(lit_settings)
    assert check.name == "literature_watch:config"
    assert check.ok
    assert "2 keywords" in check.detail

    lit_settings.literature_watch.keywords = []
    lit_settings.literature_watch.per_topic_keywords = {"genomics": []}
    (bad,) = check_literature_watch(lit_settings)
    assert not bad.ok
    assert "no keywords configured" in bad.detail
    assert "per_topic_keywords[genomics] is empty" in bad.detail


def test_repository_configuration_declares_the_patrol_and_the_timer() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root)
    assert settings.patrols["literature_watch"] == "06:30"
    assert settings.group is not None
    assert settings.group.functional["literature"].role == "scribe"
    timer = (root / "systemd" / "cube-patrol-literature-watch.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 06:30:00" in timer
    assert "Unit=cube-patrol@literature-watch.service" in timer


def test_second_run_on_the_same_day_keeps_the_candidates(lit_settings: Settings) -> None:
    """A manual run after the timer must add to the day's file, not empty it."""
    http = FakeHttp()
    first = base.run_patrol(lit_settings, _patrol(http), today=TODAY, dry_run=False, beads=None)
    path = lit_settings.state_dir() / "literature" / "2026-09-04.jsonl"
    before = path.read_text(encoding="utf-8")
    assert before.strip() and first.data["candidates"] > 0
    second = base.run_patrol(lit_settings, _patrol(http), today=TODAY, dry_run=False, beads=None)
    assert second.data["candidates"] == 0  # everything is already seen
    assert path.read_text(encoding="utf-8") == before
    assert second.data["candidates_total_today"] == first.data["candidates"]
