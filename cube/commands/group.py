"""``cube group``: plan, create, reconcile and inspect research agents."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from cube.agents import (
    journal_entries,
    load_all_agents,
    read_inbox,
    resource_usage,
)
from cube.agents.charter import render_charter
from cube.agents.scaffold import AgentScaffoldSpec, render_agent_files, scaffold_agent
from cube.beads import BeadsError
from cube.commands import Helpers
from cube.config import GroupConfig, Settings
from cube.sources.rkg import KgProjectNode, ResearchKg, load_graph
from cube.sync.reconcile import OPEN_STATES, bead_labels, bead_status

SAFE_NAME = re.compile(r"[a-z][a-z0-9-]*")


def _group(settings: Settings) -> GroupConfig | None:
    return settings.group


def _expert_title(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-")) + " expert"


def configured_specs(settings: Settings) -> list[AgentScaffoldSpec]:
    """Expand the compact group declaration into runtime-ready agent specs."""
    from cube.roles import load_role

    group = _group(settings)
    if group is None:
        return []
    specs: list[AgentScaffoldSpec] = []
    for name, expert_config in group.experts.items():
        if not SAFE_NAME.fullmatch(name):
            raise ValueError(f"group agent name is unsafe: {name}")
        role = load_role(settings.root, "senior")
        specs.append(
            AgentScaffoldSpec(
                name=name,
                kind="expert",
                title=_expert_title(name),
                topics=expert_config.topics,
                role="senior",
                runtime=role.runtime,
                skills=["literature-review", "research-planning", *expert_config.skills],
                gpu_hours=expert_config.gpu_hours,
            )
        )
    for name, functional_config in group.functional.items():
        if not SAFE_NAME.fullmatch(name):
            raise ValueError(f"group agent name is unsafe: {name}")
        role = load_role(settings.root, functional_config.role)
        specs.append(
            AgentScaffoldSpec(
                name=name,
                kind="functional",
                title=functional_config.title,
                topics=functional_config.topics,
                role=functional_config.role,
                runtime=role.runtime,
                skills=functional_config.skills,
            )
        )
    return [
        replace(
            spec,
            topics=list(dict.fromkeys(spec.topics)),
            skills=list(dict.fromkeys(spec.skills)),
        )
        for spec in sorted(specs, key=lambda item: item.name)
    ]


def _topic_slug(value: str) -> str:
    return value.rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _project_years(project: KgProjectNode) -> str:
    end = project.end_year if project.end_year is not None else "ongoing"
    return f"{project.start_year or '?'}-{end}"


def _active_projects_without_expert(
    graph: ResearchKg, expert_topics: set[str]
) -> list[dict[str, Any]]:
    current_year = date.today().year
    rows: list[dict[str, Any]] = []
    for project in graph.projects:
        if project.end_year is not None and project.end_year < current_year:
            continue
        topics = sorted({_topic_slug(topic) for topic in project.topics})
        if set(topics) & expert_topics:
            continue
        rows.append(
            {
                "slug": project.slug,
                "name": project.name,
                "years": _project_years(project),
                "topics": topics,
                "source": "rkg: projects.jsonld",
            }
        )
    return sorted(rows, key=lambda row: (row["name"].lower(), row["slug"]))


def _sources(settings: Settings) -> dict[str, str]:
    return {
        "config": str(settings.root / "cube.yaml"),
        "projects": str(settings.dirs["rkg"] / "projects.jsonld"),
        "topics": str(settings.dirs["rkg"] / "topics"),
        "agents": str(settings.root / "agents"),
    }


def group_plan(settings: Settings) -> dict[str, Any]:
    group = _group(settings)
    if group is None:
        return {
            "configured": False,
            "create": [],
            "drift": [],
            "uncovered_topics": [],
            "active_projects_without_expert": [],
            "sources": _sources(settings),
        }
    specs = configured_specs(settings)
    agents, errors = load_all_agents(settings.root)
    graph = load_graph(settings.dirs["rkg"] / "projects.jsonld")
    known_topics = set(graph.topics)
    configured_topics = [topic for config in group.experts.values() for topic in config.topics]
    coverage = {
        topic
        for agent in agents.values()
        if agent.kind == "expert"
        for topic in agent.topics
        if topic in known_topics
    }
    created = []
    drift = []
    for spec in specs:
        path = settings.root / f"agents/{spec.name}.yaml"
        if not path.exists():
            created.append(
                {
                    "name": spec.name,
                    "kind": spec.kind,
                    "role": spec.role,
                    "topics": spec.topics,
                    "skills": spec.skills,
                    "gpu_hours": spec.gpu_hours,
                    "files": [str(settings.root / path) for path in _scaffold_paths(spec)],
                }
            )
            continue
        agent = agents.get(spec.name)
        if agent is None:
            continue
        expected = _expected_fields(spec)
        fields: dict[str, dict[str, Any]] = {}
        if agent.topics != expected["topics"]:
            fields["topics"] = {"expected": expected["topics"], "actual": agent.topics}
        if agent.skills != expected["skills"]:
            fields["skills"] = {"expected": expected["skills"], "actual": agent.skills}
        gpu = agent.resources.node005_gpu_hours_per_day
        if gpu != expected["gpu_hours"]:
            fields["gpu_hours"] = {"expected": expected["gpu_hours"], "actual": gpu}
        if fields:
            drift.append(
                {
                    "name": spec.name,
                    "kind": spec.kind,
                    "fields": fields,
                }
            )
    uncovered: list[str] = []
    for topic in dict.fromkeys(configured_topics):
        if topic not in coverage:
            uncovered.append(topic)
    return {
        "configured": True,
        "create": created,
        "drift": drift,
        "errors": errors,
        "uncovered_topics": uncovered,
        "active_projects_without_expert": _active_projects_without_expert(graph, coverage),
        "sources": _sources(settings),
    }


def _expected_fields(spec: AgentScaffoldSpec) -> dict[str, Any]:
    return {
        "topics": spec.topics,
        "skills": spec.skills,
        "gpu_hours": spec.gpu_hours,
    }


def _scaffold_paths(spec: AgentScaffoldSpec) -> list[Path]:
    return [
        Path(f"agents/{spec.name}.yaml"),
        Path(f"agents/{spec.name}/charter.md"),
        Path(f"agents/{spec.name}/memory/journal.md"),
        Path(f"agents/{spec.name}/memory/reading.md"),
        Path(f"agents/{spec.name}/memory/ideas.md"),
        Path(f"agents/{spec.name}/memory/open-questions.md"),
        Path(f"agents/{spec.name}/inbox.jsonl"),
    ]


def _topic_briefs(settings: Settings, topics: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for topic in topics:
        path = settings.dirs["rkg"] / "topics" / f"{topic}.md"
        if path.exists():
            result[topic] = path.read_text(encoding="utf-8")
    return result


def _charter_spec(spec: AgentScaffoldSpec, charter: str) -> AgentScaffoldSpec:
    return spec.__class__(**{**spec.__dict__, "charter_text": charter})


def _apply_reconcile(settings: Settings, spec: AgentScaffoldSpec, *, dry_run: bool) -> list[str]:
    path = settings.root / f"agents/{spec.name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    expected = _expected_fields(spec)
    changes: list[str] = []
    if data.get("topics") != expected["topics"]:
        data["topics"] = expected["topics"]
        changes.append("topics")
    if data.get("skills") != expected["skills"]:
        data["skills"] = expected["skills"]
        changes.append("skills")
    resources = data.setdefault("resources", {})
    if resources.get("node005_gpu_hours_per_day") != expected["gpu_hours"]:
        resources["node005_gpu_hours_per_day"] = expected["gpu_hours"]
        changes.append("resources.node005_gpu_hours_per_day")
    if changes and not dry_run:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return changes


def _is_placeholder(path: Path) -> bool:
    return path.exists() and "example charter text" in path.read_text(encoding="utf-8").lower()


def _apply_charter(
    settings: Settings, spec: AgentScaffoldSpec, charter: str, *, dry_run: bool
) -> dict[str, Any] | None:
    path = settings.root / f"agents/{spec.name}/charter.md"
    if not _is_placeholder(path):
        return None
    backup = path.with_name("charter.md.bak")
    if not dry_run:
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(charter, encoding="utf-8")
    return {"name": spec.name, "charter": str(path), "backup": str(backup)}


def group_apply(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    plan = group_plan(settings)
    if not plan["configured"]:
        return {"configured": False, "dry_run": args.dry_run, "created": [], "reconciled": []}
    specs = {spec.name: spec for spec in configured_specs(settings)}
    graph = load_graph(settings.dirs["rkg"] / "projects.jsonld")
    all_topics = sorted({topic for spec in specs.values() for topic in spec.topics})
    briefs = _topic_briefs(settings, all_topics)
    created: list[dict[str, Any]] = []
    reconciled: list[dict[str, Any]] = []
    charters: list[dict[str, Any]] = []
    for row in plan["create"]:
        spec = specs[row["name"]]
        charter = render_charter(briefs, graph.projects, spec)
        charter_spec = _charter_spec(spec, charter)
        paths = (
            scaffold_agent(settings, charter_spec)
            if not args.dry_run
            else [settings.root / path for path in render_agent_files(settings, charter_spec)]
        )
        created.append({"name": spec.name, "files": [str(path) for path in paths]})
    if args.reconcile:
        agents, _ = load_all_agents(settings.root)
        for name, spec in specs.items():
            if name not in agents:
                continue
            changes = _apply_reconcile(settings, spec, dry_run=args.dry_run)
            if changes:
                reconciled.append({"name": name, "fields": changes})
    if args.charters:
        for _name, spec in specs.items():
            charter = render_charter(briefs, graph.projects, spec)
            changed = _apply_charter(settings, spec, charter, dry_run=args.dry_run)
            if changed:
                charters.append(changed)
    return {
        "configured": True,
        "dry_run": args.dry_run,
        "created": created,
        "reconciled": reconciled,
        "charters": charters,
        "plan": group_plan(settings) if not args.dry_run else plan,
        "sources": _sources(settings),
    }


def _reviewed_by(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    front = text.split("---", 2)
    if len(front) < 3:
        return None
    match = re.search(r"(?m)^reviewed_by:\s*(.+?)\s*$", front[1])
    if not match or match[1] in {"null", "~", ""}:
        return None
    return match[1].strip("'\"")


def _pipeline_rows(beads: Any, name: str) -> list[dict[str, Any]]:
    if not beads.available():
        return []
    try:
        issues = beads.list_issues("--all")
    except BeadsError:
        return []
    rows: list[dict[str, Any]] = []
    for bead in issues:
        labels = bead_labels(bead)
        if f"agent:{name}" not in labels or bead_status(bead) not in OPEN_STATES:
            continue
        stages = [label.split(":", 1)[1] for label in labels if label.startswith("pipeline-stage:")]
        if not stages:
            continue
        pipelines = [label.split(":", 1)[1] for label in labels if label.startswith("goal:")]
        rows.append(
            {
                "bead": str(bead.get("id") or ""),
                "pipeline": pipelines[0] if pipelines else None,
                "stages": sorted(stages),
            }
        )
    return sorted(rows, key=lambda row: (row["pipeline"] or "", row["bead"]))


def group_status(settings: Settings, helpers: Helpers) -> list[dict[str, Any]]:
    agents, _errors = load_all_agents(settings.root)
    beads = helpers.beads(settings, True)
    try:
        issues = beads.list_issues("--all") if beads.available() else []
    except BeadsError:
        issues = []
    rows: list[dict[str, Any]] = []
    for name, agent in agents.items():
        open_issues = [
            bead
            for bead in issues
            if f"agent:{name}" in bead_labels(bead) and bead_status(bead) in OPEN_STATES
        ]
        proposals = sum("kind:proposal" in bead_labels(bead) for bead in open_issues)
        entries = journal_entries(settings.root, agent, limit=1)
        last = entries[0].splitlines()[0][3:13] if entries else None
        usage = resource_usage(settings, agent)
        charter = settings.root / agent.charter
        reviewed = _reviewed_by(charter)
        generated = (
            charter.exists()
            and "generated_from: research-knowledge-graph" in charter.read_text(encoding="utf-8")
        )
        rows.append(
            {
                "name": name,
                "kind": agent.kind,
                "role": agent.role,
                "topics": agent.topics,
                "last_journal_entry_date": last,
                "inbox_unread": len(read_inbox(settings.root, agent, unread_only=True)),
                "pending_proposals": proposals,
                "today": {"runs": usage["runs"], "spend_usd": usage["spend_usd"]},
                "pipelines": _pipeline_rows(beads, name),
                "charter_state": (
                    "edited-by-robert"
                    if reviewed
                    else ("generated" if generated else "placeholder")
                ),
                "charter_reviewed_by": reviewed,
            }
        )
    return rows


def _plan_text(data: dict[str, Any]) -> str:
    if not data["configured"]:
        return "group: not configured"
    lines = [
        f"create: {', '.join(row['name'] for row in data['create']) or 'none'}",
        f"drift: {', '.join(row['name'] for row in data['drift']) or 'none'}",
        f"uncovered topics: {', '.join(data['uncovered_topics']) or 'none'}",
        "active projects without an expert: "
        + ", ".join(row["slug"] for row in data["active_projects_without_expert"])
        if data["active_projects_without_expert"]
        else "active projects without an expert: none",
    ]
    return "\n".join(lines)


def cmd_plan(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        data = group_plan(settings)
    except (OSError, ValueError) as exc:
        print(f"cube group plan: {exc}", file=sys.stderr)
        return 2
    helpers.emit(args, data, _plan_text(data))
    return 0


def cmd_apply(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        data = group_apply(args, settings)
    except (OSError, ValueError) as exc:
        print(f"cube group apply: {exc}", file=sys.stderr)
        return 2
    helpers.emit(args, data, "group apply complete")
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    rows = group_status(settings, helpers)
    data = {"agents": rows, "sources": _sources(settings)}
    text = "\n".join(
        f"{row['name']}: {row['charter_state']} runs={row['today']['runs']}" for row in rows
    )
    helpers.emit(args, data, text or "no standing agents")
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("group", help="manage the research group as named agents")
    commands = parser.add_subparsers(dest="group_cmd", required=True)
    plan = commands.add_parser("plan", help="compare group configuration with agents and the KG")
    helpers.add_json(plan)
    plan.set_defaults(fn=lambda args, settings: cmd_plan(args, settings, helpers))
    apply = commands.add_parser("apply", help="create or reconcile configured agents")
    apply.add_argument("--reconcile", action="store_true")
    apply.add_argument("--charters", action="store_true")
    helpers.add_json(apply)
    helpers.add_dry(apply)
    apply.set_defaults(fn=lambda args, settings: cmd_apply(args, settings, helpers))
    status = commands.add_parser("status", help="show agent work and resource status")
    helpers.add_json(status)
    status.set_defaults(fn=lambda args, settings: cmd_status(args, settings, helpers))
