"""Read-only parsers for ~/org: staff.org, papers.org and the per-person note files."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from cube.sources.dates import FuzzyDate, parse_fuzzy_date

DEFAULT_TODO_KEYWORDS = ("TODO", "DONE")
PAPER_TODO_KEYWORDS = (
    "READY_TO_SUBMIT",
    "SUBMITTED",
    "REVISING",
    "PAUSED",
    "TODO",
    "PUBLISHED",
    "CANCELED",
)

RE_HEADING = re.compile(r"^(\*+)\s+(.*?)(?:\s+(:[\w@#%:]+:))?\s*$")
RE_TODO_LINE = re.compile(r"^#\+TODO:\s*(.*)$", re.I)
RE_CLOSED = re.compile(r"CLOSED:\s*\[(\d{4}-\d{2}-\d{2})")
RE_CHECKBOX_OPEN = re.compile(r"^\s*[-+*]\s+\[ \]")
RE_CHECKBOX_DONE = re.compile(r"^\s*[-+*]\s+\[[xX]\]")
RE_PROPERTY = re.compile(r"^\s*:(\w[\w-]*):\s*(.*)$")
RE_DIRECTIVE = re.compile(r"^#\+([\w-]+):\s*(.*?)\s*$", re.I | re.M)
RE_ORG_DATE = re.compile(r"(?:DEADLINE|SCHEDULED):\s*[<[]?(\d{4}-\d{2}-\d{2})", re.I)
RE_ANY_ORG_DATE = re.compile(r"[<[]?(\d{4}-\d{2}-\d{2})(?:\s+\w+)?[>\]]?")
RE_FILE_LINK = re.compile(r"\[\[file:([^\]]+?)(?:\]\[[^\]]*)?\]\]", re.I)


@dataclass
class OrgHeading:
    level: int
    title: str
    line: int
    path: Path
    todo: str | None = None
    tags: list[str] = field(default_factory=list)
    closed: date | None = None
    properties: dict[str, str] = field(default_factory=dict)
    body: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)

    @property
    def outline(self) -> str:
        return " / ".join([*self.parents, self.title])

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line} {'*' * self.level} {self.title}"

    def bullets(self) -> list[str]:
        out: list[str] = []
        for raw in self.body:
            s = raw.strip()
            if s.startswith(("- ", "+ ")):
                out.append(s[2:].strip())
        return out


def parse_todo_keywords(text: str) -> tuple[str, ...]:
    """Extract the ``#+TODO:`` sequence (without the ``|`` separator)."""
    for line in text.splitlines():
        m = RE_TODO_LINE.match(line.strip())
        if m:
            words = [w for w in m[1].split() if w != "|"]
            # drop shortcut keys such as ``TODO(t)``
            return tuple(re.sub(r"\(.*?\)", "", w) for w in words)
    return DEFAULT_TODO_KEYWORDS


def parse_org(text: str, path: Path, keywords: tuple[str, ...] | None = None) -> list[OrgHeading]:
    """Parse org text into a flat list of headings with body lines and outline parents."""
    keywords = keywords or parse_todo_keywords(text)
    headings: list[OrgHeading] = []
    stack: list[OrgHeading] = []
    current: OrgHeading | None = None
    in_properties = False
    for i, raw in enumerate(text.splitlines(), start=1):
        m = RE_HEADING.match(raw)
        if m:
            level = len(m[1])
            title = m[2].strip()
            todo: str | None = None
            first, _, rest = title.partition(" ")
            if first in keywords and rest:
                todo, title = first, rest.strip()
            elif first in keywords and not rest:
                todo, title = first, ""
            tags = [t for t in (m[3] or "").split(":") if t]
            while stack and stack[-1].level >= level:
                stack.pop()
            current = OrgHeading(
                level=level,
                title=title,
                line=i,
                path=path,
                todo=todo,
                tags=tags,
                parents=[h.title for h in stack],
            )
            headings.append(current)
            stack.append(current)
            in_properties = False
            continue
        if current is None:
            continue
        stripped = raw.strip()
        if stripped == ":PROPERTIES:":
            in_properties = True
            continue
        if stripped == ":END:" and in_properties:
            in_properties = False
            continue
        if in_properties:
            pm = RE_PROPERTY.match(raw)
            if pm:
                current.properties[pm[1]] = pm[2].strip()
            continue
        cm = RE_CLOSED.search(raw)
        if cm and current.closed is None:
            current.closed = date.fromisoformat(cm[1])
        current.body.append(raw)
    return headings


