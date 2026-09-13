"""``cube projects`` joins the public project KG to dated activity signals."""

from __future__ import annotations

import argparse
import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.commands._common import now_iso, today_from
from cube.config import Settings
from cube.sources.github import GitHubSource, RepoRecord, Snapshot
from cube.sources.org import PaperEntry, parse_papers, slugify
from cube.sources.pa_kg import KgProject, load_projects
from cube.sources.rkg import KgProjectNode, ResearchKg, load_graph
from cube.sync.reconcile import OPEN_STATES, bead_labels, bead_status

_helpers: Helpers | None = None


@dataclass(frozen=True)
class Activity:
    when: datetime
    value: str
    source: str


def _activity(value: str | date | datetime | None, source: str) -> Activity | None:
    if value is None:
        return None
    original = value.isoformat() if isinstance(value, (date, datetime)) else value
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.min, tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
    except ValueError:
        return None
    return Activity(parsed.astimezone(UTC), original, source)


def _latest(items: Iterable[Activity | None]) -> Activity | None:
    present = [item for item in items if item is not None]
    return max(present, key=lambda item: item.when) if present else None


def _tail(ref: str) -> str:
    return ref.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _name_key(value: str) -> str:
    return slugify(value)


def _match_pa(
    project: KgProjectNode, pages: list[KgProject]
) -> tuple[KgProject | None, str | None]:
    direct = [
        page
        for page in pages
        if project.slug == page.slug
        or project.id == page.id
        or project.slug == _tail(page.id or "")
    ]
    if len(direct) == 1:
        return direct[0], None
    names = [
        page
        for page in pages
        if _name_key(project.name) in {_name_key(page.name), *map(_name_key, page.aliases)}
    ]
    if len(names) == 1:
        return names[0], None
    candidates = direct or names
    if len(candidates) > 1:
        return None, f"ambiguous pa KG match for project {project.slug}"
    return None, None


def _paper_activity(
    project: KgProjectNode,
    graph: ResearchKg,
    pa: KgProject | None,
    papers: list[PaperEntry],
) -> Activity | None:
    refs = [*project.publications, *(pa.papers if pa else [])]
    keys = {_tail(ref) for ref in refs}
    names = {
        _name_key(publication.name)
        for publication in graph.publications
        if publication.id in project.publications
    }
    names.update(_name_key(ref) for ref in (pa.papers if pa else []))
    activities: list[Activity | None] = []
    for publication in graph.publications:
        if publication.id in project.publications:
            activities.append(_activity(publication.published, "kg:publication"))
    for paper in papers:
        if paper.slug in keys or _name_key(paper.title) in names:
            activities.append(_activity(_paper_date(paper), "papers.org"))
    return _latest(activities)


def _paper_date(paper: PaperEntry) -> date | None:
    """The state date is normally CLOSED; use an explicit paper date if present."""
    if paper.closed:
        return paper.closed
    for value in [*paper.properties.values(), paper.deadline_text or "", paper.title]:
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", value)
        if match:
            return date.fromisoformat(match[1])
    return None


def _publication_year_activity(refs: Iterable[str], path: Path) -> Activity | None:
    """Use the year-only publication ledger only when papers.org has no dated link."""
    if not path.exists():
        return None
    wanted = {_name_key(ref) for ref in refs}
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                title = row.get("title") or row.get("Title") or ""
                year = row.get("year") or row.get("Year") or ""
                if _name_key(title) in wanted and str(year)[:4].isdigit():
                    return _activity(f"{str(year)[:4]}-12-31", "publications.csv")
    except OSError:
        return None
    return None


def _repo_for_software(graph: ResearchKg, ref: str, repos: list[RepoRecord]) -> RepoRecord | None:
    software = next((item for item in graph.software if item.id == ref), None)
    if software is None or not software.repository:
        return None
    path = urlparse(software.repository).path.strip("/").lower()
    name = path.rsplit("/", 1)[-1]
    return next(
        (repo for repo in repos if repo.full_name.lower() == path or repo.name.lower() == name),
        None,
    )


def _software_activity(
    project: KgProjectNode, graph: ResearchKg, snapshot: Snapshot
) -> Activity | None:
    references = [
        *project.software,
        *(software.id for software in graph.software if project.id in software.projects),
    ]
    return _latest(
        _activity(repo.pushed_at, "github:last-commit")
        for ref in references
        if (repo := _repo_for_software(graph, ref, snapshot.repos)) is not None
    )


def _pa_software_activity(project: KgProject, snapshot: Snapshot) -> Activity | None:
    names: set[str] = set()
    for item in project.software:
        names.add(item.lower())
    return _latest(
        _activity(repo.pushed_at, "github:last-commit")
        for repo in snapshot.repos
        if repo.name.lower() in names or repo.full_name.lower() in names
    )


