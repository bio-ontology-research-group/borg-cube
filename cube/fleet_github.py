"""Durable, private research notebooks in the explicitly scoped fleet repository."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from cube.config import Settings, clean_github_environment

REPOSITORY = "borg-cube-fleet/research-log"
EMAIL = "leechuck@leechuck.de"
Executor = Callable[..., Any]
_SECRET = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)|"
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_[A-Za-z0-9_]+|"
    r"sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b|"
    r"\b(?:password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+|"
    r"\bBearer\s+[A-Za-z0-9._~-]+",
    re.IGNORECASE,
)
_PRIVATE_SOURCE = re.compile(
    r"(?:^|/)(?:org|pa|Mail|mail|\.gnus|\.authinfo|\.env)(?:/|\b)|"
    r"(?:gnus|notmuch|message-id|mailto):|password|auth\.json",
    re.IGNORECASE,
)


def _safe(value: str) -> None:
    if _SECRET.search(value):
        raise ValueError("Fleet publication contains potential credentials")


def _slug(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("Invalid fleet agent or run identifier")
    return value


@contextmanager
def _lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _save(path: Path, record: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".record-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def queue_record(
    settings: Settings,
    agent_name: str,
    run_id: str,
    summary: str,
    *,
    privacy: str = "internal",
    sources: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Queue once per agent/run. Local-only work publishes metadata only."""
    _slug(agent_name)
    _slug(run_id)
    if privacy not in {"public", "internal", "local-only"}:
        raise ValueError("Unknown publication privacy class")
    sources = list(sources or [])
    if privacy == "local-only":
        summary = "Protected work completed. Details and sources remain local."
        sources = []
    elif any(_PRIVATE_SOURCE.search(source) for source in sources):
        raise ValueError("Private mail, org, or credential sources cannot be published")
    _safe(json.dumps([summary, sources]))
    identifier = hashlib.sha256(f"{agent_name}\0{run_id}".encode()).hexdigest()
    record: dict[str, Any] = {
        "id": identifier,
        "agent": agent_name,
        "run_id": run_id,
        "summary": summary,
        "sources": sources,
        "privacy": privacy,
        "queued_at": datetime.now(UTC).isoformat(),
        "status": "pending",
        "repository": REPOSITORY,
    }
    directory = settings.state_dir() / "fleet-github"
    path = directory / f"{identifier}.json"
    if dry_run:
        return {**record, "dry_run": True}
    with _lock(directory):
        if path.exists():
            existing: dict[str, Any] = json.loads(path.read_text())
            if any(
                existing.get(key) != record[key]
                for key in ("agent", "run_id", "summary", "sources", "privacy")
            ):
                raise ValueError("Fleet run already queued with different evidence")
            return existing
        _save(path, record)
    return record


def _api(
    exec_fn: Executor, endpoint: str, payload: dict[str, Any] | None = None, method: str = "GET"
) -> Any:
    args = ["gh", "api", endpoint, "--method", method]
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 60}
    environment = dict(os.environ)
    clean_github_environment(environment)
    kwargs["env"] = environment
    if payload is not None:
        args += ["--input", "-"]
        kwargs["input"] = json.dumps(payload)
    proc = exec_fn(args, **kwargs)
    if proc.returncode:
        if "HTTP 404" in proc.stderr:
            return None
        raise RuntimeError("GitHub request failed; record remains pending")
    return json.loads(proc.stdout)


def _document(record: dict[str, Any]) -> str:
    _slug(record["agent"])
    _slug(record["run_id"])
    if record["privacy"] == "local-only":
        summary = "Protected work completed. Details and sources remain local."
        sources: list[str] = []
    else:
        if record["privacy"] not in {"public", "internal"}:
            raise ValueError("Unknown publication privacy class")
        summary, sources = record["summary"], record["sources"]
        if any(_PRIVATE_SOURCE.search(source) for source in sources):
            raise ValueError("Private source in queued publication")
    document = (
        f"# Research record: {record['agent']}\n\n"
        f"Run: {record['run_id']}\n\nRecorded: {record['queued_at']}\n\n"
        f"## Result\n\n{summary}\n\n## Provenance\n\n"
        + ("\n".join(f"- {source}" for source in sources) or "Local run metadata only.")
        + "\n"
    )
    _safe(document)
    return document


