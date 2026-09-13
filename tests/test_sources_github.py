import json
from datetime import UTC, datetime
from pathlib import Path

from cube.sources.github import (
    GhUnavailableError,
    GitHubSource,
    Snapshot,
    _parse_paginated,
    audit_reasons,
)

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 2, tzinfo=UTC)


def fake_runner(calls: list[list[str]]):  # type: ignore[no-untyped-def]
    repos = (FIX / "github_repos.json").read_text()

    def run(args: list[str]) -> str:
        calls.append(args)
        endpoint = args[1]
        if endpoint.startswith("orgs/"):
            return repos
        if "no-ci" in endpoint and ("workflows" in endpoint or "license" in endpoint):
            raise GhUnavailableError("gh api failed: HTTP 404: Not Found")
        if "stale-issues" in endpoint and "readme" in endpoint:
            raise GhUnavailableError("gh api failed: HTTP 404: Not Found")
        return ""

    return run


def test_snapshot_details_and_cache(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    src = GitHubSource(cache_path=tmp_path / "gh.json", runner=fake_runner(calls), now=NOW)
    snap = src.snapshot()
    assert not snap.from_cache and len(snap.repos) == 4
    by = {r.name: r for r in snap.repos}
    assert by["fresh-ok"].has_ci is True and by["fresh-ok"].has_license is True
    assert by["fresh-ok"].has_readme is True
    assert by["no-ci"].has_ci is False and by["no-ci"].has_license is False
    # stale-issues was pushed > 730 days ago: no detail calls, flags stay unknown
    assert by["stale-issues"].has_readme is None
    assert by["old-archived"].has_ci is None
    assert not any("old-archived" in c[1] for c in calls if len(c) > 1)
    # second call served from cache
    n = len(calls)
    again = GitHubSource(cache_path=tmp_path / "gh.json", runner=fake_runner(calls), now=NOW)
    cached = again.snapshot()
    assert cached.from_cache and len(calls) == n and len(cached.repos) == 4
    # expired cache refetches
    later = GitHubSource(
        cache_path=tmp_path / "gh.json",
        runner=fake_runner(calls),
        now=datetime(2026, 9, 4, tzinfo=UTC),
    )
    assert not later.snapshot().from_cache


def test_missing_gh_never_raises(tmp_path: Path) -> None:
    def broken(args: list[str]) -> str:
        raise GhUnavailableError("gh CLI not installed")

    src = GitHubSource(cache_path=tmp_path / "gh.json", runner=broken, now=NOW)
    snap = src.snapshot()
    assert snap.repos == [] and snap.warnings == ["gh CLI not installed"]
    # with a stale cache on disk, the stale data is returned with a warning
    stale = Snapshot(org="x", fetched_at="2020-01-01T00:00:00+00:00")
    (tmp_path / "gh.json").write_text(json.dumps(stale.as_dict()))
    snap2 = src.snapshot()
    assert snap2.from_cache and any("stale" in w for w in snap2.warnings)


def test_audit_reasons() -> None:
    snap = Snapshot.from_dict({"repos": json.loads((FIX / "github_repos.json").read_text()) and []})
    assert snap.repos == []
    calls: list[list[str]] = []
    src = GitHubSource(cache_path=Path("/nonexistent/x.json"), runner=fake_runner(calls), now=NOW)
    repos = {r.name: r for r in src.snapshot().repos}
    assert audit_reasons(repos["fresh-ok"], NOW) == []
    assert audit_reasons(repos["no-ci"], NOW) == ["no CI workflows", "no LICENSE"]
    stale = audit_reasons(repos["stale-issues"], NOW)
    assert len(stale) == 1 and stale[0].startswith("4 open issue(s)")
    # a dormant repo without a licence is not flagged for the missing file alone
    repos["stale-issues"].has_license = False
    repos["stale-issues"].open_issues = 0
    assert audit_reasons(repos["stale-issues"], NOW) == []
    assert audit_reasons(repos["old-archived"], NOW) == []


def test_parse_paginated_concatenated() -> None:
    raw = '[{"name": "a"}][{"name": "b"}]'
    assert [x["name"] for x in _parse_paginated(raw)] == ["a", "b"]
    assert _parse_paginated("") == []