def _bead_summary(
    project: KgProjectNode, beads: list[dict[str, Any]]
) -> tuple[dict[str, Any], Activity | None]:
    label = f"project:{project.slug}"
    matching = [
        bead for bead in beads if label in bead_labels(bead) and bead_status(bead) in OPEN_STATES
    ]
    activity = _latest(
        _activity(
            str(bead.get("updated_at") or bead.get("created_at") or "") or None,
            "beads:last-activity",
        )
        for bead in matching
    )
    return (
        {
            "open": len(matching),
            "in_progress": sum(bead_status(bead) == "in_progress" for bead in matching),
            "blocked": sum(bead_status(bead) == "blocked" for bead in matching),
            "last_activity": activity.value if activity else None,
        },
        activity,
    )


def _status(project: KgProjectNode, today: date, latest: Activity | None) -> tuple[str, str]:
    if project.end_year is not None and project.end_year < today.year:
        return "ended", "kg:endYear"
    if project.end_year == today.year:
        return "ending", "kg:endYear"
    horizon_is_current = project.end_year is None or project.end_year > today.year
    boundary = datetime.combine(today - timedelta(days=180), time.min, tzinfo=UTC)
    if horizon_is_current and latest is not None and latest.when >= boundary:
        return "active", latest.source
    return "unknown", "no activity in the last 180 days"


