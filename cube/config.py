"""Configuration loading: cube.yaml (non-secret) plus .env (secrets, gitignored)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cube.resources import FleetLimits


class TierEntry(BaseModel):
    """One routing candidate: which harness, through which provider, on which model.

    ``runner`` names the harness (``claude``, ``codex``, ``openrouter``, ``local``).
    ``provider`` redirects an agentic harness at a non-native endpoint, so
    ``{runner: claude, provider: openrouter}`` is Claude Code talking to OpenRouter.
    The yaml may also spell that as the token ``runner: claude@openrouter``; both
    spellings normalise to the same object and ``runner_name`` is the token used
    everywhere a runner is identified by string.
    """

    model_config = ConfigDict(extra="forbid")

    runner: str
    provider: str | None = None
    model: str | None = None
    profile: str | None = None
    # Roles allowed to use this entry (empty: every role). Reserves a subscription
    # runner for one role, e.g. `only: [group-leader]` keeps Claude for the coordinator.
    only: list[str] = Field(default_factory=list)
    # Roles that skip this entry (ADR-0022): the sysadmin keeps Claude Code's
    # per-command allowlist, the programmer keeps Codex's sandbox.
    not_for: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _split_runner_token(cls, data: Any) -> Any:
        """Accept `runner: claude@openrouter` and normalise it into runner + provider."""
        if not isinstance(data, dict):
            return data
        # Imported here and below: cube.runners imports Settings from this module.
        from cube.runners.naming import SEPARATOR

        runner = data.get("runner")
        if not isinstance(runner, str) or SEPARATOR not in runner:
            return data
        harness, _, provider = runner.partition(SEPARATOR)
        declared = data.get("provider")
        if declared is not None and declared != provider:
            raise ValueError(f"runner token {runner!r} contradicts provider {declared!r}")
        return {**data, "runner": harness, "provider": provider or None}

    @model_validator(mode="after")
    def _validate_provider(self) -> TierEntry:
        from cube.runners.naming import NATIVE_PROVIDER, PROVIDERS

        if self.provider is None:
            return self
        if self.provider not in PROVIDERS:
            raise ValueError(
                f"unknown provider {self.provider!r}; allowed: {', '.join(sorted(PROVIDERS))}"
            )
        if self.runner not in NATIVE_PROVIDER and self.runner != "hermes":
            raise ValueError(
                f"provider is only valid for runners {', '.join(sorted(NATIVE_PROVIDER))}, "
                f"hermes, not {self.runner!r}"
            )
        native = NATIVE_PROVIDER.get(self.runner)
        if self.provider != native and self.provider in set(NATIVE_PROVIDER.values()):
            raise ValueError(f"provider {self.provider!r} is only valid for runner {native!r}")
        if self.runner == "hermes" and self.provider != "local":
            # Hermes has no cube-managed provider but the group's own endpoint (ADR-0022).
            raise ValueError("runner hermes takes provider local only")
        if self.provider == "openrouter" and not self.model:
            raise ValueError("provider openrouter requires an explicit model")
        return self

    @property
    def runner_name(self) -> str:
        """The composed runner token: `claude@openrouter`, or the plain runner."""
        from cube.runners.naming import compose

        return compose(self.runner, self.provider)

    def allows(self, role: str | None) -> bool:
        if role is not None and role in self.not_for:
            return False
        return not self.only or (role is not None and role in self.only)


class Price(BaseModel):
    """Equivalent on-demand price for one runner and model."""

    model_config = ConfigDict(extra="forbid")

    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    free: bool = False

    @model_validator(mode="after")
    def validate_free_price(self) -> Price:
        if self.free and (self.input_per_mtok != 0 or self.output_per_mtok != 0):
            raise ValueError("free prices must be zero for input and output")
        return self


class Paths(BaseModel):
    pa: Path = Path("~/pa")
    org: Path = Path("~/org")
    rkg: Path = Path("~/Public/software/website/research-knowledge-graph")
    website: Path = Path("~/Public/software/website/borg-website")
    skills_library: Path = Path("~/Public/software/skills")
    infra: Path = Path("~/Public/software/borg-infrastructure")
    papers: Path = Path("~/Documents/papers")
    hermes_home: Path = Path("~/.hermes")
    runs: Path = Path("runs")
    state: Path = Path("state")

    def resolved(self, root: Path) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for name, value in self.model_dump().items():
            p = Path(value).expanduser()
            out[name] = p if p.is_absolute() else (root / p)
        return out


class BeadsConfig(BaseModel):
    bin: str = "bd"
    prefix: str = "cube"


class BudgetWindow(BaseModel):
    hours: float = Field(default=5, gt=0)
    tokens: int | None = Field(default=None, ge=0)


class Budget(BaseModel):
    plan_runs_per_day: int | None = Field(default=20, ge=0)
    implement_runs_per_day: int | None = Field(default=60, ge=0)
    bulk_runs_per_day: int | None = Field(default=None, ge=0)
    local_runs_per_day: int | None = Field(default=None, ge=0)
    plan_cost_usd_per_day: float | None = Field(default=None, ge=0)
    implement_cost_usd_per_day: float | None = Field(default=None, ge=0)
    bulk_cost_usd_per_day: float | None = Field(default=None, ge=0)
    local_cost_usd_per_day: float | None = Field(default=None, ge=0)
    equivalent_cap_usd_per_day: dict[str, float] = Field(default_factory=dict)
    daily_total_usd: float | None = Field(default=None, ge=0)
    weekly_total_usd: float | None = Field(default=None, ge=0)
    soft_cap_pct: float = Field(default=85, ge=0, le=100)
    windows: dict[str, BudgetWindow] = Field(
        default_factory=lambda: {
            "claude": BudgetWindow(hours=5),
            "codex": BudgetWindow(hours=5),
        }
    )
    openrouter_credits_floor_usd: float = Field(default=5.0, ge=0)

    @field_validator("equivalent_cap_usd_per_day")
    @classmethod
    def validate_equivalent_caps(cls, value: dict[str, float]) -> dict[str, float]:
        known = {"plan", "implement", "bulk", "local"}
        unknown = set(value) - known
        if unknown:
            raise ValueError(f"unknown equivalent budget tiers: {', '.join(sorted(unknown))}")
        if any(cap < 0 for cap in value.values()):
            raise ValueError("equivalent budget caps must be non-negative")
        return value


class Privacy(BaseModel):
    local_only_requires: str = "local"
    # Robert, 2026-09-07: OpenRouter free endpoints may log, publish or train on
    # prompts. Only the agents or roles named here may be routed to a free entry;
    # every other run skips free entries and waits for a paid or local one.
    open_endpoints_for: list[str] = Field(default_factory=list)


class ContactHours(BaseModel):
    """When real people may be contacted. Agents work 24/7; people do not."""

    model_config = ConfigDict(extra="forbid")

    start: str = "07:00"
    end: str = "19:00"
    tz: str = "Asia/Riyadh"
    days: list[str] = Field(default_factory=lambda: ["Sun", "Mon", "Tue", "Wed", "Thu"])

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        hours, minutes = value.split(":")
        if not (0 <= int(hours) < 24 and 0 <= int(minutes) < 60):
            raise ValueError("contact hours must be HH:MM")
        return value


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: ContactHours = Field(default_factory=ContactHours)


class PipelineAutonomy(BaseModel):
    recruit: Literal["robert", "coordinator"] = "robert"


class CoordinationConfig(BaseModel):
    """How often the coordinator reviews the group and when work counts as stale.

    Robert, 2026-09-07: the coordinator distributes the work and makes sure it
    gets done. Its management review runs every ``review_every_hours`` (not once
    a day); an assigned bead with no run for ``stale_hours`` is chased; a
    project with no bead activity for ``project_gap_days`` gets new work.
    """

    model_config = ConfigDict(extra="forbid")

    review_every_hours: int = Field(default=4, ge=1, le=24)
    stale_hours: int = Field(default=24, ge=1)
    project_gap_days: int = Field(default=14, ge=1)


class PipelineConfig(BaseModel):
    max_iterations: int = Field(default=3, ge=1)
    max_team: int = Field(default=6, ge=1)
    stale_hours: int = Field(default=24, ge=1)
    autonomy: PipelineAutonomy = Field(default_factory=PipelineAutonomy)
    budget_usd_per_epic: float | None = Field(default=None, ge=0)


class GroupExpertConfig(BaseModel):
    """Research topics and resource allowance for one expert agent."""

    model_config = ConfigDict(extra="forbid")

    topics: list[str] = Field(min_length=1)
    gpu_hours: float = Field(default=0, ge=0)
    skills: list[str] = Field(default_factory=list)


class GroupFunctionalConfig(BaseModel):
    """Functional role assignment for one non-topic-owning group agent."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    title: str = Field(min_length=1)


