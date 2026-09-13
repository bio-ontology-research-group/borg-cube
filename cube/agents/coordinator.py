"""The coordinator's management review: deterministic context, every few hours.

Robert, 2026-09-05: the coordinator must make sure there is consistent progress
on all projects, deadlines are met, students meet their goals, and everybody is
busy at least once per day with a task; it may make up research tasks from the
literature watch, or get somebody to design new research projects.

Robert, 2026-09-07: the coordinator distributes the work and makes sure it is
being done. The review runs every ``coordination.review_every_hours`` and sees,
per agent, what is assigned, when it last ran and what is stale; per project,
how long since a bead moved; and the review queue. This module builds those
facts (all from sources of record) and the gate; the coordinator's model run
does the judging and files, chases, reassigns and closes the beads.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.agents import Agent, load_all_agents, resource_usage, state_dir
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine.context import bead_labels, label_value

DEADLINE_HORIZON_DAYS = 30
MANAGEMENT_FILE = "management.json"
IDLE_STEP_TITLE = "management review"


def management_state_path(settings: Settings, agent: Agent | str) -> Path:
    return state_dir(settings, agent) / MANAGEMENT_FILE


def last_management_review(settings: Settings, agent: Agent | str) -> datetime | None:
    """When the last review started (a bare date, from before 2026-09-07, is its midnight)."""
    path = management_state_path(settings, agent)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = str(data.get("last"))
        value = datetime.fromisoformat(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def management_due(settings: Settings, agent: Agent | str, now: datetime) -> bool:
    """Every ``coordination.review_every_hours`` hours, whatever the tick count."""
    last = last_management_review(settings, agent)
    if last is None:
        return True
    gap = timedelta(hours=settings.coordination.review_every_hours)
    return now.astimezone(UTC) - last >= gap


def record_management_review(settings: Settings, agent: Agent | str, now: datetime) -> Path:
    path = management_state_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last": now.astimezone(UTC).isoformat(timespec="seconds")}, indent=1) + "\n",
        encoding="utf-8",
    )
    return path


def _open_issues(beads: Beads | None) -> list[dict[str, Any]]:
    if beads is None or not beads.available():
        return []
    try:
        issues = beads.list_issues("--all")
    except BeadsError:
        return []
    return [issue for issue in issues if str(issue.get("status", "open")) not in {"closed", "done"}]


def busy_agents(
    settings: Settings, issues: list[dict[str, Any]], now: datetime
) -> tuple[list[str], list[str]]:
    """Agents with an open assigned bead or a run today, and the idle rest."""
    agents, _errors = load_all_agents(settings.root)
    busy: list[str] = []
    idle: list[str] = []
    for name in sorted(agents):
        agent = agents[name]
        assigned = any(
            f"agent:{name}" in bead_labels(issue) and "needs:robert" not in bead_labels(issue)
            for issue in issues
        )
        runs_today = int(resource_usage(settings, agent, now=now).get("runs", 0))
        (busy if assigned or runs_today else idle).append(name)
    return busy, idle


def busy_people(
    people: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Students and postdocs with an open bead or goal naming them, and the idle rest."""
    named: set[str] = set()
    for issue in issues:
        labels = bead_labels(issue)
        person = label_value(labels, "person:")
        if person:
            named.add(person)
        for label in labels:
            if label.startswith("people:"):
                named.update(part for part in label.split(":", 1)[1].split(",") if part)
    busy = [p["id"] for p in people if p["id"] in named]
    idle = [p["id"] for p in people if p["id"] not in named]
    return busy, idle


def _stamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _hours_since(raw: Any, now: datetime) -> float | None:
    value = _stamp(raw)
    if value is None:
        return None
    return round(max(0.0, (now - value).total_seconds() / 3600), 1)


