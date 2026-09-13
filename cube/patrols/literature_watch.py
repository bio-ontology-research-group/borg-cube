"""Literature-watch patrol: yesterday's and today's arXiv, bioRxiv and medRxiv submissions.

Deterministic, zero tokens. One paged arXiv query over all categories (Atom API) plus
paged bioRxiv and medRxiv details requests, all through an injectable ``http_get`` so
tests never touch the network. A failed request is retried once after a pause.
New entries are deduped against ``state/literature/seen.json`` (60 day memory), matched
against the configured keywords plus the group's own topic slugs, active project names
and open goal titles, and written to ``state/literature/<date>.jsonl`` for the literature
agent to summarise. A source that fails is a warning, never a crash.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from cube.beads import Beads, BeadsError
from cube.config import LiteratureWatch, Settings
from cube.literature import (
    candidates_path,
    literature_state_dir,
    load_candidates,
    write_candidates,
)
from cube.patrols.base import Finding, PatrolReport, register
from cube.runners.base import HttpGet, default_http_get
from cube.sources.rkg import load_graph

ARXIV_API = "https://export.arxiv.org/api/query"
BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"
MEDRXIV_API = "https://api.biorxiv.org/details/medrxiv"
USER_AGENT = "borg-cube literature-watch (research group reading list; contact Robert Hoehndorf)"
REQUEST_PAUSE_SECONDS = 3.0
RETRY_PAUSE_SECONDS = 10.0
REQUEST_ATTEMPTS = 2
ARXIV_PAGE = 200  # arXiv asks for pages of a few hundred, 3 s apart
DETAILS_PAGE = 100  # the bioRxiv details API fixes its page at 100
SEEN_DAYS = 60
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class FetchError(RuntimeError):
    """One preprint source could not be read; the patrol reports and continues."""


# --- seen ledger -------------------------------------------------------------------------


def seen_path(settings: Settings) -> Path:
    return literature_state_dir(settings) / "seen.json"


def load_seen(settings: Settings) -> dict[str, str]:
    path = seen_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    ids = data.get("ids")
    if not isinstance(ids, dict):
        return {}
    return {str(k): str(v) for k, v in ids.items()}


def prune_seen(ids: dict[str, str], today: date, days: int = SEEN_DAYS) -> dict[str, str]:
    horizon = today - timedelta(days=days)
    out: dict[str, str] = {}
    for key, value in ids.items():
        try:
            seen_on = date.fromisoformat(value)
        except ValueError:
            continue
        if seen_on >= horizon:
            out[key] = value
    return out


def save_seen(settings: Settings, ids: dict[str, str]) -> Path:
    path = seen_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ids": ids}, indent=1, sort_keys=True), encoding="utf-8")
    return path


# --- fetchers ----------------------------------------------------------------------------


def arxiv_query_url(categories: str | Sequence[str], max_results: int, start: int = 0) -> str:
    """One query for every category (``cat:a OR cat:b``), newest first, paged by ``start``.

    Nine sequential per-category calls hit arXiv's rate limit (HTTP 429 and read
    timeouts on 2026-09-08, 0 entries fetched); one OR query pages instead.
    """
    names = [categories] if isinstance(categories, str) else list(categories)
    query = urllib.parse.urlencode(
        {
            "search_query": " OR ".join(f"cat:{name}" for name in names),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": max_results,
        }
    )
    return f"{ARXIV_API}?{query}"


def _text(node: ET.Element | None) -> str:
    return " ".join((node.text or "").split()) if node is not None else ""


def parse_arxiv_atom(payload: bytes) -> list[dict[str, Any]]:
    """Normalise an arXiv Atom response; a malformed feed raises ``FetchError``."""
    try:
        root = ET.fromstring(payload)  # noqa: S314 - fixed, non-hostile API endpoint
    except ET.ParseError as exc:
        raise FetchError(f"arXiv returned malformed Atom: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = _text(entry.find(f"{ATOM}id"))
        if not raw_id:
            continue
        ident = raw_id.rsplit("/abs/", 1)[-1]
        url = raw_id
        for link in entry.findall(f"{ATOM}link"):
            if link.get("rel") == "alternate" and link.get("href"):
                url = str(link.get("href"))
        published = _text(entry.find(f"{ATOM}published"))[:10]
        rows.append(
            {
                "id": f"arxiv:{ident}",
                "source": "arxiv",
                "title": _text(entry.find(f"{ATOM}title")),
                "abstract": _text(entry.find(f"{ATOM}summary")),
                "authors": [
                    _text(author.find(f"{ATOM}name"))
                    for author in entry.findall(f"{ATOM}author")
                    if _text(author.find(f"{ATOM}name"))
                ],
                "categories": [
                    str(cat.get("term"))
                    for cat in entry.findall(f"{ATOM}category")
                    if cat.get("term")
                ],
                "published": published,
                "updated": _text(entry.find(f"{ATOM}updated"))[:10] or published,
                "url": url,
                "doi": _text(entry.find(f"{ARXIV_NS}doi")) or None,
            }
        )
    return rows


def _details_page(payload: bytes, source: str) -> tuple[list[dict[str, Any]], int, int]:
    """The collection of one details page plus the API's ``count`` and ``total``."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{source} returned malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FetchError(f"{source} details response is not an object")
    items = [item for item in data.get("collection") or [] if isinstance(item, dict)]
    messages = data.get("messages") or []
    meta = messages[0] if messages and isinstance(messages[0], dict) else {}
    try:
        count = int(meta.get("count", len(items)))
        total = int(meta.get("total", count))
    except (TypeError, ValueError):
        count, total = len(items), len(items)
    return items, count, total


