"""Read-only adapter for the public research knowledge graph and the roster of record.

``projects.jsonld`` is a flat ``@graph`` with ``borg-id:`` IRIs; ``roster.md`` holds markdown
tables of current members grouped by section.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


def _slug(iri: str | None) -> str:
    if not iri:
        return ""
    return iri.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _ids(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, str):
        return [value]
    out: list[str] = []
    for v in value:
        if isinstance(v, dict) and v.get("@id"):
            out.append(str(v["@id"]))
        elif isinstance(v, str):
            out.append(v)
    return out


def _date(value: Any) -> date | None:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    return None


def _year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:4].isdigit():
        return int(value[:4])
    return None


@dataclass
class KgPerson:
    id: str
    slug: str
    name: str
    position: str | None = None
    program: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    thesis_defense_date: date | None = None
    thesis_title: str | None = None
    projects: list[str] = field(default_factory=list)
    orcid: str | None = None

    @property
    def is_current(self) -> bool:
        return bool(self.position) and "current" in (self.position or "").lower()

    @property
    def locator(self) -> str:
        return f"@graph[@id={self.id}]"


@dataclass
class KgProjectNode:
    id: str
    slug: str
    name: str
    start_year: int | None = None
    end_year: int | None = None
    members: list[tuple[str, str | None]] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    publications: list[str] = field(default_factory=list)
    grants: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    abstract: str | None = None


@dataclass
class KgSoftware:
    id: str
    slug: str
    name: str
    repository: str | None = None
    projects: list[str] = field(default_factory=list)


@dataclass
class KgPublication:
    id: str
    slug: str
    name: str
    published: date | None = None


@dataclass
class KgCourse:
    id: str
    slug: str
    name: str
    code: str | None = None
    year: int | None = None
    semester: str | None = None
    role: str | None = None
    program: str | None = None
    instructors: list[str] = field(default_factory=list)


@dataclass
class ResearchKg:
    path: Path
    people: list[KgPerson] = field(default_factory=list)
    projects: list[KgProjectNode] = field(default_factory=list)
    software: list[KgSoftware] = field(default_factory=list)
    publications: list[KgPublication] = field(default_factory=list)
    courses: list[KgCourse] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    publication_count: int = 0

    def person(self, slug: str) -> KgPerson | None:
        for p in self.people:
            if p.slug == slug:
                return p
        return None

    def people_named(self, name: str) -> list[KgPerson]:
        low = name.lower()
        return [p for p in self.people if p.name.lower() == low]


def load_graph(path: Path) -> ResearchKg:
    kg = ResearchKg(path=path)
    if not path.exists():
        return kg
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("@graph", []) if isinstance(data, dict) else data
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("@type")
        types = t if isinstance(t, list) else [t]
        nid = str(n.get("@id", ""))
        if "foaf:Person" in types:
            kg.people.append(
                KgPerson(
                    id=nid,
                    slug=_slug(nid),
                    name=str(n.get("foaf:name") or n.get("schema:name") or _slug(nid)),
                    position=n.get("borg:position"),
                    program=n.get("borg:program"),
                    start_year=_year(n.get("borg:startYear")),
                    end_year=_year(n.get("borg:endYear")),
                    start_date=_date(n.get("borg:startDate")),
                    end_date=_date(n.get("borg:endDate")),
                    thesis_defense_date=_date(n.get("borg:thesisDefenseDate")),
                    thesis_title=n.get("borg:thesisTitle"),
                    projects=_ids(n.get("borg:onProject")),
                    orcid=n.get("borg:orcid"),
                )
            )
        elif "borg:Project" in types:
            members: list[tuple[str, str | None]] = []
            raw_members = n.get("borg:hasMember") or []
            if isinstance(raw_members, dict):
                raw_members = [raw_members]
            for m in raw_members:
                if isinstance(m, dict) and m.get("@id"):
                    members.append((str(m["@id"]), m.get("borg:roleOnProject")))
            kg.projects.append(
                KgProjectNode(
                    id=nid,
                    slug=_slug(nid),
                    name=str(n.get("schema:name") or _slug(nid)),
                    start_year=_year(n.get("borg:startYear")),
                    end_year=_year(n.get("borg:endYear")),
                    members=members,
                    software=_ids(n.get("borg:producedSW")),
                    publications=_ids(n.get("borg:producedPub")),
                    grants=_ids(n.get("borg:fundedBy")),
                    topics=_ids(n.get("borg:topic")),
                    abstract=_text(n.get("schema:abstract") or n.get("schema:description")),
                )
            )
        elif "borg:Topic" in types:
            kg.topics.append(_slug(nid))
        elif "schema:SoftwareApplication" in types:
            kg.software.append(
                KgSoftware(
                    id=nid,
                    slug=_slug(nid),
                    name=str(n.get("schema:name") or _slug(nid)),
                    repository=n.get("schema:codeRepository"),
                    projects=_ids(n.get("borg:fromProject")),
                )
            )
        elif "borg:Course" in types:
            kg.courses.append(
                KgCourse(
                    id=nid,
                    slug=_slug(nid),
                    name=str(n.get("schema:name") or _slug(nid)),
                    code=n.get("borg:courseCode"),
                    year=_year(n.get("borg:year")),
                    semester=n.get("borg:semester"),
                    role=n.get("borg:role"),
                    program=n.get("borg:program"),
                    instructors=_ids(n.get("borg:instructor") or n.get("schema:instructor")),
                )
            )
        elif "schema:ScholarlyArticle" in types:
            kg.publication_count += 1
            kg.publications.append(
                KgPublication(
                    id=nid,
                    slug=_slug(nid),
                    name=str(n.get("schema:name") or _slug(nid)),
                    published=_publication_date(n.get("schema:datePublished")),
                )
            )
    return kg


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _publication_date(value: Any) -> date | None:
    """Return a full date without inventing precision for year-only values."""
    return _date(value)


# --- roster.md ------------------------------------------------------------------

RE_TABLE_ROW = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*`?([a-z0-9-]+)`?\s*\|\s*$")


@dataclass
class RosterEntry:
    name: str
    slug: str
    section: str
    detail: str
    line: int
    path: Path

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}"

    @property
    def is_student(self) -> bool:
        return "student" in self.section.lower()

    @property
    def program(self) -> str | None:
        """Normalise ``PhD, Bioengineering`` to ``PhD-Bioeng`` and ``MS, CS`` to ``MS-CS``."""
        if not self.is_student:
            return None
        d = self.detail.lower()
        if "visiting" in d:
            return "visiting"
        degree = "PhD" if "phd" in d else ("MS" if d.startswith(("ms", "m.s")) else None)
        if degree is None:
            return None
        if "bioeng" in d:
            return f"{degree}-Bioeng"
        if "cs" in d or "computer" in d:
            return f"{degree}-CS"
        if "biosci" in d:
            return f"{degree}-Biosci"
        return degree


def parse_roster(path: Path) -> list[RosterEntry]:
    if not path.exists():
        return []
    entries: list[RosterEntry] = []
    section = ""
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        if raw.startswith("#"):
            continue
        m = RE_TABLE_ROW.match(raw)
        if not m:
            continue
        name = m[1]
        if name.lower() in {"name", "---"} or set(name) <= {"-", " "}:
            continue
        entries.append(
            RosterEntry(name=name, slug=m[3], section=section, detail=m[2], line=i, path=path)
        )
    return entries
