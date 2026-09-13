"""Render source-backed standing-agent charters from the research KG."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>{}\[\]]+", re.IGNORECASE)
DOI_URL_RE = re.compile(r"https?://doi\.org/(10\.\d{4,9}/[^\s<>{}\[\]]+)", re.IGNORECASE)
PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b", re.IGNORECASE)
PMCID_RE = re.compile(r"\bPMCID\s*:?\s*(PMC\d+)\b", re.IGNORECASE)
ARXIV_RE = re.compile(r"\barXiv\s*:?\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)


def _get(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _topics(spec: Any) -> list[str]:
    return [str(topic) for topic in (_get(spec, "topics", default=[]) or [])]


def _brief_text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("text", "")
    return str(value or "")


def first_paragraph(markdown: str) -> str:
    """Return the first prose paragraph in a topic brief."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    for block in blocks:
        text = " ".join(line.strip() for line in block.splitlines()).strip()
        if not text or text.startswith("#") or text.startswith("*"):
            continue
        if text.startswith("**Keywords**"):
            continue
        return text
    return ""


def _sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _topic_brief_items(topic_briefs: Any) -> list[tuple[str, str]]:
    if isinstance(topic_briefs, Mapping):
        items: list[Any] = list(topic_briefs.items())
    else:
        items = list(topic_briefs or [])
    result: list[tuple[str, str]] = []
    for item in items or []:
        if isinstance(item, tuple) and len(item) == 2:
            slug, value = item
        elif isinstance(item, Mapping):
            slug, value = item.get("slug", ""), item
        else:
            continue
        result.append((str(slug), _brief_text(value)))
    return result


def _project_items(projects: Any) -> list[Any]:
    if hasattr(projects, "projects"):
        return list(projects.projects)
    return list(projects or [])


def _project_slug(project: Any) -> str:
    slug = _get(project, "slug", default="")
    if slug:
        return str(slug)
    identifier = str(_get(project, "id", "@id", default=""))
    return identifier.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _project_name(project: Any) -> str:
    return str(_get(project, "name", "schema:name", default=_project_slug(project)))


def _project_topics(project: Any) -> set[str]:
    values = _get(project, "topics", "borg:topic", default=[]) or []
    result: set[str] = set()
    for value in values:
        identifier = value.get("@id", "") if isinstance(value, Mapping) else str(value)
        result.add(identifier.rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    return result


def _project_years(project: Any) -> str:
    start = _get(project, "start_year", "borg:startYear")
    end = _get(project, "end_year", "borg:endYear")
    return f"{start or '?'}-{end if end is not None else 'ongoing'}"


def _project_aim(project: Any) -> str | None:
    value = _get(
        project,
        "abstract",
        "aim",
        "aims",
        "description",
        "schema:abstract",
        "schema:description",
    )
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    return str(value).strip() if value and str(value).strip() else None


def _clean_identifier(value: str) -> str:
    return value.rstrip(".,;:)]}")


def identifiers_in_briefs(topic_briefs: Any) -> list[tuple[str, str]]:
    """Extract only identifiers whose syntax is accepted by the local patterns."""
    found: dict[str, str] = {}
    for slug, raw in _topic_brief_items(topic_briefs):
        text = _brief_text(raw)
        matches: list[str] = []
        matches.extend(DOI_URL_RE.findall(text))
        matches.extend(DOI_RE.findall(text))
        matches.extend(f"PMID:{item}" for item in PMID_RE.findall(text))
        matches.extend(PMCID_RE.findall(text))
        matches.extend(f"arXiv:{item}" for item in ARXIV_RE.findall(text))
        for identifier in matches:
            normalized = _clean_identifier(identifier)
            if normalized.lower().startswith("10.") and not re.fullmatch(
                r"10\.\d{4,9}/\S+", normalized
            ):
                continue
            if normalized not in found:
                found[normalized] = slug
    return list(found.items())


def _relevant_projects(projects: Iterable[Any], topics: set[str]) -> list[Any]:
    current_year = date.today().year
    result = []
    for project in projects:
        end = _get(project, "end_year", "borg:endYear")
        if end is not None and int(end) < current_year:
            continue
        if _project_topics(project) & topics:
            result.append(project)
    return sorted(result, key=lambda item: (_project_name(item).lower(), _project_slug(item)))


def render_charter(topic_briefs: Any, projects: Any, spec: Any) -> str:
    """Render a new, reviewable charter from topic briefs and active projects."""
    topics = _topics(spec)
    title = str(_get(spec, "title", default=_get(spec, "name", default="Standing agent")))
    relevant = _relevant_projects(_project_items(projects), set(topics))
    lines = [
        "---",
        "reviewed_by: null",
        "generated_from: research-knowledge-graph",
        f"generated_on: {date.today().isoformat()}",
        "---",
        f"# {title}",
        "",
        "## Mandate",
        "",
    ]
    mandate: list[str] = []
    for slug, raw in _topic_brief_items(topic_briefs):
        if slug not in topics:
            continue
        for sentence in _sentences(first_paragraph(_brief_text(raw))):
            mandate.append(f"{sentence} (rkg: topics/{slug}.md)")
    lines.append(
        " ".join(mandate) or "Work on the declared research topics using source-backed methods."
    )
    lines.extend(
        [
            "",
            "## Active projects",
            "",
        ]
    )
    if relevant:
        for project in relevant:
            lines.append(
                f"- {_project_name(project)} ({_project_years(project)}) "
                f"(rkg: projects.jsonld#{_project_slug(project)})"
            )
    else:
        lines.append("- None recorded for the declared topics.")
    lines.extend(
        [
            "",
            "## May decide alone",
            "",
            "Maintain a source-backed reading record, formulate bounded research suggestions, "
            "and run reversible local experiments within the declared allowance.",
            "",
            "## Needs Robert",
            "",
            "Additional compute, IBEX use, cloud spend, external contact, changes to work "
            "assignments, and any irreversible action.",
            "",
            "## Reading list seed",
            "",
        ]
    )
    identifiers = identifiers_in_briefs(topic_briefs)
    if identifiers:
        lines.extend(f"- {identifier} (rkg: topics/{slug}.md)" for identifier, slug in identifiers)
    else:
        lines.append("No verified-format identifiers are recorded in the topic briefs.")
    lines.extend(["", "## Success in 6 months", ""])
    aims = [(project, _project_aim(project)) for project in relevant]
    aims = [(project, aim) for project, aim in aims if aim]
    if aims:
        project, aim = aims[0]
        source = f"rkg: projects.jsonld#{_project_slug(project)}"
        lines.extend(
            [
                f"- By month 3, define a reproducible baseline that addresses: {aim} ({source}).",
                "- By month 5, produce a source-backed comparison or artefact that tests: "
                f"{aim} ({source}).",
                "- By month 6, record a result and a go or no-go decision against: "
                f"{aim} ({source}).",
            ]
        )
    else:
        lines.append("Robert to define")
    lines.extend(
        [
            "",
            f"Generated from the research knowledge graph on {date.today().isoformat()}; "
            "Robert reviews before the first workday.",
            "",
        ]
    )
    return "\n".join(lines)