def read_org(path: Path) -> list[OrgHeading]:
    return parse_org(path.read_text(encoding="utf-8", errors="replace"), path)


# --- staff.org ----------------------------------------------------------------

# kinds: graduates, proposal_done, proposal, preproposal, start, contract_end, transfer_phd,
# msc_graduates, extended_until
EstimateKind = str

_ESTIMATE_PATTERNS: list[tuple[re.Pattern[str], EstimateKind]] = [
    (re.compile(r"proposal\s+completed", re.I), "proposal_done"),
    (re.compile(r"^pre-?proposal", re.I), "preproposal"),
    (re.compile(r"^proposal", re.I), "proposal"),
    (re.compile(r"^graduates?\s*\(msc\)", re.I), "msc_graduates"),
    (re.compile(r"^graduat", re.I), "graduates"),
    (re.compile(r"^start(ed)?\s+phd", re.I), "start"),
    (re.compile(r"^start(ed)?\s+msc", re.I), "start"),
    (re.compile(r"^start", re.I), "start"),
    (re.compile(r"move\s+to\s+phd", re.I), "transfer_phd"),
    (re.compile(r"(contract\s+)?end\s*(date)?\s*:", re.I), "contract_end"),
    (re.compile(r"extended\s+until", re.I), "extended_until"),
]


@dataclass
class Estimate:
    kind: EstimateKind
    raw: str
    parsed: FuzzyDate | None
    line: int

    @property
    def when(self) -> date | None:
        return None if self.parsed is None else self.parsed.value


@dataclass
class StaffEntry:
    name: str
    section: str
    line: int
    path: Path
    bullets: list[str] = field(default_factory=list)
    estimates: list[Estimate] = field(default_factory=list)

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line} * {self.section} / ** {self.name}"

    def first(self, kind: EstimateKind) -> Estimate | None:
        for e in self.estimates:
            if e.kind == kind:
                return e
        return None


def classify_bullet(text: str) -> EstimateKind | None:
    for pattern, kind in _ESTIMATE_PATTERNS:
        if pattern.search(text):
            return kind
    return None


def parse_staff(path: Path) -> list[StaffEntry]:
    """Return one entry per ``** Name`` heading under ``* Students`` etc."""
    entries: list[StaffEntry] = []
    for h in read_org(path):
        if h.level != 2 or not h.parents:
            continue
        section = h.parents[0]
        entry = StaffEntry(name=h.title, section=section, line=h.line, path=path)
        for i, raw in enumerate(h.body):
            s = raw.strip()
            if not s.startswith("- "):
                continue
            bullet = s[2:].strip()
            entry.bullets.append(bullet)
            kind = classify_bullet(bullet)
            if kind is None:
                continue
            anchor: Literal["start", "end"] = (
                "start" if kind in {"start", "transfer_phd"} else "end"
            )
            fd = parse_fuzzy_date(bullet, month_anchor=anchor)
            entry.estimates.append(Estimate(kind=kind, raw=bullet, parsed=fd, line=h.line + i + 1))
        entries.append(entry)
    return entries


def match_staff_entry(entries: list[StaffEntry], full_name: str) -> StaffEntry | None:
    """Find a staff.org entry for a roster name (first name, or first+last)."""
    tokens = [t.lower() for t in re.split(r"\s+", full_name.strip()) if t]
    if not tokens:
        return None
    first = tokens[0]
    candidates = [e for e in entries if e.name.lower().split()[0] == first]
    if not candidates:
        # tolerate Mohammad/Mohammed style variants
        stem = first[:5]
        candidates = [e for e in entries if e.name.lower().split()[0][:5] == stem]
    if len(candidates) == 1:
        return candidates[0]
    for c in candidates:
        if c.name.lower() == full_name.lower():
            return c
        parts = c.name.lower().split()
        if len(parts) > 1 and parts[-1] in tokens:
            return c
    return None


# --- current group roster ---------------------------------------------------

RE_GROUP_SECTION = re.compile(r"^Group\s+\S+\s+\d{4}$", re.I)
RE_GROUP_BULLET = re.compile(r"^\s*[-+]\s+(.+?)(?:\s+\(([^()]*)\))?\s*$")


