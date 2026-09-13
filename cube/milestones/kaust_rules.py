"""KAUST CEMSE milestone calendar as pure functions.

Semesters: Fall starts 25 August, Spring 15 January, Summer 1 June. Only Fall and Spring
count as semesters; the summer session attaches to the preceding Spring.

Rules for cohorts starting Fall 2023 or later: PhD qualifying exam by the end of semester 3,
proposal defense by the end of semester 5, PhD duration 4 years (+1 extension). MS thesis:
4 semesters plus the following summer, thesis application in the first week of semester 3;
MS non-thesis: 3 semesters plus summer. An MS-to-PhD transfer starts a new PhD clock at the
transfer date. Pre-Fall-2023 cohorts: QE within 4 semesters, proposal within 7, 5 years
(+2 extension).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from cube.sources.dates import parse_fuzzy_date

FALL = (8, 25)
SPRING = (1, 15)
SUMMER = (6, 1)
FALL_END = (12, 20)
SPRING_END = (5, 31)
NEW_RULES_FROM = date(2023, 8, 25)

DUE_SOON_DAYS = 90
AT_RISK_DAYS = 30

Term = Literal["fall", "spring", "summer"]
Status = Literal["on_track", "due_soon", "at_risk", "overdue", "done", "unknown"]


TERM_ORDER: dict[str, int] = {"spring": 0, "summer": 1, "fall": 2}


@dataclass(frozen=True)
class Semester:
    """Academic year counter: ``year`` is the calendar year the term starts in."""

    year: int
    term: Term

    def key(self) -> tuple[int, int]:
        return (self.year, TERM_ORDER[self.term])

    def __lt__(self, other: Semester) -> bool:
        return self.key() < other.key()

    def __le__(self, other: Semester) -> bool:
        return self.key() <= other.key()

    def start(self) -> date:
        m, d = {"fall": FALL, "spring": SPRING, "summer": SUMMER}[self.term]
        return date(self.year, m, d)

    def end(self) -> date:
        if self.term == "fall":
            return date(self.year, *FALL_END)
        if self.term == "spring":
            return date(self.year, *SPRING_END)
        return date(self.year, *FALL) - timedelta(days=1)

    def is_main(self) -> bool:
        return self.term != "summer"

    def next_main(self) -> Semester:
        if self.term == "fall":
            return Semester(self.year + 1, "spring")
        return Semester(self.year, "fall")

    @property
    def label(self) -> str:
        return f"{self.term.capitalize()} {self.year}"


def semester_of(day: date) -> Semester:
    if day >= date(day.year, *FALL):
        return Semester(day.year, "fall")
    if day >= date(day.year, *SUMMER):
        return Semester(day.year, "summer")
    if day >= date(day.year, *SPRING):
        return Semester(day.year, "spring")
    return Semester(day.year - 1, "fall")


def first_semester(start: date) -> Semester:
    """The first counted semester for a start date.

    A start in the summer or in the winter break (after the Fall teaching end) counts from
    the next main semester, so a 1 January contract start is Spring.
    """
    sem = semester_of(start)
    if not sem.is_main():
        return Semester(sem.year, "fall")
    if start > sem.end():
        return sem.next_main()
    return sem


def nth_semester(start: date, n: int) -> Semester:
    """The n-th main semester (1-based) of a program that starts on ``start``."""
    sem = first_semester(start)
    for _ in range(max(0, n - 1)):
        sem = sem.next_main()
    return sem


def semester_index(start: date, day: date) -> int:
    """How many main semesters have begun for a program started on ``start`` as of ``day``.

    1 during the first semester; 0 before it. Summer counts with the preceding Spring.
    """
    first = first_semester(start)
    current = semester_of(day)
    if not current.is_main():
        current = Semester(current.year, "spring")
    if current < first:
        return 0
    n = 1
    sem = first
    while sem < current:
        sem = sem.next_main()
        n += 1
    return n


def uses_new_rules(start: date) -> bool:
    return start >= NEW_RULES_FROM


# --- milestones -----------------------------------------------------------------


@dataclass
class Milestone:
    name: str
    due: date | None
    status: Status
    source: str
    rule: str
    person: str | None = None
    done_on: date | None = None
    estimate: date | None = None
    estimate_source: str | None = None
    order: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")

    def days(self, today: date) -> int | None:
        return None if self.due is None else (self.due - today).days

    def as_dict(self, today: date | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "due": self.due.isoformat() if self.due else None,
            "status": self.status,
            "source": self.source,
            "rule": self.rule,
            "done_on": self.done_on.isoformat() if self.done_on else None,
            "estimate": self.estimate.isoformat() if self.estimate else None,
            "estimate_source": self.estimate_source,
            "notes": list(self.notes),
        }
        if today is not None:
            d["days"] = self.days(today)
        return d


def status_for(due: date | None, today: date, done: bool = False) -> Status:
    if done:
        return "done"
    if due is None:
        return "unknown"
    delta = (due - today).days
    if delta < 0:
        return "overdue"
    if delta <= AT_RISK_DAYS:
        return "at_risk"
    if delta <= DUE_SOON_DAYS:
        return "due_soon"
    return "on_track"


def _rule_milestones_phd(start: date) -> list[tuple[str, date, str]]:
    new = uses_new_rules(start)
    qe_sem, prop_sem, years, ext = (3, 5, 4, 1) if new else (4, 7, 5, 2)
    cohort = "cohort >= Fall 2023" if new else "cohort < Fall 2023"
    defense = _add_years(start, years)
    return [
        (
            "qualifying exam",
            nth_semester(start, qe_sem).end(),
            f"QE by end of semester {qe_sem} ({cohort})",
        ),
        (
            "proposal defense",
            nth_semester(start, prop_sem).end(),
            f"proposal by end of semester {prop_sem} ({cohort})",
        ),
        ("dissertation defense", defense, f"PhD duration {years} years ({cohort})"),
        ("extension limit", _add_years(start, years + ext), f"+{ext} year extension ({cohort})"),
    ]


def _rule_milestones_ms(start: date, thesis: bool = True) -> list[tuple[str, date, str]]:
    if thesis:
        app = nth_semester(start, 3).start() + timedelta(days=7)
        last = nth_semester(start, 4)
        end = Semester(last.year, "summer").end() if last.term == "spring" else last.end()
        return [
            ("thesis application", app, "MS thesis: application in first week of semester 3"),
            ("thesis defense", end, "MS thesis: 4 semesters + summer"),
        ]
    last = nth_semester(start, 3)
    end = Semester(last.year, "summer").end() if last.term == "spring" else last.end()
    return [("degree completion", end, "MS non-thesis: 3 semesters + summer")]


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def _to_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        fd = parse_fuzzy_date(value)
        return fd.value if fd else None
    return None


# staff.org estimate kinds -> (milestone name, marks it done), per program kind
ESTIMATE_TO_MILESTONE: dict[str, dict[str, tuple[str, bool]]] = {
    "phd": {
        "preproposal": ("qualifying exam", False),
        "proposal": ("proposal defense", False),
        "proposal_done": ("proposal defense", True),
        "graduates": ("dissertation defense", False),
    },
    "ms": {
        "graduates": ("thesis defense", False),
        "msc_graduates": ("thesis defense", False),
    },
}


def program_kind(program: str | None) -> Literal["phd", "ms", "none"]:
    p = (program or "").lower()
    if p.startswith("phd"):
        return "phd"
    if p.startswith(("ms", "msc", "m.s")):
        return "ms"
    return "none"


def plan_for(
    person: dict[str, Any],
    today: date,
    estimates: list[dict[str, Any]] | None = None,
) -> list[Milestone]:
    """Milestones for one person.

    ``person`` needs ``id``, ``program`` (``PhD-Bioeng``, ``MS-CS``, ``visiting``), optional
    ``start`` (date or text) and ``thesis`` (bool, MS only, default True). ``estimates`` are
    staff.org bullets as ``{kind, date, raw, source}`` with kinds from
    ``cube.sources.org`` (preproposal, proposal, proposal_done, graduates, msc_graduates,
    start, transfer_phd). A ``proposal_done`` estimate marks the proposal done; other
    estimates are attached as provenance and, when no start date is known, become the due
    date themselves (source staff.org).
    """
    pid = str(person.get("id") or person.get("slug") or "")
    kind = program_kind(person.get("program"))
    estimates = estimates or []
    start = _to_date(person.get("start"))
    if start is None:
        for e in estimates:
            if e.get("kind") in {"transfer_phd" if kind == "phd" else "start", "start"}:
                start = _to_date(e.get("date"))
                if start:
                    break
    if kind == "none":
        return []
    rule_rows = (
        _rule_milestones_phd(start)
        if kind == "phd" and start
        else _rule_milestones_ms(start, bool(person.get("thesis", True)))
        if kind == "ms" and start
        else []
    )
    by_name: dict[str, Milestone] = {}
    for i, (name, due, rule) in enumerate(rule_rows):
        by_name[name] = Milestone(
            name=name,
            due=due,
            status=status_for(due, today),
            source="kaust_rules",
            rule=rule,
            person=pid,
            order=i,
        )
    mapping = ESTIMATE_TO_MILESTONE.get(kind, {})
    for e in estimates:
        mapped = mapping.get(str(e.get("kind")))
        if mapped is None:
            continue
        name, done = mapped
        when = _to_date(e.get("date"))
        src = str(e.get("source") or "staff.org")
        ms = by_name.get(name)
        if ms is None:
            ms = Milestone(
                name=name,
                due=when,
                status=status_for(when, today),
                source=src,
                rule=f"estimate from {src}: {e.get('raw', '')}".strip(),
                person=pid,
                order=len(by_name) + 10,
            )
            by_name[name] = ms
        ms.estimate = when
        ms.estimate_source = f"{src}: {e.get('raw', '')}".strip()
        if done:
            ms.status = "done"
            ms.done_on = when
        elif when and when < today and ms.status != "done":
            # the planned date has passed and nobody recorded the outcome: do not guess
            ms.status = "unknown"
            ms.notes.append(
                f"staff.org planned {when.isoformat()}; outcome not recorded, verify with Robert"
            )
        if done or ms.status == "unknown":
            pass
        elif ms.due and when and when > ms.due:
            ms.notes.append(
                f"estimate {when.isoformat()} is later than rule due {ms.due.isoformat()}"
            )
        elif ms.due and when and when < ms.due:
            ms.notes.append(
                f"estimate {when.isoformat()} is earlier than rule due {ms.due.isoformat()}"
            )
    # an accepted proposal implies the QE was passed
    prop = by_name.get("proposal defense")
    qe = by_name.get("qualifying exam")
    if prop and prop.status == "done" and qe and qe.status != "done":
        qe.status = "done"
        qe.done_on = qe.done_on or prop.done_on
        qe.notes.append("implied by completed proposal")
    if start is None and rule_rows == [] and by_name:
        for ms in by_name.values():
            ms.notes.append("no start date known; due taken from estimate only")
    return sorted(by_name.values(), key=lambda m: (m.due or date.max, m.order))


def next_open(milestones: list[Milestone]) -> Milestone | None:
    open_ms = [m for m in milestones if m.status not in {"done", "unknown"} and m.due]
    return min(open_ms, key=lambda m: m.due or date.max) if open_ms else None