def parse_biorxiv_details(
    payload: bytes, categories: list[str], source: str = "biorxiv"
) -> list[dict[str, Any]]:
    """Normalise a bioRxiv or medRxiv details response, keeping the configured categories."""
    items, _count, _total = _details_page(payload, source)
    wanted = {c.strip().lower() for c in categories}
    host = "www.medrxiv.org" if source == "medrxiv" else "www.biorxiv.org"
    rows: list[dict[str, Any]] = []
    for item in items:
        category = str(item.get("category") or "").strip()
        if wanted and category.lower() not in wanted:
            continue
        doi = str(item.get("doi") or "")
        if not doi:
            continue
        version = str(item.get("version") or "1")
        authors = [a.strip() for a in str(item.get("authors") or "").split(";") if a.strip()]
        rows.append(
            {
                "id": f"{source}:{doi}",
                "source": source,
                "title": " ".join(str(item.get("title") or "").split()),
                "abstract": " ".join(str(item.get("abstract") or "").split()),
                "authors": authors,
                "categories": [category] if category else [],
                "published": str(item.get("date") or "")[:10],
                "url": f"https://{host}/content/{doi}v{version}",
                "doi": doi,
            }
        )
    return rows


def parse_medrxiv_details(payload: bytes, categories: list[str]) -> list[dict[str, Any]]:
    """medRxiv shares the details API shape; ids and URLs name medRxiv."""
    return parse_biorxiv_details(payload, categories, source="medrxiv")


def _get(http_get: HttpGet, url: str, timeout: float) -> bytes:
    try:
        status, body = http_get(url, {"User-Agent": USER_AGENT}, timeout)
    except OSError as exc:
        raise FetchError(f"{url}: {exc}") from exc
    if status != 200:
        raise FetchError(f"{url}: HTTP {status}")
    return body


def _get_with_retry(
    http_get: HttpGet, url: str, timeout: float, pause: Callable[[float], None]
) -> bytes:
    """One retry after a pause: arXiv answers a burst with 429 and a slow read."""
    for attempt in range(1, REQUEST_ATTEMPTS + 1):
        try:
            return _get(http_get, url, timeout)
        except FetchError:
            if attempt == REQUEST_ATTEMPTS:
                raise
            pause(RETRY_PAUSE_SECONDS)
    raise FetchError(url)  # pragma: no cover - the loop returns or raises


