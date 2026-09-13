"""Load and validate roles/<role>.yaml (schema in roles/_schema.yaml) and assemble prompts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cube.model import EscalationKind, Privacy, RunResult, Tier

Runtime = Literal["claude", "codex", "hermes", "python", "gastown"]
PermissionMode = Literal["read-only", "workspace-write", "browser", "none"]
SessionPolicy = Literal["fresh", "resume"]
RunnerHint = Literal["free"]

DEFAULT_TIMEOUT_MINUTES = 30
DOCTRINE_EXCERPT_LINES = 60

OUTBOUND_WORDS = (
    "send",
    "post",
    "email",
    "message",
    "dm",
    "submit",
    "sign",
    "publish",
    "pr",
    "comment",
    "notify",
)


class RoleError(ValueError):
    """A role yaml is missing, malformed or violates the schema rules."""


class RoleEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str
    to: str
    # What the condition is, so the engine can route it without asking Robert for
    # everything. See cube.model.Escalation for what each kind means.
    kind: EscalationKind = "decision"


class Role(BaseModel):
    """One entry of roles/<name>.yaml. Strict: unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    name: str
    summary: str
    tier: Tier
    runtime: Runtime
    model: str | None = None
    runner_hint: RunnerHint | None = None
    hermes_profile: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    permission_mode: PermissionMode
    skills: list[str] = Field(default_factory=list)
    system_prompt_file: str
    can_close: bool
    review_required_by: str | None
    escalation: list[RoleEscalation] = Field(default_factory=list)
    privacy_max: Privacy
    session_policy: SessionPolicy
    autonomous_actions: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    hard_rules: list[str] = Field(default_factory=list)
    # Optional engine knobs (not part of the human schema; defaults apply when absent).
    timeout_minutes: int | None = None
    max_turns: int | None = None
    # Robert, 2026-09-08 (ADR-0027): `host` bounds file reads to the running host's
    # `readable` directories (cube.yaml hosts.<host>.readable). Such a role lists no
    # Read, Grep or Glob in allowed_tools; the runner adds the bounded Read rule.
    read_roots: Literal["host"] | None = None
    # Repairs the loader applied to tolerate YAML authoring quirks (reported, never silent).
    lint_warnings: list[str] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def _rules(self) -> Role:
        if self.review_required_by is None and self.can_close and self.runtime != "python":
            # Top of the review chain (group-leader): its closes are its own.
            # Robert, 2026-09-07: he decides security and privacy, not closes.
            self.lint_warnings.append(
                "can_close with review_required_by null: closes without a review"
            )
        if self.review_required_by == self.name:
            raise ValueError("a role cannot review itself")
        if self.read_roots and any(
            tool.split("(", 1)[0] in {"Read", "Grep", "Glob"} for tool in self.allowed_tools
        ):
            raise ValueError(
                "read_roots bounds file reads; allowed_tools must not list Read, Grep or Glob"
            )
        outbound = [
            a
            for a in self.autonomous_actions
            if any(w in str(a).lower().replace("-", "_").split("_") for w in OUTBOUND_WORDS)
            or any(w in str(a).lower() for w in ("send", "email", "post", "submit", "publish"))
        ]
        if outbound:
            raise ValueError(f"autonomous_actions lists outbound actions: {outbound} (ADR-0009)")
        if self.runtime == "python" and self.tier not in (Tier.none, Tier.bulk):
            raise ValueError("python runtime roles use tier none or bulk")
        return self

    @property
    def closes_need_robert(self) -> bool:
        """Robert, 2026-09-07: no close waits for him; the top of the chain closes."""
        return False

    @property
    def timeout_seconds(self) -> float:
        return float((self.timeout_minutes or DEFAULT_TIMEOUT_MINUTES) * 60)

    def escalation_target(self, condition: str) -> str | None:
        for esc in self.escalation:
            if esc.condition == condition:
                return esc.to
        return None


def roles_dir(root: Path) -> Path:
    return root / "roles"