@dataclass
class GroupRosterEntry:
    """A name in the maintained current-group list or the Alumni section."""

    name: str
    section: str
    line: int
    path: Path
    role_text: str | None = None
    alumni: bool = False

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class GroupRoster:
    """The newest explicit ``* Group <season> <year>`` roster and Alumni list."""

    path: Path
    section: str | None
    current: list[GroupRosterEntry] = field(default_factory=list)
    alumni: list[GroupRosterEntry] = field(default_factory=list)


def parse_group_roster(path: Path) -> GroupRoster:
    """Parse only the explicit Group section, plus names under ``* Alumni``.

    Milestone headings elsewhere in staff.org deliberately do not count as roster
    membership. This keeps the existing ``parse_staff`` behavior intact.
    """
    result = GroupRoster(path=path, section=None)
    if not path.exists():
        return result
    headings = read_org(path)
    group = next(
        (
            heading
            for heading in headings
            if heading.level == 1 and RE_GROUP_SECTION.match(heading.title)
        ),
        None,
    )
    if group is not None:
        result.section = group.title
        for heading in headings:
            if heading.level != 2 or heading.parents != [group.title]:
                continue
            if heading.title.lower() not in {"staff", "students"}:
                continue
            for offset, raw in enumerate(heading.body, start=1):
                match = RE_GROUP_BULLET.match(raw)
                if match is None:
                    continue
                result.current.append(
                    GroupRosterEntry(
                        name=match[1].strip(),
                        section=heading.title,
                        line=heading.line + offset,
                        path=path,
                        role_text=match[2].strip() if match[2] else None,
                    )
                )
    for heading in headings:
        if heading.level != 2 or not heading.parents:
            continue
        if heading.parents[0].lower() != "alumni":
            continue
        result.alumni.append(
            GroupRosterEntry(
                name=heading.title,
                section="Alumni",
                line=heading.line,
                path=path,
                alumni=True,
            )
        )
    return result


# --- papers.org ---------------------------------------------------------------


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "untitled"


@dataclass
class PaperEntry:
    slug: str
    title: str
    state: str | None
    section: str
    outline: str
    line: int
    path: Path
    level: int
    parent_slug: str | None
    people: list[str]
    tags: list[str]
    closed: date | None
    properties: dict[str, str]
    deadline_text: str | None
    bullets: list[str]

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line} {'*' * self.level} {self.title}"


def parse_papers(path: Path) -> list[PaperEntry]:
    text = path.read_text(encoding="utf-8", errors="replace")
    keywords = parse_todo_keywords(text)
    headings = parse_org(text, path, keywords)
    papers: list[PaperEntry] = []
    slug_by_outline: dict[str, str] = {}
    for h in headings:
        if h.level < 2:
            continue
        bullets = h.bullets()
        people = _people_from_bullets(bullets)
        deadline_text = next((b for b in bullets if b.lower().startswith("deadline")), None)
        slug = slugify(h.title)
        if slug in slug_by_outline.values():
            slug = slugify(" ".join([*h.parents[1:], h.title]))
        slug_by_outline[h.outline] = slug
        parent_slug = None
        if h.level > 2:
            parent_outline = " / ".join(h.parents)
            parent_slug = slug_by_outline.get(parent_outline)
        papers.append(
            PaperEntry(
                slug=slug,
                title=h.title,
                state=h.todo,
                section=h.parents[0] if h.parents else "",
                outline=h.outline,
                line=h.line,
                path=path,
                level=h.level,
                parent_slug=parent_slug,
                people=people,
                tags=h.tags,
                closed=h.closed,
                properties=h.properties,
                deadline_text=deadline_text,
                bullets=bullets,
            )
        )
    return papers


def _people_from_bullets(bullets: list[str]) -> list[str]:
    """papers.org lists people as the first bullet: ``- Alex, Sam`` or ``- Lead: Alex``."""
    for b in bullets[:2]:
        cand = b
        low = cand.lower()
        if low.startswith("lead:"):
            cand = cand.split(":", 1)[1]
        elif low.startswith(("submit", "deadline", "with ", "based", "reviews", "for ")):
            continue
        cand = cand.replace("(", ",").replace(")", ",")
        names = [n.strip(" .") for n in re.split(r"[,;&]|\band\b", cand)]
        names = [n for n in names if n and re.fullmatch(r"[A-Z][\w'-]*(\s+[A-Z][\w'-]*)?", n)]
        if names and len(names) >= max(
            1, len([x for x in re.split(r"[,;&]", cand) if x.strip()]) - 1
        ):
            return names
    return []


