"""Standing-agent identities, bounded memory, and resource accounting.

Agents are deliberately separate from functional roles.  A role describes how a
piece of work is done; an agent owns a named, source-backed research remit.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine.context import bead_labels, resolve_skills
from cube.model import BeadHeader, Privacy, Provenance, Tier
from cube.roles import Role, RoleError, load_role
from cube.runners.naming import harness_of


class AgentError(ValueError):
    """The named standing agent is absent or its declaration is unsafe."""


AgentKind = Literal["coordinator", "expert", "functional"]
AgentRuntime = Literal["claude", "codex", "hermes"]


class AgentResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node005_gpu_hours_per_day: float = Field(ge=0)
    ws_cpu: bool
    ibex: Literal["approval", "none"]
    spend_usd_per_day: float = Field(ge=0)  # 0: no per-agent gate, global budget governs
    outbound: Literal["none"]


_CRON_RE = re.compile(r"^(?:hourly|(?:[01]\d|2[0-3]):[0-5]\d|\S+(?: \S+){4})$")
HOURLY_GAP_MINUTES = 50


class AgentWorkday(BaseModel):
    """When and how much an agent works.

    ``cron`` is ``HH:MM`` (one workday per day at that local time), ``hourly``
    (a 24/7 agent: every tick of the agent-workday timer checks the inbox and
    assigned beads, runs at most ``max_runs_per_tick`` steps, and stays idle when
    nothing is waiting), or a five-field cron expression for agents paced by
    their own timer (the laptop liaison). ``max_runs`` always caps the whole day.
    """

    model_config = ConfigDict(extra="forbid")

    cron: str = Field(min_length=1)
    max_minutes: int = Field(ge=1, le=24 * 60)
    max_runs: int = Field(ge=0, le=100)
    max_runs_per_tick: int | None = Field(default=None, ge=1, le=100)

    @field_validator("cron")
    @classmethod
    def _cron_shape(cls, value: str) -> str:
        if not _CRON_RE.match(value):
            raise ValueError("workday.cron must be HH:MM, hourly, or a five-field cron")
        return value

    @property
    def hourly(self) -> bool:
        """Frequent ticks: ``hourly`` or a cron expression (idle when nothing waits)."""
        return self.cron == "hourly" or " " in self.cron

    @property
    def daily_at(self) -> tuple[int, int] | None:
        if ":" not in self.cron or " " in self.cron:
            return None
        hour, minute = self.cron.split(":")
        return int(hour), int(minute)

    @property
    def runs_per_tick(self) -> int:
        if self.max_runs_per_tick is None:
            return self.max_runs
        return min(self.max_runs, self.max_runs_per_tick)


class Agent(BaseModel):
    """The strict on-disk declaration for one named agent."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: AgentKind
    title: str
    charter: str
    topics: list[str] = Field(min_length=1)
    role: str
    skills: list[str] = Field(default_factory=list)
    runtime: AgentRuntime
    tier: Tier
    # Robert, 2026-09-07 (ADR-0025): an agent may pin its harness and model, e.g.
    # the laptop liaison runs Claude Code through OpenRouter on GLM 5.3 Flash
    # because the group's endpoint is not reachable from the laptop. The harness
    # must equal the runtime; the router still refuses local-only work off-host.
    runner: str | None = None
    model: str | None = None
    host: str = "ws"
    privacy_default: Privacy = Privacy.internal
    memory_dir: str
    resources: AgentResources
    workday: AgentWorkday
    reports: Literal["weekly"]

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", value):
            raise ValueError("name must be lowercase letters, digits, and hyphens")
        return value


def agents_dir(root: Path) -> Path:
    return root / "agents"


def agent_path(root: Path, name: str) -> Path:
    return agents_dir(root) / f"{name}.yaml"


