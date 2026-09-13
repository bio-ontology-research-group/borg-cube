"""Coordinator-controlled ordering with deterministic, single-turn local dispatch."""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from cube.agents import append_journal, load_agent
from cube.beads import Beads
from cube.config import Settings
from cube.engine import execute
from cube.engine.context import bead_labels, label_value
from cube.engine.lease import live_leases
from cube.engine.marshal import role_for
from cube.fleet_github import _save
from cube.ledger_sync import sync_ledger
from cube.resources import load_limits
from cube.roles import load_all

# A task may end this many scheduled turns without closing or handing to review
# before the coordinator must revise it (an operator resets the counter). Two was
# too few for design tasks that legitimately span several bounded turns.
MAX_INCOMPLETE_TURNS = 4
STALE_CLAIM = "stale claim: in_progress without a live run"


def _state(settings: Settings) -> dict[str, Any]:
    path = settings.state_dir() / "scheduler.json"
    return json.loads(path.read_text()) if path.exists() else {"attempts": {}, "agents": {}}


def _number(labels: list[str], prefix: str, default: int) -> int:
    value = label_value(labels, prefix)
    result = int(value) if value is not None else default
    if result < 0:
        raise ValueError(f"{prefix} must be nonnegative")
    return result


def stale_claims(
    settings: Settings, issues: list[dict[str, Any]], *, now: datetime | None = None
) -> list[str]:
    """Beads claimed (in_progress) with no live lease: the run that claimed them is gone.

    ``bd ready`` hides claimed beads, so such a bead never returns to the queue
    on its own; two sat like that for two days after 2026-09-09 (cube-in1).
    """
    now = now or datetime.now(UTC)
    leased = {lease.bead for lease in live_leases(settings.state_dir(), now)}
    return sorted(
        str(item["id"])
        for item in issues
        if item.get("status") == "in_progress"
        and str(item["id"]) not in leased
        # Only fleet claims (the engine assigns cube/<role>); a person's own
        # claim in the cockpit is theirs to release.
        and str(item.get("assignee") or "cube/").startswith("cube/")
    )


def release_stale_claims(
    settings: Settings, beads: Beads, *, now: datetime | None = None
) -> list[str]:
    released = []
    for bid in stale_claims(settings, beads.list_issues("--all", "--limit", "0"), now=now):
        beads.unclaim(bid)
        released.append(bid)
    return released