def load_role(root: Path, name: str) -> Role:
    path = roles_dir(root) / f"{name}.yaml"
    if not path.exists():
        raise RoleError(f"no such role: {name} ({path})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RoleError(f"{path}: YAML error: {exc}") from exc
    if not isinstance(data, dict):
        raise RoleError(f"{path}: expected a mapping")
    data, warnings = normalise_yaml(data)
    try:
        role = Role.model_validate(data)
    except ValidationError as exc:
        raise RoleError(f"{path}: {exc}") from exc
    if role.name != path.stem:
        raise RoleError(f"{path}: name {role.name!r} does not equal file stem {path.stem!r}")
    prompt = root / role.system_prompt_file
    if not prompt.exists():
        raise RoleError(f"{path}: system_prompt_file {role.system_prompt_file} does not exist")
    role.lint_warnings = [*role.lint_warnings, *warnings]
    return role


STRING_LISTS = ("triggers", "inputs", "outputs", "hard_rules", "autonomous_actions")


def normalise_yaml(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Repair two common authoring quirks and report them.

    1. Flow mappings with unquoted commas: ``{condition: a (b, c), to: x}`` parses as the keys
       ``condition: a (b``, ``c)`` with null values. The extra null-valued keys are re-joined
       into the condition text.
    2. ``- key: value`` list items where a string was meant become ``"key: value"``.
    """
    warnings: list[str] = []
    out = dict(data)
    esc = out.get("escalation")
    if isinstance(esc, list):
        fixed: list[Any] = []
        for i, item in enumerate(esc):
            known = {"condition", "to", "kind"}
            if isinstance(item, dict) and set(item) - known:
                extras = [k for k, v in item.items() if k not in known and v is None]
                if extras and len(extras) == len(set(item) - known):
                    cond = str(item.get("condition") or "")
                    cond = ", ".join([cond, *extras]) if cond else ", ".join(extras)
                    entry = {"condition": cond, "to": item.get("to")}
                    if item.get("kind"):
                        entry["kind"] = item["kind"]
                    fixed.append(entry)
                    warnings.append(f"escalation[{i}]: unquoted commas in flow mapping; joined")
                    continue
            fixed.append(item)
        out["escalation"] = fixed
    for key in STRING_LISTS:
        items = out.get(key)
        if not isinstance(items, list):
            continue
        fixed = []
        for i, item in enumerate(items):
            if isinstance(item, dict):
                fixed.append("; ".join(f"{k}: {v}" for k, v in item.items()))
                warnings.append(f"{key}[{i}]: mapping where a string was expected; flattened")
            else:
                fixed.append(item)
        out[key] = fixed
    return out, warnings


def load_all(root: Path) -> tuple[dict[str, Role], dict[str, str]]:
    """Return (roles by name, errors by role name). Never raises on one bad file."""
    roles: dict[str, Role] = {}
    errors: dict[str, str] = {}
    directory = roles_dir(root)
    if not directory.exists():
        return roles, {"_": f"{directory} missing"}
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            roles[path.stem] = load_role(root, path.stem)
        except RoleError as exc:
            errors[path.stem] = str(exc)
    return roles, errors


def result_schema() -> dict[str, Any]:
    """JSON schema of RunResult, the output contract every runner enforces."""
    return RunResult.model_json_schema()


def doctrine_excerpt(root: Path, lines: int = DOCTRINE_EXCERPT_LINES) -> str:
    path = root / "brain" / "doctrine.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").splitlines()
    excerpt = text[:lines]
    if len(text) > lines:
        excerpt.append(f"(excerpt: first {lines} of {len(text)} lines; full text in {path})")
    return "\n".join(excerpt)


OUTPUT_CONTRACT = """\
## Output contract

Your final message must be exactly one JSON object matching the RunResult schema below,
with no prose around it. Every claim in `summary` names its source (path, locator,
permalink, Message-ID or commit). Never invent tool output or test results.

- `bead_updates[]`: comments to add, labels to add, and `close: true` only when the work is
  finished; the engine still applies the review gate.
- `escalations[]`: conditions from the role's escalation table; `to` is a role name or
  `robert`; `kind` is one of decision, permission, integrity, people, conflict, blocked,
  note (`decision` is the default, and only a real choice deserves it), and `options[]`
  lists the answers when the kind is a decision with fixed choices.
- Outbound intents (anything that would reach a person other than Robert): write the text to
  a file under the run directory whose first lines are a YAML front matter block with
  `to`, `person`, `channel` (email|mattermost_dm|mattermost_channel|github|portal),
  `action`, `subject`, then list it in `artifacts[]` with `kind: outbound`. The engine
  turns it into an approval; nothing is sent by you.
- File edits outside the worktree: write a unified diff under the run directory and list it
  with `kind: file_change` (or `org_edit` for ~/org); it becomes an approval.
- `verdict`: only for review roles, one of approve|revise|reject.
"""


def assemble_prompt(
    role: Role,
    context: str,
    *,
    root: Path,
    skill_paths: Mapping[str, Path | None] | None = None,
    doctrine_lines: int = DOCTRINE_EXCERPT_LINES,
) -> str:
    """System prompt file + doctrine excerpt + skill list + output contract + run context."""
    prompt_file = root / role.system_prompt_file
    parts: list[str] = [prompt_file.read_text(encoding="utf-8").rstrip()]
    if role.name not in {"sysadmin", "liaison"}:
        parts.append(
            "Fleet research authorization (Robert, 2026-09-08): when fleet_enabled is true, "
            "work autonomously within your charter and active goals. Literature handoffs may "
            "lead to reproduction experiments. Use cube fleet limits and cube fleet submit "
            "for bounded Slurm work on dragon/IBEX or unimatrix01, never compute on login nodes. "
            "Document every result, including negative results, source evidence, pinned "
            "environment and commands in borg-cube-fleet. cube fleet publish sends queued "
            "run records; cube fleet document commits code and result artifacts from a JSON "
            "path-to-content manifest; cube fleet issue and cube fleet pr create evidenced "
            "issues and draft PRs. These fleet GitHub actions and role-attributed commits "
            "have standing authorization and need no per-action Robert approval. Never "
            "publish mail/org/personal records or credentials. Other contact keeps its "
            "existing grant policy. Respect the GIT_AUTHOR_NAME/GIT_AUTHOR_EMAIL environment. "
            "Request peer review for substantive research. Record progress on Beads/GitHub; "
            "send Robert completed-goal reports and batched decisions only. A budget "
            "exhaustion queues work; do not ask him for permission on each attempt."
        )
        parts.append(
            "Project publication mandate (Robert, 2026-09-09): whenever you start or resume "
            "a project, use one stable private borg-cube-fleet/<project-slug> repository, "
            "shared by collaborators, not a new repo per run or agent. At the start, queue "
            "a README describing the sourced goal, methods and current status. At every "
            "meaningful checkpoint and before ending each work session, publish actual "
            "code, tests, reproduction commands, manuscripts/reports and measured results, "
            "not just activity summaries. Use: cube fleet document <project-slug> "
            "<manifest.json> --message 'Research checkpoint' --evidence <bead-or-run> --apply. "
            "The manifest maps relative repository paths to UTF-8 contents. The command "
            "creates a private repository if missing, saves a durable snapshot and attempts "
            "upload; failed uploads retry on the existing 15-minute decisions patrol. "
            "Reuse established project filenames and coordinate changes with peers. "
            "Keep large data/checkpoints on research storage with checksums and provenance. "
            "Record the project repository on its bead. Never treat a pending upload as "
            "published. Local-only runs keep artifacts local until a separately reviewed "
            "internal/public derivative is available; a private GitHub repo is still external."
        )
    doctrine = doctrine_excerpt(root, doctrine_lines)
    if doctrine:
        parts.append("## Doctrine (brain/doctrine.md)\n\n" + doctrine)
    if role.hard_rules:
        parts.append("## Hard rules\n\n" + "\n".join(f"- {r}" for r in role.hard_rules))
    if role.skills:
        lines = []
        for name in role.skills:
            path = (skill_paths or {}).get(name)
            lines.append(f"- {name}: {path if path else '(not installed here; do not invent it)'}")
        parts.append("## Skills available\n\n" + "\n".join(lines))
    parts.append(
        OUTPUT_CONTRACT
        + "\n```json\n"
        + json.dumps(result_schema(), indent=1, ensure_ascii=False)
        + "\n```"
    )
    if context.strip():
        parts.append("## Run context\n\n" + context.rstrip())
    return "\n\n".join(parts) + "\n"
