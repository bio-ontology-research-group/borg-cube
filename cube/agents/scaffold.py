"""Scaffold the durable files for a standing agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from cube.config import Settings
from cube.roles import RoleError, load_role


@dataclass(frozen=True)
class AgentScaffoldSpec:
    """Inputs shared by ``cube agent new`` and ``cube group apply``."""

    name: str
    kind: str
    title: str
    topics: list[str]
    role: str
    runtime: str
    skills: list[str] = field(default_factory=list)
    gpu_hours: float = 0.0
    host: str = "ws"
    spend_usd: float = 0.0
    charter_text: str | None = None


def _spec(value: AgentScaffoldSpec | Mapping[str, Any]) -> AgentScaffoldSpec:
    if isinstance(value, AgentScaffoldSpec):
        return value
    return AgentScaffoldSpec(
        name=str(value["name"]),
        kind=str(value["kind"]),
        title=str(value["title"]),
        topics=[str(item) for item in value["topics"]],
        role=str(value["role"]),
        runtime=str(value["runtime"]),
        skills=[str(item) for item in value.get("skills", [])],
        gpu_hours=float(value.get("gpu_hours", 0)),
        host=str(value.get("host", "ws")),
        spend_usd=float(value.get("spend_usd", 0)),
        charter_text=value.get("charter_text"),
    )


def render_agent_files(
    settings: Settings, spec: AgentScaffoldSpec | Mapping[str, Any]
) -> dict[Path, str]:
    """Return the files a scaffold would create without writing them."""
    item = _spec(spec)
    if not item.name or not item.title or not item.topics:
        raise ValueError("agent name, title, and at least one topic are required")
    try:
        role = load_role(settings.root, item.role)
    except RoleError as exc:
        raise ValueError(str(exc)) from exc
    if item.runtime != role.runtime:
        raise ValueError(
            f"runtime {item.runtime} must equal role {item.role} runtime {role.runtime}"
        )
    if item.kind not in {"expert", "coordinator", "functional"}:
        raise ValueError(f"unsupported agent kind: {item.kind}")
    if item.gpu_hours < 0 or item.spend_usd < 0:
        raise ValueError("gpu_hours and spend_usd must be non-negative")
    config = {
        "name": item.name,
        "kind": item.kind,
        "title": item.title,
        "charter": f"agents/{item.name}/charter.md",
        "topics": item.topics,
        "role": item.role,
        "skills": list(dict.fromkeys(item.skills)),
        "runtime": item.runtime,
        "tier": role.tier.value,
        "host": item.host,
        "privacy_default": "internal",
        "memory_dir": f"agents/{item.name}/memory",
        "resources": {
            "node005_gpu_hours_per_day": item.gpu_hours,
            "ws_cpu": True,
            "ibex": "approval",
            "spend_usd_per_day": item.spend_usd,
            "outbound": "none",
        },
        "workday": {"cron": "hourly", "max_minutes": 30, "max_runs": 24, "max_runs_per_tick": 1},
        "reports": "weekly",
    }
    charter = item.charter_text or _placeholder_charter(item.title)
    files = {
        Path(f"agents/{item.name}.yaml"): yaml.safe_dump(config, sort_keys=False),
        Path(f"agents/{item.name}/charter.md"): charter,
        Path(f"agents/{item.name}/memory/journal.md"): "# Journal\n\n",
        Path(f"agents/{item.name}/memory/reading.md"): "# Reading\n\n",
        Path(f"agents/{item.name}/memory/ideas.md"): "# Ideas\n\n",
        Path(f"agents/{item.name}/memory/open-questions.md"): "# Open questions\n\n",
        Path(f"agents/{item.name}/inbox.jsonl"): "",
    }
    return files


def _placeholder_charter(title: str) -> str:
    return (
        f"# {title}\n\n"
        "This is example charter text for Robert to edit before autonomous work begins.\n\n"
        "## Mandate\n\n"
        "Example: work independently on the named topics, with all claims linked to sources.\n\n"
        "## May decide alone\n\n"
        "Example: reading plans and bounded local experiments inside the declared allowance.\n\n"
        "## Needs Robert\n\n"
        "Example: major resources, IBEX use, spending, any contact, and all irreversible "
        "actions.\n\n"
        "## Reading list seed\n\n"
        "Example: add only verified DOI, PMID, PMCID, or arXiv identifiers.\n\n"
        "## Success in 6 months\n\n"
        "Example: source-backed research suggestions with a clear expected outcome and kill "
        "criterion.\n"
    )


def scaffold_agent(settings: Settings, spec: AgentScaffoldSpec | Mapping[str, Any]) -> list[Path]:
    """Write a new agent scaffold and return its paths.

    Callers must check that the declaration does not already exist. This function
    intentionally has no overwrite path.
    """
    item = _spec(spec)
    declaration = settings.root / f"agents/{item.name}.yaml"
    if declaration.exists():
        raise ValueError(f"agent already exists: {item.name}")
    files = render_agent_files(settings, item)
    written: list[Path] = []
    for relative, content in files.items():
        path = settings.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
