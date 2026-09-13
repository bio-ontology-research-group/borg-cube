#!/usr/bin/env python3
"""Collect the activity state of local git repositories as JSON.

For every ``--repo PATH`` (or every line of ``--repos-file``): last commit date
and age, default branch, whether a CI configuration exists, last tag and its
date, uncommitted changes, and optionally the number of open GitHub issues via
``gh`` (``--gh``; skipped when gh is missing or the remote is not GitHub).
CI status itself is not queried here; put it in the ``ci_status`` field of a
services file if a patrol has it.

Only the given paths are read; git is invoked read-only.

Example:
  repos_state.py --repo ~/src/deepgo --repo ~/src/mowl --out state/repos.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CI_PATHS = (
    ".github/workflows",
    ".gitlab-ci.yml",
    ".travis.yml",
    "azure-pipelines.yml",
    "Jenkinsfile",
    ".circleci/config.yml",
)


def git(repo: Path, *args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def github_slug(remote_url: str | None) -> str | None:
    if not remote_url or "github.com" not in remote_url:
        return None
    tail = remote_url.split("github.com", 1)[1].lstrip(":/")
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or None


def open_issues(slug: str) -> int | None:
    if shutil.which("gh") is None:
        return None
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
            "number",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        return len(json.loads(proc.stdout or "[]"))
    except json.JSONDecodeError:
        return None


def repo_state(repo: Path, today: dt.date, use_gh: bool) -> dict[str, Any]:
    state: dict[str, Any] = {"path": str(repo), "name": repo.name, "source": str(repo)}
    if not (repo / ".git").exists() and git(repo, "rev-parse", "--git-dir") is None:
        state["error"] = "not a git repository"
        return state
    last = git(repo, "log", "-1", "--format=%cI")
    state["last_commit"] = last[:10] if last else None
    state["days_since_commit"] = (today - dt.date.fromisoformat(last[:10])).days if last else None
    state["last_commit_hash"] = git(repo, "log", "-1", "--format=%h")
    branch = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    state["default_branch"] = (
        branch.split("/", 1)[1]
        if branch and "/" in branch
        else (git(repo, "rev-parse", "--abbrev-ref", "HEAD"))
    )
    state["ci_config"] = [p for p in CI_PATHS if (repo / p).exists()]
    tag = git(repo, "describe", "--tags", "--abbrev=0")
    state["last_tag"] = tag or None
    tag_date = git(repo, "log", "-1", "--format=%cI", tag) if tag else None
    state["last_tag_date"] = tag_date[:10] if tag_date else None
    if state["last_tag_date"] and state["last_commit"]:
        state["release_lag_days"] = (
            dt.date.fromisoformat(state["last_commit"])
            - dt.date.fromisoformat(state["last_tag_date"])
        ).days
    else:
        state["release_lag_days"] = None
    status = git(repo, "status", "--porcelain")
    state["dirty"] = bool(status)
    state["commits_last_90_days"] = int(
        git(repo, "rev-list", "--count", "--since=90.days", "HEAD") or 0
    )
    remote = git(repo, "remote", "get-url", "origin")
    state["remote"] = remote
    slug = github_slug(remote)
    state["github"] = slug
    state["open_issues"] = open_issues(slug) if (use_gh and slug) else None
    return state


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--repo", action="append", type=Path, default=[], help="repository path")
    p.add_argument("--repos-file", type=Path, default=None, help="file with one path per line")
    p.add_argument("--gh", action="store_true", help="count open issues with gh (network)")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--today", type=dt.date.fromisoformat, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repos = list(args.repo)
    if args.repos_file:
        for line in args.repos_file.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                repos.append(Path(line).expanduser())
    if not repos:
        print("repos-state: give --repo or --repos-file", file=sys.stderr)
        return 1
    today = args.today or dt.date.today()
    state = {
        "kind": "repos",
        "generated": today.isoformat(),
        "repos": [repo_state(r.resolve(), today, args.gh) for r in repos],
    }
    text = json.dumps(state, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"repos-state: {len(repos)} repositories -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