def assignments(
    settings: Settings, issues: list[dict[str, Any]], now: datetime
) -> dict[str, list[dict[str, Any]]]:
    """Per agent, every open assigned bead with its age, last run and whether it is stale.

    Robert, 2026-09-07: distributing work is half the job; the other half is
    making sure it is done. A bead is stale when no run of its agent touched it
    within ``coordination.stale_hours`` (the agent's ``bead-runs.json`` is the
    record) and it is not waiting on a review or on Robert.
    """
    from cube.patrols.agent_workday import bead_runs, waiting_on_review  # noqa: PLC0415

    agents, _errors = load_all_agents(settings.root)
    stale_after = settings.coordination.stale_hours
    out: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(agents):
        runs = bead_runs(settings, name)
        rows: list[dict[str, Any]] = []
        for issue in issues:
            labels = bead_labels(issue)
            if f"agent:{name}" not in labels:
                continue
            bead_id = str(issue.get("id") or "")
            record = runs.get(bead_id) or {}
            last_run = _hours_since(record.get("ts"), now)
            age = _hours_since(issue.get("created_at") or issue.get("created"), now)
            waiting = "needs:robert" in labels or waiting_on_review(issue, issues)
            never_ran = last_run is None and (age or 0.0) >= stale_after
            rows.append(
                {
                    "id": bead_id,
                    "title": str(issue.get("title") or "")[:80],
                    "status": str(issue.get("status") or "open"),
                    "age_hours": age,
                    "last_run_hours": last_run,
                    "waiting": waiting,
                    "stale": not waiting
                    and (never_ran or (last_run is not None and last_run >= stale_after)),
                }
            )
        rows.sort(key=lambda row: (-(row["age_hours"] or 0.0), row["id"]))
        out[name] = rows
    return out


