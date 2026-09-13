"""Papers patrol: papers.org states against the paper directories under ~/Documents/papers.

For SUBMITTED, REVISING and READY_TO_SUBMIT papers the patrol finds the paper directory
(``:DIR:`` property, exact slug, or a unique slug match), reads the last commit date with
``git log`` (injectable) and raises a finding when the state has been idle longer than the
threshold (skills/group-monitor/assets/thresholds.yaml, defaults 120/30/14 days).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads
from cube.config import Settings
from cube.model import BeadHeader, WorkKind
from cube.patrols.base import Finding, PatrolReport, prov, register
from cube.sources.org import PaperEntry, slugify
from cube.sync.context import SourceContext
from cube.sync.derivers import PAPER_CLOSED_STATES, DesiredBead

GitLog = Callable[[Path], date | None]

DEFAULT_THRESHOLDS: dict[str, int] = {
    "SUBMITTED": 120,
    "REVISING": 30,
    "READY_TO_SUBMIT": 14,
}
THRESHOLD_KEYS = {
    "SUBMITTED": "submitted_max_days",
    "REVISING": "revising_idle_days",
    "READY_TO_SUBMIT": "ready_idle_days",
}
WATCHED_STATES = tuple(DEFAULT_THRESHOLDS)


def git_last_commit(path: Path) -> date | None:
    """Date of the last commit in ``path`` (None when not a git checkout or git fails)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return datetime.fromisoformat(proc.stdout.strip()).date()
    except ValueError:
        return None


def load_thresholds(root: Path) -> dict[str, int]:
    out = dict(DEFAULT_THRESHOLDS)
    path = root / "skills" / "group-monitor" / "assets" / "thresholds.yaml"
    if not path.exists():
        return out
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return out
    papers = data.get("papers") if isinstance(data, dict) else None
    if not isinstance(papers, dict):
        return out
    for state, key in THRESHOLD_KEYS.items():
        entry = papers.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("value"), int):
            out[state] = int(entry["value"])
    return out


def paper_dir(paper: PaperEntry, papers_root: Path) -> tuple[Path | None, str | None]:
    """Locate the paper directory; returns (path, note) where note explains a miss."""
    for key in ("DIR", "PATH", "REPO"):
        raw = paper.properties.get(key)
        if raw:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = papers_root / p
            return (p, None) if p.is_dir() else (None, f":{key}: {raw} does not exist")
    if not papers_root.is_dir():
        return None, f"papers directory {papers_root} not present on this host"
    dirs = {d.name: d for d in papers_root.iterdir() if d.is_dir() and not d.name.startswith(".")}
    if paper.slug in dirs:
        return dirs[paper.slug], None
    title_slug = slugify(paper.title)
    if title_slug in dirs:
        return dirs[title_slug], None
    by_slug = {slugify(n): d for n, d in dirs.items()}
    if paper.slug in by_slug:
        return by_slug[paper.slug], None
    if len(paper.slug) >= 5:
        hits = [
            d
            for s, d in by_slug.items()
            if len(s) >= 5 and (s.startswith(paper.slug) or paper.slug.startswith(s))
        ]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, f"ambiguous directory match: {', '.join(sorted(h.name for h in hits))}"
    return None, "no paper directory matches the slug"


def finding_xid(paper: PaperEntry) -> str:
    return f"finding:paper:{paper.slug}:idle"