def publish_pending(
    settings: Settings, dry_run: bool = True, exec_fn: Executor = subprocess.run
) -> list[dict[str, Any]]:
    """Publish queued records; failures remain pending and retries compare content.

    Applying explicitly authorizes creation of the private fleet notebook repository.
    Dry runs never call GitHub. No queue contents can select another repository.
    """
    directory = settings.state_dir() / "fleet-github"
    results: list[dict[str, Any]] = publish_checkpoints(settings, dry_run, exec_fn)
    if not directory.exists():
        return results
    with _lock(directory):
        for path in sorted(directory.glob("*.json")):
            record = json.loads(path.read_text())
            if record.get("status") != "pending":
                continue
            try:
                document = _document(record)
                if dry_run:
                    results.append({"id": record["id"], "status": "pending", "dry_run": True})
                    continue
                repo = _api(exec_fn, f"repos/{REPOSITORY}")
                if repo is None:
                    _api(
                        exec_fn,
                        "orgs/borg-cube-fleet/repos",
                        {"name": "research-log", "private": True},
                        "POST",
                    )
                    repo = _api(exec_fn, f"repos/{REPOSITORY}")
                if not repo or repo.get("private") is not True:
                    raise ValueError("Fleet notebook repository must be private")
                endpoint = (
                    f"repos/{REPOSITORY}/contents/research/{record['agent']}/{record['run_id']}.md"
                )
                current = _api(exec_fn, endpoint)
                if current is not None:
                    content = base64.b64decode(current.get("content", "")).decode("utf-8")
                    if content != document:
                        raise ValueError("Existing fleet record differs; refusing overwrite")
                else:
                    role = "ontologist" if record["agent"] == "ontology" else record["agent"]
                    identity = {
                        "name": f"Robert Hoehndorf (BORG Cube Fleet: {role})",
                        "email": EMAIL,
                    }
                    response = _api(
                        exec_fn,
                        endpoint,
                        {
                            "message": f"Document {record['agent']} run {record['run_id']}",
                            "content": base64.b64encode(document.encode()).decode(),
                            "author": identity,
                            "committer": identity,
                        },
                        "PUT",
                    )
                    if response is None:
                        raise RuntimeError("GitHub content creation failed")
                record["status"] = "published"
                record["url"] = (
                    f"https://github.com/{REPOSITORY}/blob/HEAD/research/{record['agent']}/{record['run_id']}.md"
                )
                _save(path, record)
                results.append({"id": record["id"], "status": "published", "url": record["url"]})
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                # Never store command stderr, which can contain credentials or private data.
                results.append(
                    {"id": record["id"], "status": "pending", "error": type(exc).__name__}
                )
    return results


def _repository(repo: str) -> str:
    if "/" not in repo:
        repo = "borg-cube-fleet/" + repo
    if not re.fullmatch(r"borg-cube-fleet/[A-Za-z0-9][A-Za-z0-9_.-]*", repo):
        raise ValueError("Only borg-cube-fleet repositories are authorized")
    return repo


def _evidence(body: str, evidence: list[str]) -> str:
    if not evidence or any(not item.strip() for item in evidence):
        raise ValueError("Publication requires explicit evidence")
    if any(_PRIVATE_SOURCE.search(item) for item in [body, *evidence]):
        raise ValueError("Private sources cannot be published")
    text = body + "\n\nEvidence:\n" + "\n".join(f"- {item}" for item in evidence)
    _safe(text)
    return text


def _private_repo(repo: str, exec_fn: Executor) -> None:
    result = _api(exec_fn, f"repos/{repo}")
    if not result or result.get("private") is not True:
        raise ValueError("Fleet publication requires an existing private repository")


def ensure_project(repo: str, exec_fn: Executor) -> None:
    """Create only private fleet repositories; never change existing visibility."""
    repo = _repository(repo)
    if _api(exec_fn, f"repos/{repo}") is None:
        _api(
            exec_fn,
            "orgs/borg-cube-fleet/repos",
            {
                "name": repo.split("/", 1)[1],
                "private": True,
                "auto_init": True,
            },
            "POST",
        )
    _private_repo(repo, exec_fn)