# --- course org files -------------------------------------------------------


@dataclass
class CourseLecture:
    number: int
    topic: str
    when: date | None
    materials: list[str]
    line: int
    path: Path
    closed: bool = False

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class CourseDeadline:
    title: str
    when: date
    line: int
    path: Path

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class CourseEntry:
    code: str
    title: str | None
    semester: str | None
    instructor: str | None
    lectures: list[CourseLecture]
    materials: list[str]
    deadlines: list[CourseDeadline]
    path: Path

    @property
    def locator(self) -> str:
        return str(self.path)


def course_code_from_path(path: Path) -> str:
    """Turn names such as ``cs249.org`` into the display code ``CS 249``."""
    stem = path.stem
    match = re.fullmatch(r"([A-Za-z]+)[-_ ]*([0-9]+[A-Za-z]*)", stem)
    if match:
        return f"{match[1].upper()} {match[2].upper()}"
    return stem.replace("_", " ").replace("-", " ").upper()


def parse_course(path: Path) -> CourseEntry:
    """Parse one course Org file without assuming a rigid authoring template."""
    text = path.read_text(encoding="utf-8", errors="replace")
    headings = parse_org(text, path)
    directives = {m[1].upper().replace("-", "_"): m[2].strip() for m in RE_DIRECTIVE.finditer(text)}
    properties: dict[str, str] = {}
    for heading in headings:
        for key, value in heading.properties.items():
            properties.setdefault(key.upper().replace("-", "_"), value)

    def metadata(*names: str) -> str | None:
        for name in names:
            key = name.upper().replace("-", "_")
            value = directives.get(key) or properties.get(key)
            if value:
                return value
        return None

    code = metadata("COURSE_CODE", "COURSE", "CODE") or course_code_from_path(path)
    title = metadata("TITLE", "COURSE_TITLE")
    semester = metadata("SEMESTER", "TERM")
    instructor = metadata("INSTRUCTOR", "LECTURER")
    if semester is None:
        heading_text = "\n".join(heading.title for heading in headings if heading.level == 1)
        match = re.search(r"\b(Fall|Spring|Summer)\s+(20\d{2})\b", heading_text, re.I)
        if match:
            semester = f"{match[1].capitalize()} {match[2]}"
        else:
            year = re.search(r"\b(?:course\s+)?(20\d{2})\b", heading_text, re.I)
            semester = year[1] if year else None

    lectures: list[CourseLecture] = []
    deadlines: list[CourseDeadline] = []
    all_materials = _materials_from_text(text)
    explicit_materials = metadata("MATERIALS", "MATERIAL_PATHS")
    if explicit_materials:
        all_materials = _unique([*_split_materials(explicit_materials), *all_materials])

    for heading in headings:
        prop = {k.upper().replace("-", "_"): v for k, v in heading.properties.items()}
        body_text = "\n".join(heading.body)
        parent_names = {p.strip().lower() for p in heading.parents}
        lecture_match = re.search(r"\b(?:lecture|week|session)\s*#?\s*(\d+)\b", heading.title, re.I)
        is_lecture = bool(
            lecture_match
            or "lecture" in {tag.lower() for tag in heading.tags}
            or parent_names.intersection({"lecture", "lectures", "schedule", "course schedule"})
            or prop.get("TYPE", "").lower() == "lecture"
        )
        is_container = heading.title.strip().lower() in {
            "lecture",
            "lectures",
            "schedule",
            "course schedule",
        }
        if is_lecture and not is_container:
            raw_number = prop.get("NUMBER") or (lecture_match[1] if lecture_match else None)
            number = int(raw_number) if raw_number and raw_number.isdigit() else len(lectures) + 1
            when = _heading_date(heading, body_text, "DATE", "LECTURE_DATE", "SCHEDULED")
            topic = prop.get("TOPIC") or _clean_course_heading(heading.title)
            materials = _unique(
                [
                    *_split_materials(prop.get("MATERIALS", "")),
                    *_materials_from_text(body_text),
                ]
            )
            lectures.append(
                CourseLecture(
                    number=number,
                    topic=topic or f"Lecture {number}",
                    when=when,
                    materials=materials,
                    line=heading.line,
                    path=path,
                    closed=(heading.todo or "").upper()
                    in {"DONE", "CLOSED", "CANCELED", "CANCELLED"},
                )
            )

        deadline_date = _heading_date(heading, body_text, "DEADLINE", require_keyword=True)
        if deadline_date is None and parent_names.intersection({"deadline", "deadlines"}):
            deadline_date = _date_in_text(heading.title)
        if deadline_date is not None and (heading.todo or "").upper() not in {
            "DONE",
            "CLOSED",
            "CANCELED",
            "CANCELLED",
        }:
            deadlines.append(
                CourseDeadline(
                    title=_clean_course_heading(heading.title) or "Course deadline",
                    when=deadline_date,
                    line=heading.line,
                    path=path,
                )
            )

    lectures.sort(key=lambda lecture: (lecture.number, lecture.line))
    deadlines.sort(key=lambda deadline: (deadline.when, deadline.line))
    all_materials = _unique(
        [*all_materials, *(material for lecture in lectures for material in lecture.materials)]
    )
    return CourseEntry(
        code=code,
        title=title,
        semester=semester,
        instructor=instructor,
        lectures=lectures,
        materials=all_materials,
        deadlines=deadlines,
        path=path,
    )


