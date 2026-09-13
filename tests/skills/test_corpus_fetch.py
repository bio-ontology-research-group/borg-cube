from __future__ import annotations

import json
from pathlib import Path

import corpus_fetch
from corpus_fetch import arxiv_pdf_url, main, plos_pdf_url, resolve_download
from skillslib import load_manifest

PDF = b"%PDF-1.4 fake"


def fake_fetcher(calls: list[str]):
    def fetch(url: str) -> tuple[bytes, str]:
        calls.append(url)
        if "plos.org" in url or "arxiv.org/pdf" in url:
            return PDF, "application/pdf"
        return b"<html>page</html>", "text/html; charset=utf-8"

    return fetch


def base_args(repo, raw: Path) -> list[str]:
    return ["--manifest", str(repo.manifest), "--raw-dir", str(raw), "--delay", "0"]


def test_url_patterns() -> None:
    assert plos_pdf_url("10.1371/journal.pcbi.1003954") == (
        "https://journals.plos.org/ploscompbiol/article/file?id=10.1371/journal.pcbi.1003954&type=printable"
    )
    assert plos_pdf_url("10.1371/journal.pbio.1001745").startswith(
        "https://journals.plos.org/plosbiology/"
    )
    assert plos_pdf_url("10.1038/nbt.4089") is None
    assert arxiv_pdf_url("https://arxiv.org/abs/2003.12206") == "https://arxiv.org/pdf/2003.12206"
    assert (
        arxiv_pdf_url("https://arxiv.org/abs/2003.12206v2") == "https://arxiv.org/pdf/2003.12206v2"
    )
    assert arxiv_pdf_url("https://example.org/x") is None


def test_resolve_download(skill_repo) -> None:
    by_id = {s.id: s for s in load_manifest(skill_repo.manifest)}
    assert resolve_download(by_id["marino2014"])[1] == "pdf"
    assert resolve_download(by_id["pineau2021"]) == ("https://arxiv.org/pdf/2003.12206", "pdf")
    assert resolve_download(by_id["turing-way"]) == ("https://book.the-turing-way.org/", "")
    assert resolve_download(by_id["nap2019-mentorship"])[0].startswith(
        "https://nap.nationalacademies.org"
    )


def test_dry_run_makes_no_requests(skill_repo, tmp_path: Path, capsys) -> None:
    calls: list[str] = []
    raw = tmp_path / "raw"
    assert (
        main([*base_args(skill_repo, raw), "--dry-run", "--json"], fetcher=fake_fetcher(calls)) == 0
    )
    results = {r["id"]: r for r in json.loads(capsys.readouterr().out)}
    assert calls == [] and not raw.exists()
    assert results["lovitts2001"]["status"] == "skipped"
    assert results["marino2014"]["status"] == "dry-run"
    assert results["nap2019-mentorship"]["status"] == "manual"


def test_fetch_records_hash_and_skips_next_time(skill_repo, tmp_path: Path, capsys) -> None:
    calls: list[str] = []
    raw = tmp_path / "raw"
    rc = main(
        [*base_args(skill_repo, raw), "--id", "marino2014", "--id", "turing-way"],
        fetcher=fake_fetcher(calls),
    )
    assert rc == 0
    assert len(calls) == 2
    assert (raw / "marino2014.pdf").read_bytes() == PDF
    assert (raw / "turing-way.html").exists()
    by_id = {s.id: s for s in load_manifest(skill_repo.manifest)}
    assert by_id["marino2014"].sha256 and by_id["marino2014"].fetched
    assert by_id["gu2007"].sha256 is None
    assert skill_repo.manifest.read_text(encoding="utf-8").startswith("# test manifest")
    calls.clear()
    assert (
        main([*base_args(skill_repo, raw), "--id", "marino2014"], fetcher=fake_fetcher(calls)) == 0
    )
    assert calls == []
    out = capsys.readouterr().out
    assert "already fetched" in out


def test_manual_download_is_recorded(skill_repo, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "nap2019-mentorship.pdf").write_bytes(PDF)
    assert (
        main([*base_args(skill_repo, raw), "--id", "nap2019-mentorship"], fetcher=fake_fetcher([]))
        == 0
    )
    entry = [s for s in load_manifest(skill_repo.manifest) if s.id == "nap2019-mentorship"][0]
    assert entry.sha256 is not None


def test_bad_pdf_and_unknown_id(skill_repo, tmp_path: Path, capsys) -> None:
    def bad(url: str) -> tuple[bytes, str]:
        return b"<html>login</html>", "text/html"

    assert main([*base_args(skill_repo, tmp_path / "raw"), "--id", "marino2014"], fetcher=bad) == 1
    assert "not a PDF" in capsys.readouterr().out
    assert main([*base_args(skill_repo, tmp_path / "raw"), "--id", "ghost"], fetcher=bad) == 1


def test_topic_filter(skill_repo, tmp_path: Path, capsys) -> None:
    calls: list[str] = []
    assert (
        main(
            [*base_args(skill_repo, tmp_path / "raw"), "--topic", "reproducibility", "--json"],
            fetcher=fake_fetcher(calls),
        )
        == 0
    )
    ids = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert ids == {"turing-way", "pineau2021"}


def test_extension_for() -> None:
    assert corpus_fetch.extension_for("https://x/y", "application/pdf", "") == "pdf"
    assert corpus_fetch.extension_for("https://x/y.xml", "application/octet-stream", "") == "xml"
    assert corpus_fetch.extension_for("https://x/y", "", "") == "bin"
