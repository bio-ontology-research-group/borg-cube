"""Goal beads, their child work, and derived schedule state."""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field

from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine.context import bead_labels, label_value
from cube.model import BeadHeader, Privacy, Provenance
from cube.roles import RoleError, load_role


@lru_cache(maxsize=4)
def _load_delegation_script(root: Path, name: str) -> ModuleType:
    relative = Path("skills") / "delegation" / "scripts" / f"{name}.py"
    candidates = (root / relative, Path(__file__).resolve().parents[1] / relative)
    path = next(
        (candidate for candidate in candidates if candidate.exists()),
        root / relative,
    )
    spec = importlib.util.spec_from_file_location(f"cube._delegation_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import delegation script {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _delegation_scripts(root: Path) -> tuple[ModuleType, ModuleType]:
    return (
        _load_delegation_script(root, "beads_from_plan"),
        _load_delegation_script(root, "dependency_check"),
    )


StoredGoalStatus = Literal["proposed", "active", "done", "dropped"]
CLOSED = {"closed", "done"}
DEFAULT_TRACK_TOLERANCE = 0.10


class PipelineGoalHeader(BaseModel):
    """Optional pipeline-specific sources attached to one goal."""

    collaborators_from: str | None = None


class GoalHeader(BeadHeader):
    """The common bead header extended with the goal contract."""

    target: date
    success: list[str] = Field(min_length=1)
    project: str | None = None
    owner: Literal["robert"] = "robert"
    people: list[str] = Field(default_factory=list)
    status: StoredGoalStatus = "active"
    pipeline: PipelineGoalHeader | None = None

    @classmethod
    def parse(cls, description: str) -> GoalHeader | None:
        text = description.lstrip()
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---", 4)
        if end < 0:
            return None
        try:
            data = yaml.safe_load(text[4:end])
            return cls.model_validate(data) if isinstance(data, dict) else None
        except (ValueError, yaml.YAMLError):
            return None


def goal_header(bead: dict[str, Any]) -> GoalHeader | None:
    if "kind:goal" not in bead_labels(bead):
        return None
    return GoalHeader.parse(str(bead.get("description") or ""))


def goal_children(goal_id: str, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Children carry both links so neither a coincidental parent nor label is enough."""
    label = f"goal:{goal_id}"
    return [
        bead
        for bead in issues
        if str(bead.get("parent") or "") == goal_id and label in bead_labels(bead)
    ]


def _as_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("issues", "beads", "items", "results"):
            if isinstance(data.get(key), list):
                return [dict(item) for item in data[key] if isinstance(item, dict)]
        return [dict(data)] if data else []
    return []


def read_goal_ledger(beads: Beads) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    """Read all issues, the ready set, and ``bd blocked`` once for a goals view."""
    issues = beads.list_issues("--all") if beads.available() else []
    ready = beads.ready() if beads.available() else []
    blocked: list[dict[str, Any]] = []
    if beads.available():
        try:
            blocked = _as_list(beads._run("blocked", "--json").json())
        except BeadsError:
            blocked = []
    return issues, {str(item.get("id")) for item in ready if item.get("id")}, blocked


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text[:10]), datetime.min.time(), UTC)
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _activity(beads: list[dict[str, Any]]) -> str | None:
    values: list[datetime] = []
    for bead in beads:
        for key in ("updated_at", "closed_at", "created_at"):
            if parsed := _parse_datetime(bead.get(key)):
                values.append(parsed)
    return max(values).isoformat(timespec="seconds") if values else None


def _status(bead: dict[str, Any]) -> str:
    return str(bead.get("status") or "open").lower()


def _deadline(bead: dict[str, Any]) -> date | None:
    header = BeadHeader.parse(str(bead.get("description") or ""))
    if header and header.deadline:
        return header.deadline
    for key in ("due", "due_at", "deadline"):
        raw = bead.get(key)
        if raw:
            try:
                return date.fromisoformat(str(raw)[:10])
            except ValueError:
                continue
    return None


def tracking_tolerance(settings: Settings) -> float:
    """Read the goal tolerance without widening the global Settings schema."""
    try:
        raw = yaml.safe_load((settings.root / "cube.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return DEFAULT_TRACK_TOLERANCE
    section = raw.get("goals", raw.get("goal", {})) if isinstance(raw, dict) else {}
    value = (
        section.get("on_track_tolerance", section.get("tolerance"))
        if isinstance(section, dict)
        else None
    )
    try:
        tolerance = float(value) if value is not None else DEFAULT_TRACK_TOLERANCE
    except (TypeError, ValueError):
        return DEFAULT_TRACK_TOLERANCE
    if tolerance > 1:
        tolerance /= 100
    return min(1.0, max(0.0, tolerance))


def _blocked_reason(bead: dict[str, Any]) -> str:
    if bead.get("reason") or bead.get("blocking_reason"):
        return str(bead.get("reason") or bead.get("blocking_reason"))
    raw = bead.get("blocked_by") or bead.get("dependencies") or []
    if not isinstance(raw, list):
        raw = [raw]
    ids = [str(item.get("id")) if isinstance(item, dict) else str(item) for item in raw if item]
    return "blocked by " + ", ".join(ids) if ids else "blocked by a dependency"


def _track_state(
    goal: dict[str, Any],
    header: GoalHeader,
    children: list[dict[str, Any]],
    today: date,
    tolerance: float,
) -> tuple[bool | None, str]:
    if not children:
        return None, "No child work exists, so schedule tracking is not available."
    closed_fraction = sum(_status(child) in CLOSED for child in children) / len(children)
    created = _parse_datetime(goal.get("created_at"))
    if created is None:
        elapsed = 0.0
        prefix = "Goal creation time is unavailable; treating the elapsed fraction as 0%. "
    else:
        span = (header.target - created.date()).days
        elapsed = 1.0 if span <= 0 and today >= header.target else 0.0
        if span > 0:
            elapsed = min(1.0, max(0.0, (today - created.date()).days / span))
        prefix = ""
    required = max(0.0, elapsed - tolerance)
    on_track = closed_fraction >= required
    relation = "meets" if on_track else "is below"
    why = (
        f"{prefix}Closed {closed_fraction:.0%} of child work; {elapsed:.0%} of the goal window "
        f"has elapsed. This {relation} the {required:.0%} required fraction after a "
        f"{tolerance:.0%} tolerance."
    )
    return on_track, why


def goal_row(
    settings: Settings,
    goal: dict[str, Any],
    issues: list[dict[str, Any]],
    ready_ids: set[str],
    blocked_issues: list[dict[str, Any]],
    *,
    today: date,
    include_children: bool = False,
) -> dict[str, Any]:
    header = goal_header(goal)
    if header is None:
        raise ValueError(f"bead {goal.get('id')} is not a valid kind:goal bead")
    goal_id = str(goal.get("id") or "")
    children = goal_children(goal_id, issues)
    child_ids = {str(child.get("id")) for child in children}
    blocked_by_id = {
        str(item.get("id")): item for item in blocked_issues if str(item.get("id")) in child_ids
    }
    blockers: dict[str, dict[str, Any]] = {}
    for child in children:
        child_id = str(child.get("id") or "")
        reasons: list[str] = []
        blocked = blocked_by_id.get(child_id)
        if blocked is not None:
            reasons.append(_blocked_reason(blocked))
        elif child.get("blocked") or _status(child) == "blocked":
            reasons.append(_blocked_reason(child))
        due = _deadline(child)
        if _status(child) not in CLOSED and due and due < today:
            reasons.append(f"deadline {due.isoformat()} has passed")
        if reasons:
            blockers[child_id] = {
                "bead": child_id,
                "title": str(child.get("title") or child_id),
                "reason": "; ".join(reasons),
            }

    closed = sum(_status(child) in CLOSED for child in children)
    in_progress = sum(_status(child) == "in_progress" for child in children)
    total = len(children)
    on_track, why = _track_state(goal, header, children, today, tracking_tolerance(settings))
    stored = header.status
    if stored == "dropped":
        status = "dropped"
    elif stored == "done" or _status(goal) in CLOSED:
        status = "done"
    elif stored == "active" and on_track is False:
        status = "at-risk"
    else:
        status = stored

    open_children = [child for child in children if _status(child) not in CLOSED]
    open_children.sort(key=child_sort_key)
    agents: list[dict[str, Any]] = []
    people: list[dict[str, Any]] = []
    for child in open_children:
        labels = bead_labels(child)
        role = label_value(labels, "role:")
        person = label_value(labels, "person:")
        child_id = str(child.get("id") or "")
        if role:
            agents.append({"bead": child_id, "role": role, "ready": child_id in ready_ids})
        elif person:
            due = _deadline(child)
            people.append(
                {
                    "person": person,
                    "bead": child_id,
                    "title": str(child.get("title") or child_id),
                    "due": due.isoformat() if due else None,
                }
            )
    row: dict[str, Any] = {
        "id": goal_id,
        "title": str(goal.get("title") or goal_id),
        "target": header.target.isoformat(),
        "days_left": (header.target - today).days,
        "status": status,
        "project": header.project,
        "people": header.people,
        "progress": {
            "total": total,
            "closed": closed,
            "in_progress": in_progress,
            "blocked": len(blockers),
            "pct": round(100 * closed / total) if total else 0,
        },
        "on_track": on_track,
        "why": why,
        "blockers": list(blockers.values()),
        "next": {"agents": agents, "people": people},
        "last_activity": _activity([goal, *children]),
    }
    if include_children:
        row["success"] = header.success
        row["children"] = children
    return row


def child_sort_key(bead: dict[str, Any]) -> tuple[int, date, str]:
    try:
        priority = int(bead.get("priority", 2))
    except (TypeError, ValueError):
        priority = 2
    return priority, _deadline(bead) or date.max, str(bead.get("id") or "")


def people_work(
    issues: list[dict[str, Any]], person: str
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return current goal stakes and work owed by a person, never contact intents."""
    goals: set[str] = set()
    for bead in issues:
        header = goal_header(bead)
        if (
            header
            and _status(bead) not in CLOSED
            and person in header.people
            and header.status not in {"done", "dropped"}
        ):
            if bead.get("id"):
                goals.add(str(bead["id"]))
    owed: list[dict[str, Any]] = []
    for bead in issues:
        labels = bead_labels(bead)
        if _status(bead) in CLOSED or f"person:{person}" not in labels or "kind:goal" in labels:
            continue
        if label_value(labels, "role:"):
            continue
        due = _deadline(bead)
        goal_id = label_value(labels, "goal:")
        if goal_id:
            goals.add(goal_id)
        owed.append(
            {
                "bead": str(bead.get("id") or ""),
                "title": str(bead.get("title") or bead.get("id") or ""),
                "due": due.isoformat() if due else None,
            }
        )
    owed.sort(key=lambda item: (item["due"] or "9999-12-31", item["bead"]))
    return sorted(goals), owed


def _owner(bead: dict[str, Any]) -> tuple[str, str]:
    raw = str(bead.get("owner_role") or "")
    if raw.startswith("person:"):
        return "person", raw.split(":", 1)[1]
    if raw.startswith("role:"):
        return "role", raw.split(":", 1)[1]
    return "role", raw


def validate_plan(settings: Settings, goal: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Validate with the delegation scripts, then enforce mixed-owner rules."""
    header = goal_header(goal)
    if header is None:
        raise ValueError(f"bead {goal.get('id')} is not a valid kind:goal bead")
    beads_from_plan, dependency_check = _delegation_scripts(settings.root)
    parsed = beads_from_plan.parse_yaml(yaml.safe_dump(copy.deepcopy(plan), sort_keys=False))
    normalised = beads_from_plan.normalise(parsed)
    if not normalised.get("beads"):
        raise ValueError("delegation plan has no beads")
    schema = beads_from_plan.load_schema(beads_from_plan.DEFAULT_SCHEMA)
    owner_spec = schema["properties"]["owner_role"]
    owner_spec["enum"] = [
        *owner_spec.get("enum", []),
        *(f"role:{name}" for name in owner_spec.get("enum", [])),
        *(f"person:{person}" for person in header.people),
    ]
    errors: list[str] = []
    for child in normalised["beads"]:
        child_id = str(child.get("id") or child.get("title") or "child")
        errors.extend(
            f"{child_id}: {problem}" for problem in beads_from_plan.validate_bead(child, schema)
        )
        errors.extend(
            f"{child_id}: {problem}" for problem in beads_from_plan.checkability_warnings(child)
        )
        owner_kind, owner_name = _owner(child)
        if owner_kind == "person":
            if owner_name not in header.people:
                errors.append(f"{child_id}: person owner {owner_name!r} is not a goal stakeholder")
            if not child.get("deadline"):
                errors.append(f"{child_id}: human work needs a deadline")
            if not child.get("why_you"):
                errors.append(f"{child_id}: human work needs a why_you line")
        else:
            try:
                role = load_role(settings.root, owner_name)
                if role.runtime == "python":
                    errors.append(f"{child_id}: role {owner_name!r} is not an agent runner")
            except RoleError as exc:
                errors.append(f"{child_id}: {exc}")
        reason = child.get("why_you") if owner_kind == "person" else child.get("why")
        if not reason:
            errors.append(f"{child_id}: owner choice needs a one-line reason")
        elif "\n" in str(reason):
            errors.append(f"{child_id}: owner reason must be one line")
    dependency = dependency_check.analyse(normalised["beads"])
    errors.extend(str(error) for error in dependency["errors"])
    if errors:
        raise ValueError("invalid delegation plan: " + "; ".join(errors))
    return cast(dict[str, Any], normalised)


def load_and_validate_plan(settings: Settings, goal: dict[str, Any], path: Path) -> dict[str, Any]:
    beads_from_plan, _ = _delegation_scripts(settings.root)
    try:
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = beads_from_plan.load_plan(path)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, beads_from_plan.PlanError) as exc:
        raise ValueError(f"could not read delegation plan {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"delegation plan {path} is not an object")
    return validate_plan(settings, goal, raw)


def _provenance(values: list[Any], goal_id: str) -> list[Provenance]:
    out: list[Provenance] = []
    for value in values:
        if isinstance(value, dict):
            try:
                out.append(Provenance.model_validate(value))
            except ValueError:
                continue
        else:
            source, separator, locator = str(value).partition("::")
            if source.strip():
                out.append(
                    Provenance(
                        source=source.strip(),
                        locator=locator.strip() if separator and locator.strip() else None,
                    )
                )
    return out or [Provenance(source=f"bead:{goal_id}", locator="goal decomposition")]


def _child_body(child: dict[str, Any], human: bool) -> str:
    acceptance = "\n".join(
        f"- {item.get('check') if isinstance(item, dict) else item}"
        for item in child.get("acceptance_criteria", [])
    )
    reason_label = "Why you" if human else "Why this role"
    reason = child.get("why_you") if human else child.get("why")
    return (
        f"Objective: {child.get('objective')}\n\n"
        f"Output: {child.get('output')}\n\n"
        f"{reason_label}: {reason}\n\n"
        f"Out of scope: {child.get('out_of_scope') or 'Nothing beyond this child bead.'}\n\n"
        f"Acceptance:\n{acceptance}"
    )


def apply_plan(
    settings: Settings, beads: Beads, goal: dict[str, Any], plan: dict[str, Any]
) -> list[dict[str, Any]]:
    """Create validated children idempotently, then add their local dependencies."""
    goal_id = str(goal.get("id") or "")
    header = goal_header(goal)
    if not goal_id or header is None:
        raise ValueError("goal bead is missing its id or goal header")
    plan = validate_plan(settings, goal, plan)
    existing: dict[str, str] = {}
    for issue in beads.list_issues("--all"):
        external = issue.get("external_ref")
        if external and issue.get("id"):
            existing[str(external)] = str(issue["id"])
    ids: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for child in plan["beads"]:
        local_id = str(child["id"])
        xid = f"goal:{goal_id}:{local_id}"
        owner_kind, owner_name = _owner(child)
        labels = [
            f"goal:{goal_id}",
            f"kind:{child.get('kind', 'implement')}",
            f"stage:{child.get('stage', 'design')}",
            f"privacy:{child.get('privacy', 'internal')}",
            f"{owner_kind}:{owner_name}",
        ]
        if header.project:
            labels.append(f"project:{header.project}")
        child_deadline = (
            date.fromisoformat(str(child["deadline"])) if child.get("deadline") else None
        )
        bead_header = BeadHeader(
            xid=xid,
            provenance=_provenance(list(child.get("provenance") or []), goal_id),
            deadline=child_deadline,
            privacy=Privacy(str(child.get("privacy") or "internal")),
        )
        actual = existing.get(xid)
        created = actual is None
        if created:
            actual = beads.create(
                str(child["title"]),
                header=bead_header,
                body=_child_body(child, owner_kind == "person"),
                type_="task",
                priority=int(child.get("priority") or 2),
                labels=labels,
                parent=goal_id,
                acceptance="\n".join(
                    str(item.get("check") if isinstance(item, dict) else item)
                    for item in child["acceptance_criteria"]
                ),
            )
        if not actual:
            raise BeadsError(f"bd did not return an id for goal child {local_id}")
        ids[local_id] = actual
        results.append(
            {
                "plan_id": local_id,
                "bead": actual,
                "owner": f"{owner_kind}:{owner_name}",
                "created": created,
            }
        )
    for child in plan["beads"]:
        for dependency in child.get("depends_on") or []:
            beads.dep(ids[str(child["id"])], ids[str(dependency)], "blocks")
    return results
