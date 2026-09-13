"""Read-only GitHub snapshot through the ``gh`` CLI, cached in state/cache/github.json.

The runner is injectable so tests never touch the network. When ``gh`` is missing or fails
the adapter returns an empty snapshot with a warning instead of raising.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

Runner = Callable[[list[str]], str]

DEFAULT_ORG = "bio-ontology-research-group"


class GhUnavailableError(RuntimeError):
    pass


def gh_runner(args: list[str]) -> str:
    """Run ``gh <args>`` and return stdout; raise GhUnavailableError if gh is missing or fails."""
    if shutil.which("gh") is None:
        raise GhUnavailableError("gh CLI not installed")
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GhUnavailableError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


@dataclass
class RepoRecord:
    full_name: str
    name: str
    html_url: str
    pushed_at: str | None
    open_issues: int = 0
    archived: bool = False
    fork: bool = False
    private: bool = False
    default_branch: str = "main"
    license: str | None = None
    has_license: bool | None = None
    has_readme: bool | None = None
    has_ci: bool | None = None
    description: str | None = None

    def pushed_date(self) -> datetime | None:
        if not self.pushed_at:
            return None
        try:
            return datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
        except ValueError:
            return None

    def days_since_push(self, now: datetime) -> int | None:
        pushed = self.pushed_date()
        if pushed is None:
            return None
        return (now - pushed).days

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    org: str
    fetched_at: str
    repos: list[RepoRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "fetched_at": self.fetched_at,
            "from_cache": self.from_cache,
            "warnings": self.warnings,
            "repos": [r.as_dict() for r in self.repos],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        repos = [RepoRecord(**r) for r in data.get("repos", [])]
        return cls(
            org=str(data.get("org", DEFAULT_ORG)),
            fetched_at=str(data.get("fetched_at", "")),
            repos=repos,
            warnings=list(data.get("warnings", [])),
            from_cache=True,
        )


@dataclass
class GitHubSource:
    cache_path: Path
    org: str = DEFAULT_ORG
    ttl_hours: int = 24
    runner: Runner | None = None  # None resolves to gh_runner at call time (patchable)
    detail_window_days: int = 730
    now: datetime | None = None

    def _now(self) -> datetime:
        return self.now or datetime.now(UTC)

    def _call(self, args: list[str]) -> str:
        return (self.runner or gh_runner)(args)

    def cached(self) -> Snapshot | None:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            snap = Snapshot.from_dict(data)
        except (ValueError, TypeError):
            return None
        try:
            fetched = datetime.fromisoformat(snap.fetched_at)
        except ValueError:
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        if self._now() - fetched > timedelta(hours=self.ttl_hours):
            return None
        return snap

    def snapshot(self, *, refresh: bool = False, details: bool = True) -> Snapshot:
        if not refresh:
            cached = self.cached()
            if cached is not None:
                return cached
        snap = Snapshot(org=self.org, fetched_at=self._now().isoformat())
        try:
            raw = self._call(
                ["api", f"orgs/{self.org}/repos?per_page=100&type=public", "--paginate"]
            )
        except GhUnavailableError as exc:
            snap.warnings.append(str(exc))
            stale = self._stale_cache()
            if stale is not None:
                stale.warnings.append(f"using stale cache: {exc}")
                return stale
            return snap
        for item in _parse_paginated(raw):
            lic = item.get("license") or {}
            rec = RepoRecord(
                full_name=str(item.get("full_name") or f"{self.org}/{item.get('name')}"),
                name=str(item.get("name")),
                html_url=str(item.get("html_url") or ""),
                pushed_at=item.get("pushed_at"),
                open_issues=int(item.get("open_issues_count") or 0),
                archived=bool(item.get("archived")),
                fork=bool(item.get("fork")),
                private=bool(item.get("private")),
                default_branch=str(item.get("default_branch") or "main"),
                license=lic.get("spdx_id") if isinstance(lic, dict) else None,
                description=item.get("description"),
            )
            rec.has_license = rec.license is not None and rec.license != "NOASSERTION"
            snap.repos.append(rec)
        if details:
            self._fill_details(snap)
        self._write_cache(snap)
        return snap

    def _fill_details(self, snap: Snapshot) -> None:
        now = self._now()
        for rec in snap.repos:
            if rec.archived or rec.fork:
                continue
            age = rec.days_since_push(now)
            if age is None or age > self.detail_window_days:
                continue
            rec.has_readme = self._exists(f"repos/{rec.full_name}/readme")
            rec.has_ci = self._exists(f"repos/{rec.full_name}/contents/.github/workflows")
            if rec.has_license is None or not rec.has_license:
                rec.has_license = bool(rec.has_license) or self._exists(
                    f"repos/{rec.full_name}/license"
                )

    def _exists(self, endpoint: str) -> bool | None:
        try:
            self._call(["api", endpoint, "--silent"])
            return True
        except GhUnavailableError as exc:
            if "404" in str(exc) or "Not Found" in str(exc):
                return False
            return None

    def _stale_cache(self) -> Snapshot | None:
        if not self.cache_path.exists():
            return None
        try:
            return Snapshot.from_dict(json.loads(self.cache_path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None

    def _write_cache(self, snap: Snapshot) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(snap.as_dict(), indent=1), encoding="utf-8")
        except OSError as exc:
            snap.warnings.append(f"could not write cache {self.cache_path}: {exc}")


def _parse_paginated(raw: str) -> list[dict[str, Any]]:
    """``gh api --paginate`` concatenates JSON arrays; accept that or one array/object."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return _as_items(data)
    except json.JSONDecodeError:
        pass
    items: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(raw):
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos >= len(raw):
            break
        obj, end = decoder.raw_decode(raw, pos)
        items.extend(_as_items(obj))
        pos = end
    return items


def _as_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def audit_reasons(
    rec: RepoRecord, now: datetime, stale_days: int = 180, window_days: int = 730
) -> list[str]:
    """Why a repository deserves an audit bead; empty list means none.

    Missing CI/LICENSE/README only counts for repositories pushed within ``window_days``;
    dormant repositories are flagged only when they still carry open issues.
    """
    if rec.archived or rec.fork:
        return []
    reasons: list[str] = []
    age = rec.days_since_push(now)
    recent = age is not None and age <= window_days
    if recent and rec.has_ci is False:
        reasons.append("no CI workflows")
    if recent and rec.has_license is False:
        reasons.append("no LICENSE")
    if recent and rec.has_readme is False:
        reasons.append("no README")
    if age is not None and age > stale_days and rec.open_issues > 0:
        reasons.append(f"{rec.open_issues} open issue(s), last push {age} days ago")
    return reasons
