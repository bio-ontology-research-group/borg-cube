from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from corpus_verify import cache_path, main, title_score
from skillslib import load_manifest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    dst = tmp_path / "crossref"
    shutil.copytree(FIXTURES / "crossref", dst)
    return dst


def test_title_score() -> None:
    assert (
        title_score(
            "Ten Simple Rules for Finishing Your PhD",
            "Marino J (2014) Ten simple rules for finishing your PhD. PLoS",
        )
        == 1.0
    )
    assert title_score("Something Else Entirely", "Marino J (2014) Ten simple rules") == 0.0
    assert title_score("<i>Ten</i> simple &amp; rules", "ten simple and rules") == 1.0


def test_offline_with_cache(skill_repo, cache: Path, capsys) -> None:
    rc = main(
        ["--manifest", str(skill_repo.manifest), "--cache-dir", str(cache), "--offline", "--json"]
    )
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["marino2014"]["status"] == "ok"
    assert by_id["gu2007"]["status"] == "mismatch"  # fixture cached the wrong title
    assert by_id["nap2019-mentorship"]["status"] == "no-cache"
    assert by_id["turing-way"]["status"] == "no-doi"


def test_mark_verified_only_on_match(skill_repo, cache: Path) -> None:
    main(
        [
            "--manifest",
            str(skill_repo.manifest),
            "--cache-dir",
            str(cache),
            "--offline",
            "--mark-verified",
        ]
    )
    by_id = {s.id: s for s in load_manifest(skill_repo.manifest)}
    assert by_id["marino2014"].verified_by == "fetch"
    assert by_id["gu2007"].verified_by == "memory"


def test_online_lookup_caches_and_404(skill_repo, tmp_path: Path, capsys) -> None:
    import urllib.error

    seen: list[str] = []

    def getter(url: str) -> bytes:
        seen.append(url)
        if "25568" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return json.dumps(
            {"message": {"title": ["Ten simple rules for graduate students"]}}
        ).encode()

    cache_dir = tmp_path / "c"
    rc = main(
        [
            "--manifest",
            str(skill_repo.manifest),
            "--cache-dir",
            str(cache_dir),
            "--delay",
            "0",
            "--id",
            "gu2007",
            "--id",
            "nap2019-mentorship",
            "--json",
        ],
        getter=getter,
    )
    assert rc == 1
    by_id = {r["id"]: r for r in json.loads(capsys.readouterr().out)["results"]}
    assert (
        by_id["gu2007"]["status"] == "ok" and by_id["nap2019-mentorship"]["status"] == "not-found"
    )
    assert cache_path(cache_dir, "10.1371/journal.pcbi.0030229").exists()
    assert len(seen) == 2
    # cached now: offline run needs no getter
    rc = main(
        [
            "--manifest",
            str(skill_repo.manifest),
            "--cache-dir",
            str(cache_dir),
            "--offline",
            "--id",
            "gu2007",
        ]
    )
    assert rc == 0


def test_urls_checked(skill_repo, tmp_path: Path, capsys) -> None:
    def getter(url: str) -> bytes:
        if "turing" in url:
            raise OSError("unreachable")
        return b"ok"

    rc = main(
        [
            "--manifest",
            str(skill_repo.manifest),
            "--cache-dir",
            str(tmp_path / "c"),
            "--delay",
            "0",
            "--id",
            "turing-way",
            "--urls",
        ],
        getter=getter,
    )
    assert rc == 1
    assert "url-fail" in capsys.readouterr().out
