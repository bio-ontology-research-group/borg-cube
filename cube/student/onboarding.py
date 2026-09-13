"""`cube student onboard <id>`: the pilot onboarding pack, Robert-facing (ADR-0009).

Produces under runs/onboarding/<id>/ the transparency note (doc/student-guide.md,
personalised), the mentoring compact (skills/mentoring-compact assets when present, else
built-in), the milestone plan from ``plan_for``, an org block ``* Milestone plan (cube,
DATE)`` as a unified diff against ``~/org/<file>`` filed as an ``org_edit`` approval, and
the program/milestone beads through reconcile. It never contacts the student: Robert sends
the note himself and records the grant with ``cube contact grant``.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from cube.approvals import ApprovalStore, Intent
from cube.beads import Beads
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.milestones import kaust_rules as kr
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import derive_programs, milestones_for
from cube.sync.reconcile import apply, index_existing, plan, summarize

BUILTIN_COMPACT = """\
# Mentoring compact (draft for Robert to adapt)

What you can expect from Robert:
- A weekly 1:1 slot, or an explicit reschedule; written feedback on drafts within two weeks.
- Clear milestone dates (qualifying exam, proposal, thesis application, defense) and what
  counts as done for each.
- Honest, specific feedback on the work, never on the person, and no surprises at
  milestone meetings.

What Robert expects from you:
- Say early what is blocked; a blocker named on Monday costs less than one found in a
  committee meeting.
- Keep your artefacts visible: commits in the shared repository, drafts in the paper
  directory, a short note before each 1:1 on what moved.
- Own your milestone plan; the dates below are yours to negotiate, not to discover.

About the tools:
- Robert uses software (borg-cube) to keep track of milestones and visible progress. It
  drafts for Robert; it does not assess you and it never contacts you unless you agreed to
  the pilot (see the transparency note).