def _heading_date(
    heading: OrgHeading,
    body_text: str,
    *property_names: str,
    require_keyword: bool = False,
) -> date | None:
    prop = {k.upper().replace("-", "_"): v for k, v in heading.properties.items()}
    for name in property_names:
        if value := prop.get(name):
            if parsed := _date_in_text(value):
                return parsed
    date_text = f"{heading.title}\n{body_text}"
    match = (
        re.search(r"DEADLINE:\s*[<[]?(\d{4}-\d{2}-\d{2})", date_text, re.I)
        if require_keyword
        else RE_ORG_DATE.search(date_text)
    )
    if match:
        return date.fromisoformat(match[1])
    if not require_keyword:
        return _date_in_text(heading.title)
    return None


def _date_in_text(text: str) -> date | None:
    match = RE_ANY_ORG_DATE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match[1])
    except ValueError:
        return None


def _clean_course_heading(title: str) -> str:
    clean = RE_ANY_ORG_DATE.sub("", title)
    clean = re.sub(r"\b(?:lecture|week|session)\s*#?\s*\d+\s*[:.-]?\s*", "", clean, flags=re.I)
    return clean.strip(" :-")


def _materials_from_text(text: str) -> list[str]:
    return _unique(match[1].strip() for match in RE_FILE_LINK.finditer(text))


def _split_materials(value: str) -> list[str]:
    if not value.strip():
        return []
    return [part.strip() for part in re.split(r"\s*[,;]\s*", value) if part.strip()]


def _unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        item = str(value)
        if item and item not in out:
            out.append(item)
    return out


# --- per-person org files -----------------------------------------------------


@dataclass
class DatedHeading:
    when: date
    title: str
    line: int
    level: int


@dataclass
class PersonNotes:
    path: Path
    headings: int
    dated: list[DatedHeading]
    open_checkboxes: int
    done_checkboxes: int
    todo_headings: list[str]

    @property
    def last_meeting(self) -> date | None:
        return max((d.when for d in self.dated), default=None)

    def recent(self, n: int = 5) -> list[DatedHeading]:
        return sorted(self.dated, key=lambda d: d.when, reverse=True)[:n]


def parse_person_file(path: Path) -> PersonNotes:
    text = path.read_text(encoding="utf-8", errors="replace")
    headings = parse_org(text, path)
    dated: list[DatedHeading] = []
    todo_headings: list[str] = []
    open_boxes = done_boxes = 0
    for h in headings:
        fd = parse_fuzzy_date(h.title)
        if fd is not None and fd.precision == "day":
            dated.append(DatedHeading(when=fd.value, title=h.title, line=h.line, level=h.level))
        if h.todo and h.todo not in {"DONE", "PUBLISHED", "CANCELED", "CANCELLED"}:
            todo_headings.append(h.title)
        for raw in h.body:
            if RE_CHECKBOX_OPEN.match(raw):
                open_boxes += 1
            elif RE_CHECKBOX_DONE.match(raw):
                done_boxes += 1
    return PersonNotes(
        path=path,
        headings=len(headings),
        dated=dated,
        open_checkboxes=open_boxes,
        done_checkboxes=done_boxes,
        todo_headings=todo_headings,
    )
