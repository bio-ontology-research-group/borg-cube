"""Deterministic research pipeline creation, artifact checks, status, and transitions."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from cube.agents import AgentError, append_inbox, load_agent, load_all_agents
from cube.agents.liaison import approval_labels, classify_request
from cube.beads import Beads
from cube.config import Settings
from cube.engine import review_gate
from cube.engine.context import bead_labels, label_value
from cube.goals import GoalHeader, goal_header
from cube.model import BeadHeader, Privacy, Provenance, RunResult
from cube.roles import RoleError, load_all, load_role
from cube.roster import load_people_data
from cube.sources.pa_kg import parse_project

CLOSED = {"closed", "done"}


def is_pipeline_epic(bead: dict[str, Any]) -> bool:
    """True only for the epic itself, never for a stage bead.

    bd copies the parent's labels onto children, so every stage bead also carries
    ``kind:goal`` and ``pipeline:research``. Stage beads are told apart by their
    ``pipeline-stage:`` label and by lacking a parseable goal header.
    """
    labels = set(bead_labels(bead))
    if not {"kind:goal", "pipeline:research"} <= labels:
        return False
    if any(label.startswith("pipeline-stage:") for label in labels):
        return False
    return GoalHeader.parse(str(bead.get("description") or "")) is not None


def list_pipeline_epics(beads: Beads, *, open_only: bool = False) -> list[dict[str, Any]]:
    epics = [item for item in beads.list_issues("--all") if is_pipeline_epic(item)]
    if open_only:
        epics = [e for e in epics if str(e.get("status") or "open") not in {"closed", "done"}]
    return epics


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "research"


def _status(bead: dict[str, Any]) -> str:
    return str(bead.get("status") or "open").lower()


def _pipeline_dir(settings: Settings, epic_id: str) -> Path:
    return settings.runs_dir() / "pipelines" / epic_id


def _team_path(settings: Settings, epic_id: str) -> Path:
    return _pipeline_dir(settings, epic_id) / "team.yaml"


def _read_team(settings: Settings, epic_id: str) -> dict[str, Any] | None:
    path = _team_path(settings, epic_id)
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return dict(value) if isinstance(value, dict) else None


def _member_slug(member: str) -> str:
    return _slug(member.split(":", 1)[-1])


def _member_kind(member: str) -> str:
    return member.split(":", 1)[0]


def _external_member_bead(bead: dict[str, Any]) -> bool:
    return any(label.startswith(("person:", "collaborator:")) for label in bead_labels(bead))


def _collaborator_project_slug(epic: dict[str, Any], header: GoalHeader) -> str | None:
    """Return the project page allowed to establish external collaborators."""
    return (
        label_value(bead_labels(epic), "project:")
        or header.project
        or (header.pipeline.collaborators_from if header.pipeline else None)
    )


def _project_collaborators(
    settings: Settings, epic: dict[str, Any], header: GoalHeader
) -> tuple[dict[str, str | None], Path | None, str | None]:
    """Read collaborator candidates from the one PA project page named by an epic."""
    project_slug = _collaborator_project_slug(epic, header)
    if not project_slug:
        return {}, None, "collaborators need a project: label or pipeline.collaborators_from"
    if not re.fullmatch(r"[a-z][a-z0-9-]*", project_slug):
        return {}, None, f"invalid collaborator project slug {project_slug!r}"
    path = settings.dirs["pa"] / "kg" / "projects" / f"{project_slug}.md"
    if not path.is_file():
        return {}, path, f"collaborator project page is missing: {path}"
    try:
        project = parse_project(path)
    except OSError as exc:
        return {}, path, f"cannot read collaborator project page {path}: {exc}"
    return {member.ref: member.role for member in project.members}, path, None


def _validate_collaborator(
    settings: Settings, epic: dict[str, Any] | None, member: str
) -> str | None:
    """Return an error when a collaborator is not listed on its pipeline project page."""
    if epic is None:
        return f"{member} needs a pipeline epic to validate its project membership"
    header = goal_header(epic)
    if header is None:
        return f"{member} needs a research pipeline epic to validate its project membership"
    collaborators, path, error = _project_collaborators(settings, epic, header)
    if error:
        return error
    slug = member.split(":", 1)[1]
    if slug not in collaborators:
        return f"{member} is not a member of {path}"
    return None


def _planning_bead(
    issues: list[dict[str, Any]], epic_id: str, round_number: int, stage: str
) -> dict[str, Any] | None:
    return next(
        (
            bead
            for bead in issues
            if f"goal:{epic_id}" in bead_labels(bead)
            and f"planning-round:{round_number}" in bead_labels(bead)
            and f"pipeline-stage:{stage}" in bead_labels(bead)
        ),
        None,
    )


def _critique_beads(
    issues: list[dict[str, Any]], epic_id: str, round_number: int
) -> list[dict[str, Any]]:
    rows = [
        bead
        for bead in issues
        if f"goal:{epic_id}" in bead_labels(bead)
        and f"planning-round:{round_number}" in bead_labels(bead)
        and "pipeline-stage:critique" in bead_labels(bead)
    ]
    rows.sort(key=lambda bead: str(bead.get("external_ref") or bead.get("id") or ""))
    return rows


def _provenance(values: list[Provenance | dict[str, Any] | str]) -> list[Provenance]:
    result: list[Provenance] = []
    for value in values:
        if isinstance(value, Provenance):
            result.append(value)
        elif isinstance(value, dict):
            result.append(Provenance.model_validate(value))
        else:
            source, separator, locator = value.partition("::")
            if source.strip():
                result.append(
                    Provenance(
                        source=source.strip(),
                        locator=locator.strip() if separator and locator.strip() else None,
                    )
                )
    return result


def _child_header(
    xid: str,
    epic_id: str,
    target: date,
    privacy: Privacy,
    *extra: Provenance,
) -> BeadHeader:
    return BeadHeader(
        xid=xid,
        provenance=[
            Provenance(source=f"bead:{epic_id}", locator="research pipeline epic"),
            *extra,
        ],
        deadline=target,
        privacy=privacy,
    )


def _create_pipeline_bead(
    beads: Beads,
    *,
    xid: str,
    epic_id: str,
    title: str,
    body: str,
    target: date,
    privacy: Privacy,
    labels: list[str],
    acceptance: str,
    project: str | None = None,
    extra: Provenance | None = None,
) -> tuple[str, bool]:
    existing = beads.find_by_xid(xid)
    if existing:
        return str(existing.get("id") or xid), False
    common = [f"goal:{epic_id}", f"privacy:{privacy.value}"]
    if project:
        common.append(f"project:{project}")
    created = beads.create(
        title,
        header=_child_header(
            xid,
            epic_id,
            target,
            privacy,
            *([extra] if extra is not None else []),
        ),
        body=body,
        labels=[*common, *labels],
        parent=epic_id,
        acceptance=acceptance,
    )
    return created or xid, True


def _create_critique_bead(
    settings: Settings,
    beads: Beads,
    *,
    epic_id: str,
    round_number: int,
    member: dict[str, Any],
    draft_id: str,
    final_id: str,
    target: date,
    privacy: Privacy,
    project: str | None = None,
) -> tuple[str, bool]:
    member_name = str(member["member"])
    slug = _member_slug(member_name)
    labels = [
        # kind:critique, not kind:review: the review gate must not read a
        # critique's verdict as a verdict on the draft.
        "kind:critique",
        "stage:review",
        "pipeline-stage:critique",
        f"planning-round:{round_number}",
        f"pipeline-member:{slug}",
    ]
    prefix, name = member_name.split(":", 1)
    if prefix == "agent":
        labels.extend([f"role:{member['role']}", f"agent:{name}"])
    elif prefix == "role":
        labels.append(f"role:{name}")
    elif prefix == "person":
        labels.append(f"person:{name}")
    else:
        labels.append(f"collaborator:{name}")
    bead_id, created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:plan{round_number}:critique:{slug}",
        epic_id=epic_id,
        title=f"Critique plan {round_number} as {member_name}",
        body=(
            "Review the draft plan. Return a kind:critique Markdown artifact with Agree, "
            "Disagree, Missing, and Risks sections. End every item with a source or opinion."
        ),
        target=target,
        privacy=privacy,
        labels=labels,
        project=project,
        acceptance="A valid source-labelled critique is saved and commented on the draft.",
    )
    if created:
        dep_type = "related" if prefix in {"person", "collaborator"} else "blocks"
        beads.dep(bead_id, draft_id, dep_type)
        if prefix not in {"person", "collaborator"}:
            beads.dep(final_id, bead_id, "blocks")
    return bead_id, created


def _create_planning_round(
    settings: Settings,
    beads: Beads,
    *,
    epic_id: str,
    round_number: int,
    dependency: str,
    target: date,
    privacy: Privacy,
    team: dict[str, Any] | None,
    project: str | None = None,
) -> dict[str, Any]:
    draft_id, draft_created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:plan{round_number}:draft",
        epic_id=epic_id,
        title=f"Draft research plan {round_number}",
        body="Produce a draft research-planning YAML artifact for team critique.",
        target=target,
        privacy=privacy,
        labels=[
            "kind:design",
            "stage:design",
            "role:group-leader",
            "pipeline-stage:draft",
            f"planning-round:{round_number}",
        ],
        project=project,
        acceptance=f"A valid kind:plan artifact is saved as plan-v{round_number}-draft.yaml.",
    )
    if draft_created:
        beads.dep(draft_id, dependency, "blocks")
    final_id, final_created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:plan{round_number}:final",
        epic_id=epic_id,
        title=f"Finalize research plan {round_number} after discussion",
        body="Resolve every team critique and return the final plan and decision log.",
        target=target,
        privacy=privacy,
        labels=[
            "kind:design",
            "stage:design",
            "role:group-leader",
            "pipeline-stage:final",
            f"planning-round:{round_number}",
        ],
        project=project,
        acceptance=(
            f"Valid kind:plan and kind:decision-log artifacts are saved for plan-v{round_number}."
        ),
    )
    if final_created:
        beads.dep(final_id, draft_id, "blocks")
    critiques: dict[str, str] = {}
    for member in (team or {}).get("team") or []:
        if not isinstance(member, dict) or not str(member.get("member") or "").strip():
            continue
        critique_id, _created = _create_critique_bead(
            settings,
            beads,
            epic_id=epic_id,
            round_number=round_number,
            member=member,
            draft_id=draft_id,
            final_id=final_id,
            target=target,
            privacy=privacy,
            project=project,
        )
        critiques[str(member["member"])] = critique_id
    return {"draft": draft_id, "critiques": critiques, "final": final_id}


def new_pipeline(
    settings: Settings,
    beads: Beads,
    *,
    title: str,
    target: date,
    success: list[str],
    question: str,
    person: str | None,
    project: str | None = None,
    privacy: str = "internal",
    provenance: Sequence[Provenance | dict[str, Any] | str] | None = None,
    host_laptop: str = "laptop",
) -> dict[str, Any]:
    """Create one idempotent research pipeline epic and its first planning round."""
    if not success:
        raise ValueError("a pipeline needs at least one success criterion")
    privacy_value = Privacy(privacy)
    supplied = _provenance(list(provenance or []))
    if not supplied:
        supplied = [Provenance(source="cube pipeline new", locator=title)]
    epic_xid = f"pipeline:{_slug(title)}:{target.isoformat()}"
    existing_epic = beads.find_by_xid(epic_xid)
    epic_id = str(existing_epic.get("id") or "") if existing_epic else ""
    if not epic_id:
        header = GoalHeader(
            xid=epic_xid,
            provenance=supplied,
            deadline=target,
            privacy=privacy_value,
            target=target,
            success=success,
            project=project,
            people=[person] if person else [],
            status="active",
        )
        labels = ["kind:goal", "pipeline:research", f"privacy:{privacy_value.value}"]
        if project:
            labels.append(f"project:{project}")
        created = beads.create(
            title,
            header=header,
            body="Success criteria:\n" + "\n".join(f"- {item}" for item in success),
            type_="epic",
            priority=1,
            labels=labels,
            acceptance="\n".join(success),
        )
        epic_id = created or epic_xid

    collect_id, collect_created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:collect",
        epic_id=epic_id,
        title=f"Collect existing material for {title}",
        body=f"Question: {question.strip()}",
        target=target,
        privacy=privacy_value,
        labels=[
            "pipeline-stage:collect",
            "kind:request",
            "agent:liaison",
            f"host:{host_laptop}",
            # Robert, 2026-09-08 (ADR-0027): a laptop read beyond the readable
            # directories (mail is one) waits for his yes from the start.
            *approval_labels(classify_request(question, settings, host=host_laptop)),
        ],
        project=project,
        acceptance="The liaison records source-backed ideas, links, identifiers and repositories.",
        extra=Provenance(source="Robert request", locator=question.strip()),
    )
    del collect_created
    team_id, team_created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:team",
        epic_id=epic_id,
        title=f"Recruit the project team for {title}",
        body="Recruit the smallest source-backed team that covers the complete research project.",
        target=target,
        privacy=privacy_value,
        labels=[
            "pipeline-stage:team",
            "kind:design",
            "stage:design",
            "role:group-leader",
            "agent:coordinator",
        ],
        project=project,
        acceptance="A valid kind:team artifact is saved as team.yaml.",
    )
    if team_created:
        beads.dep(team_id, collect_id, "blocks")
    round_one = _create_planning_round(
        settings,
        beads,
        epic_id=epic_id,
        round_number=1,
        dependency=team_id,
        target=target,
        privacy=privacy_value,
        team=_read_team(settings, epic_id),
        project=project,
    )
    survey_id, survey_created = _create_pipeline_bead(
        beads,
        xid=f"pipe:{epic_id}:survey",
        epic_id=epic_id,
        title=f"Survey literature for {title}",
        body="Use the literature-review skill and return search-log and reading-list artifacts.",
        target=target,
        privacy=privacy_value,
        labels=["pipeline-stage:survey", "kind:research", "role:senior"],
        project=project,
        acceptance="The search log validates and the reading list has no cite-check errors.",
    )
    if survey_created:
        beads.dep(survey_id, round_one["final"], "blocks")
    return {
        "epic": epic_id,
        "stages": {
            "collect": collect_id,
            "team": team_id,
            "plan1:draft": round_one["draft"],
            "plan1:final": round_one["final"],
            "survey": survey_id,
        },
        "discussion": {"1": round_one},
    }


def _dependencies(bead: dict[str, Any]) -> list[str]:
    raw = bead.get("dependencies") or bead.get("blocked_by") or []
    if not isinstance(raw, list):
        raw = [raw]
    values: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            dep_type = str(item.get("dependency_type") or item.get("type") or "blocks")
            if dep_type == "related":
                continue
        value = item.get("id") if isinstance(item, dict) else item
        if value and str(value) not in values:
            values.append(str(value))
    return values


def _owner(bead: dict[str, Any]) -> str:
    labels = bead_labels(bead)
    return label_value(labels, "agent:") or label_value(labels, "role:") or "Robert"


def _verdict(bead: dict[str, Any] | None) -> str | None:
    labels = bead_labels(bead or {})
    if review_gate.LABEL_APPROVED in labels:
        return "approve"
    if review_gate.LABEL_REVISE in labels:
        return "revise"
    if review_gate.LABEL_REJECTED in labels:
        return "reject"
    return None


def _stage_bead(issues: list[dict[str, Any]], epic_id: str, stage: str) -> dict[str, Any] | None:
    return next(
        (
            bead
            for bead in issues
            if f"goal:{epic_id}" in bead_labels(bead)
            and f"pipeline-stage:{stage}" in bead_labels(bead)
        ),
        None,
    )


def _experiments(issues: list[dict[str, Any]], epic_id: str) -> list[dict[str, Any]]:
    return [
        bead
        for bead in issues
        if f"goal:{epic_id}" in bead_labels(bead)
        and "pipeline-stage:experiments" in bead_labels(bead)
    ]


def _gates(issues: list[dict[str, Any]], epic_id: str) -> list[dict[str, Any]]:
    gates = [
        bead
        for bead in issues
        if f"goal:{epic_id}" in bead_labels(bead) and "pipeline-stage:gate" in bead_labels(bead)
    ]
    gates.sort(key=lambda bead: int(label_value(bead_labels(bead), "gate:") or 0))
    return gates


def pipeline_status(
    settings: Settings, beads: Beads, epic_id: str, *, today: date
) -> dict[str, Any]:
    """Derive the complete pipeline view from ledger state without writing."""
    del today
    epic = beads.show(epic_id)
    header = goal_header(epic)
    if header is None or "pipeline:research" not in bead_labels(epic):
        raise ValueError(f"{epic_id} is not a research pipeline epic")
    issues = beads.list_issues("--all")
    by_id = {str(item.get("id")): item for item in issues if item.get("id")}
    stage_rows: list[dict[str, Any]] = []
    current: str | None = None

    def stage_row(name: str, bead: dict[str, Any] | None, *, blocking: bool = True) -> None:
        nonlocal current
        if bead is None:
            return
        blockers = [dep for dep in _dependencies(bead) if _status(by_id.get(dep, {})) not in CLOSED]
        state = _status(bead)
        stage_rows.append(
            {
                "name": name,
                "bead": str(bead.get("id")),
                "status": state,
                "owner": _owner(bead),
                "blocked_by": blockers,
            }
        )
        if current is None and blocking and state not in CLOSED:
            current = name

    stage_row("collect", _stage_bead(issues, epic_id, "collect"))
    stage_row("team", _stage_bead(issues, epic_id, "team"))
    team_data = _read_team(settings, epic_id) or {}
    team_rows = [
        {
            **dict(item),
            "kind": _member_kind(str(item.get("member") or "")),
            "blocking": _member_kind(str(item.get("member") or "")) in {"agent", "role"},
        }
        for item in team_data.get("team") or []
        if isinstance(item, dict)
    ]
    discussions: list[dict[str, Any]] = []
    for round_number in (1, 2):
        draft = _planning_bead(issues, epic_id, round_number, "draft")
        final = _planning_bead(issues, epic_id, round_number, "final")
        critiques = _critique_beads(issues, epic_id, round_number)
        stage_row(f"plan{round_number}:draft", draft)
        open_blocking: list[dict[str, Any]] = []
        for critique in critiques:
            is_external = _external_member_bead(critique)
            member_slug = label_value(bead_labels(critique), "pipeline-member:")
            stage_row(
                f"plan{round_number}:critique:{member_slug}",
                critique,
                blocking=False,
            )
            if not is_external and _status(critique) not in CLOSED:
                open_blocking.append(critique)
        if current is None and open_blocking:
            current = f"plan{round_number}:critique"
        stage_row(f"plan{round_number}:final", final)
        discussion_dir = _pipeline_dir(settings, epic_id) / "discussion" / f"plan-v{round_number}"
        draft_path = _pipeline_dir(settings, epic_id) / f"plan-v{round_number}-draft.yaml"
        final_path = _pipeline_dir(settings, epic_id) / f"plan-v{round_number}.yaml"
        decision_path = discussion_dir / "decisions.md"
        team_by_slug = {
            _member_slug(str(item.get("member") or "")): str(item.get("member") or "")
            for item in team_rows
        }
        discussions.append(
            {
                "round": round_number,
                "draft": {
                    "bead": str(draft.get("id")) if draft else None,
                    "status": _status(draft) if draft else None,
                    "artifact": str(draft_path) if draft_path.is_file() else None,
                },
                "critiques": [
                    {
                        "member": team_by_slug.get(
                            str(label_value(bead_labels(item), "pipeline-member:") or ""),
                            str(label_value(bead_labels(item), "pipeline-member:") or ""),
                        ),
                        "bead": str(item.get("id")),
                        "status": _status(item),
                    }
                    for item in critiques
                ],
                "final": {
                    "bead": str(final.get("id")) if final else None,
                    "status": _status(final) if final else None,
                    "artifact": str(final_path) if final_path.is_file() else None,
                },
                "decisions": str(decision_path) if decision_path.is_file() else None,
            }
        )
        if round_number == 1:
            stage_row("survey", _stage_bead(issues, epic_id, "survey"))

    survey = _stage_bead(issues, epic_id, "survey")
    round_two = _planning_bead(issues, epic_id, 2, "draft")
    if current is None and survey and _status(survey) in CLOSED and round_two is None:
        current = "plan2:draft"

    experiments = _experiments(issues, epic_id)
    experiment_rows: list[dict[str, Any]] = []
    reviews = {
        label_value(bead_labels(item), "reviews:"): item
        for item in issues
        if "kind:review" in bead_labels(item) and label_value(bead_labels(item), "reviews:")
    }
    for experiment in experiments:
        experiment_id = str(experiment.get("id"))
        review = reviews.get(experiment_id)
        experiment_rows.append(
            {
                "bead": experiment_id,
                "status": _status(experiment),
                "review": (
                    {
                        "bead": str(review.get("id")),
                        "status": _status(review),
                        "verdict": _verdict(review) or _verdict(experiment),
                    }
                    if review
                    else None
                ),
            }
        )
    gates = _gates(issues, epic_id)
    latest_gate = gates[-1] if gates else None
    iteration = int(label_value(bead_labels(latest_gate or {}), "gate:") or 0)
    if current is None:
        if any(_status(item) not in CLOSED for item in experiments):
            current = "experiments"
        elif latest_gate is None or _status(latest_gate) not in CLOSED:
            current = "gate" if experiments else "experiments"
        elif _verdict(latest_gate) == "revise":
            current = "experiments"
        elif _status(epic) not in CLOSED:
            current = "gate"
        else:
            current = "done"
    kill = any(label.startswith("kill:") for label in bead_labels(epic))
    needs_robert = "needs:robert" in bead_labels(epic) or any(
        "needs:robert" in bead_labels(item)
        and f"goal:{epic_id}" in bead_labels(item)
        and _status(item) not in CLOSED
        for item in issues
    )
    stored_status = "done" if _status(epic) in CLOSED or header.status == "done" else header.status
    open_blocking_critiques = [
        item
        for item in _critique_beads(issues, epic_id, 1) + _critique_beads(issues, epic_id, 2)
        if _status(item) not in CLOSED and not _external_member_bead(item)
    ]
    laptop_read_waiting = any(
        "laptop-read:approval" in bead_labels(item)
        and "needs:robert" in bead_labels(item)
        and f"goal:{epic_id}" in bead_labels(item)
        and _status(item) not in CLOSED
        for item in issues
    )
    if kill:
        next_action = "Robert reviews the kill condition and decides whether to stop or restart."
    elif laptop_read_waiting:
        # Robert, 2026-09-08 (ADR-0027): a laptop read beyond the readable directories.
        next_action = (
            "Robert approves the liaison's laptop read; then the liaison collects his sent "
            "mail and existing material."
        )
    elif needs_robert:
        next_action = "Robert reviews the pipeline finding before automatic work can continue."
    elif current == "collect":
        next_action = "The liaison collects Robert's sent mail and existing material next."
    elif current == "team":
        next_action = "The coordinator recruits the smallest source-backed project team next."
    elif current and current.endswith(":critique"):
        round_label = f"planning-round:{current.removeprefix('plan').split(':', 1)[0]}"
        waiting = [
            str(label_value(bead_labels(item), "pipeline-member:") or item.get("id"))
            for item in open_blocking_critiques
            if round_label in bead_labels(item)
        ]
        next_action = "waiting for critiques from " + ", ".join(waiting)
    elif current in {"gate", "plan1:draft", "plan1:final", "plan2:draft", "plan2:final"}:
        next_action = f"The group-leader handles the {current} stage next."
    elif current == "survey":
        next_action = "The senior runs the checked literature survey next."
    elif current == "experiments":
        next_action = (
            "Programmer workers implement the ready experiments, then senior reviews them."
        )
    else:
        next_action = "The research pipeline is complete; no actor is waiting."
    manager_path = _pipeline_dir(settings, epic_id) / "manager.json"
    try:
        manager_data = json.loads(manager_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manager_data = {}
    stale = [
        {
            "bead": str(item.get("id")),
            "stage": str(item.get("external_ref") or "").split(":stale:", 1)[-1],
            "status": _status(item),
        }
        for item in issues
        if str(item.get("external_ref") or "").startswith(f"pipe:{epic_id}:stale:")
        and _status(item) not in CLOSED
    ]
    return {
        "epic": epic_id,
        "title": str(epic.get("title") or epic_id),
        "status": stored_status,
        "stage": current,
        "iteration": iteration,
        "stages": stage_rows,
        "team": team_rows,
        "discussion": discussions,
        "experiments": experiment_rows,
        "gate": {
            "n": iteration,
            "bead": str(latest_gate.get("id")) if latest_gate else None,
            "verdict": _verdict(latest_gate),
        },
        "kill": kill,
        "manager": {
            "lead": str(team_data.get("lead") or "agent:coordinator"),
            "last_review": manager_data.get("last_review"),
            "stale": stale,
        },
        "next": next_action,
    }


@lru_cache(maxsize=8)
def _load_script(root: Path, area: str, name: str) -> ModuleType:
    relative = Path("skills") / area / "scripts" / f"{name}.py"
    candidates = (root / relative, Path(__file__).resolve().parents[1] / relative)
    path = next((item for item in candidates if item.exists()), root / relative)
    spec = importlib.util.spec_from_file_location(f"cube._pipeline_{area}_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import pipeline script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def materialise_inline_artifacts(run_dir: Path, result: RunResult) -> list[Path]:
    """Write artifacts that carry their text inline to the run directory.

    Plan-tier roles run with read-only tools, so a model returns the artifact
    text in ``content``; the file lands at ``run_dir / <basename of path>`` and
    the artifact's ``path`` is rewritten to it. Existing files are never
    overwritten and paths never escape the run directory.
    """
    written: list[Path] = []
    for artifact in result.artifacts:
        if artifact.content is None:
            continue
        name = Path(artifact.path or f"{artifact.kind}.txt").name or f"{artifact.kind}.txt"
        target = (run_dir / "artifacts" / name).resolve()
        if run_dir.resolve() not in target.parents:
            continue
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.content, encoding="utf-8")
            written.append(target)
        artifact.path = str(target)
    return written


def _artifact_source(settings: Settings, run_dir: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    for base in (run_dir, settings.root):
        candidate = base / path
        if candidate.exists():
            return candidate
    return run_dir / path


def _copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)


def _json_entries(cite_check: ModuleType, path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        raw = payload["entries"]
    elif isinstance(payload, dict):
        identifiers = payload.get("identifiers", payload)
        raw = []
        if isinstance(identifiers, dict):
            for field, kind in (("dois", "doi"), ("arxiv", "arxiv"), ("pmids", "pmid")):
                values = identifiers.get(field) or []
                if isinstance(values, str):
                    values = [values]
                raw.extend({"identifier": str(value), "identifier_kind": kind} for value in values)
    else:
        raw = payload
    if not isinstance(raw, list):
        raise ValueError("reading-list JSON must be a list or contain entries")
    entries: list[Any] = []
    for number, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"identifier": item, "title": item}
        if not isinstance(item, dict):
            raise ValueError(f"reading-list entry {number} is not an object")
        identifier = str(item.get("identifier") or item.get("doi") or item.get("url") or "")
        identifier_kind = str(item.get("identifier_kind") or "")
        fields = dict(item.get("fields") or {})
        for key in ("author", "title", "journal", "journaltitle", "year", "doi", "url", "pmid"):
            if item.get(key) and key not in fields:
                fields[key] = str(item[key])
        fields.setdefault("title", identifier)
        if identifier_kind == "doi" or identifier.startswith("10."):
            fields.setdefault("doi", identifier.removeprefix("https://doi.org/"))
        elif identifier_kind == "arxiv" or identifier.lower().startswith("arxiv:"):
            value = identifier.split(":", 1)[-1]
            fields.setdefault("url", f"https://arxiv.org/abs/{value}")
        elif identifier_kind == "pmid" or identifier.lower().startswith("pmid:"):
            value = identifier.split(":", 1)[-1]
            fields.setdefault("pmid", value)
            fields.setdefault("url", f"https://pubmed.ncbi.nlm.nih.gov/{value}/")
        elif identifier.startswith("http"):
            fields.setdefault("url", identifier)
        entries.append(
            cite_check.Entry(
                str(item.get("key") or item.get("id") or f"entry-{number}"),
                str(item.get("type") or "misc"),
                fields,
                str(path),
                number,
            )
        )
    return entries


def validate_team_artifact(
    settings: Settings, payload: Any, *, epic: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Validate and normalize the project team without inferring missing people facts."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {}, ["team artifact must be a YAML mapping"]
    raw_team = payload.get("team")
    if not isinstance(raw_team, list):
        return {}, ["team must be a list"]
    if len(raw_team) > settings.pipeline.max_team:
        errors.append(f"team has {len(raw_team)} members; maximum is {settings.pipeline.max_team}")
    lead = str(payload.get("lead") or "").strip()
    if lead != "agent:coordinator":
        errors.append("lead must be agent:coordinator")
    else:
        try:
            load_agent(settings.root, "coordinator")
        except AgentError as exc:
            errors.append(str(exc))
    current = load_people_data(settings.root / "people.yaml").get("people") or {}
    if not isinstance(current, dict):
        current = {}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    slugs: set[str] = set()
    agent_or_role = 0
    for number, raw in enumerate(raw_team, 1):
        if not isinstance(raw, dict):
            errors.append(f"team member {number} must be a mapping")
            continue
        member = str(raw.get("member") or "").strip()
        why = str(raw.get("why") or "").strip()
        role_name = str(raw.get("role") or "").strip()
        if not member or ":" not in member:
            errors.append(f"team member {number} must use agent:, role:, person:, or collaborator:")
            continue
        prefix, name = member.split(":", 1)
        if not name or prefix not in {"agent", "role", "person", "collaborator"}:
            errors.append(f"invalid team member {member!r}")
            continue
        slug = _member_slug(member)
        if member in seen:
            errors.append(f"duplicate team member {member}")
        if slug in slugs:
            errors.append(f"team member slug collision for {member}")
        seen.add(member)
        slugs.add(slug)
        if not why:
            errors.append(f"{member} needs a source-backed reason")
        elif "\n" in why:
            errors.append(f"{member} reason must be one line")
        if prefix == "agent":
            agent_or_role += 1
            try:
                agent = load_agent(settings.root, name)
                role_name = role_name or agent.role
            except AgentError as exc:
                errors.append(str(exc))
            if role_name:
                try:
                    role = load_role(settings.root, role_name)
                    if role.runtime == "python":
                        errors.append(f"{member} project role {role_name} cannot be a python role")
                except RoleError as exc:
                    errors.append(str(exc))
            else:
                errors.append(f"{member} needs a project role")
        elif prefix == "role":
            agent_or_role += 1
            try:
                role = load_role(settings.root, name)
                if role.runtime == "python":
                    errors.append(f"{member} must be a non-python role")
            except RoleError as exc:
                errors.append(str(exc))
        elif prefix == "person":
            if name not in current:
                errors.append(f"person:{name} is not current in people.yaml")
            elif not role_name:
                errors.append(f"person:{name} needs a project role")
        else:
            collaborator_error = _validate_collaborator(settings, epic, member)
            if collaborator_error:
                errors.append(collaborator_error)
            if not role_name:
                errors.append(f"collaborator:{name} needs a project role")
        row = {"member": member}
        if role_name:
            row["role"] = role_name
        row["why"] = why
        normalized.append(row)
    if not agent_or_role:
        errors.append("team needs at least one agent or role member")
    return {"team": normalized, "lead": lead}, errors


def record_team_artifact(
    settings: Settings,
    beads: Beads,
    bead: dict[str, Any],
    run_dir: Path,
    result: RunResult,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Validate, save, and expand a team artifact into round-one critique beads."""
    labels = bead_labels(bead)
    epic_id = label_value(labels, "goal:")
    report: dict[str, Any] = {"stage": "team", "paths": [], "errors": [], "close": False}
    if not epic_id:
        report["errors"].append("team bead has no goal label")
        return report
    epic = beads.show(epic_id)
    privacy = _pipeline_privacy(epic)
    checked = today or date.today()

    def invalid(error: str) -> dict[str, Any]:
        report["errors"].append(error)
        beads.add_labels(str(bead.get("id")), ["needs:robert"])
        _finding(
            beads,
            epic_id,
            f"pipe:{epic_id}:team-invalid",
            "Research pipeline team artifact is invalid",
            "\n".join(str(item) for item in report["errors"]),
            checked,
            privacy,
        )
        return report

    artifact = next((item for item in result.artifacts if item.kind == "team"), None)
    if artifact is None:
        return invalid("missing kind:team artifact")
    source = _artifact_source(settings, run_dir, artifact.path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return invalid(f"team artifact: {exc}")
    normalized, errors = validate_team_artifact(settings, payload, epic=epic)
    report["errors"].extend(errors)
    if errors:
        beads.add_labels(str(bead.get("id")), ["needs:robert"])
        _finding(
            beads,
            epic_id,
            f"pipe:{epic_id}:team-invalid",
            "Research pipeline team artifact is invalid",
            "\n".join(errors),
            checked,
            privacy,
        )
        return report
    target = _team_path(settings, epic_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
    invalid_finding = beads.find_by_xid(f"pipe:{epic_id}:team-invalid")
    if invalid_finding and _status(invalid_finding) not in CLOSED:
        beads.close(
            str(invalid_finding.get("id")), "a valid replacement team artifact was recorded"
        )
    if "needs:robert" in labels:
        beads.remove_labels(str(bead.get("id")), ["needs:robert"])
    header = goal_header(epic)
    if header is None:
        report["errors"].append("pipeline epic has no valid goal header")
        return report
    planning = _create_planning_round(
        settings,
        beads,
        epic_id=epic_id,
        round_number=1,
        dependency=str(bead.get("id")),
        target=header.target,
        privacy=privacy,
        team=normalized,
        project=header.project,
    )
    report["paths"].append(str(target))
    report["critiques"] = planning["critiques"]
    report["close"] = True
    return report


CRITIQUE_SECTIONS = ("Agree", "Disagree", "Missing", "Risks")


_SOURCE_MARKER = re.compile(
    r"source:|\bopinion\b|\blines?\s+\d|\bparagraphs?\s+\d|\bid:|\bdoi\b|10\.\d{4,9}/|https?://|"
    r"\bbead\b|open_items|\.(?:md|tex|yaml|yml|py|org|cff|toml|json)\b|\bsections?\s+[A-Za-z0-9]",
    re.IGNORECASE,
)


def _critique_items(text: str) -> list[str]:
    """Bullet items of a critique, with wrapped continuation lines joined."""
    items: list[str] = []
    for line in text.splitlines():
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line):
            items.append(line.strip())
        elif items and line.strip() and not line.lstrip().startswith("#"):
            items[-1] = items[-1] + " " + line.strip()
        elif not line.strip():
            continue
    return items


def _critique_errors(text: str) -> list[str]:
    errors: list[str] = []
    for section in CRITIQUE_SECTIONS:
        if not re.search(rf"(?m)^#+\s+{re.escape(section)}\s*$", text):
            errors.append(f"critique is missing the {section} section")
    for item in _critique_items(text):
        # A source anywhere in the item counts: models cite in parentheses mid
        # sentence and wrap long items over several lines.
        if not _SOURCE_MARKER.search(item):
            errors.append(f"critique item needs a source or the word opinion: {item[:120]}")
    return errors


def record_plan_artifacts(
    settings: Settings,
    bead: dict[str, Any],
    run_dir: Path,
    result: RunResult,
    *,
    beads: Beads | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Copy pipeline artifacts and return whether their stage may close."""
    materialise_inline_artifacts(run_dir, result)
    labels = bead_labels(bead)
    stage = label_value(labels, "pipeline-stage:")
    epic_id = label_value(labels, "goal:")
    report: dict[str, Any] = {"stage": stage, "paths": [], "errors": [], "close": False}
    if not epic_id:
        return report
    if stage == "team":
        if beads is None:
            report["errors"].append("team artifact handling requires a beads ledger")
            return report
        return record_team_artifact(settings, beads, bead, run_dir, result, today=today)
    if stage not in {"draft", "critique", "final", "survey"}:
        return report
    destination = _pipeline_dir(settings, epic_id)
    artifacts = {artifact.kind: artifact for artifact in result.artifacts}
    round_number = int(label_value(labels, "planning-round:") or 0)
    if stage == "draft":
        artifact = artifacts.get("plan")
        if artifact is None:
            report["errors"].append("missing kind:plan artifact")
            return report
        target = destination / f"plan-v{round_number}-draft.yaml"
        try:
            _copy(_artifact_source(settings, run_dir, artifact.path), target)
        except OSError as exc:
            report["errors"].append(f"plan artifact: {exc}")
            return report
        report["paths"].append(str(target))
        report["close"] = True
        return report

    if stage == "critique":
        artifact = artifacts.get("critique")
        if artifact is None:
            report["errors"].append("missing kind:critique artifact")
            return report
        member_slug = label_value(labels, "pipeline-member:") or "member"
        target = destination / "discussion" / f"plan-v{round_number}" / f"{member_slug}.md"
        try:
            source = _artifact_source(settings, run_dir, artifact.path)
            text = source.read_text(encoding="utf-8")
            report["errors"].extend(_critique_errors(text))
            if report["errors"]:
                return report
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            report["errors"].append(f"critique artifact: {exc}")
            return report
        if beads is not None:
            issues = beads.list_issues("--all")
            draft = _planning_bead(issues, epic_id, round_number, "draft")
            if draft:
                beads.comment(
                    str(draft.get("id")),
                    f"Critique from {member_slug}:\n\n{text.rstrip()}",
                )
        report["paths"].append(str(target))
        report["close"] = True
        return report

    if stage == "final":
        plan_artifact = artifacts.get("plan")
        decisions_artifact = artifacts.get("decision-log")
        if plan_artifact is None:
            report["errors"].append("missing kind:plan artifact")
        if decisions_artifact is None:
            report["errors"].append("missing kind:decision-log artifact")
        if report["errors"]:
            return report
        assert plan_artifact is not None and decisions_artifact is not None
        plan_target = destination / f"plan-v{round_number}.yaml"
        decisions_target = destination / "discussion" / f"plan-v{round_number}" / "decisions.md"
        try:
            decision_source = _artifact_source(settings, run_dir, decisions_artifact.path)
            decision_text = decision_source.read_text(encoding="utf-8")
            if not re.search(r"\b(?:accepted|rejected)\b", decision_text, re.I):
                report["errors"].append(
                    "decision log must mark critique items accepted or rejected and say why"
                )
                return report
            _copy(_artifact_source(settings, run_dir, plan_artifact.path), plan_target)
            _copy(decision_source, decisions_target)
        except OSError as exc:
            report["errors"].append(f"final plan artifacts: {exc}")
            return report
        report["paths"].extend([str(plan_target), str(decisions_target)])
        report["close"] = True
        return report

    errors: list[str] = report["errors"]
    search_artifact = artifacts.get("search-log")
    reading_artifact = artifacts.get("reading-list")
    if search_artifact is None:
        errors.append("missing kind:search-log artifact")
    if reading_artifact is None:
        errors.append("missing kind:reading-list artifact")
    if errors:
        return report
    assert search_artifact is not None and reading_artifact is not None
    search_target = destination / "search-log.jsonl"
    reading_source = _artifact_source(settings, run_dir, reading_artifact.path)
    reading_suffix = ".json" if reading_source.suffix.lower() == ".json" else ".bib"
    reading_target = destination / f"reading-list{reading_suffix}"
    try:
        _copy(_artifact_source(settings, run_dir, search_artifact.path), search_target)
        _copy(reading_source, reading_target)
        report["paths"].extend([str(search_target), str(reading_target)])
        search_log = _load_script(settings.root, "literature-review", "search_log")
        _flow, problems = search_log.validate(search_log.read_log(search_target))
        errors.extend(f"search-log: {problem}" for problem in problems)
        cite_check = _load_script(settings.root, "literature-review", "cite_check")
        if reading_suffix == ".json":
            entries = _json_entries(cite_check, reading_target)
            findings: list[Any] = []
        else:
            entries, findings = cite_check.parse_bibtex(reading_target)
        findings.extend(cite_check.offline_checks(entries, date.today()))
        errors.extend(finding.render() for finding in findings if finding.severity == "error")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    report["close"] = not errors
    return report


def write_rehearsal_search_log(path: Path, *, today: date) -> None:
    """Write the smallest valid append-only search log for offline rehearsal."""
    search_log = _load_script(
        Path(__file__).resolve().parents[1], "literature-review", "search_log"
    )
    entry = {
        "type": "protocol",
        "date": today.isoformat(),
        "question": "Fixture pipeline rehearsal",
        "review_type": "systematized",
        "protocol_path": "fixture",
        "seq": 1,
    }
    entry["chain"] = search_log.chain_of("", entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")


def stage_prompt(
    settings: Settings,
    epic: dict[str, Any],
    stage: dict[str, Any],
    *,
    beads: Beads | None = None,
) -> str:
    """Build the source-backed pipeline context supplied at marshal dispatch."""
    epic_id = str(epic.get("id") or label_value(bead_labels(stage), "goal:") or "")
    ledger = beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True)
    try:
        issues = ledger.list_issues("--all") if ledger.available() else []
    except Exception:  # noqa: BLE001 - prompt construction remains best effort
        issues = []
    collect = _stage_bead(issues, epic_id, "collect")
    team_data = _read_team(settings, epic_id) or {"team": [], "lead": "agent:coordinator"}
    agents, agent_errors = load_all_agents(settings.root)
    roles, role_errors = load_all(settings.root)
    people = load_people_data(settings.root / "people.yaml").get("people") or {}
    if not isinstance(people, dict):
        people = {}
    context: dict[str, Any] = {
        "epic": {key: epic.get(key) for key in ("id", "title", "description")},
        "stage": {
            key: stage.get(key)
            for key in ("id", "title", "description", "labels", "acceptance_criteria")
        },
        "collect": str((collect or {}).get("description") or ""),
        "team": team_data,
    }
    stage_name = label_value(bead_labels(stage), "pipeline-stage:") or "work"
    round_number = int(label_value(bead_labels(stage), "planning-round:") or 0)
    if stage_name in {"team", "recruit"}:
        context["standing_agents"] = [
            {
                "member": f"agent:{name}",
                "role": agent.role,
                "topics": agent.topics,
                "source": f"agents/{name}.yaml",
            }
            for name, agent in agents.items()
        ]
        context["agent_errors"] = agent_errors
        context["current_roster"] = [
            {
                "member": f"person:{slug}",
                "role": row.get("role"),
                "program": row.get("program"),
                "expertise": row.get("expertise") or row.get("topics") or [],
                "source": row.get("source") or "people.yaml",
            }
            for slug, row in people.items()
            if isinstance(row, dict)
        ]
        context["role_catalog"] = [
            {
                "member": f"role:{name}",
                "summary": role.summary,
                "source": f"roles/{name}.yaml",
            }
            for name, role in roles.items()
            if role.runtime != "python"
        ]
        context["role_errors"] = role_errors
        header = goal_header(epic)
        if header is not None:
            collaborators, path, collaborator_error = _project_collaborators(settings, epic, header)
            context["project_collaborators"] = [
                {
                    "member": f"collaborator:{slug}",
                    "role": role,
                    "source": str(path),
                }
                for slug, role in collaborators.items()
            ]
            if collaborator_error:
                context["project_collaborator_error"] = collaborator_error
    instruction = "Complete the assigned pipeline stage and keep every claim source-backed."
    if stage_name == "team":
        instruction = (
            "Recruit the smallest team that covers planning, literature, implementation, and "
            "review. Give one source-backed, one-line reason per member. Return a YAML artifact "
            "with kind team using the team and lead schema in the bead. People must be current."
        )
    elif stage_name == "draft":
        instruction = (
            f"Write the draft research plan and return it as kind plan for plan-v{round_number}."
        )
    elif stage_name == "critique":
        instruction = (
            "Return kind critique Markdown with sections Agree, Disagree, Missing, and Risks. "
            "End every list item with a source or the word opinion."
        )
    elif stage_name == "final":
        discussion_dir = _pipeline_dir(settings, epic_id) / "discussion" / f"plan-v{round_number}"
        draft_path = _pipeline_dir(settings, epic_id) / f"plan-v{round_number}-draft.yaml"
        context["draft"] = (
            draft_path.read_text(encoding="utf-8") if draft_path.is_file() else "(missing)"
        )
        context["critiques"] = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(discussion_dir.glob("*.md"))
            if path.name != "decisions.md"
        }
        context["person_critique_comments"] = [
            {
                "member": label_value(bead_labels(item), "person:"),
                "comments": item.get("comments") or [],
            }
            for item in _critique_beads(issues, epic_id, round_number)
            if any(label.startswith("person:") for label in bead_labels(item))
            and item.get("comments")
        ]
        instruction = (
            "Resolve every available critique. Return kind plan for the final plan and kind "
            "decision-log Markdown that marks each critique item accepted or rejected and says why."
        )
    elif stage_name == "recruit":
        instruction = (
            "Decide this recruitment request. You must call cube pipeline recruit with --apply, "
            "using --deny when the candidate should not join. Candidate agents and topics are "
            "listed."
        )
    ask_instruction = (
        f"To ask a team member for help, run `cube pipeline ask {epic_id} --from <you> "
        "--to <member> '<question>' --apply`. To involve anyone who is not on the team, run "
        "the same command; it becomes a recruitment request for the coordinator. Never contact "
        "a person directly. Collaborators are outside the group: never contact them; anything for "
        "them becomes an approval item for Robert."
    )
    artifact_instruction = (
        "Artifacts: you may have no Write tool. Return every artifact (team, plan, critique, "
        "decision-log, search-log, reading-list) inside the JSON result's artifacts list as "
        '{"kind": ..., "path": "<file name>", "content": "<the full text>"}; the cube saves '
        "the file and validates it. Do not report an artifact you did not include."
    )
    return (
        instruction
        + "\n\n"
        + ask_instruction
        + "\n\n"
        + artifact_instruction
        + "\n\n"
        + json.dumps(context, indent=1, ensure_ascii=False, default=str)
    )


def _next_number(beads: Beads, prefix: str) -> int:
    numbers: list[int] = []
    for item in beads.list_issues("--all"):
        xid = str(item.get("external_ref") or "")
        if not xid.startswith(prefix):
            continue
        suffix = xid.removeprefix(prefix)
        if suffix.isdigit():
            numbers.append(int(suffix))
    return max(numbers, default=0) + 1


def _append_thread(settings: Settings, epic_id: str, row: dict[str, Any]) -> Path:
    path = _pipeline_dir(settings, epic_id) / "discussion" / "threads.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def ask(
    settings: Settings,
    beads: Beads,
    epic_id: str,
    *,
    from_member: str,
    to_member: str,
    text: str,
    dry_run: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Route an internal project question or gate recruitment and person contact."""
    if dry_run:
        beads.dry_run = True
    if not text.strip():
        raise ValueError("pipeline ask needs non-empty text")
    if not re.fullmatch(r"(?:agent|role):[a-z][a-z0-9-]*", from_member):
        raise ValueError("--from must be agent:<name> or role:<name>")
    if not re.fullmatch(r"(?:agent|role|person|collaborator):[a-z][a-z0-9-]*", to_member):
        raise ValueError(
            "--to must be agent:<name>, role:<name>, person:<slug>, or collaborator:<slug>"
        )
    epic = beads.show(epic_id)
    if "pipeline:research" not in bead_labels(epic):
        raise ValueError(f"{epic_id} is not a research pipeline epic")
    epic_header = goal_header(epic)
    if epic_header is None:
        raise ValueError(f"{epic_id} has no valid goal header")
    team_data = _read_team(settings, epic_id)
    if not team_data:
        raise ValueError(f"pipeline {epic_id} has no valid team artifact")
    members = {
        str(item.get("member")) for item in team_data.get("team") or [] if isinstance(item, dict)
    }
    if from_member not in members:
        raise ValueError(f"sender {from_member} is not on the pipeline team")
    timestamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    privacy = _pipeline_privacy(epic)
    if to_member.startswith(("person:", "collaborator:")):
        member_kind, person = to_member.split(":", 1)
        current = load_people_data(settings.root / "people.yaml").get("people") or {}
        if member_kind == "person" and (not isinstance(current, dict) or person not in current):
            raise ValueError(f"person:{person} is not current in people.yaml")
        if member_kind == "collaborator":
            collaborator_error = _validate_collaborator(settings, epic, to_member)
            if collaborator_error:
                raise ValueError(collaborator_error)
        prefix = f"pipe:{epic_id}:contact:{person}:"
        number = _next_number(beads, prefix)
        approval = beads.create(
            f"Approve pipeline contact with {member_kind}:{person}",
            header=BeadHeader(
                xid=f"{prefix}{number}",
                provenance=[
                    Provenance(
                        source=f"bead:{epic_id}",
                        locator=f"pipeline ask from {from_member}",
                        seen=(now or datetime.now(UTC)).date(),
                    )
                ],
                deadline=epic_header.target,
                privacy=privacy,
            ),
            body=f"From: {from_member}\nTo: {to_member}\nQuestion: {text.strip()}",
            labels=[
                "kind:outbound",
                "needs:robert",
                f"goal:{epic_id}",
                f"{member_kind}:{person}",
                f"privacy:{privacy.value}",
            ],
            parent=epic_id,
            acceptance="Robert approves or declines contact. Nothing is sent by this bead.",
        )
        return {
            "delivered": False,
            "approval": approval,
            "recruit_request": None,
            "dry_run": dry_run,
        }
    if to_member not in members:
        candidate_prefix, candidate_name = to_member.split(":", 1)
        if candidate_prefix == "agent":
            load_agent(settings.root, candidate_name)
        else:
            candidate_role = load_role(settings.root, candidate_name)
            if candidate_role.runtime == "python":
                raise ValueError(f"{to_member} is a python role and cannot join a project team")
        slug = _member_slug(to_member)
        prefix = f"pipe:{epic_id}:recruit:{slug}:"
        number = _next_number(beads, prefix)
        labels = [
            "kind:request",
            "agent:coordinator",
            "pipeline-stage:recruit",
            f"goal:{epic_id}",
            f"privacy:{privacy.value}",
        ]
        if settings.pipeline.autonomy.recruit == "robert":
            labels.append("needs:robert")
        request = beads.create(
            f"Decide recruitment of {to_member}",
            header=BeadHeader(
                xid=f"{prefix}{number}",
                provenance=[
                    Provenance(
                        source=f"bead:{epic_id}",
                        locator=f"recruitment request from {from_member}",
                        seen=(now or datetime.now(UTC)).date(),
                    )
                ],
                deadline=epic_header.target,
                privacy=privacy,
            ),
            body=(
                f"From: {from_member}\nCandidate: {to_member}\n"
                f"Question: {from_member} asks to bring {to_member} into the team: {text.strip()}"
            ),
            labels=labels,
            parent=epic_id,
            acceptance="The coordinator or Robert records a recruit or deny decision.",
        )
        return {
            "delivered": False,
            "approval": None,
            "recruit_request": request,
            "dry_run": dry_run,
        }
    delivery: str
    if to_member.startswith("agent:"):
        agent = load_agent(settings.root, to_member.split(":", 1)[1])
        if not dry_run:
            append_inbox(
                settings.root,
                agent,
                text.strip(),
                sender=from_member,
                delivered=False,
            )
        delivery = f"inbox:{to_member}"
    else:
        role_name = to_member.split(":", 1)[1]
        load_role(settings.root, role_name)
        prefix = f"pipe:{epic_id}:help:"
        number = _next_number(beads, prefix)
        help_id = beads.create(
            f"Pipeline help requested from role:{role_name}",
            header=BeadHeader(
                xid=f"{prefix}{number}",
                provenance=[
                    Provenance(
                        source=f"bead:{epic_id}",
                        locator=f"help request from {from_member}",
                        seen=(now or datetime.now(UTC)).date(),
                    )
                ],
                deadline=epic_header.target,
                privacy=privacy,
            ),
            body=f"From: {from_member}\nQuestion: {text.strip()}",
            labels=[
                "kind:request",
                f"role:{role_name}",
                f"goal:{epic_id}",
                f"privacy:{privacy.value}",
            ],
            parent=epic_id,
            acceptance="The role answers the source-backed help request on the epic.",
        )
        delivery = f"bead:{help_id or prefix + str(number)}"
    thread = {
        "ts": timestamp,
        "from": from_member,
        "to": to_member,
        "text": text.strip(),
        "delivery": delivery,
    }
    thread_path = None
    if not dry_run:
        thread_path = str(_append_thread(settings, epic_id, thread))
        beads.comment(
            epic_id,
            f"Pipeline discussion: {from_member} asked {to_member}: {text.strip()} [{delivery}]",
        )
    return {
        "delivered": True,
        "delivery": delivery,
        "thread": thread_path,
        "approval": None,
        "recruit_request": None,
        "dry_run": dry_run,
    }


def recruit(
    settings: Settings,
    beads: Beads,
    epic_id: str,
    *,
    member: str,
    role_name: str | None,
    why: str,
    deny: bool,
    dry_run: bool,
    today: date | None = None,
) -> dict[str, Any]:
    """Apply the coordinator's idempotent recruitment decision."""
    if dry_run:
        beads.dry_run = True
    if not re.fullmatch(r"(?:agent|role|person|collaborator):[a-z][a-z0-9-]*", member):
        raise ValueError(
            "--member must be agent:<name>, role:<name>, person:<slug>, or collaborator:<slug>"
        )
    if not why.strip() or "\n" in why.strip():
        raise ValueError("--why must be one non-empty line")
    epic = beads.show(epic_id)
    header = goal_header(epic)
    if header is None or "pipeline:research" not in bead_labels(epic):
        raise ValueError(f"{epic_id} is not a research pipeline epic")
    team_data = _read_team(settings, epic_id)
    if not team_data:
        raise ValueError(f"pipeline {epic_id} has no valid team artifact")
    request_prefix = f"pipe:{epic_id}:recruit:{_member_slug(member)}:"
    requests = [
        item
        for item in beads.list_issues("--all")
        if str(item.get("external_ref") or "").startswith(request_prefix)
        and _status(item) not in CLOSED
    ]
    if deny:
        closed: list[str] = []
        for request in requests:
            request_id = str(request.get("id"))
            beads.close(request_id, f"denied: {why.strip()}")
            if not dry_run:
                closed.append(request_id)
        if not dry_run:
            beads.comment(epic_id, f"Recruitment denied for {member}: {why.strip()}")
        return {
            "member": member,
            "added": False,
            "denied": True,
            "closed_requests": closed,
            "critique": None,
            "dry_run": dry_run,
        }
    row: dict[str, Any] = {"member": member, "why": why.strip()}
    if role_name:
        row["role"] = role_name
    existing_members = [
        dict(item) for item in team_data.get("team") or [] if isinstance(item, dict)
    ]
    existing = next((item for item in existing_members if item.get("member") == member), None)
    added = existing is None
    normalized, errors = validate_team_artifact(
        settings,
        {
            "team": [*existing_members, row] if added else existing_members,
            "lead": team_data.get("lead"),
        },
        epic=epic,
    )
    if errors:
        raise ValueError("; ".join(errors))
    if added:
        team_data = normalized
        if not dry_run:
            _team_path(settings, epic_id).write_text(
                yaml.safe_dump(team_data, sort_keys=False), encoding="utf-8"
            )
    else:
        assert existing is not None
        row = dict(existing)
    closed = []
    for request in requests:
        request_id = str(request.get("id"))
        beads.close(request_id, f"recruited: {why.strip()}")
        if not dry_run:
            closed.append(request_id)
    issues = beads.list_issues("--all")
    open_rounds = [
        number
        for number in (1, 2)
        if (final := _planning_bead(issues, epic_id, number, "final")) is not None
        and _status(final) not in CLOSED
    ]
    critique_id: str | None = None
    if open_rounds:
        round_number = max(open_rounds)
        draft = _planning_bead(issues, epic_id, round_number, "draft")
        final = _planning_bead(issues, epic_id, round_number, "final")
        if draft and final:
            critique_id, _created = _create_critique_bead(
                settings,
                beads,
                epic_id=epic_id,
                round_number=round_number,
                member=row,
                draft_id=str(draft.get("id")),
                final_id=str(final.get("id")),
                target=header.target,
                privacy=header.privacy,
                project=header.project,
            )
    if not dry_run:
        beads.comment(
            epic_id,
            f"Recruitment {'accepted' if added else 'already present'} for {member}: {why.strip()}",
        )
    return {
        "member": member,
        "added": added,
        "denied": False,
        "closed_requests": closed,
        "critique": critique_id,
        "dry_run": dry_run,
    }


def _finding(
    beads: Beads,
    epic_id: str,
    xid: str,
    title: str,
    body: str,
    today: date,
    privacy: Privacy,
) -> str | None:
    existing = beads.find_by_xid(xid)
    if existing:
        return None
    return beads.create(
        title,
        header=BeadHeader(
            xid=xid,
            provenance=[
                Provenance(source=f"bead:{epic_id}", locator="pipeline transition", seen=today)
            ],
            deadline=today,
            privacy=privacy,
        ),
        body=body,
        priority=1,
        labels=["kind:finding", "needs:robert", f"goal:{epic_id}", f"privacy:{privacy.value}"],
        parent=epic_id,
    )


def _pipeline_privacy(epic: dict[str, Any]) -> Privacy:
    header = goal_header(epic)
    return header.privacy if header else Privacy.internal


def _create_gate(
    beads: Beads,
    epic_id: str,
    number: int,
    dependencies: list[str],
    privacy: Privacy,
    today: date,
) -> str | None:
    xid = f"pipe:{epic_id}:gate:{number}"
    existing = beads.find_by_xid(xid)
    if existing:
        return str(existing.get("id") or "")
    gate = beads.create(
        f"Research pipeline gate {number}",
        header=BeadHeader(
            xid=xid,
            provenance=[
                Provenance(source=f"bead:{epic_id}", locator=f"pipeline gate {number}", seen=today)
            ],
            deadline=today,
            privacy=privacy,
        ),
        body="Review all experiment results and return approve, revise or reject with evidence.",
        labels=[
            f"goal:{epic_id}",
            "pipeline-stage:gate",
            f"privacy:{privacy.value}",
            "kind:review",
            "stage:review",
            "role:group-leader",
            "tier:plan",
            f"gate:{number}",
            "producer:programmer",
        ],
        parent=epic_id,
        acceptance="The verdict cites experiment evidence and is approve, revise or reject.",
    )
    if gate:
        for dependency in dependencies:
            beads.dep(gate, dependency, "blocks")
    return gate


def _done_description(epic: dict[str, Any]) -> str:
    header = goal_header(epic)
    if header is None:
        raise ValueError("pipeline epic has no valid goal header")
    description = str(epic.get("description") or "")
    end = description.find("\n---", 4)
    body = description[end + 4 :].lstrip("\n") if end >= 0 else ""
    return header.model_copy(update={"status": "done"}).render() + ("\n" + body if body else "")


def _kill_comment(experiments: list[dict[str, Any]]) -> str | None:
    for experiment in experiments:
        if any(label.startswith("kill:") for label in bead_labels(experiment)):
            return f"{experiment.get('id')} carries a kill label"
        for comment in experiment.get("comments") or []:
            text = str(comment.get("text") if isinstance(comment, dict) else comment)
            match = re.search(r"(?m)^KILL:\s*(.+)$", text)
            if match:
                return f"{experiment.get('id')}: {match.group(1).strip()}"
    return None


def _stage_key(bead: dict[str, Any]) -> str:
    labels = bead_labels(bead)
    stage = label_value(labels, "pipeline-stage:") or "work"
    round_number = label_value(labels, "planning-round:")
    member = label_value(labels, "pipeline-member:")
    parts = [f"plan{round_number}" if round_number else "", stage, member or ""]
    return _slug(":".join(part for part in parts if part))


def review_pipeline_progress(
    settings: Settings,
    beads: Beads,
    epic_id: str,
    *,
    now: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    """Record one zero-token coordinator review and idempotent stale findings."""
    if dry_run:
        beads.dry_run = True
    epic = beads.show(epic_id)
    privacy = _pipeline_privacy(epic)
    issues = beads.list_issues("--all")
    ready_ids = {str(item.get("id")) for item in beads.ready()}
    from cube.engine.lease import live_leases  # noqa: PLC0415

    leased_ids = {lease.bead for lease in live_leases(settings.state_dir(), now)}
    cutoff = now - timedelta(hours=settings.pipeline.stale_hours)
    stale_rows: list[dict[str, Any]] = []
    pipeline_issues = [item for item in issues if f"goal:{epic_id}" in bead_labels(item)]
    for item in pipeline_issues:
        item_id = str(item.get("id") or "")
        if (
            not item_id
            or item_id not in ready_ids
            or item_id in leased_ids
            or _status(item) in CLOSED
            or "needs:robert" in bead_labels(item)
            or item.get("comments")
            or _external_member_bead(item)
        ):
            continue
        try:
            created = datetime.fromisoformat(str(item.get("created_at") or ""))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
        except ValueError:
            continue
        if created > cutoff:
            continue
        key = _stage_key(item)
        reason = f"{item_id} has been ready and undispatched since {created.isoformat()}"
        finding = _finding(
            beads,
            epic_id,
            f"pipe:{epic_id}:stale:{key}",
            f"Research pipeline stage is stale: {key}",
            reason,
            now.date(),
            privacy,
        )
        stale_rows.append({"stage": key, "bead": item_id, "finding": finding, "why": reason})
    for round_number in (1, 2):
        final = _planning_bead(issues, epic_id, round_number, "final")
        if final is None or _status(final) in CLOSED:
            continue
        blockers = [
            dep
            for dep in _dependencies(final)
            if _status(next((x for x in issues if str(x.get("id")) == dep), {})) not in CLOSED
        ]
        if blockers:
            continue
        for critique in _critique_beads(issues, epic_id, round_number):
            member_kind = next(
                (
                    kind
                    for kind in ("person", "collaborator")
                    if label_value(bead_labels(critique), f"{kind}:")
                ),
                None,
            )
            member = label_value(bead_labels(critique), f"{member_kind}:") if member_kind else None
            if not member_kind or not member or _status(critique) in CLOSED:
                continue
            key = f"plan{round_number}-{member_kind}-critique-{member}"
            reason = (
                f"{member_kind}:{member} critique is still open at the final step; it does not "
                "block "
                "the pipeline"
            )
            finding = _finding(
                beads,
                epic_id,
                f"pipe:{epic_id}:stale:{key}",
                f"Optional {member_kind} critique is still open: {member}",
                reason,
                now.date(),
                privacy,
            )
            stale_rows.append(
                {
                    "stage": key,
                    "bead": str(critique.get("id")),
                    "finding": finding,
                    "why": reason,
                }
            )
    manager = {
        "lead": str((_read_team(settings, epic_id) or {}).get("lead") or "agent:coordinator"),
        "last_review": now.isoformat(timespec="seconds"),
        "stale": stale_rows,
    }
    if not dry_run:
        path = _pipeline_dir(settings, epic_id) / "manager.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manager, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manager


def review_open_pipelines(
    settings: Settings,
    beads: Beads,
    *,
    now: datetime,
    dry_run: bool,
) -> list[dict[str, Any]]:
    """Review every open pipeline for the coordinator workday briefing."""
    rows: list[dict[str, Any]] = []
    for epic in list_pipeline_epics(beads, open_only=True):
        epic_id = str(epic.get("id"))
        manager = review_pipeline_progress(settings, beads, epic_id, now=now, dry_run=dry_run)
        status = pipeline_status(settings, beads, epic_id, today=now.date())
        rows.append(
            {
                "epic": epic_id,
                "stage": status["stage"],
                "next": status["next"],
                "manager": manager,
            }
        )
    return rows


def advance(
    settings: Settings,
    beads: Beads,
    epic_id: str,
    *,
    today: date,
    dry_run: bool,
) -> dict[str, Any]:
    """Apply one deterministic pipeline transition and no model work."""
    if dry_run:
        beads.dry_run = True
    epic = beads.show(epic_id)
    header = goal_header(epic)
    if header is None or "pipeline:research" not in bead_labels(epic):
        raise ValueError(f"{epic_id} is not a research pipeline epic")
    created: list[str] = []
    closed: list[str] = []
    flagged: list[str] = []
    issues = beads.list_issues("--all")
    privacy = _pipeline_privacy(epic)
    experiments = _experiments(issues, epic_id)
    kill_reason = _kill_comment(experiments)
    if kill_reason:
        finding = _finding(
            beads,
            epic_id,
            f"pipe:{epic_id}:kill",
            "Research pipeline kill criterion fired",
            kill_reason,
            today,
            privacy,
        )
        beads.add_labels(epic_id, ["needs:robert", "kill:criterion"])
        if finding:
            created.append(finding)
        flagged.append(epic_id)
    else:
        survey = _stage_bead(issues, epic_id, "survey")
        round_two = _planning_bead(issues, epic_id, 2, "draft")
        if survey and _status(survey) in CLOSED and round_two is None:
            team = _read_team(settings, epic_id)
            if team is None:
                finding = _finding(
                    beads,
                    epic_id,
                    f"pipe:{epic_id}:team-missing",
                    "Research pipeline team artifact is missing",
                    "Round two cannot start without runs/pipelines/<epic>/team.yaml.",
                    today,
                    privacy,
                )
                beads.add_labels(epic_id, ["needs:robert"])
                if finding:
                    created.append(finding)
                flagged.append(epic_id)
            else:
                before_ids = {str(item.get("id")) for item in issues}
                _create_planning_round(
                    settings,
                    beads,
                    epic_id=epic_id,
                    round_number=2,
                    dependency=str(survey.get("id")),
                    target=header.target,
                    privacy=privacy,
                    team=team,
                    project=header.project,
                )
                if not beads.dry_run:
                    after_round = beads.list_issues("--all")
                    created.extend(
                        str(item.get("id"))
                        for item in after_round
                        if str(item.get("id")) not in before_ids
                    )
                    issues = after_round
        issues = beads.list_issues("--all")
        experiments = _experiments(issues, epic_id)
        round_two_final = _planning_bead(issues, epic_id, 2, "final")
        if round_two_final and _status(round_two_final) in CLOSED and not experiments:
            plan_path = _pipeline_dir(settings, epic_id) / "plan-v2.yaml"
            plan_script = _load_script(settings.root, "research-planning", "plan_to_beads")
            try:
                plan = plan_script.load_plan(plan_path)
                errors, _warnings = plan_script.validate(plan, strict=False)
            except (OSError, plan_script.PlanError, yaml.YAMLError) as exc:
                errors = [str(exc)]
                plan = {}
            if errors:
                finding = _finding(
                    beads,
                    epic_id,
                    f"pipe:{epic_id}:plan-invalid",
                    "Research pipeline plan is invalid",
                    "\n".join(errors),
                    today,
                    privacy,
                )
                beads.add_labels(epic_id, ["needs:robert"])
                if finding:
                    created.append(finding)
                flagged.append(epic_id)
            else:
                built = [
                    item for item in plan_script.build_beads(plan) if item["kind"] == "experiment"
                ]
                ids: dict[str, str] = {}
                for item in built:
                    xid = f"pipe:{epic_id}:exp:{item['id']}"
                    existing = beads.find_by_xid(xid)
                    actual = str(existing.get("id") or "") if existing else ""
                    if not actual:
                        provenance = _provenance(list(item.get("provenance") or []))
                        provenance.insert(
                            0,
                            Provenance(
                                source=f"bead:{epic_id}",
                                locator="validated plan experiment",
                                seen=today,
                            ),
                        )
                        deadline = (
                            date.fromisoformat(item["deadline"]) if item.get("deadline") else None
                        )
                        actual = (
                            beads.create(
                                str(item["title"]),
                                header=BeadHeader(
                                    xid=xid,
                                    provenance=provenance,
                                    deadline=deadline,
                                    privacy=Privacy(item["privacy"]),
                                ),
                                body=str(item["body"]),
                                labels=[
                                    f"goal:{epic_id}",
                                    "pipeline-stage:experiments",
                                    f"privacy:{item['privacy']}",
                                    "kind:experiment",
                                    "stage:implement",
                                    "role:programmer",
                                ],
                                parent=epic_id,
                                acceptance="\n".join(item["acceptance_criteria"]),
                            )
                            or xid
                        )
                        if not beads.dry_run:
                            created.append(actual)
                    ids[str(item["id"])] = actual
                for item in built:
                    for dependency in item.get("depends_on") or []:
                        dependency_id = str(dependency).rsplit(":", 1)[-1]
                        beads.dep(ids[str(item["id"])], ids[dependency_id], "blocks")
                gate = _create_gate(beads, epic_id, 1, list(ids.values()), privacy, today)
                if gate and not beads.dry_run:
                    created.append(gate)

        issues = beads.list_issues("--all")
        experiments = _experiments(issues, epic_id)
        gates = _gates(issues, epic_id)
        if experiments and not gates and not flagged:
            gate = _create_gate(
                beads,
                epic_id,
                1,
                [str(item.get("id")) for item in experiments],
                privacy,
                today,
            )
            if gate and not beads.dry_run:
                created.append(gate)
            issues = beads.list_issues("--all")
            gates = _gates(issues, epic_id)
        if gates and not flagged:
            latest = gates[-1]
            number = int(label_value(bead_labels(latest), "gate:") or 0)
            verdict = _verdict(latest)
            if verdict == "approve" and _status(latest) in CLOSED:
                beads.update_description(epic_id, _done_description(epic))
                beads.close(epic_id, f"gate {number} passed")
                closed.append(epic_id)
            elif verdict == "reject":
                beads.add_labels(epic_id, ["needs:robert"])
                flagged.append(epic_id)
            elif verdict == "revise" and _status(latest) in CLOSED:
                experiment_ids = {str(item.get("id")) for item in experiments}
                followups = [
                    item
                    for item in issues
                    if f"after-gate:{number}" in bead_labels(item)
                    and any(
                        label.startswith("revises:") and label.split(":", 1)[1] in experiment_ids
                        for label in bead_labels(item)
                    )
                ]
                if followups and all(_status(item) in CLOSED for item in followups):
                    next_number = number + 1
                    if next_number > settings.pipeline.max_iterations:
                        beads.add_labels(epic_id, ["needs:robert", "kill:iterations"])
                        flagged.append(epic_id)
                    else:
                        gate = _create_gate(
                            beads,
                            epic_id,
                            next_number,
                            [str(item.get("id")) for item in followups],
                            privacy,
                            today,
                        )
                        if gate and not beads.dry_run:
                            created.append(gate)

    status = pipeline_status(settings, beads, epic_id, today=today)
    return {
        "created": created,
        "closed": closed,
        "flagged": list(dict.fromkeys(flagged)),
        "stage": status["stage"],
        "iteration": status["iteration"],
    }