"""


@dataclass
class OnboardingPack:
    person: str
    name: str
    date: str
    org_file: str
    new_org_file: bool
    files: dict[str, str] = field(default_factory=dict)
    approval: dict[str, Any] | None = None
    beads: dict[str, Any] = field(default_factory=dict)
    compact_source: str = ""
    note_source: str = ""
    milestones: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = True
    transparency_note: str = ""
    compact: str = ""
    plan_md: str = ""
    org_block: str = ""
    patch: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in ("transparency_note", "compact", "plan_md", "patch"):
            d.pop(key)
        return d


def load_compact(settings: Settings) -> tuple[str, str]:
    roots = [settings.root / "skills", settings.dirs["skills_library"]]
    for root in roots:
        if not root.is_dir():
            continue
        for skill_dir in sorted(root.glob("**/mentoring-compact")):
            assets = skill_dir / "assets"
            for path in sorted(assets.glob("*.md")) if assets.is_dir() else []:
                return path.read_text(encoding="utf-8", errors="replace"), str(path)
    return BUILTIN_COMPACT, "built-in (skills/mentoring-compact/assets not found)"


def transparency_note(settings: Settings, person: Person, today: date) -> tuple[str, str]:
    guide = settings.root / "doc" / "student-guide.md"
    header = (
        f"Prepared for {person.name} on {today.isoformat()}. Robert sends this note himself; "
        "the system never sends it. Taking part is voluntary and can be stopped at any time.\n\n"
    )
    if guide.exists():
        return header + guide.read_text(encoding="utf-8"), str(guide)
    body = (
        "# Note about borg-cube\n\nRobert uses software to track milestones and visible "
        "progress for the group. It drafts summaries for Robert, never decides anything about "
        "you, and never contacts you unless you agree to the advisor pilot. Ask Robert for the "
        "full rules.\n"
    )
    return header + body, "built-in (doc/student-guide.md not found)"


def milestone_plan_md(person: Person, milestones: list[kr.Milestone], today: date) -> str:
    lines = [
        f"# Milestone plan: {person.name} ({today.isoformat()})",
        "",
        f"Program {person.program or 'unknown'}, start "
        f"{person.start.isoformat() if person.start else 'unknown'} (people.yaml). Dates from "
        "the KAUST CEMSE rules in cube.milestones.kaust_rules; planned dates from staff.org.",
        "",
        "| milestone | due | status | rule |",
        "|---|---|---|---|",
    ]
    for m in milestones:
        lines.append(
            f"| {m.name} | {m.due.isoformat() if m.due else '-'} | {m.status} | {m.rule} |"
        )
    for m in milestones:
        for n in m.notes:
            lines.append(f"- {m.name}: {n}")
    lines.append("")
    return "\n".join(lines)


def org_block(milestones: list[kr.Milestone], today: date) -> str:
    lines = [
        f"* Milestone plan (cube, {today.isoformat()})".ljust(70) + ":cube:",
        "Generated by cube student onboard from people.yaml, staff.org and the KAUST CEMSE "
        "rules. Edit freely; cube reads this file, never rewrites it.",
    ]
    for m in milestones:
        box = "[X]" if m.status == "done" else "[ ]"
        due = m.due.isoformat() if m.due else "date unknown"
        lines.append(f"- {box} {m.name.capitalize()}: {due} ({m.rule})")
        if m.estimate and m.estimate_source:
            lines.append(f"  - planned: {m.estimate.isoformat()} ({m.estimate_source})")
    return "\n".join(lines) + "\n"


def org_patch(org_dir: Path, org_file: str, block: str) -> tuple[str, bool]:
    """Unified diff (``patch -p1 -d <org_dir>``) appending ``block`` to ``org_file``."""
    target = org_dir / org_file
    exists = target.exists()
    old = target.read_text(encoding="utf-8", errors="replace") if exists else ""
    sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
    new = old + sep + block
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{org_file}" if exists else "/dev/null",
        tofile=f"b/{org_file}",
    )
    return "".join(diff), not exists


def default_org_file(person: Person) -> str:
    return person.org_file or f"{person.first_name.lower()}.org"


def run_onboard(
    settings: Settings,
    person: Person,
    *,
    today: date,
    dry_run: bool,
    beads: Beads | None = None,
    now: datetime | None = None,
    ctx: SourceContext | None = None,
) -> OnboardingPack:
    ctx = ctx or SourceContext(settings, today, github_details=False)
    milestones = milestones_for(ctx, person)
    org_file = default_org_file(person)
    block = org_block(milestones, today)
    patch, new_file = org_patch(settings.dirs["org"], org_file, block)
    note, note_src = transparency_note(settings, person, today)
    compact, compact_src = load_compact(settings)
    out_dir = settings.dirs["runs"] / "onboarding" / person.id
    files = {
        "transparency_note": out_dir / "transparency-note.md",
        "compact": out_dir / "mentoring-compact.md",
        "plan": out_dir / "milestone-plan.md",
        "org_block": out_dir / "milestone-plan.org",
        "patch": out_dir / f"{Path(org_file).stem}-milestone-plan.patch",
    }
    pack = OnboardingPack(
        person=person.id,
        name=person.name,
        date=today.isoformat(),
        org_file=f"~/org/{org_file}",
        new_org_file=new_file,
        files={k: str(v) for k, v in files.items()},
        compact_source=compact_src,
        note_source=note_src,
        milestones=[m.as_dict(today) for m in milestones],
        dry_run=dry_run,
        transparency_note=note,
        compact=compact,
        plan_md=milestone_plan_md(person, milestones, today),
        org_block=block,
        patch=patch,
    )
    contents = {
        "transparency_note": note,
        "compact": compact,
        "plan": pack.plan_md,
        "org_block": block,
        "patch": patch,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        for key, path in files.items():
            path.write_text(contents[key], encoding="utf-8")
        (out_dir / "README.md").write_text(
            "Robert sends transparency-note.md and mentoring-compact.md himself (email or "
            "in person). After the student agrees: `cube contact grant <id> mattermost_dm "
            "--scope weekly-checkin --evidence <permalink> --apply`, then `cube approve` the "
            "org_edit item to add the milestone plan to the org file. Nothing here is sent by "
            "the system.\n",
            encoding="utf-8",
        )
    intent = Intent(
        kind="org_edit",
        person=person.id,
        action="edit",
        subject=f"Milestone plan block for ~/org/{org_file}",
        diff_file=str(files["patch"]),
        target_dir=str(settings.dirs["org"]),
    )
    if dry_run:
        pack.approval = {"dry_run": True, "would_create": intent.model_dump(mode="json")}
    else:
        approval = ApprovalStore(settings.state_dir()).create(
            intent,
            policy=ContactPolicy(settings.root / "contacts.yaml"),
            created_by="cube student onboard",
            now=now or datetime.now(UTC),
        )
        pack.approval = approval.cockpit()
    ledger = beads or Beads(
        bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run, actor="cube/onboard"
    )
    if dry_run:
        ledger.dry_run = True
    label = f"person:{person.id}"
    desired = [b for b in derive_programs(ctx) if label in b.labels]
    existing, warning = index_existing(ledger)
    actions = plan(desired, existing)
    results = apply(actions, desired, ledger, existing)
    pack.beads = {
        "desired": len(desired),
        "summary": summarize(actions),
        "actions": [r for r in results if r.get("op") != "noop"],
        "warning": warning,
    }
    return pack