def queue_checkpoint(
    settings: Settings,
    agent: str,
    repo: str,
    branch: str,
    files: dict[str, str],
    message: str,
    evidence: list[str],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Persist a screened snapshot before network access, independent of run success."""
    if os.environ.get("CUBE_PRIVACY") == "local-only":
        raise ValueError("Local-only runs cannot publish artifacts; use a reviewed internal run")
    publish_files(settings, agent, repo, branch, files, message, evidence, dry_run=True)
    record = dict(
        agent=agent,
        repository=_repository(repo),
        branch=branch,
        files=files,
        message=message,
        evidence=evidence,
    )
    identifier = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    record.update(id=identifier, status="pending", queued_at=datetime.now(UTC).isoformat())
    if dry_run:
        return {"dry_run": True, "repository": record["repository"], "files": sorted(files)}
    directory = settings.state_dir() / "fleet-checkpoints"
    with _lock(directory):
        path = directory / f"{identifier}.json"
        if path.exists():
            existing = json.loads(path.read_text())
            return {key: existing[key] for key in ("id", "status", "repository")}
        _save(path, record)
    return {"id": identifier, "status": "pending", "repository": record["repository"]}


def publish_checkpoints(
    settings: Settings,
    dry_run: bool = True,
    exec_fn: Executor = subprocess.run,
) -> list[dict[str, Any]]:
    directory = settings.state_dir() / "fleet-checkpoints"
    if not directory.exists():
        return []
    results: list[dict[str, Any]] = []
    with _lock(directory):
        records = [(p, json.loads(p.read_text())) for p in directory.glob("*.json")]
        blocked: set[str] = set()
        for path, record in sorted(records, key=lambda pair: pair[1]["queued_at"]):
            if record["status"] != "pending" or record["repository"] in blocked:
                continue
            try:
                result = publish_files(
                    settings,
                    record["agent"],
                    record["repository"],
                    record["branch"],
                    record["files"],
                    record["message"],
                    record["evidence"],
                    dry_run,
                    exec_fn,
                )
                if not dry_run:
                    record.update(status="published", result=result)
                    _save(path, record)
                results.append({"id": record["id"], "status": record["status"], **result})
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                blocked.add(record["repository"])
                results.append(
                    {
                        "id": record["id"],
                        "status": "pending",
                        "repository": record["repository"],
                        "error": type(exc).__name__,
                    }
                )
    return results


def _branch(branch: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", branch)
        or ".." in branch
        or "//" in branch
        or branch.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") or part.endswith(".lock") for part in branch.split("/"))
    ):
        raise ValueError("Invalid branch; externally qualified heads are forbidden")
    return branch


def create_issue(
    settings: Settings,
    repo: str,
    title: str,
    body: str,
    evidence: list[str],
    dry_run: bool = True,
    exec_fn: Executor = subprocess.run,
) -> dict[str, Any]:
    """Create an evidenced fleet issue, deduplicating against all existing issues."""
    repo = _repository(repo)
    body = _evidence(body, evidence)
    _safe(title)
    digest = hashlib.sha256(json.dumps([repo, title, body]).encode()).hexdigest()
    marker = f"<!-- borg-cube-evidence:{digest} -->"
    payload = {"title": title, "body": body + "\n\n" + marker}
    if dry_run:
        return {"dry_run": True, "repository": repo, **payload}
    with _lock(settings.state_dir() / "fleet-github"):
        _private_repo(repo, exec_fn)
        page = 1
        while True:
            rows = _api(exec_fn, f"repos/{repo}/issues?state=all&per_page=100&page={page}")
            if not isinstance(rows, list):
                raise RuntimeError("Unable to check existing issues")
            for row in rows:
                if marker in (row.get("body") or "") and "pull_request" not in row:
                    return {"duplicate": True, "number": row["number"], "url": row["html_url"]}
            if len(rows) < 100:
                break
            page += 1
        result = _api(exec_fn, f"repos/{repo}/issues", payload, "POST")
        if not result:
            raise RuntimeError("Issue creation failed")
        return {"number": result["number"], "url": result["html_url"]}


def create_pr(
    settings: Settings,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
    *,
    evidence: list[str],
    dry_run: bool = True,
    exec_fn: Executor = subprocess.run,
) -> dict[str, Any]:
    """Open a draft improvement PR with evidence, scoped to fleet-owned branches."""
    repo = _repository(repo)
    _branch(head)
    _branch(base)
    if head == base:
        raise ValueError("PR head and base must differ")
    payload = {
        "title": title,
        "body": _evidence(body, evidence),
        "head": head,
        "base": base,
        "draft": True,
    }
    _safe(title)
    if dry_run:
        return {"dry_run": True, "repository": repo, **payload}
    with _lock(settings.state_dir() / "fleet-github"):
        _private_repo(repo, exec_fn)
        endpoint = (
            f"repos/{repo}/pulls?state=all&head="
            f"{quote('borg-cube-fleet:' + head, safe='')}&base={quote(base, safe='')}"
        )
        rows = _api(exec_fn, endpoint)
        if not isinstance(rows, list):
            raise RuntimeError("Unable to check existing PRs")
        if rows:
            return {"duplicate": True, "number": rows[0]["number"], "url": rows[0]["html_url"]}
        result = _api(exec_fn, f"repos/{repo}/pulls", payload, "POST")
        if not result:
            raise RuntimeError("PR creation failed")
        return {"number": result["number"], "url": result["html_url"]}


def publish_files(
    settings: Settings,
    agent: str,
    repo: str,
    branch: str,
    files: dict[str, str],
    message: str,
    evidence: list[str],
    dry_run: bool = True,
    exec_fn: Executor = subprocess.run,
) -> dict[str, Any]:
    """Publish a complete UTF-8 artifact bundle, creating its private project if absent.

    Files can include code, environment commands, and result documents. No deletions
    are performed. Unchanged blobs are idempotent. A concurrent branch update causes
    a non-fast-forward failure, preserving the other writer's work.
    """
    repo = _repository(repo)
    if os.environ.get("CUBE_PRIVACY") == "local-only":
        raise ValueError("Local-only runs cannot publish artifacts")
    _slug(agent)
    _branch(branch)
    commit_message = _evidence(message, evidence)
    if not files:
        raise ValueError("Artifact bundle must contain files")
    if not isinstance(files, dict) or any(
        not isinstance(path, str) or not isinstance(content, str) for path, content in files.items()
    ):
        raise ValueError("Artifact manifest must map paths to UTF-8 text")
    for path, content in files.items():
        parts = PurePosixPath(path).parts
        if (
            not parts
            or path != str(PurePosixPath(path))
            or path.startswith("/")
            or ".." in parts
            or ".git" in parts
            or "\\" in path
            or any(ord(char) < 32 for char in path)
        ):
            raise ValueError("Unsafe artifact path")
        if _PRIVATE_SOURCE.search(path) or _PRIVATE_SOURCE.search(content):
            raise ValueError("Private artifact source")
        _safe(content)
    if dry_run:
        return {"dry_run": True, "repository": repo, "branch": branch, "files": sorted(files)}
    with _lock(settings.state_dir() / "fleet-github"):
        ensure_project(repo, exec_fn)
        reference = _api(exec_fn, f"repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")
        if not reference:
            info = _api(exec_fn, f"repos/{repo}")
            default = _branch(info.get("default_branch", "main"))
            source = _api(exec_fn, f"repos/{repo}/git/ref/heads/{quote(default, safe='/')}")
            if not source:
                raise ValueError("Project repository has no initial branch; retry initialization")
            reference = _api(
                exec_fn,
                f"repos/{repo}/git/refs",
                {
                    "ref": f"refs/heads/{branch}",
                    "sha": source["object"]["sha"],
                },
                "POST",
            )
        parent = reference["object"]["sha"]
        commit = _api(exec_fn, f"repos/{repo}/git/commits/{parent}")
        tree_sha = commit["tree"]["sha"]
        tree = _api(exec_fn, f"repos/{repo}/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated"):
            raise ValueError("Repository tree is too large to verify safely")
        existing = {item["path"]: item for item in tree["tree"]}
        entries: list[dict[str, str]] = []
        for path, content in files.items():
            data = content.encode("utf-8")
            blob_sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            current = existing.get(path)
            if current and current.get("mode") not in {"100644", "100755"}:
                raise ValueError("Refusing to replace symlink, directory, or submodule")
            if current and current["sha"] == blob_sha:
                continue
            entries.append(
                {
                    "path": path,
                    "mode": current["mode"] if current else "100644",
                    "type": "blob",
                    "content": content,
                }
            )
        if not entries:
            return {"unchanged": True, "sha": parent, "repository": repo}
        new_tree = _api(
            exec_fn, f"repos/{repo}/git/trees", {"base_tree": tree_sha, "tree": entries}, "POST"
        )
        role = "ontologist" if agent == "ontology" else agent
        identity = {"name": f"Robert Hoehndorf (BORG Cube Fleet: {role})", "email": EMAIL}
        new_commit = _api(
            exec_fn,
            f"repos/{repo}/git/commits",
            {
                "message": commit_message,
                "tree": new_tree["sha"],
                "parents": [parent],
                "author": identity,
                "committer": identity,
            },
            "POST",
        )
        updated = _api(
            exec_fn,
            f"repos/{repo}/git/refs/heads/{quote(branch, safe='/')}",
            {"sha": new_commit["sha"], "force": False},
            "PATCH",
        )
        if not updated:
            raise RuntimeError("Branch update failed")
        return {
            "sha": new_commit["sha"],
            "repository": repo,
            "url": f"https://github.com/{repo}/commit/{new_commit['sha']}",
        }