def load_agent(root: Path, name: str, *, validate_role: bool = True) -> Agent:
    path = agent_path(root, name)
    if not path.exists():
        raise AgentError(f"no such agent: {name} ({path})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AgentError(f"{path}: YAML error: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentError(f"{path}: expected a mapping")
    try:
        agent = Agent.model_validate(data)
    except ValidationError as exc:
        raise AgentError(f"{path}: {exc}") from exc
    if agent.name != path.stem:
        raise AgentError(f"{path}: name {agent.name!r} does not equal file stem {path.stem!r}")
    expected_memory = Path("agents") / agent.name / "memory"
    if Path(agent.memory_dir) != expected_memory:
        raise AgentError(f"{path}: memory_dir must be {expected_memory}")
    charter = root / agent.charter
    if not charter.is_file() or not charter.is_relative_to(root / "agents" / agent.name):
        raise AgentError(f"{path}: charter must be a file under agents/{agent.name}/")
    if validate_role:
        validate_agent_role(root, agent)
    return agent


def validate_agent_role(root: Path, agent: Agent) -> Role:
    """Prove identity settings cannot broaden the selected functional role."""
    try:
        role = load_role(root, agent.role)
    except RoleError as exc:
        raise AgentError(f"agent {agent.name}: {exc}") from exc
    if agent.runtime != role.runtime:
        raise AgentError(
            f"agent {agent.name}: runtime {agent.runtime} exceeds role runtime {role.runtime}"
        )
    if agent.tier != role.tier:
        raise AgentError(f"agent {agent.name}: tier {agent.tier} must equal role tier {role.tier}")
    if agent.runner and harness_of(agent.runner) != agent.runtime:
        raise AgentError(
            f"agent {agent.name}: runner {agent.runner} is not the {agent.runtime} harness"
        )
    # Contact remains centrally default-deny.  The only valid agent declaration is none.
    if agent.resources.outbound != "none":
        raise AgentError(f"agent {agent.name}: outbound must be none (ADR-0009)")
    return role


def load_all_agents(root: Path) -> tuple[dict[str, Agent], dict[str, str]]:
    found: dict[str, Agent] = {}
    errors: dict[str, str] = {}
    directory = agents_dir(root)
    if not directory.exists():
        return found, errors
    for path in sorted(directory.glob("*.yaml")):
        try:
            found[path.stem] = load_agent(root, path.stem)
        except AgentError as exc:
            errors[path.stem] = str(exc)
    return found, errors


def memory_dir(root: Path, agent: Agent) -> Path:
    return root / agent.memory_dir


def state_dir(settings: Settings, agent: Agent | str) -> Path:
    name = agent if isinstance(agent, str) else agent.name
    return settings.state_dir() / "agents" / name


def session_path(settings: Settings, agent: Agent) -> Path:
    return state_dir(settings, agent) / "session.json"


def resources_path(settings: Settings, agent: Agent) -> Path:
    return state_dir(settings, agent) / "resources.json"


def context_path(settings: Settings, agent: Agent) -> Path:
    return state_dir(settings, agent) / "context.md"


def inbox_path(root: Path, agent: Agent) -> Path:
    return root / "agents" / agent.name / "inbox.jsonl"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def session(settings: Settings, agent: Agent) -> dict[str, Any]:
    data = read_json(session_path(settings, agent), {})
    return data if isinstance(data, dict) else {}


def save_session(settings: Settings, agent: Agent, data: dict[str, Any]) -> None:
    path = session_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _today(now: datetime | None = None) -> date:
    value = now or datetime.now(UTC)
    return value.date()


def workday_state_path(settings: Settings, agent: Agent) -> Path:
    return state_dir(settings, agent) / "workday.json"


def last_workday_start(settings: Settings, agent: Agent) -> datetime | None:
    data = read_json(workday_state_path(settings, agent), {})
    raw = data.get("last_started") if isinstance(data, dict) else None
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def record_workday_start(settings: Settings, agent: Agent, now: datetime) -> None:
    path = workday_state_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_started": now.isoformat(timespec="seconds")}, indent=1) + "\n",
        encoding="utf-8",
    )


def workday_due(
    agent: Agent, now: datetime, last_started: datetime | None, *, tz: Any = None
) -> bool:
    """Whether the agent-workday timer tick at ``now`` should run this agent.

    Hourly agents are due once at least ``HOURLY_GAP_MINUTES`` passed since the
    last start. Daily agents are due once per local day, from their ``HH:MM`` on.
    ``tz`` defaults to the host's local zone (the timer's clock).
    """
    daily_at = agent.workday.daily_at
    if daily_at is None:
        if agent.workday.cron != "hourly" or last_started is None:
            return True  # own-timer agents pace themselves
        return (now - last_started).total_seconds() >= HOURLY_GAP_MINUTES * 60
    local_now = now.astimezone(tz)
    hour, minute = daily_at
    if (local_now.hour, local_now.minute) < (hour, minute):
        return False
    if last_started is None:
        return True
    return last_started.astimezone(tz).date() < local_now.date()


