"""Read-only adapter for ~/pa: kg/projects/*.md, deadlines.md and contacts/*.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

RE_STATUS_AS_OF = re.compile(r"status\s+as\s+of\s+(\d{4}-\d{2}-\d{2})", re.I)
RE_DEADLINE = re.compile(
    r"^-\s+(\d{4}-\d{2}-\d{2})\s+-\s+(.*?)\s*"
    r"(?:\[status:\s*(\w+)\])?\s*(?:\[pa:([0-9a-f]{6,12})\])?\s*$"
)
RE_STATUS_TAG = re.compile(r"\[status:\s*(\w+)\]")
RE_PA_TAG = re.compile(r"\[pa:([0-9a-f]{6,12})\]")
RE_MM_HANDLE = re.compile(r"mattermost[^`@\n]*[`@]+@?([A-Za-z0-9_.-]+)", re.I)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, body). Missing or malformed frontmatter gives ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    try:
        data = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, "\n".join(lines[end + 1 :])


# --- kg/projects --------------------------------------------------------------


@dataclass
class Member:
    ref: str
    ref_kind: str  # person | contact
    role: str | None = None
    public: str | None = None


@dataclass
class KgProject:
    slug: str
    path: Path
    id: str | None
    name: str
    aliases: list[str] = field(default_factory=list)
    kind: str | None = None
    status: str | None = None
    private: bool = False
    start_year: int | None = None
    end_year: int | None = None
    abstract: str | None = None
    members: list[Member] = field(default_factory=list)
    papers: list[str] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    directories: list[dict[str, Any]] = field(default_factory=list)
    grants: list[Any] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    public_kg: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    status_as_of: date | None = None
    modified: date | None = None

    @property
    def locator(self) -> str:
        return f"{self.path}: frontmatter"

    def member_refs(self) -> list[str]:
        return [m.ref for m in self.members]

    def freshness_date(self) -> date | None:
        """Latest 'Status as of' heading, else the file's modification date."""
        return self.status_as_of or self.modified


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict):
                for key in ("id", "path", "name", "slug"):
                    if isinstance(v.get(key), str):
                        out.append(str(v[key]))
                        break
        return out
    return [str(value)]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value[:4].isdigit():
        return int(value[:4])
    return None


def parse_project(path: Path) -> KgProject:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(text)
    members: list[Member] = []
    for raw in fm.get("members") or []:
        if not isinstance(raw, dict):
            continue
        if raw.get("person"):
            members.append(Member(str(raw["person"]), "person", raw.get("role"), raw.get("public")))
        elif raw.get("contact"):
            members.append(
                Member(str(raw["contact"]), "contact", raw.get("role"), raw.get("public"))
            )
    status_dates = [date.fromisoformat(m[1]) for m in RE_STATUS_AS_OF.finditer(body)]
    try:
        modified: date | None = datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        modified = None
    return KgProject(
        slug=path.stem,
        path=path,
        id=fm.get("id"),
        name=str(fm.get("name") or path.stem),
        aliases=_as_str_list(fm.get("aliases")),
        kind=fm.get("kind"),
        status=fm.get("status"),
        private=bool(fm.get("private", False)),
        start_year=_year(fm.get("startYear")),
        end_year=_year(fm.get("endYear")),
        abstract=str(fm["abstract"]) if fm.get("abstract") else None,
        members=members,
        papers=_as_str_list(fm.get("papers")),
        software=_as_str_list(fm.get("software")),
        directories=[d for d in (fm.get("directories") or []) if isinstance(d, dict)],
        grants=_as_list(fm.get("grants")),
        topics=_as_str_list(fm.get("topics")),
        public_kg=_as_str_list(fm.get("public_kg")),
        related=_as_str_list(fm.get("related")),
        status_as_of=max(status_dates) if status_dates else None,
        modified=modified,
    )


def load_projects(projects_dir: Path) -> list[KgProject]:
    if not projects_dir.is_dir():
        return []
    return [parse_project(p) for p in sorted(projects_dir.glob("*.md"))]


# --- deadlines.md -------------------------------------------------------------


@dataclass
class Deadline:
    when: date
    text: str
    status: str
    pa_id: str | None
    line: int
    path: Path
    section: str | None = None

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}"

    @property
    def xid(self) -> str:
        if self.pa_id:
            return f"pa:{self.pa_id}"
        import hashlib

        digest = hashlib.sha1(f"{self.when}|{self.text}".encode()).hexdigest()[:8]
        return f"pa:deadline:{self.when.isoformat()}:{digest}"

    @property
    def is_open(self) -> bool:
        return self.status == "open"


def parse_deadlines(path: Path) -> list[Deadline]:
    if not path.exists():
        return []
    out: list[Deadline] = []
    section: str | None = None
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if raw.startswith("#"):
            section = raw.lstrip("#").strip()
            continue
        if not raw.startswith("- "):
            continue
        m = re.match(r"^-\s+(\d{4}-\d{2}-\d{2})\s*-\s*(.*)$", raw)
        if not m:
            continue
        try:
            when = date.fromisoformat(m[1])
        except ValueError:
            continue
        rest = m[2]
        st = RE_STATUS_TAG.search(rest)
        pa = RE_PA_TAG.search(rest)
        status = st[1].lower() if st else "open"
        text = RE_PA_TAG.sub("", RE_STATUS_TAG.sub("", rest)).strip()
        out.append(
            Deadline(
                when=when,
                text=text,
                status=status,
                pa_id=pa[1] if pa else None,
                line=i,
                path=path,
                section=section,
            )
        )
    return out


# --- contacts -----------------------------------------------------------------


@dataclass
class Contact:
    slug: str
    name: str
    path: Path
    emails: list[str] = field(default_factory=list)
    mattermost: str | None = None
    org: str | None = None

    @property
    def locator(self) -> str:
        return f"{self.path}: frontmatter"


def parse_contact(path: Path) -> Contact:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(text)
    handle = fm.get("mattermost")
    if not handle:
        m = RE_MM_HANDLE.search(body)
        handle = m[1] if m else None
    return Contact(
        slug=path.stem,
        name=str(fm.get("name") or path.stem.replace("-", " ").title()),
        path=path,
        emails=_as_str_list(fm.get("emails") or fm.get("email")),
        mattermost=str(handle).lstrip("@") if handle else None,
        org=fm.get("org"),
    )


def load_contacts(contacts_dir: Path) -> list[Contact]:
    if not contacts_dir.is_dir():
        return []
    return [parse_contact(p) for p in sorted(contacts_dir.glob("*.md"))]