class GroupConfig(BaseModel):
    """Optional declaration of the research group represented by agents."""

    model_config = ConfigDict(extra="forbid")

    experts: dict[str, GroupExpertConfig] = Field(default_factory=dict)
    functional: dict[str, GroupFunctionalConfig] = Field(default_factory=dict)


class LiteratureSourceConfig(BaseModel):
    """Categories and the per-day fetch ceiling for one preprint server."""

    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(default_factory=list)
    max_per_day: int = Field(default=400, ge=1, le=5000)


DEFAULT_ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "q-bio.QM", "q-bio.GN", "q-bio.MN", "cs.DB"]
DEFAULT_BIORXIV_CATEGORIES = [
    "bioinformatics",
    "genomics",
    "systems biology",
    "synthetic biology",
]
DEFAULT_LITERATURE_KEYWORDS = [
    "ontology",
    "knowledge graph",
    "description logic",
    "neuro-symbolic",
    "embedding",
    "protein function",
    "phenotype",
    "rare disease",
    "gene ontology",
    "large language model",
    "semantic similarity",
    "metagenom",
    "drug mechanism",
    "systems biology",
    "bioengineering",
]


class LiteratureWatch(BaseModel):
    """Daily arXiv and bioRxiv watch: what to fetch, what counts as relevant."""

    model_config = ConfigDict(extra="forbid")

    arxiv: LiteratureSourceConfig = Field(
        default_factory=lambda: LiteratureSourceConfig(categories=list(DEFAULT_ARXIV_CATEGORIES))
    )
    biorxiv: LiteratureSourceConfig = Field(
        default_factory=lambda: LiteratureSourceConfig(categories=list(DEFAULT_BIORXIV_CATEGORIES))
    )
    medrxiv: LiteratureSourceConfig = Field(
        default_factory=lambda: LiteratureSourceConfig(
            categories=["pharmacology and toxicology", "health informatics", "oncology"]
        )
    )
    keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_LITERATURE_KEYWORDS))
    per_topic_keywords: dict[str, list[str]] = Field(default_factory=dict)
    max_summaries_per_day: int = Field(default=25, ge=1, le=200)
    digest_dir: Path = Path("briefings/literature")

    @field_validator("keywords")
    @classmethod
    def _non_empty_keywords(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("literature_watch keywords must not be blank")
        return value

    @field_validator("digest_dir")
    @classmethod
    def _relative_digest_dir(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("literature_watch digest_dir must be a path inside the repo")
        return value

    def digest_path(self, root: Path) -> Path:
        return root / self.digest_dir


class DecisionMatch(BaseModel):
    """What a policy rule looks at. Every key given must match; absent keys are ignored."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    resource_class: list[str] = Field(default_factory=list)
    within_budget: bool | None = None
    member_kind: list[str] = Field(default_factory=list)
    asker: list[str] = Field(default_factory=list, alias="from")
    title_prefix: str | None = None
    approval_kind: list[str] = Field(default_factory=list)
    target_within: list[str] = Field(default_factory=list)
    labels_all: list[str] = Field(default_factory=list)
    # Robert, 2026-09-08 (ADR-0027): whether the decision names one of the running
    # systems in `decisions.systems`, and who an outbound approval is addressed to.
    names_system: bool | None = None
    recipient: list[str] = Field(default_factory=list)


class DecisionRule(BaseModel):
    """One automatic answer: which decisions it matches, what it answers, and why."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    match: DecisionMatch = Field(default_factory=DecisionMatch)
    answer: str
    note: str

    @field_validator("answer", mode="before")
    @classmethod
    def _yaml_bool(cls, value: Any) -> Any:
        # YAML reads a bare `yes` and `no` as booleans; the answer is a word.
        return {True: "yes", False: "no"}.get(value, value) if isinstance(value, bool) else value


# Guards a decision can trigger; a rule never answers a decision under one of these.
DECISION_GUARDS = (
    "outbound",
    "people",
    "integrity",
    "conflict",
    "question",
    "deletion",
    "spend_over_budget",
)
DEFAULT_NEVER_AUTOMATIC = list(DECISION_GUARDS)


class TriageMatch(BaseModel):
    """What a triage rule looks at. Every key given must hold; absent keys are ignored."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: str | None = None
    asker: list[str] = Field(default_factory=list, alias="from")
    src: list[str] = Field(default_factory=list)
    title_regex: str | None = None
    labels_all: list[str] = Field(default_factory=list)
    labels_none: list[str] = Field(default_factory=list)
    priority_min: int | None = None
    age_days_min: int | None = None
    needs_robert: bool | None = None
    # Robert, 2026-09-08 (ADR-0027): True when the bead's title or body names one of
    # the running systems in `decisions.systems`; a change to one of those is his.
    names_system: bool | None = None


class TriageRule(BaseModel):
    """One routing rule for open beads: what it matches, what happens, and why."""

    model_config = ConfigDict(extra="forbid")

    name: str
    match: TriageMatch = Field(default_factory=TriageMatch)
    action: Literal["route", "close", "deliver", "defer"]
    to: str | None = None
    note: str = ""

    @model_validator(mode="after")
    def _route_needs_target(self) -> TriageRule:
        if self.action == "route" and not (self.to or "").startswith("agent:"):
            raise ValueError(f"triage rule {self.name!r}: route needs to: agent:<name>")
        return self


class TriageConfig(BaseModel):
    """Robert, 2026-09-07: Robert sees decisions, not a queue (ADR-0019)."""

    model_config = ConfigDict(extra="forbid")

    rules: list[TriageRule] = Field(default_factory=list)


class DecisionsConfig(BaseModel):
    """The decisions Robert would approve anyway, and the ones that stay his."""

    model_config = ConfigDict(extra="forbid")

    policy: list[DecisionRule] = Field(default_factory=list)
    never_automatic: list[str] = Field(default_factory=lambda: list(DEFAULT_NEVER_AUTOMATIC))
    digest: Literal["daily", "never"] = "daily"
    # Robert, 2026-09-08 (ADR-0027): the running systems whose changes he approves.
    # A bead or approval that names one of these (host name or domain, matched as a
    # whole word) stays his; every other decision is the policy's or the coordinator's.
    systems: list[str] = Field(default_factory=list)

    @field_validator("systems")
    @classmethod
    def _non_empty_systems(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("decisions.systems entries must not be blank")
        return cleaned

    @field_validator("never_automatic")
    @classmethod
    def _known_guards(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(DECISION_GUARDS))
        if unknown:
            raise ValueError(f"unknown never_automatic guards: {', '.join(unknown)}")
        return value


class Mattermost(BaseModel):
    team: str = "borg"
    infra_alerts_channel: str | None = None


class HermesProfile(BaseModel):
    bot: str | None = None
    home_channel: str | None = None
    allowlist_channel: str = "mattermost_dm"


class HermesConfig(BaseModel):
    profiles: dict[str, HermesProfile] = Field(default_factory=dict)


# Closed on every host whatever `readable` says: credential stores and harness homes.
ALWAYS_UNREADABLE = [
    Path("~/.ssh"),
    Path("~/.gnupg"),
    Path("~/.aws"),
    Path("~/.kube"),
    Path("~/.hermes"),
    Path("~/.claude"),
    Path("~/.codex"),
    Path("~/.config"),
]


class HostEntry(BaseModel):
    """One execution host in the shared-ledger topology."""

    role: Literal["orchestration", "personal"]
    ssh: str | None = None
    hostname: str | None = None
    # Robert, 2026-09-08 (ADR-0026): the directory on this host that receives
    # artifacts pushed by another host with `cube drop`; None means no drop.
    drop: str | None = None
    software_dirs: list[Path] = Field(default_factory=lambda: [Path("~/Public/software")])
    # Robert, 2026-09-08 (ADR-0027): directories an agent on this host may read on
    # its own (listing, grep, file contents, git history). A request that reaches
    # beyond them is a laptop read he approves first.
    readable: list[Path] = Field(default_factory=list)
    # Directories inside a readable one that stay closed (deny wins). On the laptop
    # `~/pa` is a symlink to `~/Public/software/pa`, so the private KG would sit
    # inside the software root without this list.
    unreadable: list[Path] = Field(default_factory=list)
    mail_read: bool = False


class ProjectRunnerProfile(BaseModel):
    """Execution settings applied to beads labelled for one project."""

    path: Path
    runner: str
    sandbox: str | None = None
    cwd: Literal["checkout", "worktree"] = "worktree"
    env: dict[str, str] = Field(default_factory=dict)
    pre: list[str] = Field(default_factory=list)
    worktrees_dir: Path = Path(".cube/wt")
    remote: bool = False
    budget_usd_per_day: float | None = Field(default=None, ge=0)

    def checkout_path(self, root: Path) -> Path:
        path = self.path.expanduser()
        return path if path.is_absolute() else root / path

    def worktrees_path(self, root: Path) -> Path:
        checkout = self.checkout_path(root)
        path = self.worktrees_dir.expanduser()
        return path if path.is_absolute() else checkout / path

    def effective(self, root: Path) -> dict[str, Any]:
        return {
            "path": str(self.checkout_path(root)),
            "runner": self.runner,
            "sandbox": self.sandbox,
            "cwd": self.cwd,
            "env": dict(self.env),
            "pre": list(self.pre),
            "worktrees_dir": str(self.worktrees_path(root)),
            "remote": self.remote,
            "budget_usd_per_day": self.budget_usd_per_day,
        }


class Settings(BaseModel):
    fleet_limits: FleetLimits = Field(default_factory=FleetLimits)
    fleet_enabled: bool = False
    host: str = "ws"
    hosts: dict[str, HostEntry] = Field(default_factory=dict)
    paths: Paths = Field(default_factory=Paths)
    course_files: list[Path] = Field(default_factory=list)
    beads: BeadsConfig = Field(default_factory=BeadsConfig)
    slots: dict[str, int] = Field(
        default_factory=lambda: {"plan": 1, "implement": 3, "bulk": 4, "local": 1}
    )
    tiers: dict[str, list[TierEntry]] = Field(default_factory=dict)
    prices: dict[str, Price] = Field(default_factory=dict)
    budget: Budget = Field(default_factory=Budget)
    privacy: Privacy = Field(default_factory=Privacy)
    contact: Contact = Field(default_factory=Contact)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    coordination: CoordinationConfig = Field(default_factory=CoordinationConfig)
    group: GroupConfig | None = None
    literature_watch: LiteratureWatch = Field(default_factory=LiteratureWatch)
    decisions: DecisionsConfig = Field(default_factory=DecisionsConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    patrols: dict[str, str] = Field(default_factory=dict)
    mattermost: Mattermost = Field(default_factory=Mattermost)
    hermes: HermesConfig = Field(default_factory=HermesConfig)
    projects: dict[str, ProjectRunnerProfile] = Field(default_factory=dict)

    root: Path = Field(default=Path("."), exclude=True)
    env: dict[str, str] = Field(default_factory=dict, exclude=True)

    @field_validator("prices")
    @classmethod
    def validate_prices(cls, value: dict[str, Price]) -> dict[str, Price]:
        if value and "default" not in value:
            raise ValueError("prices must include a default entry")
        return value

    @model_validator(mode="after")
    def validate_free_tier_prices(self) -> Settings:
        for tier, entries in self.tiers.items():
            for entry in entries:
                if not entry.model or not entry.model.endswith(":free"):
                    continue
                target = f"{entry.runner_name}:{entry.model}"
                price = self.prices.get(target)
                if price is None or not price.free:
                    raise ValueError(
                        f"free tier entry {tier}:{target} must have an exact free price"
                    )
                if price.input_per_mtok != 0 or price.output_per_mtok != 0:
                    raise ValueError(f"free tier entry {tier}:{target} must have zero rates")
        for target, price in self.prices.items():
            if target.endswith(":free") and not price.free:
                raise ValueError(f"price {target} must set free: true")
        return self

    @property
    def dirs(self) -> dict[str, Path]:
        return self.paths.resolved(self.root)

    def state_dir(self) -> Path:
        path = self.dirs["state"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def runs_dir(self) -> Path:
        path = self.dirs["runs"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def configured_course_files(self) -> list[Path]:
        """Return explicitly configured course Org files with host paths resolved."""
        out: list[Path] = []
        for value in self.course_files:
            path = value.expanduser()
            out.append(path if path.is_absolute() else self.root / path)
        return out

    def runner_profile(self, slug: str) -> dict[str, Any] | None:
        profile = self.projects.get(slug)
        return profile.effective(self.root) if profile else None

    def readable_dirs(self, host: str | None = None) -> list[Path]:
        """Directories agents on HOST read without approval (ADR-0027), expanded."""
        entry = self.hosts.get(host or self.host)
        return self._expand(entry.readable if entry else [])

    def unreadable_dirs(self, host: str | None = None) -> list[Path]:
        """Directories never read on HOST, even inside a readable one (deny wins)."""
        entry = self.hosts.get(host or self.host)
        configured = entry.unreadable if entry else []
        return self._expand([*ALWAYS_UNREADABLE, *configured])

    def _expand(self, values: list[Path]) -> list[Path]:
        roots: list[Path] = []
        for value in values:
            path = Path(value).expanduser()
            path = path if path.is_absolute() else self.root / path
            if path not in roots:
                roots.append(path)
        return roots

    def software_dirs(self, host: str | None = None) -> list[Path]:
        """Return configured software roots for a host, expanded but not traversed."""
        entry = self.hosts.get(host or self.host)
        values = entry.software_dirs if entry else [Path("~/Public/software")]
        roots: list[Path] = []
        for value in values:
            path = value.expanduser()
            roots.append(path if path.is_absolute() else self.root / path)
        return roots


def find_root(start: Path | None = None) -> Path:
    """Locate the repo root: $CUBE_ROOT, else walk up from start looking for cube.yaml."""
    env_root = os.environ.get("CUBE_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "cube.yaml").exists():
            return candidate
    # Fall back to the package's parent (installed checkout).
    return Path(__file__).resolve().parent.parent


def clean_github_environment(environ: dict[str, str]) -> None:
    """Discard empty/comment placeholders, never fall back from an actual bad token.

    systemd EnvironmentFile does not implement shell-style inline comments.
    Older .env examples therefore supplied '# fine-grained...' as GH_TOKEN,
    shadowing a valid gh auth login. Preserve every real scoped credential.
    """
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if key in environ and (not environ[key].strip() or environ[key].lstrip().startswith("#")):
            del environ[key]


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; ignores comments, blanks and inline comments after a value."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        result[key.strip()] = value
    return result


LOCAL_CONFIG = "cube.local.yaml"


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return base updated by overlay; nested mappings merge, everything else is replaced."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping")
    return loaded


def load_settings(root: Path | None = None) -> Settings:
    """cube.yaml holds the shareable configuration; cube.local.yaml (gitignored) holds
    the site-specific overlay: hosts, project checkouts, roster exceptions, the names
    of running systems, Mattermost ids. The overlay deep-merges over cube.yaml."""
    root = root or find_root()
    data: dict[str, Any] = {}
    cfg = root / "cube.yaml"
    if cfg.exists():
        data = _load_mapping(cfg)
    local = root / LOCAL_CONFIG
    if local.exists():
        data = deep_merge(data, _load_mapping(local))
    settings = Settings.model_validate(data)
    if os.environ.get("CUBE_HOST"):
        settings.host = os.environ["CUBE_HOST"]
    settings.root = root
    settings.env = parse_env_file(root / ".env")
    if settings.fleet_enabled:
        from cube.resources import load_limits

        settings.budget.daily_total_usd = load_limits(settings).daily_cost_usd
    return settings
