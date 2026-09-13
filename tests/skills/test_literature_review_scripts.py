# ruff: noqa: E501
"""Tests for the literature-review skill scripts (search_log.py, cite_check.py)."""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "literature-review"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"lr_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


search_log = load("search_log")
cite_check = load("cite_check")


# --------------------------------------------------------------------------- search_log


def run_log(*argv: str) -> int:
    return search_log.main(list(argv))


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # treat tmp_path as inside the checkout so the scripts write without --apply
    monkeypatch.setattr(search_log, "REPO_ROOT", tmp_path)
    return tmp_path / "runs" / "42" / "search.jsonl"


def init(log: Path) -> None:
    assert (
        run_log(
            "init",
            "--log",
            str(log),
            "--date",
            "2026-09-02",
            "--question",
            "how are protein function predictions evaluated",
            "--review-type",
            "systematized",
        )
        == 0
    )


def seed_searches(log: Path, hits: int = 4) -> None:
    assert (
        run_log(
            "add-search",
            "--log",
            str(log),
            "--date",
            "2026-09-02",
            "--database",
            "PubMed",
            "--query",
            '("protein function"[tiab]) AND (prediction[tiab])',
            "--filters",
            "2015:2026[dp]",
            "--hits",
            str(hits),
        )
        == 0
    )


def _append_search_worker(path: str, worker: int) -> None:
    search_log.append(
        Path(path),
        {
            "type": "search",
            "date": "2026-09-02",
            "source_kind": "database",
            "database": f"worker-{worker}",
            "interface": "API",
            "query": f"query-{worker}",
            "filters": "",
            "hits": worker,
            "note": "",
        },
        True,
    )


def screen(log: Path, stage: str, record: str, decision: str, reason: str | None = None) -> int:
    argv = [
        "add-screen",
        "--log",
        str(log),
        "--date",
        "2026-09-03",
        "--stage",
        stage,
        "--record",
        record,
        "--decision",
        decision,
    ]
    if reason:
        argv += ["--reason", reason]
    return run_log(*argv)


def test_init_writes_protocol_and_default_codes(log_path: Path) -> None:
    init(log_path)
    entries = search_log.read_log(log_path)
    assert entries[0]["type"] == "protocol"
    assert entries[0]["question"].startswith("how are protein function")
    codes = {e["code"] for e in entries if e["type"] == "code"}
    assert {"E1", "E4"} <= codes
    assert [e["seq"] for e in entries] == list(range(1, len(entries) + 1))


def test_init_refuses_to_reinitialize(log_path: Path) -> None:
    init(log_path)
    assert (
        run_log("init", "--log", str(log_path), "--question", "q", "--review-type", "narrative")
        == 2
    )