def derive(
    ctx: SourceContext,
    *,
    papers_root: Path,
    thresholds: dict[str, int],
    git_log: GitLog = git_last_commit,
) -> tuple[list[DesiredBead], list[Finding], dict[str, Any]]:
    beads: list[DesiredBead] = []
    notes: list[Finding] = []
    checked: list[dict[str, Any]] = []
    for paper in ctx.papers:
        xid = finding_xid(paper)
        state = paper.state or ""
        people_labels = [
            f"person:{p.id}" for p in (ctx.index.by_first_name(n) for n in paper.people) if p
        ]
        provenance = [prov(str(paper.path), paper.locator, ctx.today)]
        if state in PAPER_CLOSED_STATES:
            beads.append(
                DesiredBead(
                    xid=xid,
                    title=f"Paper idle: {paper.title}",
                    kind=WorkKind.finding,
                    labels=["src:papers.org", *people_labels],
                    header=BeadHeader(xid=xid, provenance=provenance),
                    closed=True,
                    close_reason=f"papers.org state {state}",
                )
            )
            continue
        if state not in WATCHED_STATES:
            continue
        path, miss = paper_dir(paper, papers_root)
        last = git_log(path) if path else None
        age = (ctx.today - last).days if last else None
        limit = thresholds[state]
        checked.append(
            {
                "slug": paper.slug,
                "state": state,
                "dir": str(path) if path else None,
                "last_commit": last.isoformat() if last else None,
                "age_days": age,
                "limit": limit,
            }
        )
        if path is None:
            notes.append(
                Finding(
                    key=f"paper-nodir:{paper.slug}",
                    title=f"{state} {paper.title}: {miss}",
                    severity="info",
                    detail="state cannot be dated without a paper directory",
                    source=paper.locator,
                )
            )
            continue
        if last is None:
            notes.append(
                Finding(
                    key=f"paper-nogit:{paper.slug}",
                    title=f"{state} {paper.title}: {path} has no git history",
                    severity="info",
                    source=paper.locator,
                )
            )
            continue
        if age is not None and age <= limit:
            beads.append(
                DesiredBead(
                    xid=xid,
                    title=f"Paper idle: {paper.title}",
                    kind=WorkKind.finding,
                    labels=["src:papers.org", *people_labels],
                    header=BeadHeader(xid=xid, provenance=provenance),
                    closed=True,
                    close_reason=f"last commit {last.isoformat()} within {limit} days",
                )
            )
            continue
        what = {
            "SUBMITTED": "ask the journal or the first author about the status",
            "REVISING": "no commits while revising; check with the first author",
            "READY_TO_SUBMIT": "ready but not submitted; decide on the venue or submit",
        }[state]
        body = [
            f"papers.org state {state} ({paper.outline})",
            f"Paper directory: {path}",
            f"Last commit: {last.isoformat()} ({age} days ago; threshold {limit} days)",
            what,
        ]
        if paper.people:
            body.append("People: " + ", ".join(paper.people))
        beads.append(
            DesiredBead(
                xid=xid,
                title=f"Paper idle: [{state}] {paper.title} ({age} days since last commit)",
                kind=WorkKind.finding,
                labels=[
                    "src:papers.org",
                    "src:git",
                    f"paper-state:{state.lower()}",
                    *people_labels,
                ],
                parent_xid=f"paper:{paper.slug}",
                header=BeadHeader(
                    xid=xid,
                    provenance=[
                        *provenance,
                        prov(
                            str(path),
                            f"git log -1 --format=%cI -> {last.isoformat()}",
                            ctx.today,
                        ),
                    ],
                ),
                body="\n".join(body),
                priority=2,
            )
        )
    return beads, notes, {"checked": checked, "thresholds": thresholds}


@dataclass
class PapersPatrol:
    name: str = "papers"
    git_log: GitLog = git_last_commit

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=False)
        thresholds = load_thresholds(settings.root)
        desired, notes, data = derive(
            ctx, papers_root=settings.dirs["papers"], thresholds=thresholds, git_log=self.git_log
        )
        report = PatrolReport(self.name, today, dry_run)
        report.findings = [*desired, *notes]
        report.warnings = list(ctx.warnings)
        report.data.update(data)
        idle = [b for b in desired if not b.closed]
        report.summary = (
            f"{len(data['checked'])} paper(s) checked, {len(idle)} idle, "
            f"{len(notes)} without a datable directory"
        )
        return report


register(PapersPatrol, "papers")