def plan(settings: Settings, beads: Beads, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only order and exclusions. Never ask a model whether a slot is free."""
    now = now or datetime.now(UTC)
    limits = load_limits(settings)
    saved = _state(settings)
    ready = {str(row["id"]) for row in beads.ready()}
    issues = beads.list_issues("--all", "--limit", "0")
    leased = {lease.bead for lease in live_leases(settings.state_dir(), now)}
    stale = set(stale_claims(settings, issues, now=now))
    roles, _ = load_all(settings.root)
    queue, waiting = [], []
    for item in issues:
        if item.get("status") in {"closed", "done"}:
            continue
        bid = str(item["id"])
        labels = bead_labels(item)
        owner = label_value(labels, "agent:")
        role = role_for(item, roles, root=settings.root)
        goal = "kind:goal" in labels and not owner and not label_value(labels, "role:")
        if goal:
            owner, role = "coordinator", "group-leader"
        reason = None
        if bid in leased:
            reason = "running"
        elif "needs:robert" in labels or any(
            label in labels for label in ("kind:approval", "kind:outbound")
        ):
            reason = "awaiting approval"
        elif label_value(labels, "host:") not in {None, settings.host}:
            reason = "another host"
        elif str(item.get("external_ref", "")).startswith("mattermost-goal:"):
            reason = "owned by goal-intake dispatcher"
        elif any(label in labels for label in ("review:pending", "review:revise")):
            reason = "waiting for review"
        elif bid in stale:
            reason = STALE_CLAIM
        elif bid not in ready:
            reason = "not ready: dependencies, claim or deferred state"
        elif goal and any(
            row.get("status") not in {"closed", "done"}
            and (
                row.get("parent") == bid
                or str(row.get("id", "")).startswith(bid + ".")
                or f"goal:{bid}" in bead_labels(row)
            )
            for row in issues
        ):
            reason = "goal has open child work"
        elif not role or roles[role].runtime == "python":
            reason = "no model worker assigned"
        elif role in {"sysadmin", "liaison", "concierge"}:
            reason = "restricted role or gateway: use its dedicated route"
        if owner and reason is None:
            try:
                agent = load_agent(settings.root, owner)
                if agent.host != settings.host:
                    reason = f"agent lives on {agent.host}"
                elif (settings.state_dir() / "agents" / owner / "PAUSED").exists():
                    reason = "agent paused"
            except (OSError, ValueError) as exc:
                reason = f"invalid owner: {exc}"
        previous = saved.get("attempts", {}).get(bid, {})
        if reason is None and previous.get("checkpoints", 0) >= MAX_INCOMPLETE_TURNS:
            reason = (
                f"{MAX_INCOMPLETE_TURNS} incomplete turns: coordinator must revise task; "
                "operator resets counter"
            )
        if (
            reason is None
            and previous.get("next_at")
            and now < datetime.fromisoformat(previous["next_at"])
        ):
            reason = "cooldown until " + previous["next_at"]
        if reason:
            waiting.append({"bead": bid, "agent": owner, "reason": reason})
            continue
        try:
            minutes = min(
                _number(labels, "runtime:minutes:", limits.local_run_timeout_minutes),
                limits.local_run_timeout_minutes,
            )
            if minutes == 0:
                raise ValueError("runtime:minutes:0 pauses this task")
            order = _number(labels, "schedule:order:", 1000000)
        except ValueError as exc:
            waiting.append({"bead": bid, "reason": str(exc)})
            continue
        queue.append(
            {
                "bead": bid,
                "agent": owner,
                "role": role,
                "goal": goal,
                "priority": int(item.get("priority", 2)),
                "order": order,
                "runtime_minutes": minutes,
                "review": "kind:review" in labels,
                "last_agent_turn": saved.get("agents", {}).get(owner or role, 0),
                "last_task_turn": previous.get("sequence", 0),
                "reason": "ready; priority/order; review then fair rotation",
            }
        )
    queue.sort(
        key=lambda row: (
            row["priority"],
            row["order"],
            not row["review"],
            row["last_agent_turn"],
            row["last_task_turn"],
            row["bead"],
        )
    )
    paused = (
        (settings.state_dir() / "KILL").exists()
        or limits.local_workday_concurrency == 0
        or limits.local_inference_concurrency == 0
    )
    return {
        "host": settings.host,
        "paused": paused,
        "queue": queue,
        "waiting": waiting,
        "selected": None if paused or not queue else queue[0],
        "concurrency": 1,
    }


def tick(settings: Settings, beads: Beads, *, dry_run: bool = True) -> dict[str, Any]:
    if dry_run:
        return plan(settings, beads)
    directory = settings.state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "scheduler.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "busy"}
        # The laptop liaison answers on its own ledger; the shared Dolt remote is
        # the only path between the hosts. Pull first so its answers unblock work
        # here, push last so requests filed here reach it.
        syncs = [sync_ledger(settings, beads, "pull", host=settings.host, dry_run=False)]
        released = release_stale_claims(settings, beads)
        proposal = plan(settings, beads)
        proposal["released"] = released
        proposal["syncs"] = syncs
        _save(directory / "schedule-plan.json", proposal)
        selected = proposal["selected"]
        if selected is None:
            syncs.append(sync_ledger(settings, beads, "push", host=settings.host, dry_run=False))
            return {**proposal, "state": "paused" if proposal["paused"] else "idle"}
        saved = _state(settings)
        sequence = int(saved.get("sequence", 0)) + 1
        previous = saved.setdefault("attempts", {}).get(selected["bead"], {})
        saved["sequence"] = sequence
        saved.setdefault("agents", {})[selected["agent"] or selected["role"]] = sequence
        attempt = {
            "sequence": sequence,
            "state": "running",
            "failures": previous.get("failures", 0),
            "checkpoints": previous.get("checkpoints", 0),
        }
        saved["attempts"][selected["bead"]] = attempt
        _save(directory / "scheduler.json", saved)
        model = next(
            entry.model
            for entry in settings.tiers.get("local", [])
            if entry.runner_name == "hermes@local" and entry.model
        )
        prompt = (
            f"Scheduled turn for {selected['agent'] or selected['role']}: at most "
            f"{selected['runtime_minutes']} minutes and the central tool-turn limit. "
            "Advance only this assigned task with one useful saved artifact/checkpoint. "
            "Use its existing goal and dependencies, not a general management scan. "
            "Publish permitted code and results to the stable private fleet project repository, "
            "Record the commit and arrange independent review. Local-only sources stay local. "
            "Do not claim uploads without evidence or close a whole goal after planning. "
            "If this is an undecomposed goal, create owned, dependency-linked child tasks first. "
            "Use bd priority (0 highest), schedule:order:N and runtime:minutes:N to allocate "
            "turns. Dependencies and approvals cannot be overridden by order. "
            "When the task's acceptance criteria are met and the evidence is on the ledger, "
            "return close: true for the task bead; the engine then opens the independent "
            "review. close: false means you need another turn; after "
            f"{MAX_INCOMPLETE_TURNS} such turns the task waits for the coordinator. "
            "A design brief for a programmer is a finished design turn: return it as an "
            "artifact of kind brief or spec and the next turn runs the programmer on it. "
            "No service changes, laptop SSH, broad task creation, or progress-message flood. "
            "Return compact RunResult JSON, under 3000 characters. Save larger artifacts "
            "using permitted file tools; without write access, return only a short "
            "inline checkpoint."
        )
        if selected["agent"]:
            agent = load_agent(settings.root, selected["agent"])
            charter = settings.root / agent.charter
            if charter.exists():
                prompt += "\n\nAgent charter:\n" + charter.read_text()[:5000]
        goal_row: dict[str, Any] | None = None
        if selected.get("goal"):
            # An undecomposed goal gets the same turn as `cube goal decompose`: the
            # group leader returns a YAML plan and the engine creates the children.
            # Four generic turns on cube-ihu re-verified "no children" and created
            # none (2026-09-11); creating fifteen beads by hand does not fit a
            # bounded local turn, applying a validated plan does.
            goal_row, prompt = _goal_turn(settings, beads, selected["bead"], prompt)
        report: Any
        try:
            report = execute(
                settings,
                selected["role"],
                bead=selected["bead"],
                agent=selected["agent"],
                runner_name="hermes@local",
                model=model,
                runtime_minutes=selected["runtime_minutes"],
                respect_project_runner=False,
                prompt_text=prompt,
            )
        except Exception as exc:
            # Record a cooldown even when an infrastructure error escapes the engine.
            # Do not clear a claim here: a surviving child may still own its lease.
            report = SimpleNamespace(
                ok=False,
                state="error",
                run_id=None,
                message="",
                error=f"dispatch failed: {type(exc).__name__}",
            )
        failures = 0 if report.ok else int(attempt["failures"]) + 1
        delay = 15 if report.ok else min(60, 2 ** min(failures, 6))
        applied = getattr(report, "applied", None) or {}
        closed = list(applied.get("closed") or []) + list(
            (applied.get("verdict") or {}).get("closed") or []
        )
        settled = selected["bead"] in closed or bool(applied.get("review_bead"))
        children: list[str] = []
        if goal_row is not None and report.ok:
            children = _apply_goal_plan(settings, beads, goal_row, report)
            settled = settled or bool(children)
        # A finished turn that neither closed its task nor handed it to review is
        # an incomplete turn like a malformed checkpoint: it counts toward the
        # coordinator-must-revise limit instead of looping forever.
        incomplete = report.state == "checkpoint" or (report.state == "finished" and not settled)
        attempt.update(
            state=report.state,
            run_id=report.run_id,
            failures=failures,
            next_at=(datetime.now(UTC) + timedelta(minutes=delay)).isoformat(),
            checkpoints=int(attempt["checkpoints"]) + 1 if incomplete else 0,
        )
        _save(directory / "scheduler.json", saved)
        if incomplete and attempt["checkpoints"] >= MAX_INCOMPLETE_TURNS:
            _ask_coordinator_to_revise(settings, beads, selected["bead"], attempt)
        syncs.append(sync_ledger(settings, beads, "push", host=settings.host, dry_run=False))
        if selected["agent"]:
            append_journal(
                settings.root,
                agent,
                body=f"Scheduled {selected['bead']}: {report.state}. {report.message or ''}",
                sources=[f"bead:{selected['bead']}", f"runs/{report.run_id}"],
            )
        return {
            "state": report.state,
            "selected": selected,
            "run_id": report.run_id,
            "error": report.error,
            "released": released,
            "syncs": syncs,
            "children": children,
        }


def _goal_turn(
    settings: Settings, beads: Beads, goal_id: str, fallback: str
) -> tuple[dict[str, Any] | None, str]:
    """The decomposition prompt of ``cube goal decompose`` for a goal with a header."""
    from cube.commands.goal import _decomposition_prompt  # noqa: PLC0415
    from cube.goals import goal_header  # noqa: PLC0415

    try:
        goal = beads.show(goal_id)
        if goal_header(goal) is None:
            return None, fallback
        issues = beads.list_issues("--all")
        ready = beads.ready()
        planned = settings.runs_dir() / "goals" / goal_id / "plan.yaml"
        return goal, _decomposition_prompt(settings, goal, issues, ready, planned)
    except Exception:  # noqa: BLE001 - a malformed goal still gets the generic turn
        return None, fallback


def _apply_goal_plan(
    settings: Settings, beads: Beads, goal: dict[str, Any], report: Any
) -> list[str]:
    """Create the goal's children from the plan the turn returned; note failures on the goal."""
    from cube.commands.goal import _artifact_plan, _inline_plan, _save_proposal  # noqa: PLC0415
    from cube.goals import apply_plan, load_and_validate_plan, validate_plan  # noqa: PLC0415

    goal_id = str(goal.get("id") or "")
    rep = report.as_dict() if hasattr(report, "as_dict") else dict(report)
    try:
        artifact = _artifact_plan(rep, settings)
        if artifact and artifact.exists():
            plan = load_and_validate_plan(settings, goal, artifact)
        elif inline := _inline_plan(rep):
            plan = validate_plan(settings, goal, inline)
        else:
            beads.comment(
                goal_id,
                f"[scheduler {rep.get('run_id')}] decomposition turn returned no plan "
                "artifact (kind plan) and no inline YAML plan; goal stays undecomposed.",
            )
            return []
        _save_proposal(rep, plan)
        children = apply_plan(settings, beads, goal, plan)
    except Exception as exc:  # noqa: BLE001 - the ledger note is the audit trail
        try:
            beads.comment(goal_id, f"[scheduler {rep.get('run_id')}] plan not applied: {exc}")
        except Exception:  # noqa: BLE001
            pass
        return []
    ids = [str(child.get("id") or "") for child in children if child.get("id")]
    if ids:
        try:
            beads.comment(
                goal_id,
                f"[scheduler {rep.get('run_id')}] created {len(ids)} child bead(s) from the "
                f"returned plan: {', '.join(ids)}",
            )
        except Exception:  # noqa: BLE001
            pass
    return ids


def _ask_coordinator_to_revise(
    settings: Settings, beads: Beads, bead_id: str, attempt: dict[str, Any]
) -> None:
    """Label the stalled task and put it in the coordinator's inbox once."""
    from cube.agents import AgentError, append_inbox  # noqa: PLC0415

    text = (
        f"{bead_id} ended {attempt['checkpoints']} scheduled turns without closing or handing "
        f"to review (last run {attempt.get('run_id')}). Revise it: split it, reassign the "
        "owner, or close it with evidence; then remove the label schedule:revise or reset "
        "its counter in state/scheduler.json."
    )
    try:
        beads.add_labels(bead_id, ["schedule:revise"])
        beads.comment(bead_id, "[scheduler] " + text)
    except Exception:  # noqa: BLE001 - the inbox note below still reaches the coordinator
        pass
    try:
        append_inbox(
            settings.root, load_agent(settings.root, "coordinator"), text, sender="scheduler"
        )
    except (AgentError, OSError, ValueError):
        pass
