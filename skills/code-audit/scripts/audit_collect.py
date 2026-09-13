#!/usr/bin/env python3
"""Collect deterministic facts about a software repository for the code audit.

Read-only. Walks the checkout at ``--repo`` (tracked files via ``git ls-files``
when available, otherwise a directory walk that skips .git and virtual
environments) and records, with file paths and line numbers where relevant:

* git: last commit, age, commit count, tags, default branch, remote
* documentation: README (and which sections it has), LICENSE (detected type),
  CITATION.cff (parseable, fields), CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md,
  CHANGELOG
* tests: test files, source files, ratio, framework hints
* CI: configuration files, GitHub Actions ``uses:`` references and whether they
  are pinned to a commit SHA, dangerous triggers
* dependencies: manifest files, pinned versus unpinned specs, lock files, installs from URLs
* Dockerfile: base images and whether they are tagged, USER instruction
* secrets: regex hits (redacted) in text files
* risky calls: eval, exec, shell=True, os.system, pickle.load, yaml.load without Loader,
  verify=False
* notebooks with committed outputs; large or binary files
* open issues via ``gh`` when ``--gh`` is given and the remote is GitHub

Output is JSON for audit_report.py. Nothing in the repository is modified.

Example:
  audit_collect.py --repo runs/12/repo --out runs/12/facts.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

CHECKS_VERSION = "2026-09-02"
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    "dist",
    "build",
    ".eggs",
}
TEXT_EXT = {
    ".py",
    ".md",
    ".txt",
    ".rst",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
    ".sh",
    ".bash",
    ".zsh",
    ".env",
    ".r",
    ".R",
    ".java",
    ".groovy",
    ".kt",
    ".js",
    ".ts",
    ".ipynb",
    ".tex",
    ".org",
    ".xml",
    ".properties",
    ".gradle",
    ".sql",
    ".pl",
    ".jl",
    ".nf",
    ".smk",
    ".cwl",
    ".wdl",
    "",
}
LANG_EXT = {
    ".py": "python",
    ".java": "java",
    ".groovy": "groovy",
    ".sh": "shell",
    ".r": "r",
    ".R": "r",
    ".js": "javascript",
    ".ts": "typescript",
    ".ipynb": "notebook",
    ".jl": "julia",
    ".nf": "nextflow",
    ".smk": "snakemake",
    ".cwl": "cwl",
    ".pl": "perl",
    ".kt": "kotlin",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
}
BINARY_EXT = {
    ".pkl",
    ".pickle",
    ".h5",
    ".hdf5",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".bin",
    ".zip",
    ".gz",
    ".tgz",
    ".tar",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".parquet",
    ".feather",
    ".db",
    ".sqlite",
    ".owl",
    ".jar",
    ".war",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".mp4",
}
DATA_LIKE_EXT = {".owl", ".pdf", ".png", ".jpg", ".jpeg", ".gif"}
README_SECTIONS = {
    "install": re.compile(
        r"^#+\s*.*\b(install|installation|setup|getting started|requirements)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    "usage": re.compile(
        r"^#+\s*.*\b(usage|example|examples|quick ?start|tutorial|how to)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    "cite": re.compile(
        r"^#+\s*.*\b(cite|citation|citing|reference|how to cite)\b|\bdoi\.org/",
        re.IGNORECASE | re.MULTILINE,
    ),
    "license": re.compile(r"^#+\s*.*\blicen[sc]e\b", re.IGNORECASE | re.MULTILINE),
    "contributing": re.compile(r"^#+\s*.*\bcontribut", re.IGNORECASE | re.MULTILINE),
    "test": re.compile(r"^#+\s*.*\b(test|testing|tests)\b", re.IGNORECASE | re.MULTILINE),
}
LICENSE_PATTERNS = [
    (
        "MIT",
        re.compile(r"\bMIT License\b|Permission is hereby granted, free of charge", re.IGNORECASE),
    ),
    ("Apache-2.0", re.compile(r"Apache License,?\s*Version 2\.0", re.IGNORECASE)),
    ("GPL-3.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.IGNORECASE)),
    ("GPL-2.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 2", re.IGNORECASE)),
    ("LGPL", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE", re.IGNORECASE)),
    ("AGPL-3.0", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.IGNORECASE)),
    (
        "BSD-3-Clause",
        re.compile(
            r"Redistribution and use in source and binary forms.*Neither the name",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "BSD-2-Clause",
        re.compile(r"Redistribution and use in source and binary forms", re.IGNORECASE),
    ),
    ("MPL-2.0", re.compile(r"Mozilla Public License,? v(ersion)? 2\.0", re.IGNORECASE)),
    ("CC-BY-4.0", re.compile(r"Creative Commons Attribution 4\.0", re.IGNORECASE)),
    ("CC0", re.compile(r"CC0 1\.0 Universal", re.IGNORECASE)),
    ("Unlicense", re.compile(r"This is free and unencumbered software", re.IGNORECASE)),
]
SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    (
        "generic-password",
        re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"),
    ),
    (
        "generic-api-key",
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-/.+=]{12,}['\"]"
        ),
    ),
    ("url-with-credentials", re.compile(r"https?://[^/\s:@]+:[^/\s:@]+@[^\s/]+")),
]
RISKY_PATTERNS = [
    ("eval", re.compile(r"(?<![\w.])eval\(")),
    ("exec", re.compile(r"(?<![\w.])exec\(")),
    ("shell-true", re.compile(r"shell\s*=\s*True")),
    ("os-system", re.compile(r"\bos\.system\(")),
    ("pickle-load", re.compile(r"\bpickle\.loads?\(|\bjoblib\.load\(|torch\.load\(")),
    ("yaml-unsafe-load", re.compile(r"\byaml\.load\((?![^)]*Loader)")),
    ("verify-false", re.compile(r"verify\s*=\s*False")),
    ("curl-pipe-sh", re.compile(r"(curl|wget)[^|\n]*\|\s*(sudo\s+)?(ba)?sh\b")),
    ("chmod-777", re.compile(r"chmod\s+(-R\s+)?777")),
]
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
SHA_RE = re.compile(r"@[0-9a-f]{40}$")
REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*([<>=!~]=?.*)?$")
TEST_FILE_RE = re.compile(
    r"(^|/)(tests?|testing|spec)(/|$)|(^|/)test_[^/]*\.py$|_test\.(py|java|groovy|js|ts|r|R)$|Test[A-Za-z]*\.(java|groovy|kt)$"
)


def git(repo: Path, *args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def tracked_files(repo: Path) -> list[Path]:
    listing = git(repo, "ls-files", "-z")
    if listing is not None and listing:
        return [repo / p for p in listing.split("\0") if p and (repo / p).is_file()]
    out: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            out.append(Path(root) / f)
    return out


def rel(repo: Path, path: Path) -> str:
    return str(path.relative_to(repo))


def read_text(path: Path, limit: int = 2_000_000) -> str | None:
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def find_file(repo: Path, files: list[Path], names: tuple[str, ...]) -> Path | None:
    lowered = {rel(repo, f).lower(): f for f in files}
    for name in names:
        for key, path in lowered.items():
            if key == name.lower() or key.startswith(name.lower() + "."):
                return path
    return None


# --------------------------------------------------------------------------- collectors


def collect_git(repo: Path, today: dt.date) -> dict[str, Any]:
    last = git(repo, "log", "-1", "--format=%cI")
    tags_raw = git(repo, "tag", "--sort=-creatordate")
    tags = [t for t in (tags_raw or "").splitlines() if t]
    branch = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return {
        "is_repo": last is not None or (repo / ".git").exists(),
        "last_commit": last[:10] if last else None,
        "days_since_commit": (today - dt.date.fromisoformat(last[:10])).days if last else None,
        "commit_count": int(git(repo, "rev-list", "--count", "HEAD") or 0),
        "commits_last_year": int(git(repo, "rev-list", "--count", "--since=365.days", "HEAD") or 0),
        "tags": tags[:20],
        "last_tag": tags[0] if tags else None,
        "default_branch": branch.split("/", 1)[1]
        if branch and "/" in branch
        else git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "remote": git(repo, "remote", "get-url", "origin"),
        "gitignore": (repo / ".gitignore").exists(),
    }


def collect_docs(repo: Path, files: list[Path]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    readme = find_file(repo, files, ("README",))
    if readme:
        text = read_text(readme) or ""
        out["readme"] = {
            "path": rel(repo, readme),
            "lines": len(text.splitlines()),
            "sections": {k: bool(p.search(text)) for k, p in README_SECTIONS.items()},
            "has_code_block": "```" in text or "\n    " in text,
        }
    else:
        out["readme"] = None
    lic = find_file(repo, files, ("LICENSE", "LICENCE", "COPYING"))
    if lic:
        text = read_text(lic) or ""
        kind = next((name for name, pat in LICENSE_PATTERNS if pat.search(text)), "unknown")
        out["license"] = {"path": rel(repo, lic), "type": kind}
    else:
        out["license"] = None
    cff = repo / "CITATION.cff"
    if cff.exists():
        text = read_text(cff) or ""
        try:
            data = yaml.safe_load(text) or {}
            parse_ok = isinstance(data, dict)
        except yaml.YAMLError:
            data, parse_ok = {}, False
        out["citation_cff"] = {
            "path": "CITATION.cff",
            "parseable": parse_ok,
            "fields": sorted(
                k
                for k in (
                    "cff-version",
                    "title",
                    "authors",
                    "version",
                    "doi",
                    "date-released",
                    "license",
                    "repository-code",
                )
                if isinstance(data, dict) and k in data
            ),
        }
    else:
        out["citation_cff"] = None
    for key, names in (
        ("contributing", ("CONTRIBUTING",)),
        ("code_of_conduct", ("CODE_OF_CONDUCT",)),
        ("security_md", ("SECURITY",)),
        ("changelog", ("CHANGELOG", "CHANGES", "HISTORY", "NEWS")),
    ):
        found = find_file(repo, files, names)
        out[key] = rel(repo, found) if found else None
    docs_dir = next(
        (rel(repo, f) for f in files if rel(repo, f).lower().startswith(("docs/", "doc/"))), None
    )
    out["docs_dir"] = docs_dir.split("/")[0] if docs_dir else None
    return out


def collect_tests(repo: Path, files: list[Path]) -> dict[str, Any]:
    source = [f for f in files if f.suffix in LANG_EXT and f.suffix != ".ipynb"]
    tests = [f for f in source if TEST_FILE_RE.search(rel(repo, f).replace(os.sep, "/"))]
    non_test = [f for f in source if f not in tests]

    def loc(paths: list[Path]) -> int:
        total = 0
        for p in paths:
            t = read_text(p, 5_000_000)
            total += len(t.splitlines()) if t else 0
        return total

    config_text = ""
    for name in (
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        "package.json",
        "build.gradle",
        "pom.xml",
    ):
        p = repo / name
        if p.exists():
            config_text += read_text(p) or ""
    hints = [
        h
        for h in ("pytest", "unittest", "junit", "testthat", "jest", "mocha", "spock")
        if h in config_text.lower()
    ]
    return {
        "test_files": len(tests),
        "test_paths": [rel(repo, t) for t in tests[:50]],
        "source_files": len(non_test),
        "test_loc": loc(tests),
        "source_loc": loc(non_test),
        "ratio": round(len(tests) / len(non_test), 3) if non_test else None,
        "framework_hints": hints,
    }


def collect_ci(repo: Path, files: list[Path]) -> dict[str, Any]:
    configs = [
        rel(repo, f)
        for f in files
        if rel(repo, f).replace(os.sep, "/").startswith(".github/workflows/")
        or f.name in (".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "Jenkinsfile")
        or rel(repo, f).replace(os.sep, "/") == ".circleci/config.yml"
    ]
    actions: list[dict[str, Any]] = []
    dangerous: list[dict[str, Any]] = []
    for path in files:
        r = rel(repo, path).replace(os.sep, "/")
        if not r.startswith(".github/workflows/"):
            continue
        text = read_text(path) or ""
        for m in USES_RE.finditer(text):
            ref = m.group(1)
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            line = text.count("\n", 0, m.start()) + 1
            pinned = bool(SHA_RE.search(ref))
            actions.append(
                {
                    "file": r,
                    "line": line,
                    "uses": ref,
                    "pinned_sha": pinned,
                    "tag_or_branch": ref.split("@", 1)[1] if "@" in ref else None,
                }
            )
        for lineno, line in enumerate(text.splitlines(), 1):
            if "pull_request_target" in line:
                dangerous.append({"file": r, "line": lineno, "pattern": "pull_request_target"})
            if (
                re.search(
                    r"\$\{\{\s*github\.event\.(issue|pull_request|comment|review)[^}]*\}\}", line
                )
                and "run:" in text
            ):
                dangerous.append({"file": r, "line": lineno, "pattern": "event-data-in-run"})
    return {
        "configs": configs,
        "actions": actions,
        "unpinned_actions": sum(1 for a in actions if not a["pinned_sha"]),
        "dangerous": dangerous,
    }


def collect_dependencies(repo: Path, files: list[Path]) -> dict[str, Any]:
    manifests = [
        rel(repo, f)
        for f in files
        if f.name
        in (
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "environment.yml",
            "environment.yaml",
            "package.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "DESCRIPTION",
            "Project.toml",
            "Cargo.toml",
        )
        or re.match(r"requirements[^/]*\.txt$", f.name)
    ]
    locks = [
        rel(repo, f)
        for f in files
        if f.name
        in (
            "uv.lock",
            "poetry.lock",
            "Pipfile.lock",
            "conda-lock.yml",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Cargo.lock",
            "renv.lock",
            "Manifest.toml",
        )
    ]
    pinned = unpinned = 0
    url_installs: list[dict[str, Any]] = []
    for path in files:
        if not re.match(r"requirements[^/]*\.txt$", path.name):
            continue
        text = read_text(path) or ""
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if "://" in line or line.startswith("git+"):
                url_installs.append({"file": rel(repo, path), "line": lineno, "spec": line[:80]})
                continue
            m = REQ_LINE_RE.match(line)
            if m and m.group(2) and "==" in m.group(2):
                pinned += 1
            else:
                unpinned += 1
    env = find_file(repo, files, ("environment",))
    if env and env.suffix in (".yml", ".yaml"):
        text = read_text(env) or ""
        try:
            data = yaml.safe_load(text) or {}
            for dep in data.get("dependencies", []) if isinstance(data, dict) else []:
                if isinstance(dep, str):
                    if "=" in dep:
                        pinned += 1
                    else:
                        unpinned += 1
        except yaml.YAMLError:
            pass
    pip_urls_in_scripts: list[dict[str, Any]] = []
    for path in files:
        if path.suffix in (".sh", ".bash", "") and path.name.lower() in (
            "install.sh",
            "setup.sh",
            "bootstrap.sh",
            "makefile",
        ):
            text = read_text(path) or ""
            for lineno, line in enumerate(text.splitlines(), 1):
                if re.search(r"pip3?\s+install\s+.*(https?://|git\+)", line):
                    pip_urls_in_scripts.append({"file": rel(repo, path), "line": lineno})
    return {
        "manifests": manifests,
        "lock_files": locks,
        "pinned_specs": pinned,
        "unpinned_specs": unpinned,
        "url_installs": url_installs + pip_urls_in_scripts,
    }


def collect_docker(repo: Path, files: list[Path]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for path in files:
        if (
            path.name != "Dockerfile"
            and not path.name.startswith("Dockerfile.")
            and path.suffix != ".dockerfile"
        ):
            continue
        text = read_text(path) or ""
        bases: list[dict[str, Any]] = []
        user = False
        unpinned_pip: list[int] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.upper().startswith("FROM "):
                image = s.split()[1]
                tag = (
                    image.split("@")[0].rsplit(":", 1)[1]
                    if ":" in image.split("@")[0].split("/")[-1]
                    else None
                )
                bases.append(
                    {
                        "line": lineno,
                        "image": image,
                        "tag": tag,
                        "pinned": bool(tag and tag != "latest") or "@sha256:" in image,
                    }
                )
            if s.upper().startswith("USER "):
                user = True
            if (
                re.search(r"pip3?\s+install", s)
                and "==" not in s
                and "requirements" not in s
                and "-e ." not in s
                and " ." not in s
            ):
                unpinned_pip.append(lineno)
        out.append(
            {
                "file": rel(repo, path),
                "bases": bases,
                "user_set": user,
                "unpinned_pip_lines": unpinned_pip,
            }
        )
    return {"dockerfiles": out}


def redact(text: str) -> str:
    return text[:6] + "..." if len(text) > 6 else "..."


def collect_secrets_and_risks(
    repo: Path, files: list[Path]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    secrets: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for path in files:
        if path.suffix not in TEXT_EXT and path.suffix not in LANG_EXT:
            continue
        r = rel(repo, path)
        if r.endswith((".lock", "package-lock.json")):
            continue
        text = read_text(path)
        if text is None:
            continue
        is_test = bool(TEST_FILE_RE.search(r.replace(os.sep, "/")))
        is_example = "example" in r.lower() or r.lower().endswith((".env.example", ".env.sample"))
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pat in SECRET_PATTERNS:
                m = pat.search(line)
                if m and not is_example:
                    secrets.append(
                        {"file": r, "line": lineno, "pattern": name, "match": redact(m.group(0))}
                    )
            if path.suffix in (
                ".py",
                ".sh",
                ".bash",
                ".ipynb",
                ".r",
                ".R",
                ".groovy",
                ".java",
                ".js",
                ".ts",
                "",
            ) or path.name in ("Dockerfile", "Makefile"):
                for name, pat in RISKY_PATTERNS:
                    if pat.search(line) and not line.strip().startswith("#"):
                        risks.append(
                            {
                                "file": r,
                                "line": lineno,
                                "pattern": name,
                                "in_test": is_test,
                                "snippet": line.strip()[:100],
                            }
                        )
    return secrets, risks


def collect_notebooks_and_files(repo: Path, files: list[Path], max_mb: float) -> dict[str, Any]:
    notebooks: list[dict[str, Any]] = []
    large: list[dict[str, Any]] = []
    binaries: list[dict[str, Any]] = []
    langs: dict[str, int] = {}
    total_bytes = 0
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        lang = LANG_EXT.get(path.suffix)
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
        r = rel(repo, path)
        if size > max_mb * 1024 * 1024:
            large.append({"file": r, "mb": round(size / 1024 / 1024, 1)})
        if path.suffix.lower() in BINARY_EXT and path.suffix.lower() not in DATA_LIKE_EXT:
            binaries.append({"file": r, "mb": round(size / 1024 / 1024, 2)})
        if path.suffix == ".ipynb":
            text = read_text(path, 20_000_000)
            outputs = 0
            cells = 0
            if text:
                try:
                    nb = json.loads(text)
                    for cell in nb.get("cells", []):
                        cells += 1
                        if cell.get("cell_type") == "code" and cell.get("outputs"):
                            outputs += 1
                except json.JSONDecodeError:
                    pass
            notebooks.append({"file": r, "code_cells_with_outputs": outputs, "cells": cells})
    return {
        "file_count": len(files),
        "total_mb": round(total_bytes / 1024 / 1024, 1),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "notebooks": notebooks,
        "notebooks_with_outputs": sum(1 for n in notebooks if n["code_cells_with_outputs"]),
        "large_files": large,
        "binary_files": binaries[:50],
        "binary_count": len(binaries),
    }


def collect_issues(remote: str | None) -> dict[str, Any]:
    if not remote or "github.com" not in remote or shutil.which("gh") is None:
        return {"open_issues": None, "source": None}
    slug = remote.split("github.com", 1)[1].lstrip(":/")
    slug = slug[:-4] if slug.endswith(".git") else slug
    proc = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            slug,
            "--state",
            "open",
            "--limit",
            "500",
            "--json",
            "number,createdAt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"open_issues": None, "source": f"gh failed: {proc.stderr.strip()[:120]}"}
    try:
        issues = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {"open_issues": None, "source": "gh returned invalid JSON"}
    oldest = min((i["createdAt"][:10] for i in issues), default=None)
    return {
        "open_issues": len(issues),
        "oldest_open": oldest,
        "source": f"gh issue list --repo {slug}",
    }


def collect(repo: Path, today: dt.date, use_gh: bool, max_mb: float) -> dict[str, Any]:
    files = tracked_files(repo)
    git_facts = collect_git(repo, today)
    secrets, risks = collect_secrets_and_risks(repo, files)
    return {
        "checks_version": CHECKS_VERSION,
        "collected": today.isoformat(),
        "repo": {"path": str(repo), "name": repo.name},
        "git": git_facts,
        "docs": collect_docs(repo, files),
        "tests": collect_tests(repo, files),
        "ci": collect_ci(repo, files),
        "dependencies": collect_dependencies(repo, files),
        "docker": collect_docker(repo, files),
        "secrets": secrets,
        "risky_calls": risks,
        "files": collect_notebooks_and_files(repo, files, max_mb),
        "issues": collect_issues(git_facts.get("remote"))
        if use_gh
        else {"open_issues": None, "source": "not queried (--gh not given)"},
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--repo", required=True, type=Path, help="path to the checkout")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--gh", action="store_true", help="query open issues with gh (network)")
    p.add_argument("--max-file-mb", type=float, default=50.0)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"audit-collect: {repo} is not a directory", file=sys.stderr)
        return 1
    facts = collect(repo, args.today or dt.date.today(), args.gh, args.max_file_mb)
    text = json.dumps(facts, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(
            f"audit-collect: {facts['files']['file_count']} files, {len(facts['secrets'])} secret "
            f"hit(s), {len(facts['risky_calls'])} risky call(s) -> {args.out}"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
