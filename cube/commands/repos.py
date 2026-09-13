"""`cube repos --json`: GitHub organisation snapshot with hygiene flags."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from cube.commands import Helpers
from cube.commands._common import Ledger, add_today, context, now_iso
from cube.config import Settings
from cube.sources.github import audit_reasons
from cube.sync.derivers import REPO_STALE_DAYS

_helpers: Helpers | None = None


def cmd_repos(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args, github_details=not args.no_details)
    if args.refresh:
        cache = settings.state_dir() / "cache" / "github.json"
        if cache.exists():
            cache.unlink()
    snap = ctx.github
    # A malformed third-party Beads description must not turn a JSON read command
    # into a traceback. Repository facts remain useful without audit-bead links.
    try:
        ledger = Ledger(_helpers.beads(settings, True))
        ledger_warning: str | None = None
    except Exception as exc:  # Beads data is external to this read-only command.
        ledger = None
        ledger_warning = f"could not index existing beads: {exc}"
    now = datetime.combine(ctx.today, datetime.min.time(), tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for r in snap.repos:
        if args.active and (r.archived or r.fork):
            continue
        reasons = audit_reasons(r, now, REPO_STALE_DAYS)
        rows.append(
            {
                "name": r.name,
                "full_name": r.full_name,
                "path": None,
                "url": r.html_url,
                "branch": r.default_branch,
                "dirty": None,
                "ahead": None,
                "behind": None,
                "open_prs": None,
                "open_issues": r.open_issues,
                "ci": "configured" if r.has_ci else ("none" if r.has_ci is False else None),
                "license": r.license,
                "has_readme": r.has_readme,
                "archived": r.archived,
                "fork": r.fork,
                "last_commit": r.pushed_at,
                "days_since_push": r.days_since_push(now),
                "audit_reasons": reasons,
                "audit_bead": ledger.id_for(f"audit:{r.full_name}") if ledger else None,
            }
        )
    rows.sort(key=lambda x: x["last_commit"] or "", reverse=True)
    payload = {
        "generated": now_iso(),
        "org": snap.org,
        "fetched_at": snap.fetched_at,
        "from_cache": snap.from_cache,
        "repos": rows,
        "warnings": ctx.warnings + snap.warnings + ([ledger_warning] if ledger_warning else []),
    }
    lines = [
        f"{snap.org}: {len(rows)} repos (snapshot {snap.fetched_at}"
        f"{', cached' if snap.from_cache else ''})"
    ]
    for row in rows:
        flag = "; ".join(row["audit_reasons"])
        lines.append(
            f"  {row['name']:40} pushed {str(row['last_commit'])[:10]} "
            f"issues {row['open_issues']:3} ci {str(row['ci'] or '?'):10} {flag}"
        )
    _helpers.emit(args, payload, "\n".join(lines))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("repos", help="GitHub organisation snapshot")
    sp.add_argument("--refresh", action="store_true", help="ignore the cache")
    sp.add_argument("--no-details", action="store_true", help="skip README/CI/LICENSE checks")
    sp.add_argument("--active", action="store_true", help="hide archived repos and forks")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_repos)
