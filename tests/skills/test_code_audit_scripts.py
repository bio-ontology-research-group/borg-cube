# ruff: noqa: E501
"""Tests for the code-audit skill scripts (audit_collect.py, audit_report.py) on a synthetic repository."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "code-audit"
SCRIPTS = SKILL / "scripts"
TEMPLATE = SKILL / "assets" / "code-audit-report.md"


def load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"ca_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit_collect = load("audit_collect")
audit_report = load("audit_report")

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
    "GIT_AUTHOR_DATE": "2025-01-15T10:00:00",
    "GIT_COMMITTER_DATE": "2025-01-15T10:00:00",
    "PATH": "/usr/bin:/bin",
}


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**ENV, "HOME": str(repo)},
    )


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def messy_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = tmp_path / "messy"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "README.md", "# messy\n\nA tool.\n")
    write(r, "messy/__init__.py", "")
    write(
        r,
        "messy/core.py",
        "import os\nimport pickle\nimport subprocess\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n\ndef load(p):\n    return pickle.load(open(p, 'rb'))\n\nPASSWORD = 'hunter2secret'\nAPI_KEY = 'sk-abcdefghijklmnopqrstuvwxyz123456'\n",
    )
    write(
        r, "requirements.txt", "numpy\npandas>=1.0\nscipy==1.11.0\ngit+https://github.com/x/y.git\n"
    )
    write(r, "Dockerfile", "FROM python:latest\nRUN pip install numpy\n")
    write(
        r,
        ".github/workflows/ci.yml",
        "on: [push, pull_request_target]\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c\n",
    )
    write(
        r,
        "analysis.ipynb",
        json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "outputs": [{"text": "1"}]},
                    {"cell_type": "code", "outputs": []},
                ]
            }
        ),
    )
    write(r, "model.pkl", "binary")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    return r


@pytest.fixture
def tidy_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    r = tmp_path / "tidy"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(
        r,
        "README.md",
        "# tidy\n\n## Installation\n\n```\npip install tidy\n```\n\n## Usage\n\n```\ntidy run data.tsv\n```\n\n## How to cite\n\nSee CITATION.cff.\n\n## License\n\nMIT\n"
        + "\n" * 10,
    )
    write(
        r,
        "LICENSE",
        "MIT License\n\nPermission is hereby granted, free of charge, to any person...\n",
    )
    write(
        r,
        "CITATION.cff",
        "cff-version: 1.2.0\ntitle: tidy\nauthors:\n  - family-names: Doe\nversion: 1.0.0\n",
    )
    write(r, "CONTRIBUTING.md", "PRs welcome\n")
    write(r, "SECURITY.md", "report to robert\n")
    write(r, "CODE_OF_CONDUCT.md", "be kind\n")
    write(r, ".gitignore", "*.pyc\n")
    write(
        r,
        "pyproject.toml",
        "[project]\nname='tidy'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n",
    )
    write(r, "uv.lock", "version = 1\n")
    write(r, "tidy/__init__.py", "def add(a, b):\n    return a + b\n")
    write(
        r,
        "tests/test_add.py",
        "from tidy import add\n\ndef test_add():\n    assert add(1, 2) == 3\n    subprocess_shell = 'shell=True'\n",
    )
    write(r, ".env.example", "API_KEY='replace-me-with-your-key'\n")
    write(
        r,
        ".github/workflows/ci.yml",
        "on: push\njobs:\n  t:\n    steps:\n      - uses: actions/checkout@0a5c61591373683505ea898e09a3ea4f39ef2b9c\n",
    )
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    git(r, "tag", "v1.0.0")
    return r


def test_collect_messy_repo(messy_repo: Path, tmp_path: Path) -> None:
    facts = audit_collect.collect(
        messy_repo, audit_collect.dt.date(2026, 9, 2), use_gh=False, max_mb=50
    )
    assert facts["git"]["last_commit"] == "2025-01-15" and facts["git"]["days_since_commit"] == 595
    assert facts["git"]["tags"] == [] and facts["git"]["gitignore"] is False
    assert facts["docs"]["license"] is None and facts["docs"]["citation_cff"] is None
    assert facts["docs"]["readme"]["sections"]["install"] is False
    assert facts["tests"]["test_files"] == 0 and facts["tests"]["source_files"] == 2
    secrets = {(s["file"], s["pattern"]) for s in facts["secrets"]}
    assert ("messy/core.py", "generic-password") in secrets
    assert ("messy/core.py", "openai-key") in secrets
    assert all("hunter2secret" not in s["match"] for s in facts["secrets"])  # redacted
    risks = {(r["pattern"], r["line"]) for r in facts["risky_calls"]}
    assert ("shell-true", 6) in risks and ("pickle-load", 9) in risks
    assert (
        facts["dependencies"]["pinned_specs"] == 1 and facts["dependencies"]["unpinned_specs"] == 2
    )
    assert facts["dependencies"]["url_installs"][0]["line"] == 4
    assert facts["dependencies"]["lock_files"] == []
    docker = facts["docker"]["dockerfiles"][0]
    assert (
        docker["bases"][0]["pinned"] is False
        and docker["user_set"] is False
        and docker["unpinned_pip_lines"] == [2]
    )
    actions = {a["uses"]: a["pinned_sha"] for a in facts["ci"]["actions"]}
    assert actions["actions/checkout@v4"] is False
    assert actions["actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c"] is True
    assert facts["ci"]["dangerous"][0]["pattern"] == "pull_request_target"
    assert facts["files"]["notebooks_with_outputs"] == 1
    assert facts["files"]["binary_count"] == 1
    assert facts["files"]["languages"]["python"] == 2
    assert facts["issues"]["open_issues"] is None


def test_collect_tidy_repo_and_cli(tidy_repo: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "facts.json"
    assert (
        audit_collect.main(["--repo", str(tidy_repo), "--out", str(out), "--today", "2026-09-02"])
        == 0
    )
    facts = json.loads(out.read_text(encoding="utf-8"))
    assert facts["docs"]["license"]["type"] == "MIT"
    assert facts["docs"]["citation_cff"]["parseable"] is True
    assert "authors" in facts["docs"]["citation_cff"]["fields"]
    assert (
        facts["docs"]["readme"]["sections"]["install"]
        and facts["docs"]["readme"]["sections"]["usage"]
    )
    assert facts["docs"]["security_md"] == "SECURITY.md"
    assert facts["tests"]["test_files"] == 1 and facts["tests"]["ratio"] == 1.0
    assert "pytest" in facts["tests"]["framework_hints"]
    assert facts["dependencies"]["lock_files"] == ["uv.lock"]
    assert facts["secrets"] == []  # .env.example is exempt
    assert all(r["in_test"] for r in facts["risky_calls"])
    assert facts["git"]["last_tag"] == "v1.0.0"
    assert audit_collect.main(["--repo", str(tmp_path / "missing")]) == 1


def test_report_messy_findings_and_beads(messy_repo: Path, tmp_path: Path, capsys) -> None:
    facts = audit_collect.collect(
        messy_repo, audit_collect.dt.date(2026, 9, 2), use_gh=False, max_mb=50
    )
    findings, passed, not_checked = audit_report.derive(facts, published=False)
    by_id = {f["id"]: f for f in findings}
    assert by_id["license:missing"]["severity"] == "high"
    assert by_id["readme:install"]["severity"] == "medium"
    assert by_id["tests:none"]["severity"] == "medium"
    assert by_id["risk:messy/core.py:6"]["severity"] == "high"
    assert by_id["risk:messy/core.py:9"]["severity"] == "medium"
    assert by_id["ci:unpinned:.github/workflows/ci.yml:5"]["severity"] == "medium"
    assert by_id["ci:dangerous:.github/workflows/ci.yml:1"]["severity"] == "high"
    assert by_id["deps:unpinned"]["severity"] == "medium"
    assert by_id["docker:base:Dockerfile:1"]["severity"] == "medium"
    assert by_id["docker:root:Dockerfile"]["severity"] == "low"
    assert by_id["notebooks:outputs"]["severity"] == "low"
    assert by_id["files:binaries"]["severity"] == "low"
    assert by_id["release:none"]["severity"] == "low"
    secret_findings = [f for f in findings if f["id"].startswith("secret:")]
    assert secret_findings and all(
        f["owner_role"] == "robert" and f["severity"] == "high" for f in secret_findings
    )
    assert all(f["sources"] for f in findings) and all(f["location"] for f in findings)
    published, _, _ = audit_report.derive(facts, published=True)
    pub = {f["id"]: f for f in published}
    assert pub["tests:none"]["severity"] == "high" and pub["readme:install"]["severity"] == "high"
    assert any("open issues" in n for n in not_checked)

    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    report = tmp_path / "audit.md"
    beads = tmp_path / "fixes.json"
    args = [
        "--facts",
        str(facts_path),
        "--template",
        str(TEMPLATE),
        "--out",
        str(report),
        "--beads",
        str(beads),
        "--today",
        "2026-09-02",
    ]
    assert audit_report.main(args) == 0
    printed = capsys.readouterr().out
    assert "[dry-run]" in printed and not report.exists()
    assert audit_report.main([*args, "--apply"]) == 0
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# Code audit: messy")
    assert "### High" in text and "messy/core.py:6" in text and "Sources: owasp-top-ten" in text
    assert "{{" not in text and "—" not in text
    fixes = json.loads(beads.read_text(encoding="utf-8"))
    assert fixes["review_by"] == "senior" and fixes["beads"]
    for b in fixes["beads"]:
        assert b["acceptance_criteria"] and b["provenance"] and b["out_of_scope"] and b["output"]
    assert any(b["owner_role"] == "robert" for b in fixes["beads"])


def test_report_tidy_repo_mostly_passes(tidy_repo: Path, tmp_path: Path, capsys) -> None:
    facts = audit_collect.collect(
        tidy_repo, audit_collect.dt.date(2026, 9, 2), use_gh=False, max_mb=50
    )
    findings, passed, _ = audit_report.derive(facts, published=True)
    severities = {f["severity"] for f in findings}
    assert "high" not in severities and "medium" not in severities
    assert all(
        f["id"].startswith("risk:") and f["severity"] == "info"
        for f in findings
        if f["id"].startswith("risk:")
    )
    assert any("LICENSE present (MIT)" == p for p in passed)
    assert any(p.startswith("release tag present") for p in passed)
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    assert audit_report.main(["--facts", str(facts_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"findings", "passed", "not_checked"}
    assert audit_report.main(["--facts", str(tmp_path / "none.json")]) == 1
