"""``cube goal`` creation, decomposition, inspection, and agent spin commands."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from cube.approvals import ApprovalError, ApprovalStore, Intent
from cube.beads import Beads, BeadsError
from cube.commands import Helpers
from cube.commands._common import (
    add_today,
    now_iso,
    people_records,
    require_person,
    require_project,
    today_from,
)
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.engine.context import bead_labels, label_value
from cube.engine.run import execute
from cube.goals import (
    GoalHeader,
    apply_plan,
    child_sort_key,
    goal_children,
    goal_header,
    goal_row,
    load_and_validate_plan,
    people_work,
    read_goal_ledger,
    validate_plan,
)
from cube.milestones.kaust_rules import next_open
from cube.model import Privacy, Provenance
from cube.roles import RoleError, load_all, load_role
from cube.runners import RUNNER_NAMES
from cube.sources.rkg import load_graph
from cube.sync.context import SourceContext
from cube.sync.derivers import milestones_for

_helpers: Helpers | None = None
GOAL_PROPOSAL_ACTION = "goal-decompose"


def _commands(beads: Beads) -> list[str]:
    return [shlex.join(command) for command in beads.logged_commands()]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "goal"


def _provenance(values: list[str], title: str) -> list[Provenance]:
    if not values:
        return [Provenance(source="cube goal new", locator=title)]
    result: list[Provenance] = []
    for value in values:
        source, separator, locator = value.partition("::")
        if not source.strip():
            raise ValueError("provenance must name a source path or permalink")
        result.append(
            Provenance(
                source=source.strip(),
                locator=locator.strip() if separator and locator.strip() else None,
            )
        )
    return result


def cmd_new(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    if not args.target:
        print("cube goal new: --target YYYY-MM-DD is required", file=sys.stderr)
        return 2
    if not args.success:
        print("cube goal new: at least one --success criterion is required", file=sys.stderr)
        return 2
    try:
        target = date.fromisoformat(args.target)
        require_project(settings, args.project)
        for person in args.person:
            require_person(settings, person)
        provenance = _provenance(args.provenance, args.title)
    except ValueError as exc:
        print(f"cube goal new: {exc}", file=sys.stderr)
        return 2
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    header = GoalHeader(
        xid=f"goal:{_slug(args.title)}:{stamp}",
        provenance=provenance,
        deadline=target,
        target=target,
        success=args.success,
        project=args.project,
        people=list(dict.fromkeys(args.person)),
        status="active",
        privacy=Privacy.internal,
    )
    labels = ["kind:goal", "privacy:internal"]
    if args.project:
        labels.append(f"project:{args.project}")
    body = "Success criteria:\n" + "\n".join(f"- {criterion}" for criterion in args.success)
    beads = _helpers.beads(settings, args.dry_run)
    try:
        goal_id = beads.create(
            args.title,
            header=header,
            body=body,
            type_="epic",
            priority=1,
            labels=labels,
            acceptance="\n".join(args.success),
        )
    except BeadsError as exc:
        print(f"cube goal new: {exc}", file=sys.stderr)
        return 2
    payload = {
        "goal": goal_id,
        "title": args.title,
        "header": header.model_dump(mode="json"),
        "labels": labels,
        "dry_run": args.dry_run,
        "commands": _commands(beads),
    }
    _helpers.emit(
        args,
        payload,
        "\n".join(payload["commands"]) if args.dry_run else f"created goal {goal_id}",
    )
    return 0


def _find_goal(beads: Beads, goal_id: str) -> dict[str, Any]:
    goal = beads.show(goal_id)
    if goal_header(goal) is None:
        raise ValueError(f"{goal_id} is not a valid kind:goal bead")
    return goal


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    beads = _helpers.beads(settings, True)
    try:
        goal = _find_goal(beads, args.goal)
        issues, ready, blocked = read_goal_ledger(beads)
        row = goal_row(
            settings,
            goal,
            issues,
            ready,
            blocked,
            today=today_from(args) or date.today(),
            include_children=True,
        )
    except (BeadsError, ValueError) as exc:
        print(f"cube goal show: {exc}", file=sys.stderr)
        return 2
    assert _helpers is not None
    _helpers.emit(args, row, f"{row['id']} {row['status']} {row['progress']['pct']}%")
    return 0


def _project_context(settings: Settings, project_slug: str | None) -> dict[str, Any] | None:
    if not project_slug:
        return None
    graph = load_graph(settings.dirs["rkg"] / "projects.jsonld")
    project = next((item for item in graph.projects if item.slug == project_slug), None)
    if project is None:
        return {
            "slug": project_slug,
            "error": "not found in the research KG",
            "source": str(graph.path),
        }
    data = asdict(project)
    data["source"] = f"{graph.path}::@graph[@id={project.id}]"
    return data


def _people_context(
    settings: Settings,
    people: list[str],
    issues: list[dict[str, Any]],
    project_slug: str | None,
) -> list[dict[str, Any]]:
    registry = people_records(settings.root / "people.yaml")
    ctx = SourceContext(settings)
    output: list[dict[str, Any]] = []
    project = next((item for item in ctx.rkg.projects if item.slug == project_slug), None)
    for slug in people:
        row = dict(registry.get(slug) or {})
        person = ctx.index.get(slug)
        _, owed = people_work(issues, slug)
        expertise: list[str] = []
        if row.get("title"):
            expertise.append(f"title: {row['title']} (people.yaml)")
        if row.get("program"):
            expertise.append(f"program: {row['program']} (people.yaml)")
        if project:
            for member, project_role in project.members:
                if member.endswith(f"/{slug}") or member.endswith(f":{slug}"):
                    expertise.append(f"project role: {project_role or 'member'} ({ctx.rkg.path})")
        notes = ctx.person_notes(person) if person else None
        if notes:
            expertise.extend(
                f"open org topic: {title} ({notes.path})" for title in notes.todo_headings[:5]
            )
        milestones = milestones_for(ctx, person) if person and person.is_student else []
        milestone = next_open(milestones)
        output.append(
            {
                "slug": slug,
                "record": row,
                "expertise_evidence": expertise,
                "current_load": {"open_owed": len(owed), "items": owed},
                "milestone_stage": (
                    {
                        "name": milestone.name,
                        "due": milestone.due.isoformat() if milestone.due else None,
                        "status": milestone.status,
                        "source": milestone.source,
                    }
                    if milestone
                    else None
                ),
                "org_evidence": (
                    {
                        "path": str(notes.path),
                        "open_checkboxes": notes.open_checkboxes,
                        "recent_headings": [item.title for item in notes.recent(3)],
                    }
                    if notes
                    else None
                ),
            }
        )
    return output


def _decomposition_prompt(
    settings: Settings,
    goal: dict[str, Any],
    issues: list[dict[str, Any]],
    ready: list[dict[str, Any]],
    output_path: Path,
) -> str:
    header = goal_header(goal)
    assert header is not None
    roles, _ = load_all(settings.root)
    context = {
        "goal": {
            "id": goal.get("id"),
            "title": goal.get("title"),
            **header.model_dump(mode="json"),
        },
        "project": _project_context(settings, header.project),
        "people": _people_context(settings, header.people, issues, header.project),
        "ready": [
            {
                key: item.get(key)
                for key in ("id", "title", "priority", "status", "labels", "deadline", "due")
                if item.get(key) is not None
            }
            for item in ready
        ],
        "agent_roles": sorted(name for name, role in roles.items() if role.runtime != "python"),
    }
    return (
        "Decompose this goal using skills/delegation/SKILL.md. Do not update or close any bead. "
        "Produce a YAML plan accepted by skills/delegation/scripts/beads_from_plan.py. Each child "
        "uses owner: person:<slug> or owner: role:<name> and gives a one-line reason. Human work "
        "also has deadline and why_you. Write the plan to "
        f"{output_path} and return it as an artifact with kind plan. If the runner cannot write "
        "that file, put the complete YAML plan in the RunResult summary instead.\n\n"
        + json.dumps(context, indent=1, ensure_ascii=False, default=str)
    )


def _stub_plan(goal: dict[str, Any]) -> dict[str, Any]:
    header = goal_header(goal)
    assert header is not None
    goal_id = str(goal["id"])
    return {
        "goal": str(goal.get("title") or goal_id),
        "pattern": "single",
        "provenance": [f"bead:{goal_id}"],
        "review_by": "group-leader",
        "beads": [
            {
                "id": "first-agent-step",
                "title": f"First agent step for {str(goal.get('title') or goal_id)[:70]}",
                "kind": "implement",
                "stage": "design",
                "owner": "role:programmer",
                "privacy": "internal",
                "depends_on": [],
                "effort": "10 calls",
                "deadline": header.target.isoformat(),
                "objective": "Produce the first inspectable artifact needed by the goal.",
                "output": f"A goal child bead linked to {goal_id}",
                "sources": [f"bead:{goal_id}"],
                "out_of_scope": "Later goal work remains with later child beads.",
                "provenance": [f"bead:{goal_id}"],
                "why": (
                    "An agent can prepare this mechanical first artifact without blocking a person."
                ),
                "acceptance_criteria": [
                    {
                        "check": (
                            f"The child bead exists with parent {goal_id} and label goal:{goal_id}"
                        )
                    }
                ],
            }
        ],
    }


def _artifact_plan(report: dict[str, Any], settings: Settings) -> Path | None:
    result = report.get("result") or {}
    run_dir = Path(str(report.get("run_dir") or settings.root))
    for artifact in result.get("artifacts") or []:
        if artifact.get("kind") != "plan" or not artifact.get("path"):
            continue
        path = Path(str(artifact["path"])).expanduser()
        if path.is_absolute():
            return path
        if (run_dir / path).exists():
            return run_dir / path
        return settings.root / path
    return None


def _inline_plan(report: dict[str, Any]) -> dict[str, Any] | None:
    summary = str((report.get("result") or {}).get("summary") or "").strip()
    if summary.startswith("```"):
        lines = summary.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            summary = "\n".join(lines[1:-1])
    try:
        parsed = yaml.safe_load(summary)
    except yaml.YAMLError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("beads"), list):
        return dict(parsed)
    return None


def _save_proposal(report: dict[str, Any], plan: dict[str, Any]) -> Path:
    run_dir = Path(str(report.get("run_dir") or "."))
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "goal-proposal.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _new_review(settings: Settings, goal_id: str, report: dict[str, Any], proposal: Path) -> Any:
    return ApprovalStore(settings.state_dir()).create(
        Intent(
            kind="file_change",
            action=GOAL_PROPOSAL_ACTION,
            subject=f"Approve decomposition of {goal_id}",
            diff_file=str(proposal),
            target_dir=str(settings.root),
        ),
        policy=ContactPolicy(settings.root / "contacts.yaml"),
        created_by=f"group-leader/{report.get('run_id')}",
        run_id=str(report.get("run_id") or "") or None,
        bead=goal_id,
    )


def cmd_decompose(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    beads = _helpers.beads(settings, False)
    try:
        goal = _find_goal(beads, args.goal)
        issues = beads.list_issues("--all")
        ready = beads.ready()
    except (BeadsError, ValueError) as exc:
        print(f"cube goal decompose: {exc}", file=sys.stderr)
        return 2
    planned_path = settings.runs_dir() / "goals" / args.goal / "plan.yaml"
    report = execute(
        settings,
        "group-leader",
        bead=args.goal,
        runner_name=args.runner,
        dry_run=False,
        prompt_text=_decomposition_prompt(settings, goal, issues, ready, planned_path),
        beads=beads,
    ).as_dict()
    if not report["ok"]:
        _helpers.emit(
            args,
            {"ok": False, "run": report},
            f"decomposition failed: {report['error']}",
        )
        return 1
    try:
        artifact = _artifact_plan(report, settings)
        if artifact and artifact.exists():
            plan = load_and_validate_plan(settings, goal, artifact)
        elif inline := _inline_plan(report):
            plan = validate_plan(settings, goal, inline)
        elif args.runner == "stub":
            plan = validate_plan(settings, goal, _stub_plan(goal))
        else:
            raise ValueError("group-leader returned no readable plan artifact")
        proposal = _save_proposal(report, plan)
        review = _new_review(settings, args.goal, report, proposal)
        children: list[dict[str, Any]] = []
        if not args.dry_run:
            ApprovalStore(settings.state_dir()).decide(review.id, approve=True, by="robert")
            children = apply_plan(settings, beads, goal, plan)
    except (ApprovalError, BeadsError, OSError, ValueError) as exc:
        print(f"cube goal decompose: {exc}", file=sys.stderr)
        return 2
    payload = {
        "ok": True,
        "goal": args.goal,
        "proposal": str(proposal),
        "review": ApprovalStore(settings.state_dir()).get(review.id).cockpit(),
        "children": children,
        "applied": not args.dry_run,
        "run": report,
    }
    text = (
        f"created {len(children)} goal children from approved review {review.id}"
        if children
        else f"proposal {review.id} awaits Robert's approval; no child beads created"
    )
    _helpers.emit(args, payload, text)
    return 0


def _append_assignment(description: str, role: str) -> str:
    text = description.lstrip()
    if not text.startswith("---\n"):
        raise ValueError("child bead has no YAML header")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("child bead has an incomplete YAML header")
    header = yaml.safe_load(text[4:end])
    if not isinstance(header, dict) or not header.get("xid"):
        raise ValueError("child bead has an invalid YAML header")
    provenance = header.setdefault("provenance", [])
    if not isinstance(provenance, list):
        raise ValueError("child bead provenance is not a list")
    provenance.append({"source": "cube goal spin", "by": "robert", "at": now_iso(), "role": role})
    rendered = "---\n" + yaml.safe_dump(header, sort_keys=False).rstrip() + "\n---\n"
    return rendered + text[end + 4 :].lstrip("\n")


def cmd_spin(args: argparse.Namespace, settings: Settings) -> int:
    assert _helpers is not None
    beads = _helpers.beads(settings, args.dry_run)
    try:
        _find_goal(beads, args.goal)
        issues, ready_ids, _ = read_goal_ledger(beads)
        children = goal_children(args.goal, issues)
        if args.role:
            load_role(settings.root, args.role)
    except (BeadsError, RoleError, ValueError) as exc:
        print(f"cube goal spin: {exc}", file=sys.stderr)
        return 2
    if args.bead:
        candidates = [child for child in children if str(child.get("id")) == args.bead]
        if not candidates:
            print(f"cube goal spin: {args.bead} is not a child of {args.goal}", file=sys.stderr)
            return 2
    else:
        candidates = [child for child in children if label_value(bead_labels(child), "role:")]
    candidates = [child for child in candidates if str(child.get("id")) in ready_ids]
    candidates.sort(key=child_sort_key)
    if not candidates:
        print(f"cube goal spin: no ready agent child for {args.goal}", file=sys.stderr)
        return 3
    selected = candidates[0]
    selected_id = str(selected["id"])
    labels = bead_labels(selected)
    current_role = label_value(labels, "role:")
    role = args.role or current_role
    if not role:
        print(f"cube goal spin: {selected_id} has no agent role", file=sys.stderr)
        return 2
    before = len(beads.log)
    stale_people = [label for label in labels if label.startswith("person:")]
    stale_roles = [
        label for label in labels if label.startswith("role:") and label != f"role:{role}"
    ]
    if args.role and (current_role != role or stale_people):
        beads.remove_labels(selected_id, [*stale_roles, *stale_people])
        if current_role != role:
            beads.add_labels(selected_id, [f"role:{role}"])
        try:
            beads.update_description(
                selected_id, _append_assignment(str(selected.get("description") or ""), role)
            )
        except ValueError as exc:
            print(f"cube goal spin: {exc}", file=sys.stderr)
            return 2
    assignment_end = len(beads.log)
    report = execute(
        settings,
        role,
        bead=selected_id,
        runner_name=args.runner,
        dry_run=args.dry_run,
        beads=beads,
    ).as_dict()
    payload = {
        "goal": args.goal,
        "selected": {
            "bead": selected_id,
            "role": role,
            "priority": selected.get("priority", 2),
        },
        "dry_run": args.dry_run,
        "assignment_commands": [
            shlex.join(command)
            for command in beads.logged_commands()[before:assignment_end]
            if command[0] == beads.bin
        ],
        "run": report,
    }
    _helpers.emit(
        args,
        payload,
        f"{('DRY-RUN ' if args.dry_run else '')}spin {selected_id} as {role}: {report['state']}",
    )
    return 0 if report.get("ok") else 1


def _goal_approval(
    args: argparse.Namespace,
    settings: Settings,
    helpers: Helpers,
    fallback: Callable[[argparse.Namespace, Settings], int],
) -> int:
    """Extend the existing approval command for goal proposal review items."""
    store = ApprovalStore(settings.state_dir())
    try:
        approval = store.get(args.id)
    except ApprovalError:
        return fallback(args, settings)
    if approval.action != GOAL_PROPOSAL_ACTION:
        return fallback(args, settings)
    if approval.status not in {"pending", "approved"}:
        helpers.emit(
            args,
            {"ok": False, "id": approval.id, "error": f"proposal is {approval.status}"},
            f"error: proposal is {approval.status}",
        )
        return 3
    try:
        if not approval.bead or not approval.diff_file:
            raise ValueError("goal proposal review lacks its goal or plan path")
        beads = helpers.beads(settings, False)
        goal = _find_goal(beads, approval.bead)
        plan = load_and_validate_plan(settings, goal, Path(approval.diff_file))
        if approval.status == "pending":
            approval = store.decide(approval.id, approve=True, by=args.by)
        children = apply_plan(settings, beads, goal, plan)
    except (ApprovalError, BeadsError, OSError, ValueError) as exc:
        helpers.emit(args, {"ok": False, "id": approval.id, "error": str(exc)}, f"error: {exc}")
        return 3
    message = f"approved goal decomposition; {len(children)} child bead(s) ready"
    data = {
        "ok": True,
        "id": approval.id,
        "action": "approve",
        "result": "applied",
        "message": message,
        "approval": approval.cockpit(),
        "children": children,
    }
    helpers.emit(args, data, message)
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    global _helpers
    _helpers = helpers
    sp = sub.add_parser("goal", help="set, decompose, inspect, and spin a research goal")
    commands = sp.add_subparsers(dest="goal_cmd", required=True)

    new = commands.add_parser("new", help="create a provenance-backed goal epic")
    new.add_argument("--title", required=True)
    new.add_argument("--target")
    new.add_argument("--success", action="append", default=[])
    new.add_argument("--project")
    new.add_argument("--person", action="append", default=[])
    new.add_argument("--provenance", action="append", default=[])
    helpers.add_json(new)
    helpers.add_dry(new)
    new.set_defaults(fn=cmd_new)

    show = commands.add_parser("show", help="show one goal and its children")
    show.add_argument("goal")
    add_today(show)
    helpers.add_json(show)
    show.set_defaults(fn=cmd_show)

    decompose = commands.add_parser("decompose", help="ask the group leader for child work")
    decompose.add_argument("goal")
    decompose.add_argument("--run", action="store_true", help="accepted for cockpit compatibility")
    decompose.add_argument("--runner", choices=RUNNER_NAMES)
    helpers.add_json(decompose)
    helpers.add_dry(decompose)
    decompose.set_defaults(fn=cmd_decompose)

    spin = commands.add_parser("spin", help="assign and run the next ready agent child")
    spin.add_argument("goal")
    spin.add_argument("--bead")
    spin.add_argument("--role")
    spin.add_argument("--runner", choices=RUNNER_NAMES)
    helpers.add_json(spin)
    helpers.add_dry(spin)
    spin.set_defaults(fn=cmd_spin)

    approve_parser = getattr(sub, "choices", {}).get("approve")
    if approve_parser is not None:
        fallback = approve_parser.get_default("fn")
        if callable(fallback):
            approve_parser.set_defaults(
                fn=lambda args, settings: _goal_approval(args, settings, helpers, fallback)
            )