def project_activity(
    projects: list[dict[str, Any]], issues: list[dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """Per project, open beads and days since a bead naming it last moved."""
    rows: list[dict[str, Any]] = []
    for project in projects:
        slug = str(project.get("slug") or "")
        named = [issue for issue in issues if f"project:{slug}" in bead_labels(issue)]
        stamps = [
            value
            for value in (
                _stamp(issue.get("updated_at") or issue.get("updated")) for issue in named
            )
            if value is not None
        ]
        newest = max(stamps) if stamps else None
        rows.append(
            {
                **project,
                "open_beads": len(named),
                "last_activity_days": (
                    round((now - newest).total_seconds() / 86400, 1) if newest else None
                ),
            }
        )
    return rows


def upcoming_deadlines(settings: Settings, today: date) -> list[dict[str, Any]]:
    from cube.sources.pa_kg import parse_deadlines  # noqa: PLC0415

    path = settings.dirs["pa"] / "deadlines.md"
    horizon = today + timedelta(days=DEADLINE_HORIZON_DAYS)
    rows: list[dict[str, Any]] = []
    for item in parse_deadlines(path):
        if not item.is_open or item.when > horizon:
            continue
        rows.append(
            {
                "when": item.when.isoformat(),
                "days": (item.when - today).days,
                "text": item.text,
                "source": f"{path}#L{item.line}",
            }
        )
    rows.sort(key=lambda row: row["when"])
    return rows


def literature_seeds(settings: Settings, today: date, limit: int = 8) -> list[dict[str, Any]]:
    """High and normal priority entries from today's or yesterday's literature digest."""
    from cube.literature import load_digest  # noqa: PLC0415

    for day in (today, today - timedelta(days=1)):
        digest = load_digest(settings, day)
        if not digest:
            continue
        entries = [
            entry
            for entry in digest.get("entries", [])
            if isinstance(entry, dict) and entry.get("priority") in {"high", "normal"}
        ]
        return [
            {
                "title": str(entry.get("title") or ""),
                "url": str(entry.get("url") or ""),
                "for": [
                    f"{rel.get('kind')} {rel.get('ref')}"
                    for rel in entry.get("relevance", [])
                    if isinstance(rel, dict)
                ],
                "digest": str(
                    settings.literature_watch.digest_path(settings.root) / day.isoformat()
                ),
            }
            for entry in entries[:limit]
        ]
    return []


def management_facts(
    settings: Settings, beads: Beads | None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Everything the daily review needs, each item with its source."""
    from cube.literature import build_context  # noqa: PLC0415

    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).date()
    ctx = build_context(settings, beads=beads)
    issues = _open_issues(beads)
    agents_busy, agents_idle = busy_agents(settings, issues, now)
    people_busy, people_idle = busy_people(ctx.students, issues)
    goals: list[dict[str, Any]] = []
    for goal in ctx.goals:
        days = None
        if goal.get("deadline"):
            try:
                days = (date.fromisoformat(str(goal["deadline"])) - today).days
            except ValueError:
                days = None
        goals.append({**goal, "days_left": days})
    pipelines: list[dict[str, Any]] = []
    if beads is not None and beads.available():
        try:
            from cube.pipeline import list_pipeline_epics, pipeline_status  # noqa: PLC0415

            for epic in list_pipeline_epics(beads, open_only=True):
                status = pipeline_status(settings, beads, str(epic.get("id")), today=today)
                pipelines.append(
                    {
                        "epic": str(epic.get("id")),
                        "title": str(epic.get("title") or ""),
                        "stage": status.get("stage"),
                        "next": status.get("next"),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - a broken epic must not stop the review
            pipelines.append({"epic": "?", "title": f"pipeline status failed: {exc}"})
    assigned = assignments(settings, issues, now)
    reviews = [issue for issue in issues if "kind:review" in bead_labels(issue)]
    return {
        "date": today.isoformat(),
        "time": now.astimezone(UTC).isoformat(timespec="minutes"),
        "projects": project_activity(ctx.projects, issues, now),
        "pipelines": pipelines,
        "goals": goals,
        "deadlines": upcoming_deadlines(settings, today),
        "agents": {"busy": agents_busy, "idle": agents_idle},
        "assignments": assigned,
        "stale": [row for rows in assigned.values() for row in rows if row["stale"]],
        "reviews_pending": len(reviews),
        "people": {"busy": people_busy, "idle": people_idle, "roster": ctx.students},
        "literature": literature_seeds(settings, today),
        "sources": [*ctx.sources, str(settings.dirs["pa"] / "deadlines.md")],
    }


def management_context(
    settings: Settings, beads: Beads | None, *, now: datetime | None = None
) -> str:
    """The daily management review prompt block, deterministic and source-backed."""
    facts = management_facts(settings, beads, now=now)
    gap_days = settings.coordination.project_gap_days
    stale_hours = settings.coordination.stale_hours
    lines: list[str] = [
        f"# Management review {facts['date']} ({facts.get('time', '')})",
        "",
        "Charter: consistent progress on every project, deadlines met, students meeting",
        "their goals, everybody busy at least once a day. You distribute the work and",
        "make sure it is being done. Sources: " + "; ".join(facts["sources"]),
        "",
        "## Pipelines and projects",
    ]
    for row in facts["pipelines"]:
        lines.append(f"- {row['epic']} {row['title']}: stage {row.get('stage')}; {row.get('next')}")
    for project in facts["projects"]:
        days = project.get("last_activity_days")
        quiet = days is None or days >= gap_days
        activity = (
            "no bead has ever named it" if days is None else f"last bead activity {days} day(s) ago"
        )
        lines.append(
            f"- project {project['slug']} ({project['name']}): members "
            + (", ".join(project["members"]) or "none")
            + "; topics "
            + (", ".join(project["topics"]) or "none")
            + f"; {project.get('open_beads', 0)} open bead(s); {activity}"
            + (f"; QUIET (over {gap_days} days)" if quiet else "")
        )
    lines += ["", "## Goals"]
    for goal in facts["goals"] or []:
        days = goal.get("days_left")
        lines.append(
            f"- {goal['id']} {goal['title']}: deadline {goal.get('deadline') or 'none'}"
            + (f" ({days} days left)" if days is not None else "")
        )
    if not facts["goals"]:
        lines.append("- no open goals")
    lines += ["", f"## Deadlines within {DEADLINE_HORIZON_DAYS} days"]
    for row in facts["deadlines"]:
        lines.append(
            f"- {row['when']} ({row['days']} days): {row['text']} (source: {row['source']})"
        )
    if not facts["deadlines"]:
        lines.append("- none")
    lines += ["", f"## Assigned work per agent (stale: no run for {stale_hours} h)"]
    for name, rows in facts.get("assignments", {}).items():
        if not rows:
            lines.append(f"- {name}: nothing assigned")
            continue
        parts = []
        for row in rows:
            ran = (
                "never ran"
                if row["last_run_hours"] is None
                else f"last run {row['last_run_hours']} h ago"
            )
            flag = " STALE" if row["stale"] else (" waiting" if row["waiting"] else "")
            parts.append(f"{row['id']} ({row['status']}, {ran}{flag}) {row['title']}")
        lines.append(f"- {name}: " + "; ".join(parts))
    lines.append(f"- review beads open: {facts.get('reviews_pending', 0)}")
    lines += [
        "",
        "## Who is busy today",
        f"- agents busy: {', '.join(facts['agents']['busy']) or 'none'}",
        f"- agents idle: {', '.join(facts['agents']['idle']) or 'none'}",
        f"- people busy: {', '.join(facts['people']['busy']) or 'none'}",
        f"- people idle (students and postdocs with no open bead or goal): "
        f"{', '.join(facts['people']['idle']) or 'none'}",
        "",
        "## Literature seeds (today's watch)",
    ]
    for entry in facts["literature"]:
        lines.append(
            f"- {entry['title']} {entry['url']} for: {', '.join(entry['for']) or 'topics'}"
        )
    if not facts["literature"]:
        lines.append("- no digest yet today")
    lines += [
        "",
        "## What to do now",
        "1. Distribute. Every QUIET project gets work this review, assigned to the expert",
        "   agent whose topics it names: a literature scan (new papers since the last",
        "   scan, positioned against the project), a research plan refinement (what the",
        "   next result is and how it is measured), or an improvement (a bounded change",
        "   to its code, data, mappings or manuscript, one batch at a time). A goal or",
        "   project with a table, a list or a corpus to go through gets one batch bead at",
        "   a time, each naming its rows or files, the next filed when one closes.",
        "   `cube create --title '<task>' --kind task --role <its role> --project <slug>",
        "   --provenance '<url or path>' --apply`, then `bd label add <id> agent:<name>`.",
        "2. Chase. Every STALE bead: read its comments; if a run failed, say what to change",
        "   in a comment and leave it for the next tick; if nothing happened, tell the",
        "   agent (`cube agent tell <name> '<what>' --apply`) or reassign it; if it is",
        "   done, close it with the evidence. A bead that has been waiting on a review",
        "   for more than a day is dispatched by the marshal; do not file a second one.",
        "3. Maintain a small ready queue against explicit active goals. One owner and",
        "   one reviewer per project checkpoint. Prioritize finishing, reviewing and",
        "   publishing existing work over starting another literature/planning loop.",
        "4. Do not manufacture agent or person tasks merely because someone is idle.",
        "   Capacity-deferred agents are waiting, not failing. Student/twin work needs",
        "   a sourced topic and milestone; never contact students yourself.",
        "5. For every deadline or goal within 30 days without an open bead, create the",
        "   beads that make it happen and assign them to agents or people.",
        "6. For a pipeline whose `next` waits on an agent, tell that agent; if it waits",
        "   on Robert, leave it.",
        "7. Decide. Escalations routed to you (agent:coordinator, kind finding, request or",
        "   conflict) are yours to settle: pick, record why on the bead, file the",
        "   follow-up, close it. Robert sees only security-critical (a change to a running",
        "   system, spend over budget, contact) and privacy-critical (a person's data,",
        "   secrets, local-only material) matters; mark those `critical`. Report actual",
        "   artifact and pushed commit links, not activity counts as research progress.",
        "Every bead needs provenance; every claim a source line from above.",
    ]
    return "\n".join(lines)