def fetch_arxiv(
    config: LiteratureWatch,
    *,
    http_get: HttpGet,
    timeout: float = 30.0,
    pause: Callable[[float], None] = time.sleep,
    window: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Page the OR query newest first; stop at ``max_per_day`` or once past ``window``."""
    rows: list[dict[str, Any]] = []
    categories = list(config.arxiv.categories)
    if not categories:
        return rows, []
    limit = config.arxiv.max_per_day
    start = 0
    while start < limit:
        page = min(ARXIV_PAGE, limit - start)
        if start:
            pause(REQUEST_PAUSE_SECONDS)
        url = arxiv_query_url(categories, page, start)
        try:
            parsed = parse_arxiv_atom(_get_with_retry(http_get, url, timeout, pause))
        except FetchError as exc:
            return rows, [f"arxiv {', '.join(categories)}: {exc}"]
        rows.extend(parsed)
        if len(parsed) < page:
            break
        oldest = str(parsed[-1].get("updated") or parsed[-1].get("published") or "")
        if window and oldest and oldest < min(window):
            break
        start += page
    return rows, []


def _fetch_details(
    api: str,
    source: str,
    categories: list[str],
    limit: int,
    *,
    since: date,
    until: date,
    http_get: HttpGet,
    timeout: float,
    pause: Callable[[float], None],
) -> tuple[list[dict[str, Any]], list[str]]:
    """The details API pages 100 entries per cursor; one page missed most of a day."""
    rows: list[dict[str, Any]] = []
    cursor = fetched = 0
    while fetched < limit:
        if cursor:
            pause(REQUEST_PAUSE_SECONDS)
        url = f"{api}/{since.isoformat()}/{until.isoformat()}/{cursor}"
        try:
            payload = _get_with_retry(http_get, url, timeout, pause)
            items, count, total = _details_page(payload, source)
            rows.extend(parse_biorxiv_details(payload, categories, source=source))
        except FetchError as exc:
            return rows, [f"{source}: {exc}"]
        fetched += max(count, len(items))
        cursor += max(count, len(items))
        if count < DETAILS_PAGE or cursor >= total or not items:
            break
    return rows[:limit], []


def fetch_biorxiv(
    config: LiteratureWatch,
    *,
    since: date,
    until: date,
    http_get: HttpGet,
    timeout: float = 30.0,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], list[str]]:
    return _fetch_details(
        BIORXIV_API,
        "biorxiv",
        list(config.biorxiv.categories),
        config.biorxiv.max_per_day,
        since=since,
        until=until,
        http_get=http_get,
        timeout=timeout,
        pause=pause,
    )


def fetch_medrxiv(
    config: LiteratureWatch,
    *,
    since: date,
    until: date,
    http_get: HttpGet,
    timeout: float = 30.0,
    pause: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], list[str]]:
    """medRxiv uses the same details API host as bioRxiv, a different path."""
    return _fetch_details(
        MEDRXIV_API,
        "medrxiv",
        list(config.medrxiv.categories),
        config.medrxiv.max_per_day,
        since=since,
        until=until,
        http_get=http_get,
        timeout=timeout,
        pause=pause,
    )


# --- matching ----------------------------------------------------------------------------


def slug_terms(slug: str) -> list[str]:
    """A topic slug matches both verbatim and as the phrase it abbreviates."""
    phrase = slug.replace("-", " ").replace("_", " ").strip()
    return [slug] if phrase == slug else [slug, phrase]


def auto_terms(
    settings: Settings, *, beads: Beads | None = None
) -> tuple[list[str], dict[str, list[str]]]:
    """Topic slugs, active project names and open goal titles, with their sources."""
    terms: list[str] = []
    sources: dict[str, list[str]] = {"topics": [], "projects": [], "goals": []}
    graph = load_graph(settings.dirs["rkg"] / "projects.jsonld")
    for topic in graph.topics:
        sources["topics"].append(topic)
        terms.extend(slug_terms(topic))
    year = date.today().year
    for project in graph.projects:
        if project.end_year is not None and project.end_year < year:
            continue
        if project.name:
            sources["projects"].append(project.name)
            terms.append(project.name)
    if beads is not None and beads.available():
        try:
            from cube.goals import goal_header, read_goal_ledger  # noqa: PLC0415

            goals, _ready, _blocked = read_goal_ledger(beads)
        except (BeadsError, ValueError):
            goals = []
        for goal in goals:
            if goal_header(goal) is None:
                continue
            title = str(goal.get("title") or "").strip()
            if title:
                sources["goals"].append(title)
                terms.append(title)
    return list(dict.fromkeys(t for t in terms if t.strip())), sources


def match_terms(row: dict[str, Any], terms: list[str]) -> list[str]:
    haystack = f"{row.get('title', '')} {row.get('abstract', '')}".lower()
    return [term for term in terms if term.strip() and term.lower() in haystack]


def all_terms(config: LiteratureWatch, auto: list[str]) -> list[str]:
    extra = [term for values in config.per_topic_keywords.values() for term in values]
    return list(dict.fromkeys([*config.keywords, *extra, *auto]))


# --- patrol ------------------------------------------------------------------------------


@dataclass
class LiteratureWatchPatrol:
    name: str = "literature_watch"
    http_get: HttpGet = default_http_get
    pause: Callable[[float], None] = field(default=time.sleep)
    timeout: float = 30.0

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(self.name, today, dry_run)
        config = settings.literature_watch
        yesterday = today - timedelta(days=1)
        window = {yesterday.isoformat(), today.isoformat()}

        arxiv_rows, arxiv_warnings = fetch_arxiv(
            config, http_get=self.http_get, timeout=self.timeout, pause=self.pause, window=window
        )
        biorxiv_rows, biorxiv_warnings = fetch_biorxiv(
            config,
            since=yesterday,
            until=today,
            http_get=self.http_get,
            timeout=self.timeout,
            pause=self.pause,
        )
        medrxiv_rows, medrxiv_warnings = fetch_medrxiv(
            config,
            since=yesterday,
            until=today,
            http_get=self.http_get,
            timeout=self.timeout,
            pause=self.pause,
        )
        report.warnings.extend([*arxiv_warnings, *biorxiv_warnings, *medrxiv_warnings])

        auto, term_sources = auto_terms(settings, beads=beads)
        terms = all_terms(config, auto)
        seen = prune_seen(load_seen(settings), today)

        counts: dict[str, dict[str, int]] = {}
        candidates: list[dict[str, Any]] = []
        fresh_ids: dict[str, str] = {}
        for source, rows in (
            ("arxiv", arxiv_rows),
            ("biorxiv", biorxiv_rows),
            ("medrxiv", medrxiv_rows),
        ):
            fetched = new = matched = 0
            for row in rows:
                fetched += 1
                if row.get("published") and row["published"] not in window:
                    continue
                if row["id"] in seen or row["id"] in fresh_ids:
                    continue
                new += 1
                fresh_ids[row["id"]] = today.isoformat()
                hits = match_terms(row, terms)
                if not hits:
                    continue
                matched += 1
                # Robert, 2026-09-08: each candidate names which of the five
                # research directions it hits, the same matcher as the terms.
                topic_hits = sorted(
                    topic
                    for topic, keywords in config.per_topic_keywords.items()
                    if match_terms(row, keywords)
                )
                candidates.append(
                    {**row, "matched": hits, "topics": topic_hits, "summarised": False}
                )
            counts[source] = {"fetched": fetched, "new": new, "matched": matched}
            report.findings.append(
                Finding(
                    key=f"literature:{source}",
                    title=(
                        f"{source}: {fetched} fetched, {new} new, {matched} matched"
                        + (" (would be written)" if dry_run else "")
                    ),
                    severity="info",
                    source={"arxiv": ARXIV_API, "biorxiv": BIORXIV_API, "medrxiv": MEDRXIV_API}[
                        source
                    ],
                )
            )

        path = candidates_path(settings, today)
        if not dry_run:
            # A second run on the same day (timer plus a manual run) must add to
            # the day's candidates, never replace them with the few not yet seen.
            existing = load_candidates(settings, today)
            known = {str(row.get("id")) for row in existing}
            merged = existing + [row for row in candidates if str(row.get("id")) not in known]
            write_candidates(settings, today, merged)
            save_seen(settings, {**seen, **fresh_ids})
            report.data["candidates_total_today"] = len(merged)

        report.data.update(
            {
                "counts": counts,
                "terms": len(terms),
                "term_sources": {k: len(v) for k, v in term_sources.items()},
                "candidates": len(candidates),
                "path": str(path),
                "cursor": {
                    "candidates": len(candidates),
                    "seen": len(seen) + len(fresh_ids),
                },
            }
        )
        total_fetched = sum(c["fetched"] for c in counts.values())
        report.summary = (
            f"{total_fetched} entries fetched, {len(candidates)} matched candidate(s) "
            f"{'would go' if dry_run else 'written'} to {path.name}"
        )
        return report


register(LiteratureWatchPatrol, "literature_watch")