def test_hash_chain_detects_an_edit(log_path: Path) -> None:
    init(log_path)
    seed_searches(log_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["hits"] = 999
    lines[-1] = json.dumps(tampered)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = search_log.check_chain(search_log.read_log(log_path))
    assert any("hash chain broken" in p for p in problems)


def test_concurrent_appends_keep_sequence_and_chain(log_path: Path, monkeypatch) -> None:
    init(log_path)
    workers = 8
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(workers)
    original_read_log = search_log.read_log

    def gated_read_log(path: Path) -> list[dict]:
        entries = original_read_log(path)
        barrier.wait(timeout=10)
        return entries

    # Force the old read-then-open implementation to give every writer the same snapshot.
    monkeypatch.setattr(search_log, "read_log", gated_read_log)
    processes = [
        context.Process(target=_append_search_worker, args=(str(log_path), worker))
        for worker in range(workers)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    entries = original_read_log(log_path)
    assert len(entries) == 7 + workers
    assert [entry["seq"] for entry in entries] == list(range(1, len(entries) + 1))
    assert search_log.check_chain(entries) == []


def test_exclusion_without_a_reason_code_is_refused(log_path: Path) -> None:
    init(log_path)
    assert screen(log_path, "title-abstract", "10.1/a", "exclude") == 2


def test_undeclared_reason_code_is_refused(log_path: Path) -> None:
    init(log_path)
    assert screen(log_path, "title-abstract", "10.1/a", "exclude", "Z9") == 2
    assert (
        run_log(
            "add-code",
            "--log",
            str(log_path),
            "--code",
            "Z9",
            "--stage",
            "both",
            "--description",
            "preprint superseded by a journal version",
        )
        == 0
    )
    assert screen(log_path, "title-abstract", "10.1/a", "exclude", "Z9") == 0


def test_duplicate_decision_on_one_record_is_refused(log_path: Path) -> None:
    init(log_path)
    assert screen(log_path, "title-abstract", "10.1/a", "include") == 0
    assert screen(log_path, "title-abstract", "10.1/A ", "exclude", "E1") == 2


def test_flow_refuses_when_numbers_do_not_reconcile(
    log_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(log_path)
    seed_searches(log_path, hits=4)
    assert screen(log_path, "title-abstract", "10.1/a", "include") == 0
    assert run_log("flow", "--log", str(log_path)) == 2
    err = capsys.readouterr().err
    assert "records screened (1)" in err


def complete_log(log: Path) -> None:
    init(log)
    seed_searches(log, hits=4)
    assert run_log("add-dedup", "--log", str(log), "--removed", "1") == 0
    assert screen(log, "title-abstract", "10.1/a", "include") == 0
    assert screen(log, "title-abstract", "10.1/b", "include") == 0
    assert screen(log, "title-abstract", "10.1/c", "exclude", "E1") == 0
    assert (
        run_log(
            "add-retrieval",
            "--log",
            str(log),
            "--record",
            "10.1/b",
            "--status",
            "not-retrieved",
            "--reason",
            "no access",
        )
        == 0
    )
    assert screen(log, "full-text", "10.1/a", "include") == 0


def test_flow_renders_and_reconciles(log_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    complete_log(log_path)
    assert run_log("validate", "--log", str(log_path)) == 0
    assert run_log("flow", "--log", str(log_path)) == 0
    out = capsys.readouterr().out
    assert "records screened on title and abstract: 3" in out
    assert "reports sought for retrieval: 2" in out
    assert "reports assessed for eligibility: 1" in out
    assert "studies included in the review: 1" in out
    assert "Search dates: 2026-09-02" in out


def test_flow_json_carries_the_counts_and_reasons(log_path: Path) -> None:
    complete_log(log_path)
    flow, problems = search_log.validate(search_log.read_log(log_path))
    assert problems == []
    assert flow["identified_total"] == 4
    assert flow["duplicates_removed"] == 1
    assert flow["excluded_title_abstract_by_reason"] == {"E1": 1}
    assert flow["included_records"] == ["10.1/a"]
    assert flow["search_dates"] == ["2026-09-02"]


def test_retrieval_for_an_unscreened_record_is_a_problem(log_path: Path) -> None:
    complete_log(log_path)
    assert (
        run_log(
            "add-retrieval",
            "--log",
            str(log_path),
            "--record",
            "10.1/zz",
            "--status",
            "retrieved",
        )
        == 0
    )
    _, problems = search_log.validate(search_log.read_log(log_path))
    assert any("never included at title-abstract" in p for p in problems)


def test_dry_run_outside_the_checkout_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(search_log, "REPO_ROOT", tmp_path / "checkout")
    outside = tmp_path / "elsewhere" / "search.jsonl"
    assert (
        run_log("init", "--log", str(outside), "--question", "q", "--review-type", "narrative") == 0
    )
    assert not outside.exists()


# --------------------------------------------------------------------------- cite_check

BIB = """
@article{pautasso2013,
  title = {Ten Simple Rules for Writing a Literature Review},
  author = {Pautasso, Marco},
  journal = {PLoS Computational Biology},
  year = {2013},
  doi = {10.1371/journal.pcbi.1003149}
}

@article{wrongyear,
  title = {Ten simple rules for reading a scientific paper},
  author = {Carey, Maureen A.},
  year = {2011},
  doi = {10.1371/journal.pcbi.1008032}
}

@article{wrongtitle,
  title = {A completely different paper about something else entirely},
  year = {2021},
  doi = {10.1136/bmj.n71}
}

@article{ghost,
  title = {Deep learning solves protein folding for good},
  author = {Nobody, A.},
  year = {2024},
  doi = {10.9999/does.not.exist}
}

@inproceedings{noid,
  title = {A workshop paper with no identifier},
  author = {Someone, B.},
  year = {2019}
}

@article{pulled,
  title = {A retracted study},
  year = {2018},
  pmid = {12345678}
}
"""

REGISTRY = {
    "doi": {
        "10.1371/journal.pcbi.1003149": {
            "source": "crossref",
            "title": "Ten Simple Rules for Writing a Literature Review",
            "year": 2013,
            "retracted": False,
        },
        "10.1371/journal.pcbi.1008032": {
            "source": "crossref",
            "title": "Ten simple rules for reading a scientific paper",
            "year": 2020,
            "retracted": False,
        },
        "10.1136/bmj.n71": {
            "source": "crossref",
            "title": "The PRISMA 2020 statement: an updated guideline for reporting systematic reviews",
            "year": 2021,
            "retracted": False,
        },
    },
    "pmid": {
        "12345678": {
            "source": "pubmed",
            "title": "A retracted study",
            "year": 2018,
            "retracted": True,
        }
    },
}


@pytest.fixture
def bib_and_registry(tmp_path: Path) -> tuple[Path, Path]:
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(REGISTRY), encoding="utf-8")
    return bib, registry


def test_bibtex_parser_reads_keys_and_fields(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []
    assert [entry.key for entry in entries][:3] == ["pautasso2013", "wrongyear", "wrongtitle"]
    assert entries[0].fields["doi"] == "10.1371/journal.pcbi.1003149"
    assert cite_check.entry_year(entries[1]) == "2011"


def test_cite_checker_matches_paper_writing_and_parses_parentheses(tmp_path: Path) -> None:
    other = SKILL.parent / "paper-writing" / "scripts" / "cite_check.py"
    assert (SCRIPTS / "cite_check.py").read_text(encoding="utf-8") == other.read_text(
        encoding="utf-8"
    )
    bib = tmp_path / "parenthesized.bib"
    bib.write_text("@article(key, title={T}, doi={10.1/x})\n", encoding="utf-8")
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []
    assert [(entry.key, entry.fields["title"], entry.fields["doi"]) for entry in entries] == [
        ("key", "T", "10.1/x")
    ]


def test_every_resolved_identifier_is_checked_for_retraction(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{both, author={A}, title={T}, journal={J}, year={2020}, "
        "doi={10.1/clean}, pmid={123}}\n",
        encoding="utf-8",
    )
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []

    class Client:
        def get(self, url: str):
            if "10.1%2Fclean" in url:
                return 200, {"message": {"title": ["T"], "issued": {"date-parts": [[2020]]}}}
            if "filter=updates" in url:
                return 200, {"message": {"items": []}}
            return 200, {
                "result": {
                    "123": {
                        "title": "T",
                        "pubdate": "2020",
                        "authors": [],
                        "articleids": [],
                        "pubtype": ["Retracted Publication"],
                    }
                }
            }

    findings = cite_check.online_checks(entries, Client(), 0.8, cite_check.Report())
    assert any(finding.code == "pubmed.retracted" for finding in findings)


def test_offline_check_flags_incomplete_entries(bib_and_registry: tuple[Path, Path]) -> None:
    bib, _ = bib_and_registry
    entries, problems = cite_check.parse_bibtex(bib)
    assert problems == []
    findings = cite_check.offline_checks(entries, cite_check.dt.date(2026, 9, 2))
    codes = {finding.code for finding in findings}
    assert {"bib.missing-field", "bib.no-doi"} <= codes


def test_cli_offline_exits_two_and_never_opens_a_socket(
    bib_and_registry: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    bib, registry = bib_and_registry

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("cite_check opened the network in --offline mode")

    monkeypatch.setattr(cite_check.urllib.request, "urlopen", forbidden)
    code = cite_check.main([str(bib), "--offline", "--json"])
    assert code == 1


def test_cli_offline_needs_no_registry_snapshot(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a, author={A}, title={T}, journal={J}, year={2020}, doi={10.1234/x}}\n",
        encoding="utf-8",
    )
    assert cite_check.main([str(bib), "--offline"]) == 0


def test_clean_bibliography_exits_zero(tmp_path: Path) -> None:
    bib = tmp_path / "clean.bib"
    bib.write_text(
        "@article{a, author={Pautasso, Marco}, title={Ten Simple Rules for Writing a Literature Review},"
        " journal={PLoS Computational Biology}, year={2013}, doi={10.1371/journal.pcbi.1003149}}",
        encoding="utf-8",
    )
    assert cite_check.main([str(bib), "--offline"]) == 0


def test_offline_findings_name_the_problem_entries(bib_and_registry: tuple[Path, Path]) -> None:
    bib, _ = bib_and_registry
    entries, _ = cite_check.parse_bibtex(bib)
    findings = cite_check.offline_checks(entries, cite_check.dt.date(2026, 9, 2))
    assert any(finding.code == "bib.no-doi" and "noid" in finding.message for finding in findings)


def test_cite_check_accepts_multiple_bibliographies(tmp_path: Path) -> None:
    first = tmp_path / "first.bib"
    second = tmp_path / "second.bib"
    first.write_text(
        "@article{a, author={A}, title={T}, journal={J}, year={2020}, doi={10.1234/a}}\n",
        encoding="utf-8",
    )
    second.write_text(
        "@article{b, author={B}, title={U}, journal={J}, year={2021}, doi={10.1234/b}}\n",
        encoding="utf-8",
    )
    assert cite_check.main([str(first), str(second), "--offline"]) == 0
