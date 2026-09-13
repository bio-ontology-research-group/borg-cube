"""`cube work --json`: one answer to "what is the cube working on".

The payload joins four deterministic sources: the standing-agent declarations in
``agents/*.yaml``, the live leases and run metadata under ``state/`` and
``runs/``, the Beads work ledger, and the research-pipeline view.  No model runs
here and nothing is written.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from cube.agents import (
    Agent,
    last_workday_start,
    load_all_agents,
    read_inbox,
    resource_usage,
    state_dir,
    workday_due,
)
from cube.beads import Beads, BeadsError
from cube.commands import Helpers
from cube.config import Settings
from cube.engine import lease as leases
from cube.engine.context import bead_labels, label_value
from cube.engine.run import list_runs

CLOSED = {"closed", "done"}
OWNER_PREFIXES = ("agent:", "role:")
TASK_LABEL_PREFIXES = ("agent:", "role:", "pipeline-stage:")


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def _all_issues(beads: Beads) -> list[dict[str, Any]]:
    if not beads.available():
        return []
    try:
        return beads.list_issues("--all")
    except BeadsError:
        return []


def _bead_deadline(bead: dict[str, Any]) -> str | None:
    for key in ("due", "due_date", "deadline"):
        value = bead.get(key)
        if value:
            return str(value)
    return None


def _run_meta(settings: Settings) -> dict[str, dict[str, Any]]:
    """Return run metadata by run id, newest first, without touching tmux."""
    out: dict[str, dict[str, Any]] = {}
    for meta in list_runs(settings, limit=100):
        run_id = str(meta.get("run_id") or "")
        if run_id and run_id not in out:
            out[run_id] = meta
    return out


def _agent_state(settings: Settings, agent: Agent, now: datetime, running: bool) -> str:
    if (settings.state_dir() / "KILL").exists():
        return "killed"
    if (state_dir(settings, agent) / "PAUSED").exists():
        return "paused"
    if running:
        return "running"
    if workday_due(agent, now, last_workday_start(settings, agent)):
        return "idle"
    return "not-due"


def _current_for(
    agent: Agent,
    live: list[dict[str, Any]],
    labels_by_bead: dict[str, list[str]],
    titles: dict[str, str],
    metas: dict[str, dict[str, Any]],
    sole_role_agent: dict[str, str],
) -> dict[str, Any] | None:
    """Match a live lease to AGENT by its bead label, else by a unique role."""
    chosen: dict[str, Any] | None = None
    for lease in live:
        bead = str(lease.get("bead") or "")
        if f"agent:{agent.name}" in labels_by_bead.get(bead, []):
            chosen = lease
            break
        if chosen is None and sole_role_agent.get(str(lease.get("role") or "")) == agent.name:
            chosen = lease
    if chosen is None:
        return None
    bead = str(chosen.get("bead") or "")
    run_id = str(chosen.get("run_id") or "")
    meta = metas.get(run_id, {})
    return {
        "bead": bead or None,
        "title": titles.get(bead) or bead or None,
        "run_id": run_id or None,
        "since": chosen.get("created"),
        "runner": meta.get("runner"),
        "model": meta.get("model"),
    }


def _assigned_rows(name: str, open_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bead in open_issues:
        labels = bead_labels(bead)
        if f"agent:{name}" not in labels:
            continue
        rows.append(
            {
                "bead": str(bead.get("id") or ""),
                "title": str(bead.get("title") or bead.get("id") or ""),
                "status": str(bead.get("status") or "open"),
                "stage": label_value(labels, "pipeline-stage:"),
                "epic": label_value(labels, "goal:"),
            }
        )
    rows.sort(key=lambda row: row["bead"])
    return rows


def _owner(labels: list[str]) -> str | None:
    for prefix in OWNER_PREFIXES:
        value = label_value(labels, prefix)
        if value:
            return f"{prefix}{value}"
    return None


def _task_rows(open_issues: list[dict[str, Any]], running_beads: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bead in open_issues:
        labels = bead_labels(bead)
        wanted = (
            any(label.startswith(prefix) for prefix in TASK_LABEL_PREFIXES for label in labels)
            or "kind:goal" in labels
        )
        if not wanted:
            continue
        bead_id = str(bead.get("id") or "")
        rows.append(
            {
                "bead": bead_id,
                "title": str(bead.get("title") or bead_id),
                "status": str(bead.get("status") or "open"),
                "owner": _owner(labels),
                "epic": label_value(labels, "goal:"),
                "stage": label_value(labels, "pipeline-stage:"),
                "kind": label_value(labels, "kind:"),
                "deadline": _bead_deadline(bead),
                "running": bead_id in running_beads,
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["running"] else 1,
            0 if row["status"] == "in_progress" else 1,
            row["deadline"] or "9999-12-31",
            row["bead"],
        )
    )
    return rows


def _epic_rows(
    settings: Settings, beads: Beads, issues: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from cube.pipeline import list_pipeline_epics, pipeline_status

    if not beads.available():
        return []
    try:
        epics = list_pipeline_epics(beads, open_only=True)
    except (BeadsError, ValueError):
        return []
    rows: list[dict[str, Any]] = []
    for epic in epics:
        epic_id = str(epic.get("id") or "")
        children = [item for item in issues if f"goal:{epic_id}" in bead_labels(item)]
        try:
            status = pipeline_status(settings, beads, epic_id, today=_now().date())
        except (BeadsError, ValueError, OSError):
            status = {}
        rows.append(
            {
                "bead": epic_id,
                "title": str(epic.get("title") or epic_id),
                "stage": status.get("stage"),
                "next": status.get("next"),
                "open": sum(
                    1 for item in children if str(item.get("status") or "open") not in CLOSED
                ),
                "done": sum(1 for item in children if str(item.get("status") or "") in CLOSED),
            }
        )
    rows.sort(key=lambda row: str(row["bead"]))
    return rows


def build_work(settings: Settings, beads: Beads, *, now: datetime | None = None) -> dict[str, Any]:
    """Materialise the cockpit work view.  Read-only by construction."""
    moment = _now(now)
    agents, _errors = load_all_agents(settings.root)
    issues = _all_issues(beads)
    open_issues = [item for item in issues if str(item.get("status") or "open") not in CLOSED]
    labels_by_bead = {str(item.get("id")): bead_labels(item) for item in issues}
    titles = {str(item.get("id")): str(item.get("title") or item.get("id")) for item in issues}
    live = [lease.as_dict() for lease in leases.live_leases(settings.state_dir(), moment)]
    running_beads = {str(lease.get("bead") or "") for lease in live}
    metas = _run_meta(settings)
    role_counts: dict[str, list[str]] = {}
    for agent in agents.values():
        role_counts.setdefault(agent.role, []).append(agent.name)
    sole_role_agent = {role: names[0] for role, names in role_counts.items() if len(names) == 1}
    agent_rows: list[dict[str, Any]] = []
    for name in sorted(agents):
        agent = agents[name]
        current = _current_for(agent, live, labels_by_bead, titles, metas, sole_role_agent)
        started = last_workday_start(settings, agent)
        usage = resource_usage(settings, agent, now=moment)
        agent_rows.append(
            {
                "name": agent.name,
                "kind": agent.kind,
                "host": agent.host,
                "cron": agent.workday.cron,
                "state": _agent_state(settings, agent, moment, current is not None),
                "current": current,
                "assigned": _assigned_rows(agent.name, open_issues),
                "inbox_unread": len(read_inbox(settings.root, agent, unread_only=True)),
                "last_workday": started.isoformat(timespec="seconds") if started else None,
                "next_tick": agent.workday.cron,
                "today": {"runs": int(usage["runs"]), "spend_usd": float(usage["spend_usd"])},
            }
        )
    return {
        "generated": moment.isoformat(timespec="seconds"),
        "agents": agent_rows,
        "tasks": _task_rows(open_issues, running_beads),
        "epics": _epic_rows(settings, beads, issues),
    }


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(head) for head in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(head.ljust(widths[i]) for i, head in enumerate(headers)).rstrip()]
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(lines)


def work_text(data: dict[str, Any]) -> str:
    """Render the work view as one table per block."""
    agents = [
        [
            str(row["name"]),
            str(row["host"]),
            str(row["next_tick"]),
            str(row["state"]),
            str((row["current"] or {}).get("bead") or "-"),
            str(row["inbox_unread"]),
            str(len(row["assigned"])),
            str(row["today"]["runs"]),
        ]
        for row in data["agents"]
    ]
    tasks = [
        [
            str(row["bead"]),
            "run" if row["running"] else str(row["status"]),
            str(row["owner"] or "-"),
            str(row["stage"] or "-"),
            str(row["deadline"] or "-"),
            str(row["title"]),
        ]
        for row in data["tasks"]
    ]
    epics = [
        [
            str(row["bead"]),
            str(row["stage"] or "-"),
            f"{row['open']}/{row['open'] + row['done']}",
            str(row["next"] or "-"),
        ]
        for row in data["epics"]
    ]
    blocks = [
        "Agents\n"
        + (
            _table(["name", "host", "tick", "state", "bead", "inbox", "assigned", "runs"], agents)
            if agents
            else "no standing agents"
        ),
        "Tasks\n"
        + (
            _table(["bead", "status", "owner", "stage", "due", "title"], tasks)
            if tasks
            else "no open tasks"
        ),
        "Epics\n"
        + (_table(["bead", "stage", "open", "next"], epics) if epics else "no research pipelines"),
    ]
    return "\n\n".join(blocks)


def cmd_work(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, True)
    data = build_work(settings, beads)
    helpers.emit(args, data, work_text(data))
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("work", help="what the cube is working on: agents, tasks, epics")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_work(a, s, helpers))
