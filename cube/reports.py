"""Reports for Robert: one per finished goal (ADR-0027).

Robert, 2026-09-08: fewer messages, larger reports, mainly when larger goals are
finished. The goals patrol calls ``goal_report`` once per goal it sees closed,
writes the markdown under ``briefings/goals/`` and leaves the text in hermes-ws's
inbox, so the outbox cron posts it to his Mattermost DM once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.engine.context import bead_labels, label_value
from cube.goals import CLOSED, goal_children, goal_header

REPORT_DIR = Path("briefings") / "goals"
# Mattermost posts up to 16k characters; the inbox line stays well under that and
# points at the full file for the rest.
MESSAGE_CHARS = 6000
MAX_ITEMS = 40


def _status(bead: dict[str, Any]) -> str:
    return str(bead.get("status") or "open")


def _when(value: Any) -> str:
    text = str(value or "")
    return text[:10] if text else "?"


def _owner(bead: dict[str, Any]) -> str:
    labels = bead_labels(bead)
    for prefix in ("agent:", "role:", "person:"):
        name = label_value(labels, prefix)
        if name:
            return name
    return "cube"


def _line(bead: dict[str, Any]) -> str:
    ident = str(bead.get("id") or "?")
    title = str(bead.get("title") or ident)
    owner = _owner(bead)
    status = _status(bead)
    reason = str(bead.get("close_reason") or "").strip()
    tail = f" ({reason[:120]})" if status in CLOSED and reason else ""
    return f"- {ident} [{owner}] {title}{tail}"


def goal_report(
    settings: Settings,
    goal: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> str:
    """The markdown report for one finished goal: what was asked, what was done, by whom."""
    now = now or datetime.now(UTC)
    header = goal_header(goal)
    goal_id = str(goal.get("id") or "")
    title = str(goal.get("title") or goal_id)
    children = goal_children(goal_id, issues)
    done = [c for c in children if _status(c) in CLOSED]
    open_items = [c for c in children if _status(c) not in CLOSED]
    owners: dict[str, int] = {}
    for child in done:
        owners[_owner(child)] = owners.get(_owner(child), 0) + 1
    lines = [f"# Goal report: {title}", ""]
    lines.append(
        f"Goal {goal_id}, closed {_when(goal.get('closed_at') or goal.get('updated_at'))}."
    )
    if header is not None:
        lines.append(
            f"Target date {header.target.isoformat()}; project {header.project or 'none'}."
        )
        if header.people:
            lines.append("People: " + ", ".join(header.people) + ".")
    reason = str(goal.get("close_reason") or "").strip()
    if reason:
        lines += ["", f"Closed because: {reason}"]
    if header is not None and header.success:
        lines += ["", "## Success criteria", ""]
        lines += [f"- {item}" for item in header.success]
    lines += ["", "## What was done", ""]
    lines.append(
        f"{len(done)} of {len(children)} work item(s) closed"
        + (
            "; by " + ", ".join(f"{name} ({count})" for name, count in sorted(owners.items()))
            if owners
            else ""
        )
        + "."
    )
    if done:
        lines.append("")
        lines += [_line(c) for c in done[:MAX_ITEMS]]
        if len(done) > MAX_ITEMS:
            lines.append(f"- and {len(done) - MAX_ITEMS} more")
    if open_items:
        lines += ["", "## Still open", ""]
        lines += [_line(c) for c in open_items[:MAX_ITEMS]]
    lines += [
        "",
        f"Generated {now.isoformat(timespec='seconds')} from the Beads ledger (ADR-0027).",
        "",
    ]
    return "\n".join(lines)


def report_path(settings: Settings, goal_id: str) -> Path:
    safe = "".join(ch for ch in goal_id if ch.isalnum() or ch in "-._") or "goal"
    return settings.root / REPORT_DIR / f"{safe}.md"


def write_goal_report(
    settings: Settings,
    goal: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Write the report file and leave it for hermes-ws; returns what happened."""
    from cube.agents import AgentError, append_inbox, load_agent  # noqa: PLC0415

    goal_id = str(goal.get("id") or "")
    text = goal_report(settings, goal, issues, now=now)
    path = report_path(settings, goal_id)
    out: dict[str, Any] = {"goal": goal_id, "path": str(path), "chars": len(text), "posted": False}
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    try:
        agent = load_agent(settings.root, "hermes-ws", validate_role=False)
    except AgentError:
        return out
    if agent.host != settings.host:
        return out
    message = text
    if len(message) > MESSAGE_CHARS:
        message = message[:MESSAGE_CHARS].rstrip() + f"\n\n(continued in {path})"
    out["posted"] = True
    if not dry_run:
        append_inbox(settings.root, agent, message, sender="cube")
    return out


def goal_reports(
    settings: Settings,
    ledger: Beads,
    goals: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    del ledger  # the issues were listed by the caller; kept for symmetry with patrols
    return [write_goal_report(settings, goal, issues, now=now, dry_run=dry_run) for goal in goals]
