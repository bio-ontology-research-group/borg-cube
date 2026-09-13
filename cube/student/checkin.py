"""Weekly check-in pack for Robert (playbook: brain/playbooks/student-checkin.md).

``cube student checkin <id>`` produces the three questions plus one milestone-aware
prompt, a suggested 1:1 agenda and a draft message file under runs/checkin/. With a
``mattermost_dm`` grant scoped to ``weekly-checkin`` the draft becomes an approval item of
kind ``mattermost_dm`` (still never sent by this command); otherwise it stays Robert-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from cube.approvals import ApprovalStore, Intent
from cube.beads import Beads
from cube.commands._common import Ledger
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.milestones import kaust_rules as kr
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import milestones_for

BUILTIN_QUESTIONS = (
    "What moved since last week? Name the artefact (commit, figure, section, result).",
    "What is blocked, and what have you tried?",
    "What is the next concrete step, and by when?",
)
ACTION_CLASS = "weekly-checkin"


def load_question_bank(settings: Settings) -> tuple[list[str], str]:
    """Questions from skills/mentoring-session assets when present, else the built-ins."""
    roots = [settings.root / "skills", settings.dirs["skills_library"]]
    for root in roots:
        if not root.is_dir():
            continue
        for skill_dir in sorted(root.glob("**/mentoring-session")):
            assets = skill_dir / "assets"
            if not assets.is_dir():
                continue
            for path in sorted(assets.glob("*.md")):
                if "question" not in path.name.lower() and "checkin" not in path.name.lower():
                    continue
                lines = [
                    ln.strip()[2:].strip()
                    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if ln.strip().startswith(("- ", "* "))
                ]
                if lines:
                    return lines, str(path)
    return list(BUILTIN_QUESTIONS), "built-in (skills/mentoring-session/assets not found)"


def milestone_prompt(milestones: list[kr.Milestone], today: date) -> str | None:
    nxt = kr.next_open(milestones)
    if nxt is None or nxt.due is None:
        return None
    days = nxt.days(today)
    return (
        f"Your next milestone is the {nxt.name} on {nxt.due.isoformat()} "
        f"({days} days). What has to be true by then, and is anything in the way?"
    )


def suggested_agenda(
    ctx: SourceContext, person: Person, ledger: Ledger, milestones: list[kr.Milestone]
) -> list[str]:
    agenda: list[str] = []
    nxt = kr.next_open(milestones)
    if nxt and nxt.due:
        agenda.append(
            f"Milestone: {nxt.name} due {nxt.due.isoformat()} ({nxt.days(ctx.today)} days); "
            "confirm the artefact and the committee."
        )
    for m in milestones:
        for note in m.notes:
            if "verify" in note or "later than" in note:
                agenda.append(f"Clarify {m.name}: {note}")
    notes = ctx.person_notes(person)
    if notes:
        if notes.open_checkboxes:
            agenda.append(
                f"Open action items from the org file: {notes.open_checkboxes} unchecked "
                f"(~/org/{person.org_file})"
            )
        for h in notes.recent(2):
            agenda.append(f"Follow up on '{h.title}' ({h.when.isoformat()}, line {h.line})")
        for t in notes.todo_headings[:2]:
            agenda.append(f"TODO heading in the org file: {t}")
    for pa in ctx.papers:
        if any(ctx.index.by_first_name(n) is person for n in pa.people) and pa.state not in {
            "PUBLISHED",
            "CANCELED",
            "CANCELLED",
        }:
            agenda.append(f"Paper [{pa.state or 'no state'}] {pa.title}: next step and venue")
    for d in ctx.deadlines:
        if d.is_open and person in ctx.index.mentioned_in(d.text):
            agenda.append(f"Deadline {d.when.isoformat()}: {d.text}")
    for b in ledger.open_with_label(f"person:{person.id}"):
        if "needs:robert" in (b.get("labels") or []):
            agenda.append(f"Bead {b.get('id')}: {b.get('title')}")
    return agenda[:8]


@dataclass
class CheckinPack:
    person: str
    name: str
    date: str
    questions: list[str]
    prompt: str | None
    agenda: list[str]
    routing: str  # approval | robert
    grant_reason: str
    question_source: str
    message: str = ""
    pack: str = ""
    files: dict[str, str] = field(default_factory=dict)
    approval: dict[str, Any] | None = None
    to: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("message", None)
        d.pop("pack", None)
        return d


def render_message(pack: CheckinPack, handle: str | None) -> str:
    lines = [
        "---",
        "kind: mattermost_dm",
        f"person: {pack.person}",
        f"to: {handle or ''}",
        f"action: {ACTION_CLASS}",
        f"subject: Weekly check-in {pack.date}",
        "---",
        f"Hi {pack.name.split()[0]}, quick weekly check-in from @borg-advisor.",
        "",
    ]
    lines.extend(f"{i}. {q}" for i, q in enumerate(pack.questions, 1))
    if pack.prompt:
        lines.append(f"{len(pack.questions) + 1}. {pack.prompt}")
    lines.extend(
        [
            "",
            "Answer as much or as little as you like. I will summarise what you write for "
            "Robert, with a link to your message, and nothing else.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_pack(pack: CheckinPack) -> str:
    lines = [
        f"# Weekly check-in pack: {pack.name} ({pack.date})",
        "",
        "Robert-only. Prepared by cube student checkin; nothing here reaches the student "
        "unless Robert sends it or approves the draft.",
        "",
        f"Routing: {pack.routing} ({pack.grant_reason})",
        "",
        "## Questions",
        "",
    ]
    lines.extend(f"- {q}" for q in pack.questions)
    if pack.prompt:
        lines.append(f"- {pack.prompt}")
    lines.extend(["", "## Suggested 1:1 agenda", ""])
    lines.extend(f"- {a}" for a in pack.agenda or ["(nothing derived from the sources)"])
    lines.extend(["", f"Question source: {pack.question_source}", ""])
    return "\n".join(lines)


def build_checkin(
    settings: Settings,
    ctx: SourceContext,
    person: Person,
    ledger: Ledger,
    policy: ContactPolicy,
) -> CheckinPack:
    questions, source = load_question_bank(settings)
    milestones = milestones_for(ctx, person)
    decision = policy.check(person.id, "mattermost_dm", ACTION_CLASS, ctx.today)
    contact = ctx.contact_for(person)
    handle = person.mattermost or (contact.mattermost if contact else None)
    pack = CheckinPack(
        person=person.id,
        name=person.name,
        date=ctx.today.isoformat(),
        questions=list(questions),
        prompt=milestone_prompt(milestones, ctx.today),
        agenda=suggested_agenda(ctx, person, ledger, milestones),
        routing="approval" if decision.allowed else "robert",
        grant_reason=decision.reason,
        question_source=source,
        to=f"@{handle}" if handle else None,
    )
    pack.message = render_message(pack, pack.to)
    pack.pack = render_pack(pack)
    return pack


def run_checkin(
    settings: Settings,
    person: Person,
    *,
    today: date,
    dry_run: bool,
    beads: Beads | None = None,
    via: str | None = None,
    now: datetime | None = None,
    ctx: SourceContext | None = None,
) -> CheckinPack:
    ctx = ctx or SourceContext(settings, today, github_details=False)
    ledger = Ledger(
        beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True, actor="cube")
    )
    policy = ContactPolicy(settings.root / "contacts.yaml")
    pack = build_checkin(settings, ctx, person, ledger, policy)
    out_dir = settings.dirs["runs"] / "checkin" / today.isoformat() / person.id
    pack_path = out_dir / "pack.md"
    msg_path = out_dir / "message.md"
    pack.files = {"pack": str(pack_path), "message": str(msg_path)}
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(pack.pack, encoding="utf-8")
        msg_path.write_text(pack.message, encoding="utf-8")
    intent = Intent(
        kind="mattermost_dm",
        to=pack.to,
        person=person.id,
        channel="mattermost_dm",
        action=ACTION_CLASS,
        subject=f"Weekly check-in {today.isoformat()}" + (f" via {via}" if via else ""),
        body_file=str(msg_path),
    )
    if pack.routing == "approval":
        if dry_run:
            pack.approval = {"dry_run": True, "would_create": intent.model_dump(mode="json")}
        else:
            ap = ApprovalStore(settings.state_dir()).create(
                intent,
                policy=policy,
                created_by="cube student checkin",
                now=now or datetime.now(UTC),
            )
            pack.approval = ap.cockpit()
    return pack
