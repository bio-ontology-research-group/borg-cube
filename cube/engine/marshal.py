"""Marshal: dispatch ready beads into free slots, expire dead leases, honour state/KILL."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.audit import audit
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine import lease as leases
from cube.engine.context import bead_labels, bead_privacy, bead_tier, label_value
from cube.model import Privacy, Tier
from cube.roles import Role, load_all
from cube.router import BudgetLedger, effective_tier

STAGE_ROLES = {"stage:design": "senior", "stage:implement": "programmer"}
# kind:review beads carry a role:<x> label set by the review gate; no default here.
KIND_ROLES: dict[str, str] = {
    "kind:audit": "auditor",
    "kind:incident": "sysadmin",
    "kind:meeting-note": "scribe",
    "kind:lecture": "lecturer",
    "kind:course": "lecturer",
    "kind:mentoring": "advisor",
    "kind:service": "secretary",
}

Dispatch = Callable[[str, str, str], int | None]
"""dispatch(role, bead, tier) -> pid or None"""


@dataclass
class Plan:
    dispatched: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    killed: bool = False
    slots: dict[str, dict[str, int]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def role_for(
    bead: dict[str, Any], roles: dict[str, Role], *, root: Path | None = None
) -> str | None:
    labels = bead_labels(bead)
    # A goal epic is Robert's; bd copies the parent's labels onto children, so a
    # stage bead also carries kind:goal. Only a bead without an explicit owner
    # (agent: or role:) is treated as the epic itself.
    if "kind:goal" in labels and not (
        label_value(labels, "agent:") or label_value(labels, "role:")
    ):
        return None
    agent_name = label_value(labels, "agent:")
    if agent_name:
        # Standing-agent identity overrides broad stage dispatch, but its role and
        # tier are validated from agents/<name>.yaml before execution.
        try:
            from cube.agents import load_agent, validate_agent_role  # noqa: PLC0415

            agent_root = root or Path.cwd()
            agent = load_agent(agent_root, agent_name)
            validate_agent_role(agent_root, agent)
            return agent.role if agent.role in roles else None
        except Exception:  # noqa: BLE001 - malformed identities stay queued for Robert
            return None
    explicit = label_value(labels, "role:")
    if explicit and explicit in roles:
        return explicit
    # Goal children require an explicit agent owner. A person-owned child has
    # no role label and stays on Robert's People board instead of inheriting a
    # stage role and being dispatched.
    if any(label.startswith("goal:") for label in labels):
        return None
    for label, role in STAGE_ROLES.items():
        if label in labels and role in roles:
            return role
    for label, role in KIND_ROLES.items():
        if label in labels and role in roles:
            return role
    return None


def subprocess_dispatch(
    settings: Settings,
    *,
    host: str | None = None,
    popen: Callable[..., Any] | None = None,
) -> Dispatch:
    def dispatch(role: str, bead: str, tier: str) -> int | None:
        cmd = [
            sys.executable,
            "-m",
            "cube.cli",
            "--root",
            str(settings.root),
            "run",
            role,
            "--bead",
            bead,
            "--json",
        ]
        try:
            ledger = Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True)
            stage = ledger.show(bead)
            labels = bead_labels(stage)
            epic_id = label_value(labels, "goal:")
            if epic_id and any(label.startswith("pipeline-stage:") for label in labels):
                from cube.pipeline import stage_prompt  # noqa: PLC0415

                prompt = stage_prompt(settings, ledger.show(epic_id), stage, beads=ledger)
                cmd.extend(["--prompt", prompt])
        except (BeadsError, ValueError):
            pass
        start = popen or subprocess.Popen
        proc = start(  # noqa: S603 - fixed argv
            cmd,
            cwd=settings.root,
            env={**os.environ, "CUBE_HOST": host or settings.host},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid

    return dispatch


def subprocess_agent_dispatch(
    settings: Settings, *, host: str | None = None
) -> Callable[[str, str], int]:
    """Start a standing agent's bounded workday for an assigned bead."""

    def dispatch(agent: str, bead: str) -> int:
        cmd = [
            sys.executable,
            "-m",
            "cube.cli",
            "--root",
            str(settings.root),
            "agent",
            "workday",
            agent,
            "--now",
            "--bead",
            bead,
            "--apply",
            "--json",
        ]
        proc = subprocess.Popen(  # noqa: S603 - fixed argv
            cmd,
            cwd=settings.root,
            env={**os.environ, "CUBE_HOST": host or settings.host},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid

    return dispatch


def tick(
    settings: Settings,
    beads: Beads,
    *,
    slots: dict[str, int] | None = None,
    max_dispatch: int | None = None,
    dry_run: bool = False,
    dispatch: Dispatch | None = None,
    now: datetime | None = None,
    host: str | None = None,
) -> Plan:
    """One marshal pass. Idempotent: leased beads are never dispatched twice."""
    now = now or datetime.now(UTC)
    state_dir = settings.state_dir()
    plan = Plan()
    if (state_dir / "KILL").exists():
        plan.killed = True
        return plan
    plan.expired = [x.bead for x in leases.expire_dead(state_dir, now)]
    for b in plan.expired:
        audit(state_dir, "lease.expired", bead=b)

    slots = dict(slots or settings.slots)
    live = leases.live_leases(state_dir, now)
    used: dict[str, int] = {}
    for lease in live:
        used[lease.tier or "implement"] = used.get(lease.tier or "implement", 0) + 1
    leased = {x.bead for x in live}
    roles, _errors = load_all(settings.root)
    worker_host = host or settings.host
    custom_dispatch = dispatch
    dispatch = dispatch or subprocess_dispatch(settings, host=worker_host)
    agent_dispatch = subprocess_agent_dispatch(settings, host=worker_host)

    try:
        ready = beads.ready() if beads.available() else []
    except BeadsError as exc:
        plan.skipped.append({"reason": f"bd ready failed: {exc}"})
        ready = []

    ledger = BudgetLedger(state_dir, settings)
    budget_cap = ledger.caps()
    count = 0
    for bead in ready:
        bead_id = str(bead.get("id") or "")
        if not bead_id:
            continue
        labels = bead_labels(bead)
        bead_host = label_value(labels, "host:")
        if bead_host and bead_host != worker_host:
            plan.skipped.append({"bead": bead_id, "reason": "host"})
            continue
        agent_name = label_value(labels, "agent:")
        if worker_host != settings.host and not bead_host and not agent_name:
            # A thin client (the laptop) plays only beads that name it or its
            # own agents; everything else belongs to the orchestration host.
            plan.skipped.append({"bead": bead_id, "reason": f"not for {worker_host}"})
            continue
        if bead_id in leased:
            plan.skipped.append({"bead": bead_id, "reason": "leased"})
            continue
        if "needs:robert" in labels:
            plan.skipped.append({"bead": bead_id, "reason": "needs:robert"})
            continue
        role_name = role_for(bead, roles, root=settings.root)
        if not role_name:
            plan.skipped.append({"bead": bead_id, "reason": "no role label or stage"})
            continue
        role = roles[role_name]
        if role.runtime == "python":
            plan.skipped.append({"bead": bead_id, "reason": f"{role_name} is a python role"})
            continue
        agent_tier: Tier | None = None
        if agent_name:
            try:
                from cube.agents import load_agent, validate_agent_role  # noqa: PLC0415

                agent = load_agent(settings.root, agent_name)
                validate_agent_role(settings.root, agent)
                agent_tier = agent.tier
            except Exception as exc:  # noqa: BLE001 - retain malformed declarations for Robert
                plan.skipped.append(
                    {"bead": bead_id, "reason": f"invalid agent:{agent_name}: {exc}"}
                )
                continue
            elsewhere = (
                agent.host != worker_host
                if worker_host != settings.host
                else agent.host != worker_host and agent.host in settings.hosts
            )
            if elsewhere:
                # The coordinator's beads never run on the laptop, the liaison's
                # never on ws: an agent's workday runs where the agent lives. A
                # thin client plays only its own agents; the orchestration host
                # plays every agent except those on another configured host.
                plan.skipped.append(
                    {"bead": bead_id, "reason": f"agent:{agent_name} lives on {agent.host}"}
                )
                continue
        try:
            tier = agent_tier or effective_tier(role.tier, bead_tier(labels))
        except Exception as exc:  # noqa: BLE001 - Refused; report, do not stop the loop
            plan.skipped.append({"bead": bead_id, "reason": str(exc)})
            continue
        if bead_privacy(bead, labels) == Privacy.local_only:
            tier = Tier.local
        if tier == Tier.none:
            plan.skipped.append({"bead": bead_id, "reason": "tier none"})
            continue
        key = tier.value
        if used.get(key, 0) >= slots.get(key, 0):
            plan.skipped.append({"bead": bead_id, "reason": f"no free {key} slot"})
            continue
        if key in budget_cap and ledger.exhausted(tier, now):
            plan.skipped.append({"bead": bead_id, "reason": f"{key} budget exhausted"})
            continue
        if max_dispatch is not None and count >= max_dispatch:
            plan.skipped.append({"bead": bead_id, "reason": "max dispatch reached"})
            continue
        entry = {"bead": bead_id, "role": role_name, "tier": key, "dry_run": dry_run}
        if not dry_run:
            pid = (
                agent_dispatch(agent_name, bead_id)
                if agent_name and custom_dispatch is None
                else dispatch(role_name, bead_id, key)
            )
            entry["pid"] = pid
            audit(
                state_dir, "marshal.dispatch", bead=bead_id, role=role_name, tier=key, child_pid=pid
            )
        used[key] = used.get(key, 0) + 1
        count += 1
        plan.dispatched.append(entry)
    plan.slots = {k: {"limit": v, "used": used.get(k, 0)} for k, v in slots.items()}
    return plan
