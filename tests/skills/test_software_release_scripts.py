# ruff: noqa: E501
"""Tests for the software-release scripts/release_check.py and cff_gen.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "software-release"
SCRIPTS = SKILL / "scripts"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        f"software_release_{name}", SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


release_check = load("release_check")
cff_gen = load("cff_gen")


def write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def valid_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "release-project"
    repo.mkdir()
    write(
        repo,
        "pyproject.toml",
        """[project]
name = "release-project"
version = "1.2.3"
dependencies = ["numpy>=1.25,<2"]
""",
    )
    write(
        repo,
        "CHANGELOG.md",
        """# Changelog

## [Unreleased]

## [1.2.3] - 2026-09-02

### Fixed

- Correct the release check.
""",
    )
    write(
        repo,
        "CITATION.cff",
        """cff-version: 1.2.0
message: Cite this software.
title: release-project
version: 1.2.3
authors:
  - family-names: Example
    given-names: Ada
date-released: '2026-09-02'
identifiers:
  - type: doi
    value: 10.5281/zenodo.1234567
""",
    )
    write(repo, "LICENSE", "MIT License\nPermission is hereby granted.\n")
    write(repo, "README.md", "# release-project\n\nhttps://doi.org/10.5281/zenodo.1234567\n")
    write(repo, "tests/test_core.py", "def test_core():\n    assert True\n")
    write(repo, ".github/workflows/ci.yml", "name: CI\non: push\njobs: {}\n")
    return repo


def test_release_check_passes_complete_repository(tmp_path: Path, monkeypatch) -> None:
    repo = valid_repo(tmp_path)
    monkeypatch.setattr(release_check, "_git_tags", lambda target: ["v1.2.3"])
    result = release_check.check_repository(repo, "1.2.3")
    assert result["summary"]["errors"] == 0
    assert any("CITATION.cff" in item for item in result["passed"])
    assert any("release tag" in item for item in result["passed"])


def test_release_tag_must_point_to_inspected_head(tmp_path: Path, monkeypatch) -> None:
    repo = valid_repo(tmp_path)
    monkeypatch.setattr(release_check, "_git_tags", lambda target: ["v1.2.3"])
    revisions = {"HEAD": "new-head-revision", "v1.2.3": "old-tag-revision"}
    monkeypatch.setattr(release_check, "_git_revision", lambda target, ref: revisions[ref])
    result = release_check.check_repository(repo, "1.2.3")
    assert any(item["id"] == "tag:target-mismatch" for item in result["findings"])


def test_zenodo_metadata_must_be_parseable_and_complete(tmp_path: Path, monkeypatch) -> None:
    repo = valid_repo(tmp_path)
    write(repo, ".zenodo.json", "not JSON")
    write(repo, "README.md", "# release-project\n")
    write(
        repo,
        "CITATION.cff",
        """cff-version: 1.2.0
message: Cite this software.
title: release-project
version: 1.2.3
authors:
  - family-names: Example
    given-names: Ada
date-released: '2026-09-02'
""",
    )
    monkeypatch.setattr(release_check, "_git_tags", lambda target: [])
    result = release_check.check_repository(repo, "1.2.3")
    ids = {item["id"] for item in result["findings"]}
    assert {"doi:zenodo-invalid", "doi:missing"} <= ids
    assert not any("Zenodo metadata record present" in item for item in result["passed"])


def test_release_check_reports_findings_and_never_writes(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "incomplete"
    repo.mkdir()
    write(repo, "pyproject.toml", "[project]\nname='x'\nversion='1.0.0'\ndependencies=['numpy']\n")
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    monkeypatch.setattr(release_check, "_git_tags", lambda target: [])
    result = release_check.check_repository(repo, "1.0.0")
    ids = {item["id"] for item in result["findings"]}
    assert {
        "tag:missing",
        "changelog:missing",
        "cff:missing",
        "license:missing",
        "tests:missing",
        "ci:missing",
    } <= ids
    assert any(item["id"].startswith("dependency:unbounded") for item in result["findings"])
    assert all(item["severity"] and item["fix"] for item in result["findings"])
    assert before == {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}


def test_release_check_cli_json_and_joss_sections(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = valid_repo(tmp_path)
    write(
        repo,
        "paper.md",
        """# Summary
This tool performs the stated analysis.
# Statement of need
Researchers need this tool for the stated problem.
# State of the field
It differs from the compared tools.
# Software design
The design makes the workflow reproducible.
# Research impact statement
The repository contains evidence of use.
# AI usage disclosure
No generative AI was used.
""",
    )
    monkeypatch.setattr(release_check, "_git_tags", lambda target: ["1.2.3"])
    monkeypatch.setattr(release_check, "_git_log_dates", lambda target: None)
    assert release_check.main(["--repo", str(repo), "--version", "1.2.3", "--joss", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["version"] == "1.2.3" and output["joss"] is True


def test_cff_generator_prints_then_applies(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "cff-project"
    repo.mkdir()
    write(repo, "pyproject.toml", "[project]\nname='cff-project'\nversion='0.4.0'\n")
    authors = tmp_path / "authors.yaml"
    authors.write_text(
        "authors:\n  - given-names: Ada\n    family-names: Example\n", encoding="utf-8"
    )
    assert cff_gen.main(["--repo", str(repo), "--authors", str(authors)]) == 0
    printed = capsys.readouterr().out
    assert "title: cff-project" in printed and "version: 0.4.0" in printed
    assert not (repo / "CITATION.cff").exists()
    assert (
        cff_gen.main(
            [
                "--repo",
                str(repo),
                "--authors",
                str(authors),
                "--date-released",
                "2026-09-02",
                "--apply",
            ]
        )
        == 0
    )
    generated = (repo / "CITATION.cff").read_text(encoding="utf-8")
    assert "cff-version: 1.2.0" in generated
    assert "date-released: '2026-09-02'" in generated
