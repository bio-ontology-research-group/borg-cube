"""Student-digest patrol (Thu 12:00): one Robert-only markdown per student.

``briefings/students/<date>-<id>.md`` holds milestones, the age of the last org heading and
of the pa KG status, open beads, recent repository pushes (from the GitHub cache), and a
suggested 1:1 agenda with questions (skills/mentoring-session assets when present, built-in
otherwise). For granted students the advisor context JSON for the Hermes hook is refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads
from cube.commands._common import Ledger
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.literature import student_digest_lines
from cube.patrols.base import Finding, PatrolReport, register
from cube.sources import github as gh
from cube.student.checkin import load_question_bank, milestone_prompt, suggested_agenda
from cube.student.context import context_filename, is_granted, render_context, write_context
from cube.sync.context import Person, SourceContext
from cube.sync.derivers import milestones_for
from cube.sync.reconcile import bead_labels

MEETING_GAP_DAYS = 21
RECENT_PUSH_DAYS = 7


def meeting_gap_days(root: Path) -> int:
    path = root / "skills" / "group-monitor" / "assets" / "thresholds.yaml"
    if not path.exists():
        return MEETING_GAP_DAYS
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        value = data["students"]["meeting_gap_days"]["value"]
        return int(value)
    except (yaml.YAMLError, KeyError, TypeError, ValueError):
        return MEETING_GAP_DAYS


def person_repos(ctx: SourceContext, person: Person, ledger: Ledger) -> list[str]:
    repos: list[str] = []
    for b in ledger.open_with_label(f"person:{person.id}"):
        for lab in bead_labels(b):
            if lab.startswith("repo:") and lab[5:] not in repos:
                repos.append(lab[5:])
    kg_person = ctx.rkg.person(person.id)
    if kg_person:
        for proj in ctx.rkg.projects:
            if proj.id not in kg_person.projects and not any(
                m[0] == kg_person.id for m in proj.members
            ):
                continue
            for sw_id in proj.software:
                sw = next((s for s in ctx.rkg.software if s.id == sw_id), None)
                if sw and sw.repository:
                    name = sw.repository.rstrip("/").split("github.com/")[-1]
                    if name not in repos:
                        repos.append(name)
    return repos


def recent_pushes(settings: Settings, repos: list[str], today: date) -> list[dict[str, Any]]:
    """Pushes within RECENT_PUSH_DAYS from the GitHub cache only (never a network call)."""
    cache = settings.dirs["state"] / "cache" / "github.json"
    snap = gh.GitHubSource(cache_path=cache, ttl_hours=24 * 14).cached()
    if snap is None:
        return []
    now = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    out: list[dict[str, Any]] = []
    wanted = {r.lower() for r in repos}
    for rec in snap.repos:
        if rec.full_name.lower() not in wanted and rec.name.lower() not in wanted:
            continue
        age = rec.days_since_push(now)
        out.append(
            {
                "repo": rec.full_name,
                "pushed_at": rec.pushed_at,
                "days": age,
                "recent": age is not None and age <= RECENT_PUSH_DAYS,
            }
        )
    return out


def render_student_digest(
    settings: Settings,
    ctx: SourceContext,
    person: Person,
    ledger: Ledger,
    questions: list[str],
    question_source: str,
    gap_days: int,
) -> tuple[str, list[Finding]]:
    today = ctx.today
    notes: list[Finding] = []
    milestones = milestones_for(ctx, person)
    org = ctx.person_notes(person)
    staff = ctx.staff_entry(person)
    contact = ctx.contact_for(person)
    refs = {person.id} | ({contact.slug} if contact else set())
    # Enforces CLAUDE.md's privacy-class rule: progress assessments and staff notes are
    # local-only even though the generated digest is shown only to Robert.
    lines = [
        f"# Student digest: {person.name} ({today.isoformat()})",
        "",
        "Robert-only (privacy: local-only). Never posted, never shown to the student. Every line "
        "names its source; nothing here comes from the student that they did not write down "
        "in an artefact Robert already has.",
        "",
        f"Program: {person.program or 'unknown'}; start: "
        f"{person.start.isoformat() if person.start else 'unknown'} (source: people.yaml, "
        f"{person.source or 'no source recorded'})",
        "",
        "## Milestones (KAUST rules vs staff.org)",
        "",
        "| milestone | due | days | status | source |",
        "|---|---|---|---|---|",
    ]
    for m in milestones:
        lines.append(
            f"| {m.name} | {m.due.isoformat() if m.due else '-'} | "
            f"{m.days(today) if m.due else '-'} | {m.status} | {m.rule} |"
        )
    for m in milestones:
        for n in m.notes:
            lines.append(f"- {m.name}: {n}")
    lines.extend(["", "## Evidence", ""])
    if org:
        last = org.last_meeting
        age = (today - last).days if last else None
        lines.append(
            f"- Org notes ~/org/{person.org_file}: last dated heading "
            f"{last.isoformat() if last else 'none'}"
            + (f" ({age} days ago)" if age is not None else "")
            + f"; {org.open_checkboxes} open / {org.done_checkboxes} done checkboxes; "
            f"{len(org.todo_headings)} TODO heading(s)"
        )
        for h in org.recent(3):
            lines.append(f"  - {h.when.isoformat()}: {h.title} (line {h.line})")
        if age is None or age > gap_days:
            notes.append(
                Finding(
                    key=f"meeting-gap:{person.id}",
                    title=(
                        f"{person.name}: no dated org heading for "
                        f"{age if age is not None else 'any'} days (threshold {gap_days})"
                    ),
                    severity="warn",
                    source=str(org.path),
                )
            )
    else:
        lines.append("- Org notes: no org_file in people.yaml or file missing")
        notes.append(Finding(f"no-org:{person.id}", f"{person.name}: no org notes file", "info"))
    kg_hits = 0
    for pr in ctx.kg_projects:
        hit = next((m for m in pr.members if m.ref in refs), None)
        if hit is None:
            continue
        kg_hits += 1
        fresh = pr.freshness_date()
        age = (today - fresh).days if fresh else None
        lines.append(
            f"- pa KG {pr.slug}: status {pr.status or '?'}, Status as of "
            f"{pr.status_as_of.isoformat() if pr.status_as_of else 'never'}"
            + (f" ({age} days ago)" if age is not None else "")
            + f" (role: {hit.role or '?'}; {pr.path})"
        )
    if not kg_hits:
        lines.append("- pa KG: no project lists this person as a member")
    repos = person_repos(ctx, person, ledger)
    pushes = recent_pushes(settings, repos, today)
    if repos:
        lines.append(f"- Repositories: {', '.join(repos)}")
        for p in pushes:
            lines.append(
                f"  - {p['repo']}: last push {str(p['pushed_at'])[:10]} "
                f"({p['days']} days ago{'; recent' if p['recent'] else ''})"
            )
        if not pushes:
            lines.append(
                "  - no GitHub cache entry for these repositories (state/cache/github.json)"
            )
    else:
        lines.append("- Repositories: none linked via beads (repo: label) or the research KG")
    beads = ledger.open_with_label(f"person:{person.id}")
    if beads:
        lines.append(f"- Open beads ({len(beads)}):")
        for b in beads[:10]:
            flag = " [needs:robert]" if "needs:robert" in bead_labels(b) else ""
            lines.append(f"  - {b.get('id')}: {b.get('title')}{flag}")
    else:
        lines.append("- Open beads: none" + (f" ({ledger.warning})" if ledger.warning else ""))
    for d in ctx.deadlines:
        if d.is_open and person in ctx.index.mentioned_in(d.text):
            lines.append(f"- Deadline {d.when.isoformat()}: {d.text} ({d.locator})")
    for pa in ctx.papers:
        if any(ctx.index.by_first_name(n) is person for n in pa.people):
            lines.append(f"- Paper [{pa.state or 'no state'}] {pa.title} ({pa.locator})")
    if staff:
        lines.append(f"- staff.org: {'; '.join(staff.bullets)} ({staff.locator})")
    lines.extend(student_digest_lines(settings, person.id, today))
    lines.extend(["", "## Suggested 1:1 agenda", ""])
    agenda = suggested_agenda(ctx, person, ledger, milestones)
    lines.extend(f"{i}. {a}" for i, a in enumerate(agenda, 1))
    if not agenda:
        lines.append("1. (nothing derived from the sources; ask what moved)")
    lines.extend(["", "## Questions", ""])
    lines.extend(f"- {q}" for q in questions)
    prompt = milestone_prompt(milestones, today)
    if prompt:
        lines.append(f"- {prompt}")
    lines.extend(
        [
            "",
            f"Questions: {question_source}. Rubric: brain/rubrics/progress-assessment.md. "
            "Playbook: brain/playbooks/student-checkin.md.",
            "",
        ]
    )
    return "\n".join(lines), notes


@dataclass
class StudentDigestPatrol:
    name: str = "student_digest"
    only: str | None = None
    refresh_context: bool = True

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        ctx = SourceContext(settings, today, github_details=False)
        ledger = Ledger(
            beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True, actor="cube")
        )
        policy = ContactPolicy(settings.root / "contacts.yaml")
        questions, source = load_question_bank(settings)
        gap = meeting_gap_days(settings.root)
        out_dir = settings.root / "briefings" / "students"
        ctx_dir = settings.dirs["hermes_home"] / "profiles" / "advisor" / "context"
        report = PatrolReport(self.name, today, dry_run)
        report.warnings = list(ctx.warnings)
        files: list[str] = []
        contexts: list[str] = []
        previews: dict[str, str] = {}
        for p in ctx.people:
            if not p.is_student or (self.only and p.id != self.only):
                continue
            md, notes = render_student_digest(settings, ctx, p, ledger, questions, source, gap)
            path = out_dir / f"{today.isoformat()}-{p.id}.md"
            files.append(str(path))
            report.findings.extend(notes)
            if dry_run:
                previews[p.id] = md
            else:
                out_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(md, encoding="utf-8")
            if self.refresh_context and is_granted(policy, p, today):
                target = ctx_dir / context_filename(p)
                contexts.append(str(target))
                if not dry_run:
                    write_context(render_context(ctx, p, ledger, policy), ctx_dir, target.name)
        report.data["files"] = files
        report.data["contexts"] = contexts
        if dry_run:
            report.data["previews"] = previews
        if ledger.warning:
            report.warnings.append(ledger.warning)
        report.summary = (
            f"{len(files)} student digest(s) {'would be ' if dry_run else ''}written to "
            f"{out_dir}; {len(contexts)} advisor context(s) for granted students; "
            f"{sum(1 for n in report.notes() if n.severity == 'warn')} meeting-gap warning(s)"
        )
        return report


register(StudentDigestPatrol, "student_digest")
