"""Turn source records into DesiredBead lists. Pure with respect to bd; reads via context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from cube.milestones import kaust_rules as kr
from cube.model import BeadHeader, Privacy, Provenance, WorkKind
from cube.sources import calendar as cal
from cube.sources import github as gh
from cube.sync.context import Person, SourceContext

KG_STALE_DAYS = 21
REPO_STALE_DAYS = 180

PAPER_WORDS = (
    "paper",
    "manuscript",
    "preprint",
    "camera-ready",
    "camera ready",
    "proofs",
    "revision",
    "resubmi",
    "submission",
    "abstract due",
)


class DesiredBead(BaseModel):
    xid: str
    title: str
    kind: WorkKind
    type_: str = "task"
    labels: list[str] = Field(default_factory=list)
    parent_xid: str | None = None
    deps: list[str] = Field(default_factory=list)  # xids that block this bead
    header: BeadHeader
    body: str = ""
    priority: int = 2
    closed: bool = False
    close_reason: str | None = None

    def all_labels(self) -> list[str]:
        base = [f"kind:{self.kind.value}", f"privacy:{self.header.privacy.value}"]
        out: list[str] = []
        for lab in [*base, *self.labels]:
            if lab not in out:
                out.append(lab)
        return out


def _prov(source: str, locator: str | None, today: Any) -> Provenance:
    return Provenance(source=source, locator=locator, seen=today)


def _person_labels(p: Person) -> list[str]:
    return [f"person:{p.id}"]


# --- courses -----------------------------------------------------------------------


def derive_courses(ctx: SourceContext) -> list[DesiredBead]:
    """Project course offerings and their lectures into stable desired beads."""
    out: list[DesiredBead] = []
    for course in ctx.courses:
        provenance: list[Provenance] = []
        source_labels: list[str] = []
        if course.org_path is not None:
            provenance.append(_prov(str(course.org_path), str(course.org_path), ctx.today))
            source_labels.append("src:course-org")
        if course.kg_path is not None:
            provenance.append(_prov(str(course.kg_path), course.kg_id, ctx.today))
            source_labels.append("src:rkg")
        dates = [lecture.when for lecture in course.lectures if lecture.when]
        dates.extend(deadline.when for deadline in course.deadlines)
        body = [f"Code: {course.code}", f"Semester: {course.semester}"]
        if course.instructor:
            body.append(f"Instructor: {course.instructor}")
        if course.materials:
            body.append("Materials: " + ", ".join(course.materials))
        out.append(
            DesiredBead(
                xid=course.xid,
                title=f"Course {course.code}: {course.title} ({course.semester})",
                kind=WorkKind.course,
                type_="epic",
                labels=[f"course:{course.code_key}", *source_labels, "role:lecturer"],
                header=BeadHeader(
                    xid=course.xid,
                    provenance=provenance,
                    deadline=max(dates) if dates else None,
                ),
                body="\n".join(body),
                priority=2,
            )
        )
        for lecture in course.lectures:
            xid = f"lecture:{course.code_key}:{course.semester_key}:{lecture.number}"
            lecture_body = [f"Course: {course.title}", f"Topic: {lecture.topic}"]
            if lecture.materials:
                lecture_body.append("Materials: " + ", ".join(lecture.materials))
            out.append(
                DesiredBead(
                    xid=xid,
                    title=f"Lecture {lecture.number}: {lecture.topic} ({course.code})",
                    kind=WorkKind.lecture,
                    labels=[f"course:{course.code_key}", "src:course-org", "role:lecturer"],
                    parent_xid=course.xid,
                    header=BeadHeader(
                        xid=xid,
                        provenance=[_prov(str(lecture.path), lecture.locator, ctx.today)],
                        deadline=lecture.when,
                    ),
                    body="\n".join(lecture_body),
                    priority=2,
                    closed=lecture.closed,
                    close_reason="course Org state done" if lecture.closed else None,
                )
            )
    return out


# --- people + milestones ------------------------------------------------------------


def _estimates_for(ctx: SourceContext, person: Person) -> tuple[list[dict[str, Any]], str | None]:
    entry = ctx.staff_entry(person)
    if entry is None:
        return [], None
    rows = [
        {"kind": e.kind, "date": e.when, "raw": e.raw, "source": "staff.org", "line": e.line}
        for e in entry.estimates
    ]
    return rows, entry.locator


def milestones_for(ctx: SourceContext, person: Person) -> list[kr.Milestone]:
    estimates, _ = _estimates_for(ctx, person)
    return kr.plan_for(
        {"id": person.id, "program": person.program, "start": person.start}, ctx.today, estimates
    )


def derive_programs(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    people_path = str(ctx.settings.root / "people.yaml")
    for p in ctx.people:
        if not p.is_student:
            continue
        estimates, staff_locator = _estimates_for(ctx, p)
        milestones = kr.plan_for(
            {"id": p.id, "program": p.program, "start": p.start}, ctx.today, estimates
        )
        prov = [_prov(people_path, f"people.{p.id}", ctx.today)]
        if staff_locator:
            prov.append(_prov(str(ctx.dirs["org"] / "staff.org"), staff_locator, ctx.today))
        roster_hit = next((r for r in ctx.roster if r.slug == p.id or r.name == p.name), None)
        if roster_hit:
            prov.append(_prov(str(roster_hit.path), roster_hit.locator, ctx.today))
        degree = "PhD" if kr.program_kind(p.program) == "phd" else "MS"
        program_xid = f"program:{p.id}"
        final_name = "dissertation defense" if degree == "PhD" else "thesis defense"
        final = next((m for m in milestones if m.name == final_name), None)
        body_lines = [
            f"Program: {p.program}",
            f"Start: {p.start.isoformat() if p.start else 'unknown'}",
            f"Source: {p.source or 'people.yaml'}",
        ]
        if not p.start:
            body_lines.append(
                "No start date in people.yaml; milestones come from staff.org estimates only."
            )
        out.append(
            DesiredBead(
                xid=program_xid,
                title=f"{degree} program: {p.name}",
                kind=WorkKind.program,
                type_="epic",
                labels=[*_person_labels(p), "src:people.yaml", "src:staff.org"],
                header=BeadHeader(
                    xid=program_xid, provenance=prov, deadline=final.due if final else None
                ),
                body="\n".join(body_lines),
                priority=2,
            )
        )
        prev_xid: str | None = None
        for m in milestones:
            xid = f"milestone:{p.id}:{m.slug}"
            m_prov = [_prov("cube.milestones.kaust_rules", m.rule, ctx.today)]
            if m.estimate_source and staff_locator:
                m_prov.append(
                    _prov(
                        str(ctx.dirs["org"] / "staff.org"),
                        f"{staff_locator}: {m.estimate_source}",
                        ctx.today,
                    )
                )
            body = [f"Rule: {m.rule}", f"Status: {m.status}"]
            if m.estimate:
                body.append(f"staff.org estimate: {m.estimate.isoformat()} ({m.estimate_source})")
            body.extend(m.notes)
            out.append(
                DesiredBead(
                    xid=xid,
                    title=f"{m.name.capitalize()}: {p.name}",
                    kind=WorkKind.milestone,
                    labels=[
                        *_person_labels(p),
                        f"milestone:{m.slug}",
                        f"status:{m.status}",
                        "src:staff.org",
                    ],
                    parent_xid=program_xid,
                    deps=[prev_xid] if prev_xid else [],
                    header=BeadHeader(xid=xid, provenance=m_prov, deadline=m.due),
                    body="\n".join(body),
                    priority=1 if m.status in {"overdue", "at_risk"} else 2,
                    closed=m.status == "done",
                    close_reason=f"done on {m.done_on}"
                    if m.done_on
                    else ("done" if m.status == "done" else None),
                )
            )
            prev_xid = xid
            if m.estimate and m.due and m.estimate > m.due and m.status != "done":
                cx = f"conflict:{p.id}:milestone-{m.slug}"
                out.append(
                    DesiredBead(
                        xid=cx,
                        title=(
                            f"Conflict: {p.name} {m.name} estimate {m.estimate} "
                            f"vs KAUST rule {m.due}"
                        ),
                        kind=WorkKind.conflict,
                        labels=[
                            *_person_labels(p),
                            "needs:robert",
                            "src:staff.org",
                            "src:kaust_rules",
                        ],
                        header=BeadHeader(xid=cx, provenance=m_prov),
                        body=(
                            f"staff.org plans {m.name} for {m.estimate}; the KAUST rule "
                            f"({m.rule}) requires it by {m.due}."
                        ),
                        priority=1,
                    )
                )
    return out


# --- deadlines.md -------------------------------------------------------------------


def derive_deadlines(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    for d in ctx.deadlines:
        low = d.text.lower()
        kind = WorkKind.paper if any(w in low for w in PAPER_WORDS) else WorkKind.service
        labels = ["src:deadlines.md"]
        for p in ctx.index.mentioned_in(d.text):
            labels.append(f"person:{p.id}")
        title = d.text if len(d.text) <= 120 else d.text[:117].rstrip() + "..."
        out.append(
            DesiredBead(
                xid=d.xid,
                title=title,
                kind=kind,
                labels=labels,
                header=BeadHeader(
                    xid=d.xid,
                    provenance=[_prov(str(d.path), d.locator, ctx.today)],
                    deadline=d.when,
                ),
                body=d.text,
                priority=1 if d.when <= ctx.today + timedelta(days=7) else 2,
                closed=not d.is_open,
                close_reason=f"deadlines.md status {d.status}" if not d.is_open else None,
            )
        )
    return out


# --- papers.org ---------------------------------------------------------------------

PAPER_CLOSED_STATES = {"PUBLISHED", "CANCELED", "CANCELLED", "DONE"}


def derive_papers(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    for paper in ctx.papers:
        xid = f"paper:{paper.slug}"
        labels = ["src:papers.org", f"paper-state:{(paper.state or 'none').lower()}"]
        for name in paper.people:
            p = ctx.index.by_first_name(name)
            if p:
                labels.append(f"person:{p.id}")
        for tag in paper.tags:
            labels.append(f"tag:{tag}")
        body = [f"Outline: {paper.outline}"]
        if paper.people:
            body.append("People: " + ", ".join(paper.people))
        if paper.deadline_text:
            body.append(paper.deadline_text)
        title = f"{paper.title}" if paper.state is None else f"[{paper.state}] {paper.title}"
        out.append(
            DesiredBead(
                xid=xid,
                title=title,
                kind=WorkKind.paper,
                type_="epic",
                labels=labels,
                parent_xid=f"paper:{paper.parent_slug}" if paper.parent_slug else None,
                header=BeadHeader(
                    xid=xid, provenance=[_prov(str(paper.path), paper.locator, ctx.today)]
                ),
                body="\n".join(body),
                priority=2 if paper.state in {"READY_TO_SUBMIT", "REVISING"} else 3,
                closed=(paper.state or "") in PAPER_CLOSED_STATES,
                close_reason=f"papers.org state {paper.state}"
                if paper.state in PAPER_CLOSED_STATES
                else None,
            )
        )
    return out


# --- pa KG freshness ----------------------------------------------------------------


def derive_kg_stale(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    for proj in ctx.kg_projects:
        if (proj.status or "active").lower() not in {"active", "ongoing"}:
            continue
        fresh = proj.freshness_date()
        age = (ctx.today - fresh).days if fresh else None
        if age is not None and age <= KG_STALE_DAYS:
            continue
        xid = f"finding:kg-stale:{proj.slug}"
        labels = ["src:pa/kg", f"project:{proj.slug}"]
        for m in proj.members:
            p = ctx.person_for_ref(m.ref)
            if p and p.id != "robert-hoehndorf" and f"person:{p.id}" not in labels:
                labels.append(f"person:{p.id}")
        what = (
            f"last 'Status as of' {proj.status_as_of} ({age} days ago)"
            if proj.status_as_of
            else f"no 'Status as of' section; file modified {proj.modified}"
        )
        out.append(
            DesiredBead(
                xid=xid,
                title=f"KG status stale: {proj.name}",
                kind=WorkKind.finding,
                labels=labels,
                header=BeadHeader(
                    xid=xid, provenance=[_prov(str(proj.path), proj.locator, ctx.today)]
                ),
                body=f"{what}; threshold {KG_STALE_DAYS} days.",
                priority=3,
            )
        )
    return out


# --- GitHub audit candidates --------------------------------------------------------


def derive_github_audits(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    now = datetime.combine(ctx.today, datetime.min.time(), tzinfo=UTC)
    snap = ctx.github
    for rec in snap.repos:
        reasons = gh.audit_reasons(rec, now, REPO_STALE_DAYS)
        if not reasons:
            continue
        xid = f"audit:{rec.full_name}"
        out.append(
            DesiredBead(
                xid=xid,
                title=f"Audit {rec.name}: {'; '.join(reasons)}",
                kind=WorkKind.audit,
                labels=["src:github", f"repo:{rec.full_name}"],
                header=BeadHeader(
                    xid=xid,
                    provenance=[_prov(rec.html_url, f"snapshot {snap.fetched_at}", ctx.today)],
                    privacy=Privacy.public,
                ),
                body="\n".join(reasons),
                priority=3,
            )
        )
    return out


# --- calendar -----------------------------------------------------------------------


def derive_meetings(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    tomorrow = ctx.today + timedelta(days=1)
    aliases = ctx.people_aliases()
    seen: set[str] = set()
    for ev in cal.events_in_window(ctx.calendar, tomorrow, tomorrow):
        if (ev.status or "").upper() == "CANCELLED":
            continue
        for slug in cal.match_people(ev, aliases):
            xid = f"meeting-note:{tomorrow.isoformat()}:{slug}"
            if xid in seen:
                continue
            seen.add(xid)
            p = ctx.index.get(slug)
            when = ev.start_dt.strftime("%H:%M") if ev.start_dt else "all day"
            out.append(
                DesiredBead(
                    xid=xid,
                    title=f"Prepare meeting {tomorrow.isoformat()} {when}: {ev.summary}",
                    kind=WorkKind.meeting_note,
                    type_="chore",
                    labels=[f"person:{slug}", "src:calendar"],
                    parent_xid=f"program:{slug}" if p and p.is_student else None,
                    header=BeadHeader(
                        xid=xid,
                        provenance=[_prov(str(ev.path), ev.locator, ctx.today)],
                        deadline=tomorrow,
                    ),
                    body=(
                        f"Calendar event '{ev.summary}' on {tomorrow} matched "
                        f"{p.name if p else slug}."
                    ),
                    priority=2,
                )
            )
    return out


# --- people.yaml conflicts ----------------------------------------------------------


def derive_conflicts(ctx: SourceContext) -> list[DesiredBead]:
    out: list[DesiredBead] = []
    people_path = str(ctx.settings.root / "people.yaml")
    for c in ctx.conflicts:
        person = str(c.get("person") or "unknown")
        fld = str(c.get("field") or "field")
        xid = f"conflict:{person}:{fld}"
        p = ctx.index.get(person)
        name = p.name if p else person
        out.append(
            DesiredBead(
                xid=xid,
                title=f"Conflict: {name} {fld}: {c.get('a')} vs {c.get('b')}",
                kind=WorkKind.conflict,
                labels=[f"person:{person}", "needs:robert", "src:people.yaml"],
                header=BeadHeader(
                    xid=xid,
                    provenance=[
                        _prov(people_path, f"conflicts[person={person}, field={fld}]", ctx.today)
                    ],
                ),
                body=f"A: {c.get('a')}\nB: {c.get('b')}\nNoted: {c.get('noted')}",
                priority=1,
            )
        )
    return out


Deriver = Callable[[SourceContext], list[DesiredBead]]

DERIVERS: dict[str, Deriver] = {
    "courses": derive_courses,
    "people": derive_programs,
    "deadlines": derive_deadlines,
    "papers": derive_papers,
    "kg": derive_kg_stale,
    "github": derive_github_audits,
    "calendar": derive_meetings,
    "conflicts": derive_conflicts,
}


def derive_all(ctx: SourceContext, sources: list[str] | None = None) -> list[DesiredBead]:
    names = sources or list(DERIVERS)
    out: list[DesiredBead] = []
    seen: dict[str, str] = {}
    for name in names:
        fn = DERIVERS.get(name)
        if fn is None:
            ctx.warn(f"unknown source {name!r}; known: {', '.join(DERIVERS)}")
            continue
        try:
            beads = fn(ctx)
        except Exception as exc:  # noqa: BLE001 - one broken source must not stop the plan
            ctx.warn(f"source {name} failed: {exc}")
            continue
        for b in beads:
            if b.xid in seen:
                ctx.warn(f"duplicate xid {b.xid} from {name} (first from {seen[b.xid]}); skipped")
                continue
            seen[b.xid] = name
            out.append(b)
    return out
