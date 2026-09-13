"""`cube courses`: course offerings joined from Org files and the research KG."""

from __future__ import annotations

import argparse
from typing import Any

from cube.commands import Helpers
from cube.commands._common import add_today, context, now_iso
from cube.config import Settings
from cube.sync.derivers import DesiredBead, derive_courses

_helpers: Helpers | None = None


def _work_item(bead: DesiredBead) -> dict[str, Any]:
    return {
        "xid": bead.xid,
        "title": bead.title,
        "type": bead.type_,
        "kind": bead.kind.value,
        "parent_xid": bead.parent_xid,
        "deadline": bead.header.deadline.isoformat() if bead.header.deadline else None,
        "closed": bead.closed,
    }


def cmd_courses(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    ctx = context(settings, args, github_details=False)
    desired = derive_courses(ctx)
    by_course: dict[str, list[DesiredBead]] = {}
    for bead in desired:
        course_xid = bead.xid if bead.kind.value == "course" else bead.parent_xid
        if course_xid:
            by_course.setdefault(course_xid, []).append(bead)

    rows: list[dict[str, Any]] = []
    text: list[str] = []
    for course in ctx.courses:
        upcoming = [deadline for deadline in course.deadlines if deadline.when >= ctx.today]
        row = {
            "xid": course.xid,
            "code": course.code,
            "title": course.title,
            "semester": course.semester,
            "instructor": course.instructor,
            "lectures": [
                {
                    "number": lecture.number,
                    "date": lecture.when.isoformat() if lecture.when else None,
                    "topic": lecture.topic,
                    "materials": lecture.materials,
                    "source": lecture.locator,
                }
                for lecture in course.lectures
            ],
            "materials": course.materials,
            "upcoming_deadlines": [
                {
                    "date": deadline.when.isoformat(),
                    "title": deadline.title,
                    "source": deadline.locator,
                }
                for deadline in upcoming
            ],
            "work_items": [_work_item(bead) for bead in by_course.get(course.xid, [])],
            "sources": [
                source
                for source in (
                    str(course.org_path) if course.org_path else None,
                    str(course.kg_path) if course.kg_path else None,
                )
                if source
            ],
        }
        rows.append(row)
        text.append(
            f"{course.code}: {course.title} [{course.semester}]"
            + (f"; {course.instructor}" if course.instructor else "")
        )
        for lecture in course.lectures:
            text.append(
                f"  {lecture.number:02d}  "
                f"{lecture.when.isoformat() if lecture.when else '-':10}  {lecture.topic}"
            )
        for deadline in upcoming:
            text.append(f"  due {deadline.when.isoformat()}  {deadline.title}")

    payload = {
        "generated": now_iso(),
        "today": ctx.today.isoformat(),
        "courses": rows,
        "warnings": ctx.warnings,
    }
    _helpers.emit(args, payload, "\n".join(text) or "no courses found")
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("courses", help="course offerings from Org files and the research KG")
    add_today(sp)
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_courses)