GRANTS_FILE = "grants.json"
# Keys that live only in the in-memory usage mapping; they never reach resources.json.
TRANSIENT_USAGE_KEYS = ("grants", "grants_file")


def grants_path(settings: Settings, agent: Agent | str) -> Path:
    """Path of the single-use resource grants Robert answered in the cockpit."""
    return state_dir(settings, agent) / GRANTS_FILE


def load_grants(path: Path) -> list[dict[str, Any]]:
    data = read_json(path, [])
    if not isinstance(data, list):
        return []
    return [dict(row) for row in data if isinstance(row, dict)]


def save_grants(path: Path, grants: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grants, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def add_grant(
    path: Path,
    *,
    step_title: str,
    needs: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record that Robert allowed one blocked workday step; the grant is single use."""
    entry: dict[str, Any] = {
        "step_title": step_title,
        "granted_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "needs": dict(needs),
        "used_at": None,
    }
    grants = load_grants(path)
    grants.append(entry)
    save_grants(path, grants)
    return entry


def matching_grant(
    grants: list[dict[str, Any]], needs: dict[str, Any], step_title: str | None = None
) -> dict[str, Any] | None:
    """Return the first unused grant whose declared needs equal NEEDS.

    With ``step_title`` the grant must also carry that title, so a grant for one
    step never unlocks a different step with the same resource shape.
    """
    for grant in grants:
        if grant.get("used_at"):
            continue
        if step_title is not None and grant.get("step_title") not in (None, step_title):
            continue
        if dict(grant.get("needs") or {}) == dict(needs):
            return grant
    return None


def consume_grant(path: Path, grant: dict[str, Any], *, now: datetime | None = None) -> None:
    """Mark GRANT used so the next identical step needs Robert again."""
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    grants = load_grants(path)
    for row in grants:
        if (
            not row.get("used_at")
            and row.get("granted_at") == grant.get("granted_at")
            and dict(row.get("needs") or {}) == dict(grant.get("needs") or {})
        ):
            row["used_at"] = stamp
            break
    save_grants(path, grants)


def resource_usage(
    settings: Settings, agent: Agent, *, now: datetime | None = None
) -> dict[str, Any]:
    today = _today(now).isoformat()
    path = grants_path(settings, agent)
    extra: dict[str, Any] = {"grants": load_grants(path), "grants_file": str(path)}
    data = read_json(resources_path(settings, agent), {})
    if not isinstance(data, dict) or data.get("date") != today:
        return {"date": today, "gpu_hours": 0.0, "runs": 0, "spend_usd": 0.0, **extra}
    return {
        "date": today,
        "gpu_hours": float(data.get("gpu_hours", 0.0)),
        "runs": int(data.get("runs", 0)),
        "spend_usd": float(data.get("spend_usd", 0.0)),
        **extra,
    }


def save_resource_usage(settings: Settings, agent: Agent, usage: dict[str, Any]) -> None:
    path = resources_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = {key: value for key, value in usage.items() if key not in TRANSIENT_USAGE_KEYS}
    path.write_text(json.dumps(stored, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def read_inbox(root: Path, agent: Agent, *, unread_only: bool = False) -> list[dict[str, Any]]:
    from cube.mailbox import read

    return read(inbox_path(root, agent), unread_only=unread_only)


def append_inbox(
    root: Path,
    agent: Agent,
    text: str,
    *,
    sender: str = "robert",
    delivered: bool = False,
) -> dict[str, Any]:
    from cube.mailbox import append

    return append(inbox_path(root, agent), text, sender=sender, delivered=delivered)


def mark_inbox_read(root: Path, agent: Agent, ids: list[str] | None = None) -> None:
    from cube.mailbox import acknowledge

    selected = ids if ids is not None else [str(row["id"]) for row in read_inbox(root, agent)]
    acknowledge(inbox_path(root, agent), selected)


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return "(empty)"
    data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[:lines])


def _group_context(settings: Settings) -> str:
    """Render the deterministic group summary included in the coordinator context."""
    if settings.group is None:
        return ""
    agents, _errors = load_all_agents(settings.root)
    lines = [
        "## Group",
        "",
        "Standing agents (source: agents/*.yaml):",
    ]
    for name, member in sorted(agents.items()):
        topics = ", ".join(member.topics)
        if member.kind == "coordinator":
            mandate = "Coordinates source-backed work across the research group."
        elif member.kind == "functional":
            mandate = f"Provides the {member.role} function for the declared topics."
        else:
            mandate = f"Owns source-backed research on {topics}."
        lines.append(f"- {name} ({member.role}): topics {topics}; mandate: {mandate}")
    configured = [topic for config in settings.group.experts.values() for topic in config.topics]
    covered = {
        topic for member in agents.values() if member.kind == "expert" for topic in member.topics
    }
    uncovered = [topic for topic in dict.fromkeys(configured) if topic not in covered]
    lines.extend(
        [
            "",
            "Uncovered configured expert topics (source: cube.yaml): "
            + (", ".join(uncovered) or "none"),
        ]
    )
    return "\n".join(lines)


def _talking_section(settings: Settings, agent: Agent) -> str:
    """The deterministic roster and command an agent needs to message another agent."""
    others, _errors = load_all_agents(settings.root)
    roster = (
        "\n".join(
            f"- {name} ({member.title}): {', '.join(member.topics)}"
            for name, member in sorted(others.items())
            if name != agent.name
        )
        or "- (no other standing agents in this checkout)"
    )
    return (
        "## Talking to other agents\n\n"
        "To message another standing agent run\n"
        f"`cube agent tell <name> '<text>' --from agent:{agent.name} --apply`; the message "
        "lands in\ntheir inbox and they answer on their next hourly tick with the same command\n"
        "addressed to you. Agents in the fleet:\n"
        f"{roster}\n"
        "Only agents; never a person, never Robert (use cube question new for him).\n"
        "Prefix a reply with the id of the bead or drill it answers."
    )


def agent_context(settings: Settings, agent: Agent, *, memory_lines: int = 80) -> str:
    """Build the persistent conversation context without writing or invoking a model."""
    role = validate_agent_role(settings.root, agent)
    charter = (settings.root / agent.charter).read_text(encoding="utf-8")
    skills = list(dict.fromkeys([*role.skills, *agent.skills]))
    skill_paths = resolve_skills(settings, skills)
    skills_text = (
        "\n".join(
            f"- {name}: {path if path else '(not installed here; do not invent it)'}"
            for name, path in skill_paths.items()
        )
        or "(none)"
    )
    mem = memory_dir(settings.root, agent)
    unread = read_inbox(settings.root, agent, unread_only=True)
    inbox = (
        "\n".join(
            f"- {row.get('ts', '?')} {row.get('from', '?')}: {row.get('text', '')}"
            for row in unread
        )
        or "(none)"
    )
    parts = [
        "# Standing agent: "
        + agent.title
        + f"\n\nname: {agent.name}\nkind: {agent.kind}\n"
        + "topics: "
        + ", ".join(agent.topics),
        "## Charter\n\n" + charter.strip(),
        "## Functional role prompt\n\n"
        + (settings.root / role.system_prompt_file).read_text(encoding="utf-8").strip(),
        "## Doctrine\n\n"
        + (settings.root / "brain" / "doctrine.md").read_text(encoding="utf-8").strip(),
        "## Skills\n\n" + skills_text,
        "## Memory tail\n\n### Journal\n"
        + _tail(mem / "journal.md", memory_lines)
        + "\n\n### Reading\n"
        + _tail(mem / "reading.md", memory_lines),
        "## Unread inbox\n\n" + inbox,
        "## Asking Robert\n\n"
        "When you need a decision only Robert can make, ask him and stop. Run\n"
        f"`cube question new --from agent:{agent.name} --text '<question>' "
        "[--options yes,no] --apply` and wait; his answer arrives in your inbox.\n"
        "Never guess in place of asking, and never ask for grades, HR details, "
        "or anything about a person's contract, health or visa.",
        _talking_section(settings, agent),
    ]
    if agent.name == "coordinator":
        group = _group_context(settings)
        if group:
            parts.insert(1, group)
    return "\n\n".join(parts) + "\n"


def context_block(settings: Settings, name: str) -> str:
    """Best-effort engine addendum for a bead labelled ``agent:<name>``."""
    try:
        return "### Standing-agent context\n\n" + agent_context(
            settings, load_agent(settings.root, name)
        )
    except (AgentError, OSError) as exc:
        return f"### Standing-agent context\n\nagent:{name} unavailable: {exc}"


def journal_entries(root: Path, agent: Agent, limit: int = 5) -> list[str]:
    text = (
        (memory_dir(root, agent) / "journal.md").read_text(encoding="utf-8")
        if (memory_dir(root, agent) / "journal.md").exists()
        else ""
    )
    entries = ["## " + item for item in re.split(r"(?m)^## ", text)[1:] if item.strip()]
    return entries[:limit]


def append_journal(
    root: Path, agent: Agent, *, body: str, sources: list[str], now: datetime | None = None
) -> None:
    if not sources:
        raise AgentError("journal entries require at least one source path or identifier")
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    entry = (
        f"## {stamp}\n\n{body.strip()}\n\nSources:\n"
        + "\n".join(f"- {s}" for s in sources)
        + "\n\n"
    )
    path = memory_dir(root, agent) / "journal.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(entry + existing, encoding="utf-8")


@lru_cache(maxsize=2)
def cite_check(root: Path) -> Any:
    """Import the literature-review verifier rather than duplicating identifier rules."""
    candidates = (
        root / "skills" / "literature-review" / "scripts" / "cite_check.py",
        Path(__file__).resolve().parents[2]
        / "skills"
        / "literature-review"
        / "scripts"
        / "cite_check.py",
    )
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    spec = importlib.util.spec_from_file_location("cube_literature_cite_check", path)
    if spec is None or spec.loader is None:
        raise AgentError(f"cannot import literature cite_check from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verified_identifier(root: Path, identifier: str) -> bool:
    """Use cite_check patterns; malformed or anonymous references cannot enter memory."""
    checker = cite_check(root)
    value = identifier.strip().removeprefix("https://doi.org/")
    if re.fullmatch(r"arXiv:\d{4}\.\d{4,5}(v\d+)?", value, re.I):
        return True
    fields = {"title": "Identifier validation"}
    if checker.DOI_RE.match(value):
        fields["doi"] = value
    elif checker.PMID_RE.match(value):
        fields["pmid"] = value
        fields["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{value}/"
    else:
        return False
    entry = checker.Entry("agent-reference", "misc", fields, "agents/reading.md", 1)
    findings = checker.offline_checks([entry], date.today())
    return not any(finding.severity == "error" for finding in findings)


def append_reading(root: Path, agent: Agent, *, identifier: str, note: str, source: str) -> None:
    if not source or not verified_identifier(root, identifier):
        raise AgentError("reading.md accepts only a cite_check-valid identifier and a source")
    path = memory_dir(root, agent) / "reading.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    entry = f"- {identifier}: {note.strip()} (source: {source})\n"
    path.write_text(entry + existing, encoding="utf-8")


def append_memory_note(
    root: Path,
    agent: Agent,
    *,
    filename: Literal["ideas.md", "open-questions.md"],
    text: str,
    source: str,
) -> None:
    """Append a source-linked idea or question, newest first."""
    if not text.strip() or not source.strip():
        raise AgentError(f"{filename} entries require text and a source")
    path = memory_dir(root, agent) / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(f"- {text.strip()} (source: {source.strip()})\n" + existing, encoding="utf-8")


@dataclass(frozen=True)
class StepDecision:
    allowed: bool
    resource_class: str
    reason: str
    gpu_hours: float = 0.0
    spend_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def step_decision(
    agent: Agent,
    needs: dict[str, Any],
    usage: dict[str, Any],
    *,
    step_title: str | None = None,
    consume: bool = True,
    settings: Settings | None = None,
) -> StepDecision:
    """Enforce every resource boundary, then honour one grant Robert answered.

    A step that only lacks Robert's approval is allowed when ``usage`` carries an
    unused grant (from ``cube decide <id> --choice yes`` on the
    ``resource:approval`` bead) whose declared needs equal this step's and, when
    ``step_title`` is given, whose title matches. With ``consume`` (an applied
    workday) the grant is marked used at that moment, so the next identical step
    asks again; a dry run leaves it unused. Budget and outbound denials are never
    lifted this way.
    """
    if settings is not None and settings.fleet_enabled:
        target = str(needs.get("compute_target") or needs.get("compute") or "ws").lower()
        outbound = needs.get("outbound")
        if outbound not in (None, "", "none", False, "github", "fleet-github"):
            return StepDecision(False, "approval", "contact outside fleet GitHub needs a grant")
        if target in {"ibex", "dragon", "unimatrix01"}:
            return StepDecision(
                True, "slurm", "submit through cube fleet submit within central limits"
            )
        if target in {"ws", "workstation", "none"}:
            return StepDecision(True, "ws_cpu", "central fleet limits govern research work")
    decision = _resource_decision(agent, needs, usage)
    if decision.allowed or decision.resource_class != "approval":
        return decision
    if needs.get("outbound") not in (None, "", "none", False):
        return decision
    grants = usage.get("grants")
    grant = matching_grant(grants if isinstance(grants, list) else [], needs, step_title)
    if grant is None:
        return decision
    path = usage.get("grants_file")
    if consume and isinstance(path, str) and path:
        consume_grant(Path(path), grant)
    return StepDecision(
        True,
        "granted",
        f"Robert approved this step on {grant.get('granted_at')}",
        gpu_hours=float(needs.get("gpu_hours") or 0.0),
        spend_usd=float(needs.get("spend_usd") or 0.0),
    )


def _resource_decision(agent: Agent, needs: dict[str, Any], usage: dict[str, Any]) -> StepDecision:
    """The declared resource boundaries alone, before any grant is considered."""
    target = str(needs.get("compute_target") or needs.get("compute") or "ws")
    outbound = needs.get("outbound")
    spend = float(needs.get("spend_usd") or 0.0)
    gpu = float(needs.get("gpu_hours") or 0.0)
    if outbound not in (None, "", "none", False):
        return StepDecision(
            False, "approval", "outbound actions require the contact-policy approval gate"
        )
    if target.lower() == "ibex" or agent.resources.ibex == "approval" and target.lower() == "ibex":
        return StepDecision(False, "approval", "IBEX use requires Robert approval")
    if target.lower() == "node005":
        if gpu <= 0:
            return StepDecision(False, "approval", "node005 step must declare positive gpu_hours")
        if usage["gpu_hours"] + gpu > agent.resources.node005_gpu_hours_per_day:
            return StepDecision(False, "gpu", "node005 GPU allowance exhausted", gpu_hours=gpu)
        return StepDecision(True, "gpu", "node005 local-tier work allowed", gpu_hours=gpu)
    # spend_usd_per_day 0 means "governed by the global budget" (cube.yaml budget:
    # daily_total_usd and the per-tier ceilings, enforced by the router); only a
    # positive per-agent allowance gates a step that declares spend.
    allowance = agent.resources.spend_usd_per_day
    if spend > 0 and allowance > 0 and spend > allowance - usage["spend_usd"]:
        return StepDecision(False, "approval", "daily spend allowance exhausted", spend_usd=spend)
    if target.lower() not in {"ws", "workstation", "none"}:
        return StepDecision(
            False, "approval", f"unknown compute target {target!r} requires approval"
        )
    if not agent.resources.ws_cpu and target.lower() in {"ws", "workstation"}:
        return StepDecision(False, "approval", "workstation CPU is not granted to this agent")
    return StepDecision(True, "ws_cpu", "local workstation work allowed", spend_usd=spend)


RESOURCE_STEP_SEPARATOR = " resource step: "


def resource_approval_title(agent: Agent, step_title: str) -> str:
    """Title of a `resource:approval` bead; `cube decide` reads the step back out of it."""
    return f"Approve {agent.title}{RESOURCE_STEP_SEPARATOR}{step_title}"


def resource_approval_bead(
    beads: Beads,
    agent: Agent,
    step: dict[str, Any],
    decision: StepDecision,
    *,
    now: datetime | None = None,
) -> str | None:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    title = resource_approval_title(agent, str(step.get("title") or "planned work"))
    header = BeadHeader(
        xid=f"agent:{agent.name}:resource:{stamp}",
        provenance=[Provenance(source=f"agents/{agent.name}.yaml", locator="resources")],
        privacy=Privacy.internal,
    )
    body = "\n".join(
        [
            f"Agent: {agent.name}",
            f"Resource class: {decision.resource_class}",
            f"Reason: {decision.reason}",
            "Declared needs:",
            yaml.safe_dump(step.get("needs") or {}, sort_keys=True).rstrip(),
        ]
    )
    return beads.create(
        title,
        header=header,
        body=body,
        labels=[f"agent:{agent.name}", "needs:robert", "resource:approval"],
        acceptance="Robert approves or declines the declared resource use.",
    )


PROPOSAL_FIELDS = ("title", "rationale", "resources", "expected_outcome", "kill_criterion")


def file_proposal(
    beads: Beads,
    agent: Agent,
    proposal: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    missing = [field for field in PROPOSAL_FIELDS if not str(proposal.get(field) or "").strip()]
    if missing:
        raise AgentError("proposal missing required fields: " + ", ".join(missing))
    citations = proposal.get("citations") or []
    if (
        not isinstance(citations, list)
        or not citations
        or not all(
            isinstance(item, str) and verified_identifier(beads.cwd or Path.cwd(), item)
            for item in citations
        )
    ):
        raise AgentError("proposal rationale requires cite_check-valid citation identifiers")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    header = BeadHeader(
        xid=f"agent:{agent.name}:proposal:{stamp}",
        provenance=[
            Provenance(source=f"agents/{agent.name}/memory/journal.md", locator="latest entry"),
            *[Provenance(source=citation) for citation in citations],
        ],
        privacy=Privacy.internal,
    )
    body = "\n".join(
        [
            f"Rationale: {proposal['rationale']}",
            "Citations: " + ", ".join(citations),
            f"Resources requested: {proposal['resources']}",
            f"Expected outcome: {proposal['expected_outcome']}",
            f"Kill criterion: {proposal['kill_criterion']}",
        ]
    )
    return beads.create(
        str(proposal["title"]),
        header=header,
        body=body,
        labels=["kind:proposal", "needs:robert", f"agent:{agent.name}"],
        acceptance="Robert reviews the rationale, resources, expected outcome, and kill criterion.",
    )


def agent_summary(
    settings: Settings, agent: Agent, *, beads: Beads | None = None
) -> dict[str, Any]:
    ledger = beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True)
    issues: list[dict[str, Any]] = []
    if ledger.available():
        try:
            issues = ledger.list_issues("--all")
        except BeadsError:
            issues = []
    label = f"agent:{agent.name}"
    open_issues = [
        b
        for b in issues
        if label in bead_labels(b) and str(b.get("status", "open")) not in {"closed", "done"}
    ]
    proposals = [b for b in open_issues if "kind:proposal" in bead_labels(b)]
    tmux = session(settings, agent).get("tmux")
    paused = (state_dir(settings, agent) / "PAUSED").exists()
    state = "paused" if paused else ("talking" if tmux else "idle")
    journals = journal_entries(settings.root, agent, 1)
    last_journal = journals[0].splitlines()[0][3:] if journals else None
    usage = resource_usage(settings, agent)
    return {
        "name": agent.name,
        "kind": agent.kind,
        "title": agent.title,
        "topics": agent.topics,
        "runtime": agent.runtime,
        "tier": agent.tier.value,
        "host": agent.host,
        "state": state,
        "session": tmux if isinstance(tmux, str) else None,
        "last_journal": last_journal,
        "pending_proposals": len(proposals),
        "inbox_unread": len(read_inbox(settings.root, agent, unread_only=True)),
        "resources_used_today": {key: usage[key] for key in ("gpu_hours", "runs", "spend_usd")},
    }


def agent_list(settings: Settings, *, beads: Beads | None = None) -> list[dict[str, Any]]:
    agents, _errors = load_all_agents(settings.root)
    return [agent_summary(settings, agent, beads=beads) for agent in agents.values()]