def build_project_rows(
    graph: ResearchKg,
    pa_projects: list[KgProject],
    papers: list[PaperEntry],
    snapshot: Snapshot,
    beads: list[dict[str, Any]],
    *,
    today: date,
    publications_csv: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    kg_by_id = {project.id: project for project in graph.projects}
    for pa in pa_projects:
        paper_activity = _paper_activity(
            KgProjectNode(id="", slug=pa.slug, name=pa.name), graph, pa, papers
        )
        if paper_activity is None and publications_csv is not None:
            paper_activity = _publication_year_activity(pa.papers, publications_csv)
        software_activity = _pa_software_activity(pa, snapshot)
        synthetic = KgProjectNode(id=pa.id or "", slug=pa.slug, name=pa.name)
        bead_data, bead_activity = _bead_summary(synthetic, beads)
        pa_activity = _activity(pa.freshness_date(), "pa:project")
        latest = _latest([pa_activity, paper_activity, software_activity, bead_activity])
        linked = [
            {"iri": ref, "slug": node.slug, "name": node.name}
            for ref in pa.public_kg
            if (node := kg_by_id.get(ref)) is not None
        ]
        rows.append(
            {
                "slug": pa.slug,
                "name": pa.name,
                "kind": pa.kind or "project",
                "source": "pa",
                "start_year": pa.start_year,
                "end_year": pa.end_year,
                "status": pa.status or "unknown",
                "status_source": "pa:frontmatter" if pa.status else "no pa status",
                "privacy": "local-only" if pa.private else "internal",
                "abstract": None if pa.private else pa.abstract,
                "members": [member.ref for member in pa.members],
                "member_roles": [{"person": m.ref, "role": m.role} for m in pa.members],
                "lead": next((m.ref for m in pa.members if (m.role or "").lower() == "pi"), None),
                "grants": pa.grants,
                "topics": pa.topics,
                "directories": pa.directories,
                "related": pa.related,
                "public_kg": linked,
                "papers": {
                    "count": len(pa.papers),
                    "last": paper_activity.value if paper_activity else None,
                },
                "software": {
                    "count": len(pa.software),
                    "last_commit": software_activity.value if software_activity else None,
                },
                "beads": bead_data,
                "kg_iri": None,
                "pa_status": pa.status,
                "pa_status_as_of": pa.status_as_of.isoformat() if pa.status_as_of else None,
                "last_activity": latest.value if latest else None,
            }
        )
    for project in graph.projects:
        matched_pa, warning = _match_pa(project, pa_projects)
        if warning:
            warnings.append(warning)
        paper_activity = _paper_activity(project, graph, matched_pa, papers)
        if paper_activity is None and publications_csv is not None:
            paper_activity = _publication_year_activity(
                [
                    publication.name
                    for publication in graph.publications
                    if publication.id in project.publications
                ],
                publications_csv,
            )
        software_activity = _software_activity(project, graph, snapshot)
        bead_data, bead_activity = _bead_summary(project, beads)
        pa_activity = _activity(matched_pa.status_as_of, "pa:status-as-of") if matched_pa else None
        latest = _latest([pa_activity, paper_activity, software_activity, bead_activity])
        status, status_source = _status(project, today, latest)
        members = list(dict.fromkeys(_tail(ref) for ref, _ in project.members))
        lead = next(
            (_tail(ref) for ref, role in project.members if (role or "").lower() == "pi"),
            None,
        )
        rows.append(
            {
                "slug": project.slug,
                "name": project.name,
                "kind": "grant",
                "source": "research-kg",
                "start_year": project.start_year,
                "end_year": project.end_year,
                "status": status,
                "status_source": status_source,
                "members": members,
                "lead": lead,
                "grants": [_tail(ref) for ref in project.grants],
                "topics": [_tail(ref) for ref in project.topics],
                "papers": {
                    "count": len(set(project.publications)),
                    "last": paper_activity.value if paper_activity else None,
                },
                "software": {
                    "count": len(set(project.software)),
                    "last_commit": software_activity.value if software_activity else None,
                },
                "beads": bead_data,
                "kg_iri": project.id,
                "privacy": "public",
                "abstract": None,
                "directories": [],
                "related": [],
                "public_kg": [],
                "pa_status": matched_pa.status if matched_pa else None,
                "pa_status_as_of": (
                    matched_pa.status_as_of.isoformat()
                    if matched_pa and matched_pa.status_as_of
                    else None
                ),
                "last_activity": latest.value if latest else None,
            }
        )
    # The human view starts with active PA work. Grants are then stable by end year.
    rows.sort(
        key=lambda row: (
            0
            if row["source"] == "pa" and row["status"] == "active"
            else (1 if row["source"] == "pa" else 2),
            row["end_year"] is None,
            row["end_year"] or 9999,
            row["name"].lower(),
        )
    )
    return rows, warnings


def projects_summary(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    projects = list(rows)
    return {
        "total": len(projects),
        "active": sum(row["status"] == "active" for row in projects),
        "ending": sum(row["status"] == "ending" for row in projects),
        "ended": sum(row["status"] == "ended" for row in projects),
        "unknown": sum(row["status"] == "unknown" for row in projects),
    }


def _papers(path: Path) -> list[PaperEntry]:
    return parse_papers(path) if path.exists() else []


def attach_runner_profiles(rows: list[dict[str, Any]], settings: Settings) -> None:
    """Add the effective runner profile (cube.yaml projects:) to every project row, in place."""
    for row in rows:
        row["runner_profile"] = settings.runner_profile(str(row.get("slug", "")))


def project_payload(
    settings: Settings,
    helpers: Helpers,
    *,
    today: date,
    cache_only: bool = False,
) -> dict[str, Any]:
    graph_path = settings.dirs["rkg"] / "projects.jsonld"
    graph = load_graph(graph_path)
    github_source = GitHubSource(settings.state_dir() / "cache" / "github.json")
    snapshot = github_source.cached() if cache_only else github_source.snapshot(details=False)
    if snapshot is None:
        snapshot = Snapshot(org=github_source.org, fetched_at="")
    beads_source = helpers.beads(settings, True)
    bead_rows: list[dict[str, Any]] = []
    ledger_warning: str | None = None
    if not beads_source.available():
        ledger_warning = f"bd binary {beads_source.bin!r} not found; no project beads loaded"
    else:
        try:
            bead_rows = beads_source.list_issues("--all")
        except BeadsError as exc:
            ledger_warning = f"bd list failed: {exc}; no project beads loaded"
    rows, warnings = build_project_rows(
        graph,
        load_projects(settings.dirs["pa"] / "kg" / "projects"),
        _papers(settings.dirs["org"] / "papers.org"),
        snapshot,
        bead_rows,
        today=today,
        publications_csv=settings.dirs["rkg"] / "publications.csv",
    )
    attach_runner_profiles(rows, settings)
    if not graph_path.exists():
        warnings.append(f"missing {graph_path}")
    warnings.extend(snapshot.warnings)
    if ledger_warning:
        warnings.append(ledger_warning)
    return {"generated": now_iso(), "projects": rows, "warnings": warnings}


def project_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "LAST ACTIVITY             STATUS   KIND          PROJECT",
        "------------------------- -------- ------------- ----------------------------------------",
    ]
    for row in rows:
        lines.append(
            f"{str(row['last_activity'] or '-')[:25]:25} {row['status']:8} {row['kind'][:13]:13} "
            f"{row['slug']}  {row['name']}"
        )
    return "\n".join(lines)


def cmd_projects(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    payload = project_payload(settings, _helpers, today=today_from(args) or date.today())
    _helpers.emit(args, payload, project_table(payload["projects"]))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    parser = sub.add_parser("projects", help="project portfolio joined to activity signals")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    helpers.add_json(parser)
    parser.set_defaults(fn=cmd_projects)
