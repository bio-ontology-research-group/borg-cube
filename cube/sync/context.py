"""Lazy, read-only access to every source the derivers and read commands need."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from cube.config import Settings
from cube.sources import calendar as cal
from cube.sources import github as gh
from cube.sources import org, pa_kg
from cube.sources import rkg as rkg_mod


@dataclass
class Person:
    """One row of people.yaml (the join table), nothing more."""

    id: str
    name: str
    role: str
    program: str | None = None
    start: date | None = None
    org_file: str | None = None
    mattermost: str | None = None
    title: str | None = None
    cosupervisor: str | None = None
    source: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else self.id

    @property
    def cockpit_role(self) -> str:
        """people.role -> INTERFACE.md role: phd|msc|postdoc|staff|visitor|pi."""
        p = (self.program or "").lower()
        if self.role == "student":
            if p.startswith("phd"):
                return "phd"
            if p.startswith("ms"):
                return "msc"
            return "visitor"
        if self.role == "postdoc":
            return "postdoc"
        if self.role in {"visiting-faculty", "visitor"}:
            return "visitor"
        if self.role == "pi":
            return "pi"
        return "staff"

    @property
    def is_student(self) -> bool:
        return self.role == "student" and (self.program or "").lower() != "visiting"

    def aliases(self) -> list[str]:
        out = [self.name, self.first_name]
        if self.mattermost:
            out.append(f"@{self.mattermost}")
        return out


@dataclass
class Course:
    """One course offering joined from an Org file and an optional RKG node."""

    code: str
    title: str
    semester: str
    instructor: str | None = None
    lectures: list[org.CourseLecture] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    deadlines: list[org.CourseDeadline] = field(default_factory=list)
    org_path: Path | None = None
    kg_path: Path | None = None
    kg_id: str | None = None

    @property
    def code_key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "", self.code.lower()) or "course"

    @property
    def semester_key(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.semester.lower()).strip("-") or "unspecified"

    @property
    def xid(self) -> str:
        return f"course:{self.code_key}:{self.semester_key}"


def load_people(path: Path) -> tuple[list[Person], list[dict[str, Any]]]:
    if not path.exists():
        return [], []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("people") if isinstance(data, dict) else None
    people: list[Person] = []
    for pid, rec in (rows or {}).items():
        if not isinstance(rec, dict):
            continue
        start = rec.get("start")
        if isinstance(start, str):
            try:
                start = date.fromisoformat(start)
            except ValueError:
                start = None
        known = {
            "name",
            "role",
            "program",
            "start",
            "org_file",
            "mattermost",
            "title",
            "cosupervisor",
            "source",
        }
        people.append(
            Person(
                id=str(pid),
                name=str(rec.get("name") or pid),
                role=str(rec.get("role") or "unknown"),
                program=rec.get("program"),
                start=start if isinstance(start, date) else None,
                org_file=rec.get("org_file"),
                mattermost=rec.get("mattermost"),
                title=rec.get("title"),
                cosupervisor=rec.get("cosupervisor"),
                source=rec.get("source"),
                extra={k: v for k, v in rec.items() if k not in known},
            )
        )
    conflicts = data.get("conflicts") if isinstance(data, dict) else None
    return people, [c for c in (conflicts or []) if isinstance(c, dict)]


def _squash(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


class PeopleIndex:
    def __init__(self, people: list[Person]):
        self.people = people
        self.by_id = {p.id: p for p in people}
        self._by_first: dict[str, list[Person]] = {}
        for p in people:
            self._by_first.setdefault(p.first_name.lower(), []).append(p)

    def get(self, pid: str) -> Person | None:
        return self.by_id.get(pid)

    def by_first_name(self, name: str) -> Person | None:
        """Unique first-name match (tolerates Mohammad/Mohammed)."""
        tokens = name.strip().split()
        if not tokens:
            return None
        first = tokens[0].lower()
        hits = self._by_first.get(first) or [
            p for p in self.people if p.first_name.lower()[:5] == first[:5] and len(first) >= 5
        ]
        if len(hits) > 1 and len(tokens) > 1:
            hits = [p for p in hits if tokens[-1].lower() in p.name.lower()]
        return hits[0] if len(hits) == 1 else None

    def mentioned_in(self, text: str) -> list[Person]:
        low = text.lower()
        hits: list[Person] = []
        for p in self.people:
            if p.name.lower() in low or (p.mattermost and f"@{p.mattermost.lower()}" in low):
                hits.append(p)
                continue
            parts = p.name.split()
            if len(parts) >= 2 and re.search(
                rf"\b{re.escape(parts[0].lower())}\s+{re.escape(parts[-1].lower())}\b", low
            ):
                hits.append(p)
        return hits


class SourceContext:
    """Loads each source at most once; every accessor tolerates a missing file."""

    def __init__(
        self, settings: Settings, today: date | None = None, *, github_details: bool = True
    ):
        self.settings = settings
        self.today = today or date.today()
        self.dirs = settings.dirs
        self.warnings: list[str] = []
        self.github_details = github_details

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"cube sync: {msg}", file=sys.stderr)

    # -- people.yaml ----------------------------------------------------------

    @cached_property
    def _people_loaded(self) -> tuple[list[Person], list[dict[str, Any]]]:
        return load_people(self.settings.root / "people.yaml")

    @property
    def people(self) -> list[Person]:
        return self._people_loaded[0]

    @property
    def conflicts(self) -> list[dict[str, Any]]:
        return self._people_loaded[1]

    @cached_property
    def index(self) -> PeopleIndex:
        return PeopleIndex(self.people)

    # -- ~/org ----------------------------------------------------------------

    @cached_property
    def staff(self) -> list[org.StaffEntry]:
        path = self.dirs["org"] / "staff.org"
        if not path.exists():
            self.warn(f"missing {path}")
            return []
        return org.parse_staff(path)

    def staff_entry(self, person: Person) -> org.StaffEntry | None:
        return org.match_staff_entry(self.staff, person.name)

    @cached_property
    def papers(self) -> list[org.PaperEntry]:
        path = self.dirs["org"] / "papers.org"
        if not path.exists():
            self.warn(f"missing {path}")
            return []
        return org.parse_papers(path)

    def person_notes(self, person: Person) -> org.PersonNotes | None:
        if not person.org_file:
            return None
        path = self.dirs["org"] / person.org_file
        if not path.exists():
            return None
        return org.parse_person_file(path)

    @cached_property
    def course_files(self) -> list[Path]:
        paths = sorted(self.dirs["org"].glob("cs*.org"))
        for path in self.settings.configured_course_files():
            if path not in paths:
                paths.append(path)
        return paths

    @cached_property
    def org_courses(self) -> list[org.CourseEntry]:
        courses: list[org.CourseEntry] = []
        for path in self.course_files:
            if not path.is_file():
                self.warn(f"missing configured course source {path}")
                continue
            try:
                courses.append(org.parse_course(path))
            except OSError as exc:
                self.warn(f"could not read course source {path}: {exc}")
        return courses

    # -- ~/pa -----------------------------------------------------------------

    @cached_property
    def kg_projects(self) -> list[pa_kg.KgProject]:
        return pa_kg.load_projects(self.dirs["pa"] / "kg" / "projects")

    @cached_property
    def deadlines(self) -> list[pa_kg.Deadline]:
        return pa_kg.parse_deadlines(self.dirs["pa"] / "deadlines.md")

    @cached_property
    def contacts(self) -> list[pa_kg.Contact]:
        return pa_kg.load_contacts(self.dirs["pa"] / "contacts")

    def contact_for(self, person: Person) -> pa_kg.Contact | None:
        """Match by slug, then by name ignoring spacing (``Al Ex Example`` is ``Alex Example``)."""
        want = _squash(person.name)
        for c in self.contacts:
            if c.slug == person.id or _squash(c.name) == want:
                return c
        return None

    def person_for_ref(self, ref: str) -> Person | None:
        """Resolve a pa KG member ref (people id or contact slug) to a people.yaml row."""
        p = self.index.get(ref)
        if p is not None:
            return p
        for cand in self.people:
            c = self.contact_for(cand)
            if c is not None and c.slug == ref:
                return cand
        return None

    # -- research KG + roster -------------------------------------------------

    @cached_property
    def rkg(self) -> rkg_mod.ResearchKg:
        return rkg_mod.load_graph(self.dirs["rkg"] / "projects.jsonld")

    @cached_property
    def courses(self) -> list[Course]:
        """Join Org teaching notes to course offerings in the research KG."""
        available = list(self.org_courses)
        offerings: list[Course] = []
        newest_year: dict[str, int] = {}
        for kg_course in self.rkg.courses:
            if kg_course.code and kg_course.year:
                key = _course_code_key(kg_course.code)
                newest_year[key] = max(newest_year.get(key, kg_course.year), kg_course.year)

        for kg_course in self.rkg.courses:
            match = _take_org_course(available, kg_course, newest_year)
            instructors = [_rkg_person_name(self.rkg, ref) for ref in kg_course.instructors]
            instructor = match.instructor if match and match.instructor else None
            if instructor is None:
                instructor = ", ".join(name for name in instructors if name) or None
            semester = (
                match.semester
                if match and match.semester
                else kg_course.semester
                or (str(kg_course.year) if kg_course.year else "unspecified")
            )
            offerings.append(
                Course(
                    code=kg_course.code or (match.code if match else kg_course.slug),
                    title=(match.title if match and match.title else kg_course.name),
                    semester=semester,
                    instructor=instructor,
                    lectures=list(match.lectures) if match else [],
                    materials=list(match.materials) if match else [],
                    deadlines=list(match.deadlines) if match else [],
                    org_path=match.path if match else None,
                    kg_path=self.rkg.path,
                    kg_id=kg_course.id,
                )
            )

        for course in available:
            offerings.append(
                Course(
                    code=course.code,
                    title=course.title or course.code,
                    semester=course.semester or "unspecified",
                    instructor=course.instructor,
                    lectures=list(course.lectures),
                    materials=list(course.materials),
                    deadlines=list(course.deadlines),
                    org_path=course.path,
                )
            )
        return sorted(offerings, key=lambda course: (course.code_key, course.semester_key))

    @cached_property
    def roster(self) -> list[rkg_mod.RosterEntry]:
        return rkg_mod.parse_roster(self.dirs["website"] / "people" / "roster.md")

    # -- GitHub ---------------------------------------------------------------

    @cached_property
    def github(self) -> gh.Snapshot:
        cache = self.settings.state_dir() / "cache" / "github.json"
        src = gh.GitHubSource(cache_path=cache)
        snap = src.snapshot(details=self.github_details)
        for w in snap.warnings:
            self.warn(w)
        return snap

    # -- calendar -------------------------------------------------------------

    @cached_property
    def calendar(self) -> list[cal.Event]:
        return cal.load_calendars(self.dirs["org"])

    def people_aliases(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in self.people:
            if p.id == "robert-hoehndorf":
                continue
            aliases = [p.name]
            c = self.contact_for(p)
            if c:
                aliases.extend(c.emails)
            out[p.id] = aliases
        return out


def _course_code_key(code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", code.lower())


def _semester_matches_year(semester: str | None, year: int | None) -> bool:
    return bool(semester and year and re.search(rf"\b{year}\b", semester))


def _take_org_course(
    available: list[org.CourseEntry],
    kg_course: rkg_mod.KgCourse,
    newest_year: dict[str, int],
) -> org.CourseEntry | None:
    if not kg_course.code:
        return None
    code = _course_code_key(kg_course.code)
    candidates = [course for course in available if _course_code_key(course.code) == code]
    if not candidates:
        return None
    exact = next(
        (
            course
            for course in candidates
            if _semester_matches_year(course.semester, kg_course.year)
        ),
        None,
    )
    if exact is not None:
        available.remove(exact)
        return exact
    undated = next((course for course in candidates if course.semester is None), None)
    if undated is not None and kg_course.year == newest_year.get(code):
        available.remove(undated)
        return undated
    return None


def _rkg_person_name(graph: rkg_mod.ResearchKg, ref: str) -> str:
    person = next((candidate for candidate in graph.people if candidate.id == ref), None)
    return person.name if person else ref.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
