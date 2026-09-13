from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from cube.config import Settings
from cube.fleet_github import (
    create_issue,
    create_pr,
    ensure_project,
    publish_files,
    publish_pending,
    queue_checkpoint,
    queue_record,
)


def settings(path: Path) -> Settings:
    return cast(Settings, SimpleNamespace(state_dir=lambda: path))


class GitHub:
    def __init__(self) -> None:
        self.private = True
        self.exists = True
        self.timeout = False
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.content: str | None = None

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        endpoint, method = args[2], args[4]
        payload = json.loads(kwargs.get("input", "{}"))
        self.calls.append((endpoint, method, payload))
        result: dict[str, Any] = {}
        if method == "POST":
            assert endpoint == "orgs/borg-cube-fleet/repos"
            assert payload == {"name": "research-log", "private": True}
            self.exists = True
        elif "/contents/" not in endpoint:
            if not self.exists:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
            result = {"private": self.private}
        elif method == "GET":
            if self.content is None:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
            result = {"content": self.content}
        else:
            assert method == "PUT"
            self.content = payload["content"]
            if self.timeout:
                self.timeout = False
                raise subprocess.TimeoutExpired(args, 60)
        return subprocess.CompletedProcess(args, 0, json.dumps(result), "")


def test_queue_idempotent_and_dry_run(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(config, "ontology", "run-1", "Result")
    assert not (tmp_path / "fleet-github").exists()
    first = queue_record(config, "ontology", "run-1", "Result", dry_run=False)
    assert queue_record(config, "ontology", "run-1", "Result", dry_run=False) == first
    with pytest.raises(ValueError, match="different evidence"):
        queue_record(config, "ontology", "run-1", "Changed", dry_run=False)
    github = GitHub()
    assert publish_pending(config, exec_fn=github)[0]["dry_run"]
    assert not github.calls


def test_private_creation_and_author(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(
        config, "ontology", "run-1", "Reproduced result", sources=["paper:doi"], dry_run=False
    )
    github = GitHub()
    github.exists = False
    result = publish_pending(config, False, github)
    assert result[0]["status"] == "published"
    payload = next(payload for _, method, payload in github.calls if method == "PUT")
    assert (
        payload["author"]
        == payload["committer"]
        == {
            "name": "Robert Hoehndorf (BORG Cube Fleet: ontologist)",
            "email": "leechuck@leechuck.de",
        }
    )
    assert "paper:doi" in base64.b64decode(payload["content"]).decode()
    assert publish_pending(config, False, github) == []


def test_timeout_after_commit_does_not_duplicate(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(config, "researcher", "run-2", "Result", dry_run=False)
    github = GitHub()
    github.timeout = True
    assert publish_pending(config, False, github)[0]["status"] == "pending"
    assert publish_pending(config, False, github)[0]["status"] == "published"
    assert sum(method == "PUT" for _, method, _ in github.calls) == 1


def test_public_repo_refused(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(config, "researcher", "run-2", "Result", dry_run=False)
    github = GitHub()
    github.private = False
    assert publish_pending(config, False, github)[0]["status"] == "pending"
    assert all(method == "GET" for _, method, _ in github.calls)


@pytest.mark.parametrize("source", ["~/org/staff.org", "gnus:mail", ".env"])
def test_private_sources_refused(tmp_path: Path, source: str) -> None:
    with pytest.raises(ValueError, match="Private"):
        queue_record(settings(tmp_path), "liaison", "run-1", "Result", sources=[source])


def test_local_only_details_never_persisted(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(
        config,
        "liaison",
        "run-1",
        "password=confidential",
        privacy="local-only",
        sources=["~/org/staff.org"],
        dry_run=False,
    )
    queued = next((tmp_path / "fleet-github").glob("*.json")).read_text()
    assert "confidential" not in queued and "staff.org" not in queued
    github = GitHub()
    assert publish_pending(config, False, github)[0]["status"] == "published"
    assert "Protected work completed" in base64.b64decode(github.content or "").decode()


def test_secret_and_path_traversal_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="credentials"):
        queue_record(settings(tmp_path), "researcher", "run-1", "password=confidential")
    with pytest.raises(ValueError, match="identifier"):
        queue_record(settings(tmp_path), "../other-org", "run-1", "Result")


def test_existing_different_content_refused(tmp_path: Path) -> None:
    config = settings(tmp_path)
    queue_record(config, "researcher", "run-1", "Result", dry_run=False)
    github = GitHub()
    github.content = base64.b64encode(b"Existing work").decode()
    assert publish_pending(config, False, github)[0]["status"] == "pending"
    assert all(method == "GET" for _, method, _ in github.calls)


class Fleet:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.issues: list[dict[str, Any]] = []
        self.prs: list[dict[str, Any]] = []
        self.tree: list[dict[str, Any]] = []
        self.conflict = False

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        endpoint, method = args[2], args[4]
        payload = json.loads(kwargs.get("input", "{}"))
        self.calls.append((endpoint, method, payload))
        result: Any = {"private": True}
        if "/issues" in endpoint or "/pulls" in endpoint:
            rows = self.issues if "/issues" in endpoint else self.prs
            if method == "POST":
                result = {**payload, "number": len(rows) + 1, "html_url": "https://example.test/1"}
                rows.append(result)
            else:
                result = rows
        elif "/git/ref/" in endpoint:
            result = {"object": {"sha": "parent"}}
        elif "/git/commits/" in endpoint:
            result = {"tree": {"sha": "tree"}}
        elif "/git/trees/" in endpoint:
            result = {"tree": self.tree, "truncated": False}
        elif method == "POST":
            result = {"sha": "new-sha"}
        elif method == "PATCH":
            if self.conflict:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 422 non-fast-forward")
            result = {"object": {"sha": "new-sha"}}
        return subprocess.CompletedProcess(args, 0, json.dumps(result), "")


def test_issue_and_pr_scoped_deduplication(tmp_path: Path) -> None:
    config = settings(tmp_path)
    github = Fleet()
    kwargs: dict[str, Any] = {"evidence": ["runs/run-1"], "dry_run": False, "exec_fn": github}
    assert create_issue(config, "study", "Bug", "Observed failure", **kwargs)["number"] == 1
    assert create_issue(config, "study", "Bug", "Observed failure", **kwargs)["duplicate"]
    assert create_pr(config, "study", "Fix", "Tested", "fix/one", **kwargs)["number"] == 1
    assert create_pr(config, "study", "Fix", "Tested", "fix/one", **kwargs)["duplicate"]
    assert len(github.issues) == len(github.prs) == 1
    assert github.prs[0]["draft"] is True
    assert all(
        endpoint.startswith("repos/borg-cube-fleet/study") for endpoint, _, _ in github.calls
    )


def test_fleet_dry_run_no_calls_and_validation(tmp_path: Path) -> None:
    config = settings(tmp_path)
    github = Fleet()
    assert create_issue(config, "study", "Bug", "Result", ["runs/run-1"], exec_fn=github)["dry_run"]
    assert create_pr(
        config, "study", "Fix", "Result", "fix", evidence=["runs/run-1"], exec_fn=github
    )["dry_run"]
    assert not github.calls
    with pytest.raises(ValueError, match="Only"):
        create_issue(config, "other/repo", "Bug", "Result", ["source"])
    with pytest.raises(ValueError, match="evidence"):
        create_issue(config, "study", "Bug", "Result", [])
    with pytest.raises(ValueError, match="externally"):
        create_pr(config, "study", "Fix", "Result", "outsider:fix", evidence=["source"])
    with pytest.raises(ValueError, match="Private"):
        create_issue(config, "study", "Bug", "Read /home/user/org/staff.org", ["source"])


def test_artifact_bundle_single_commit_preserves_modes(tmp_path: Path) -> None:
    github = Fleet()
    github.tree = [{"path": "run.sh", "sha": "old", "mode": "100755"}]
    result = publish_files(
        settings(tmp_path),
        "ontology",
        "study",
        "research/run-1",
        {"run.sh": "echo hello", "results/result.txt": "42"},
        "Reproduce result",
        ["runs/run-1"],
        False,
        github,
    )
    assert result["sha"] == "new-sha"
    tree = next(
        payload
        for endpoint, method, payload in github.calls
        if endpoint.endswith("/git/trees") and method == "POST"
    )
    assert tree["tree"][0]["mode"] == "100755"
    commit = next(
        payload
        for endpoint, method, payload in github.calls
        if endpoint.endswith("/git/commits") and method == "POST"
    )
    assert commit["parents"] == ["parent"]
    assert "ontologist" in commit["author"]["name"]
    assert github.calls[-1][2]["force"] is False


def test_artifact_retry_unchanged_and_conflict(tmp_path: Path) -> None:
    import hashlib

    github = Fleet()
    github.tree = [
        {"path": "result.txt", "mode": "100644", "sha": hashlib.sha1(b"blob 2\x0042").hexdigest()}
    ]
    args = (
        settings(tmp_path),
        "researcher",
        "study",
        "main",
        {"result.txt": "42"},
        "Results",
        ["runs/run-1"],
        False,
        github,
    )
    assert publish_files(*args)["unchanged"]
    assert all(method == "GET" for _, method, _ in github.calls)
    github.tree = []
    github.conflict = True
    with pytest.raises(RuntimeError):
        publish_files(*args)


def test_project_creation_private_and_initialized() -> None:
    calls = []

    def api(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
        return subprocess.CompletedProcess(args, 0, '{"private": true}', "")

    ensure_project("study", api)
    assert calls[1][0][2] == "orgs/borg-cube-fleet/repos"
    assert json.loads(calls[1][1]["input"]) == {
        "name": "study",
        "private": True,
        "auto_init": True,
    }


def test_checkpoints_durable_retry_and_privacy(tmp_path: Path, monkeypatch: Any) -> None:
    config = settings(tmp_path)
    args = (config, "ontology", "study", "main", {"result.txt": "42"}, "Checkpoint", ["runs/run-1"])
    assert queue_checkpoint(*args)["dry_run"]
    assert not (tmp_path / "fleet-checkpoints").exists()
    record = queue_checkpoint(*args, dry_run=False)
    assert queue_checkpoint(*args, dry_run=False)["id"] == record["id"]
    github = Fleet()
    github.conflict = True
    assert publish_pending(config, False, github)[0]["status"] == "pending"
    github.conflict = False
    assert publish_pending(config, False, github)[0]["status"] == "published"
    assert publish_pending(config, False, github) == []
    monkeypatch.setenv("CUBE_PRIVACY", "local-only")
    with pytest.raises(ValueError, match="Local-only"):
        queue_checkpoint(*args, dry_run=False)


def test_checkpoint_rejects_secrets_before_queue(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        queue_checkpoint(
            settings(tmp_path),
            "ontology",
            "study",
            "main",
            {"result.txt": "password: secretvalue"},
            "Result",
            ["run:1"],
            False,
        )
    assert not (tmp_path / "fleet-checkpoints").exists()


@pytest.mark.parametrize("path", ["../file", "/tmp/file", ".git/config", "x/../file", ".env"])
def test_artifact_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        publish_files(
            settings(tmp_path),
            "researcher",
            "study",
            "main",
            {path: "result"},
            "Result",
            ["runs/run-1"],
        )
