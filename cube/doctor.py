"""`cube doctor`: environment, auth, paths, policy checks. Never changes anything."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from cube.config import Settings
from cube.contact import ContactPolicy
from cube.hosts import is_orchestration_host, peer_status
from cube.router.policy import RUNNER_BINARIES
from cube.runners.naming import uses_openrouter

OUTBOUND_WORDS = (
    "send",
    "post",
    "email",
    "message",
    "dm",
    "submit",
    "sign",
    "publish",
    "notify_student",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "error"  # error | warn | info

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (
            (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""
        )
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def check_binaries() -> list[Check]:
    checks: list[Check] = []
    required = {"bd": "Beads work ledger", "uv": "Python runner", "git": "git", "ssh": "ssh"}
    optional = {
        "claude": "Claude Code (plan tier)",
        "codex": "Codex (implement tier)",
        "hermes": "Hermes (standing roles)",
        "just": "task runner",
        "tmux": "persistent sessions on the host",
        "gh": "GitHub CLI",
        "pdftotext": "corpus conversion",
        "pandoc": "corpus conversion",
    }
    for name, what in required.items():
        path = _which(name)
        checks.append(Check(f"bin:{name}", path is not None, path or f"missing ({what})"))
    for name, what in optional.items():
        path = _which(name)
        checks.append(
            Check(f"bin:{name}", path is not None, path or f"missing ({what})", severity="warn")
        )
    return checks


def check_paths(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    settings.state_dir()
    settings.runs_dir()
    for name, path in settings.dirs.items():
        exists = path.exists()
        sev = "warn" if name in {"papers", "hermes_home", "website"} else "error"
        checks.append(Check(f"path:{name}", exists, str(path), severity=sev))
    return checks


def check_project_paths(settings: Settings) -> list[Check]:
    missing = [
        f"{slug}={profile.checkout_path(settings.root)}"
        for slug, profile in settings.projects.items()
        if not profile.remote and not profile.checkout_path(settings.root).exists()
    ]
    remote = sorted(slug for slug, profile in settings.projects.items() if profile.remote)
    if missing:
        detail = "missing local project path(s): " + ", ".join(missing)
    else:
        detail = f"{len(settings.projects)} project path(s) available"
        if remote:
            detail += f"; marked remote: {', '.join(remote)}"
    return [Check("projects:paths", not missing, detail)]


def check_secrets(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    env_file = settings.root / ".env"
    if env_file.exists():
        mode = stat.S_IMODE(env_file.stat().st_mode)
        checks.append(Check("env:mode", mode & 0o077 == 0, f".env mode {oct(mode)} (want 0600)"))
        for key in ("MATTERMOST_TOKEN", "GH_TOKEN", "OPENROUTER_API_KEY"):
            present = bool(settings.env.get(key))
            checks.append(
                Check(f"env:{key}", present, "set" if present else "empty", severity="warn")
            )
    else:
        checks.append(Check("env:file", False, ".env missing (copy .env.example)", severity="warn"))
    ignored = (
        (settings.root / ".gitignore").read_text(encoding="utf-8")
        if (settings.root / ".gitignore").exists()
        else ""
    )
    checks.append(Check("gitignore:env", ".env" in ignored.split(), ".env must be gitignored"))
    return checks


CODEX_OPENROUTER_PROFILE = "cube-openrouter"


def _codex_openrouter_entries(settings: Settings) -> list[str]:
    """Tier entries routed at `codex@openrouter`, as `<tier>: <model>` strings."""
    return _codex_entries(settings, "codex@openrouter")


def _codex_entries(settings: Settings, token: str) -> list[str]:
    return [
        f"{tier}: {entry.model}"
        for tier, entries in settings.tiers.items()
        for entry in entries
        if entry.runner_name == token
    ]


CODEX_LOCAL_PROFILE = "cube-local"


def check_codex_local_profile(cfg: Path, severity: str = "error") -> list[Check]:
    """The `cube-local` profile must exist and name the local provider (ADR-0021)."""
    profile_file = cfg.parent / f"{CODEX_LOCAL_PROFILE}.config.toml"
    fix = f"copy deploy/codex-local-profile.toml to {profile_file}"
    if not profile_file.exists():
        return [Check("codex:local-profile", False, f"missing {profile_file}; {fix}", severity)]
    text = profile_file.read_text(encoding="utf-8")
    missing = [
        label
        for label, pattern in (
            ("a model line", r"^\s*model\s*="),
            ('model_provider = "local"', r'^\s*model_provider\s*=\s*"local"'),
            ("[model_providers.local]", r"^\s*\[model_providers\.local\]"),
            ('env_key = "VLLM_API_KEY"', r'^\s*env_key\s*=\s*"VLLM_API_KEY"'),
            ('web_search = "disabled"', r'^\s*web_search\s*=\s*"disabled"'),
        )
        if not re.search(pattern, text, re.M)
    ]
    if missing:
        return [
            Check(
                "codex:local-profile",
                False,
                f"{profile_file} is missing {', '.join(missing)}; {fix}",
                severity,
            )
        ]
    return [Check("codex:local-profile", True, f"{profile_file} present", severity="info")]


def check_hermes_worker_profile(settings: Settings) -> list[Check]:
    """A `hermes@local` tier entry needs its profile rendered on this host (ADR-0022)."""
    profiles = sorted(
        {
            entry.profile or "cube-worker"
            for entries in settings.tiers.values()
            for entry in entries
            if entry.runner == "hermes"
        }
    )
    if not profiles:
        return [Check("hermes:worker-profile", True, "no Hermes tier entry", severity="info")]
    severity = "error" if is_orchestration_host(settings) else "warn"
    out: list[Check] = []
    for profile in profiles:
        cfg = settings.paths.hermes_home.expanduser() / "profiles" / profile / "config.yaml"
        ok = cfg.exists() and "single_query_mode: deny" in cfg.read_text(encoding="utf-8")
        out.append(
            Check(
                f"hermes:worker-profile:{profile}",
                ok,
                f"{cfg} present with single_query_mode deny"
                if ok
                else f"{cfg} missing or without approvals.single_query_mode deny; "
                f"run hermes profile create {profile} --no-skills --no-alias, then "
                f"cube hermes render {profile} --apply",
                severity="info" if ok else severity,
            )
        )
    return out


def check_local_endpoint(settings: Settings) -> list[Check]:
    """Entries on the group's own endpoint need VLLM_BASE_URL and VLLM_API_KEY (ADR-0021)."""
    from cube.runners.naming import uses_local

    entries = [
        f"{tier}: {entry.runner_name}"
        for tier, entries in settings.tiers.items()
        for entry in entries
        if uses_local(entry.runner_name)
    ]
    if not entries:
        return [
            Check("local:endpoint", True, "no tier entry on the local endpoint", severity="info")
        ]
    severity = "error" if is_orchestration_host(settings) else "warn"
    url = settings.env.get("VLLM_BASE_URL") or ""
    key = bool(settings.env.get("VLLM_API_KEY"))
    ok = bool(url) and key
    return [
        Check(
            "local:endpoint",
            ok,
            f"VLLM_BASE_URL={url}, key {'set' if key else 'missing'}; {len(entries)} tier entries"
            if url
            else f"VLLM_BASE_URL empty in .env; {len(entries)} tier entries cannot run",
            severity="info" if ok else severity,
        )
    ]


def check_codex_openrouter_profile(cfg: Path, severity: str = "error") -> list[Check]:
    """The `cube-openrouter` profile must exist and name the OpenRouter responses API."""
    profile_file = cfg.parent / f"{CODEX_OPENROUTER_PROFILE}.config.toml"
    fix = f"copy deploy/codex-openrouter-profile.toml to {profile_file}"
    if not profile_file.exists():
        return [
            Check("codex:openrouter-profile", False, f"missing {profile_file}; {fix}", severity)
        ]
    text = profile_file.read_text(encoding="utf-8")
    missing = [
        label
        for label, pattern in (
            ("a model line", r"^\s*model\s*="),
            ('model_provider = "openrouter"', r'^\s*model_provider\s*=\s*"openrouter"'),
            ("[model_providers.openrouter]", r"^\s*\[model_providers\.openrouter\]"),
            ('wire_api = "responses"', r'^\s*wire_api\s*=\s*"responses"'),
            ('web_search = "disabled"', r'^\s*web_search\s*=\s*"disabled"'),
        )
        if not re.search(pattern, text, re.M)
    ]
    if missing:
        return [
            Check(
                "codex:openrouter-profile",
                False,
                f"{profile_file} is missing {', '.join(missing)}; {fix}",
                severity,
            )
        ]
    return [Check("codex:openrouter-profile", True, f"{profile_file} present", severity="info")]


def check_codex_profile(settings: Settings | None = None) -> list[Check]:
    cfg = Path("~/.codex/config.toml").expanduser()
    if not cfg.exists():
        return [Check("codex:config", False, "no ~/.codex/config.toml", severity="warn")]
    text = cfg.read_text(encoding="utf-8")
    # Codex reads a profile from ~/.codex/<name>.config.toml; a legacy
    # [profiles.<name>] table in config.toml makes `-p` fail. The profile must pin
    # a model or runs inherit config.toml's default (an OpenRouter id on laptops).
    profile_file = cfg.parent / "cube-chatgpt.config.toml"
    legacy = "[profiles.cube-chatgpt]" in text
    has_model = profile_file.exists() and re.search(
        r"^\s*model\s*=", profile_file.read_text(encoding="utf-8"), re.M
    )
    has_profile = bool(has_model) and not legacy
    default_openrouter = (
        "openrouter" in text.split("[", 1)[0] or 'model_provider = "openrouter"' in text
    )
    out = [
        Check(
            "codex:profile",
            has_profile,
            "profile cube-chatgpt present"
            if has_profile
            else (
                "remove the legacy [profiles.cube-chatgpt] table from ~/.codex/config.toml"
                if legacy
                else "create ~/.codex/cube-chatgpt.config.toml with a model line "
                "(deploy/codex-profile.toml)"
            ),
        )
    ]
    if default_openrouter:
        out.append(
            Check(
                "codex:default-provider",
                True,
                "default provider is OpenRouter; workers MUST pass -p cube-chatgpt",
                severity="info",
            )
        )
    if settings is not None and _codex_openrouter_entries(settings):
        severity = "error" if is_orchestration_host(settings) else "warn"
        out.extend(check_codex_openrouter_profile(cfg, severity))
    if settings is not None and _codex_entries(settings, "codex@local"):
        severity = "error" if is_orchestration_host(settings) else "warn"
        out.extend(check_codex_local_profile(cfg, severity))
    return out


def check_openrouter_free(settings: Settings) -> list[Check]:
    """The free pool: discovered daily by the budget patrol, fresh, and non-empty."""
    from cube.router.free_pool import STALE_AFTER, cache_path, load_pool

    configured = sorted(
        f"{tier}: {entry.model}"
        for tier, entries in settings.tiers.items()
        for entry in entries
        if entry.model and entry.model.endswith(":free")
    )
    checks: list[Check] = []
    if configured:
        checks.append(
            Check(
                "openrouter:free-models",
                False,
                "free models are hand-listed in tiers; the budget patrol's pool replaces "
                "them (ADR-0018): " + ", ".join(configured),
                severity="warn",
            )
        )
    cache = cache_path(settings)
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = None
    if not isinstance(raw, dict) or "free" not in raw:
        checks.append(
            Check(
                "openrouter:free-pool",
                False,
                f"no free pool in {cache}; run cube patrol budget --apply",
                severity="warn",
            )
        )
        return checks
    pool = load_pool(settings)
    if not pool:
        checks.append(
            Check(
                "openrouter:free-pool",
                False,
                f"free pool empty or older than {STALE_AFTER.days} days "
                f"(checked {raw.get('checked')}); run cube patrol budget --apply",
                severity="warn",
            )
        )
        return checks
    checks.append(
        Check(
            "openrouter:free-pool",
            True,
            f"{len(pool)} of {len(raw['free'])} free models in the pool, checked "
            f"{raw.get('checked')}: " + ", ".join(item.id for item in pool),
            severity="info",
        )
    )
    return checks


def check_beads(settings: Settings) -> list[Check]:
    beads_dir = settings.root / ".beads"
    checks = [Check("beads:init", beads_dir.exists(), str(beads_dir))]
    if _which(settings.beads.bin):
        checks.append(
            Check(
                "beads:version", True, _version([settings.beads.bin, "--version"]), severity="info"
            )
        )
    return checks


def check_contacts(settings: Settings) -> list[Check]:
    path = settings.root / "contacts.yaml"
    try:
        policy = ContactPolicy(path)
    except ValueError as exc:
        return [Check("contacts:parse", False, str(exc))]
    grants = policy.grants
    people = sorted(grants)
    return [
        Check(
            "contacts:grants",
            True,
            f"{len(people)} people with grants: {', '.join(people) or 'none (default deny)'}",
            severity="info",
        )
    ]


def check_roles(settings: Settings) -> list[Check]:
    roles_dir = settings.root / "roles"
    checks: list[Check] = []
    if not roles_dir.exists():
        return [Check("roles:dir", False, "roles/ missing", severity="warn")]
    for path in sorted(roles_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            checks.append(Check(f"role:{path.stem}", False, f"YAML error: {exc}"))
            continue
        actions = data.get("autonomous_actions") or []
        outbound = [a for a in actions if any(w in str(a).lower() for w in OUTBOUND_WORDS)]
        checks.append(
            Check(
                f"role:{path.stem}:no-outbound-autonomy",
                not outbound,
                f"outbound autonomous actions: {outbound}" if outbound else "ok",
            )
        )
    return checks


def check_agents(settings: Settings) -> list[Check]:
    """One declaration check: named agents may narrow, never widen, role policy."""
    from cube.agents import load_all_agents

    agents, errors = load_all_agents(settings.root)
    if settings.hosts:
        errors.update(
            {
                name: f"agent host {agent.host!r} is not configured under hosts"
                for name, agent in agents.items()
                if agent.host not in settings.hosts
            }
        )
    detail = (
        f"{len(agents)} agent declaration(s) validate; role tier and "
        "default-deny contact policy hold"
        if not errors
        else "; ".join(f"{name}: {error}" for name, error in sorted(errors.items()))
    )
    return [Check("agents:declarations", not errors, detail)]


def check_open_endpoints(settings: Settings) -> list[Check]:
    """privacy.open_endpoints_for names agents or roles that exist; free entries need it."""
    from cube.agents import load_all_agents
    from cube.roles.loader import load_all

    names = [name for name in settings.privacy.open_endpoints_for if name]
    agents, _ = load_all_agents(settings.root)
    roles = set(load_all(settings.root)[0])
    unknown = sorted(name for name in names if name not in agents and name not in roles)
    free = sorted(
        {
            f"{tier}: {entry.model}"
            for tier, entries in settings.tiers.items()
            for entry in entries
            if entry.model and entry.model.endswith(":free")
        }
    )
    if unknown:
        return [
            Check(
                "privacy:open-endpoints",
                False,
                "unknown agent or role in privacy.open_endpoints_for: " + ", ".join(unknown),
            )
        ]
    if free and not names:
        return [
            Check(
                "privacy:open-endpoints",
                True,
                f"{len(free)} free entries configured and no agent may use them "
                "(privacy.open_endpoints_for is empty); they are dead weight",
                severity="warn",
            )
        ]
    return [
        Check(
            "privacy:open-endpoints",
            True,
            "free endpoints allowed for: " + (", ".join(names) or "nobody"),
            severity="info",
        )
    ]


def check_agent_topics(settings: Settings) -> list[Check]:
    """Ensure declared group and agent topics exist in the public research KG."""
    from cube.agents import load_all_agents
    from cube.sources.rkg import load_graph

    agents, _errors = load_all_agents(settings.root)
    declared: list[tuple[str, str]] = []
    for name, agent in agents.items():
        for topic in agent.topics:
            declared.append((f"agent:{name}", topic))
    if settings.group is not None:
        for name, expert_config in settings.group.experts.items():
            declared.extend((f"group:experts:{name}", topic) for topic in expert_config.topics)
        for name, functional_config in settings.group.functional.items():
            declared.extend(
                (f"group:functional:{name}", topic) for topic in functional_config.topics
            )
    allowed = {("agent:liaison", "personal-context")}
    allowed.update(
        (f"agent:{name}", "student-research")
        for name, agent in agents.items()
        if agent.role in {"student-researcher", "student-reviewer"}
    )
    kg_path = settings.dirs["rkg"] / "projects.jsonld"
    graph = load_graph(kg_path)
    known = set(graph.topics)
    unknown = [
        f"{owner}={topic}"
        for owner, topic in declared
        if topic not in known and (owner, topic) not in allowed
    ]
    if not declared:
        return [Check("agents:topics", True, "no agent or group topics declared", severity="info")]
    if not kg_path.exists():
        return [Check("agents:topics", False, f"research KG missing: {kg_path}")]
    if unknown:
        return [Check("agents:topics", False, "unknown topic slug(s): " + ", ".join(unknown))]
    return [
        Check(
            "agents:topics",
            True,
            f"{len(declared)} declared topic assignment(s) exist in {kg_path}",
        )
    ]


def check_literature_watch(settings: Settings) -> list[Check]:
    """The literature watch must name categories, terms and a digest dir inside the repo."""
    config = settings.literature_watch
    problems: list[str] = []
    if not config.arxiv.categories and not config.biorxiv.categories:
        problems.append("no arxiv or biorxiv categories configured")
    if not config.keywords:
        problems.append("no keywords configured")
    for topic, values in config.per_topic_keywords.items():
        if not values:
            problems.append(f"per_topic_keywords[{topic}] is empty")
    digest_dir = config.digest_path(settings.root)
    if digest_dir.exists() and not digest_dir.is_dir():
        problems.append(f"digest_dir {digest_dir} is not a directory")
    detail = (
        "; ".join(problems)
        if problems
        else (
            f"{len(config.arxiv.categories)} arxiv and {len(config.biorxiv.categories)} "
            f"biorxiv categories, {len(config.keywords)} keywords, "
            f"at most {config.max_summaries_per_day} summaries per day, digest {digest_dir}"
        )
    )
    return [Check("literature_watch:config", not problems, detail, severity="warn")]


def check_decisions_policy(settings: Settings) -> list[Check]:
    """Every automatic answer must be legal: no guarded kind, no answer off the options."""
    from cube.decisions import options_for_rule_kind  # noqa: PLC0415

    config = settings.decisions
    problems: list[str] = []
    never = set(config.never_automatic)
    for index, rule in enumerate(config.policy):
        if rule.kind in never:
            problems.append(f"policy[{index}]: kind {rule.kind} is in never_automatic")
        options = options_for_rule_kind(rule.kind)
        if options and rule.answer not in options:
            problems.append(
                f"policy[{index}]: answer {rule.answer!r} is not one of {', '.join(options)}"
            )
        if not rule.note.strip():
            problems.append(f"policy[{index}]: needs a note saying why the answer is safe")
    detail = (
        "; ".join(problems)
        if problems
        else (
            f"{len(config.policy)} automatic rule(s), "
            f"{len(config.never_automatic)} guard(s) always human, digest {config.digest}"
        )
    )
    return [Check("decisions:policy", not problems, detail)]


def check_state(settings: Settings) -> list[Check]:
    kill = settings.state_dir() / "KILL"
    events = settings.dirs["state"] / "events.jsonl"
    events_ok = events.is_file() and os.access(events, os.R_OK)
    return [
        Check(
            "state:kill-switch",
            not kill.exists(),
            "KILL file present: everything paused" if kill.exists() else "clear",
            severity="warn",
        ),
        Check(
            "state:events-readable",
            events_ok,
            str(events) if events_ok else f"{events} missing or unreadable",
            severity="warn",
        ),
    ]


def check_course_sources(settings: Settings) -> list[Check]:
    configured = settings.configured_course_files()
    if not configured:
        return [
            Check(
                "courses:sources",
                True,
                f"auto-discovery under {settings.dirs['org']}/cs*.org",
                severity="info",
            )
        ]
    unreachable = [
        path for path in configured if not path.is_file() or not os.access(path, os.R_OK)
    ]
    detail = (
        f"{len(configured)} configured course source(s) reachable"
        if not unreachable
        else "missing or unreadable: " + ", ".join(str(path) for path in unreachable)
    )
    return [Check("courses:sources", not unreachable, detail)]


def check_corpus_verify_timer(settings: Settings) -> list[Check]:
    del settings
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    timer = config_home / "systemd" / "user" / "cube-corpus-verify.timer"
    installed = timer.is_file() and os.access(timer, os.R_OK)
    return [
        Check(
            "systemd:corpus-verify-timer",
            installed,
            str(timer) if installed else f"not installed at {timer}",
            severity="warn",
        )
    ]


def check_host(settings: Settings) -> list[Check]:
    hostname = os.uname().nodename
    if not settings.hosts:
        return [
            Check(
                "host",
                True,
                f"running on {hostname}; configured host is {settings.host}",
                severity="info",
            )
        ]
    entry = settings.hosts.get(settings.host)
    if entry is None:
        checks = [
            Check(
                "host:configured",
                False,
                f"settings.host {settings.host!r} is absent from hosts",
                severity="warn",
            )
        ]
    else:
        expected = entry.hostname or settings.host
        matches = hostname == expected
        checks = [
            Check(
                "host:configured",
                matches,
                f"running on {hostname}; {settings.host} expects hostname {expected}",
                severity="info" if matches else "warn",
            )
        ]
    for peer in peer_status(settings):
        if peer.get("route") == "none":
            checks.append(
                Check(
                    f"host:peer:{peer['name']}",
                    True,
                    "no ssh route from here; it pulls and relays on its own",
                    severity="info",
                )
            )
            continue
        checks.append(
            Check(
                f"host:peer:{peer['name']}",
                bool(peer["reachable"]),
                (
                    f"reachable at {peer['sha']}; lag {peer['lag_commits']} commit(s)"
                    if peer["reachable"]
                    else "unreachable; relay will defer to the next Beads sync"
                ),
                severity="warn",
            )
        )
    return checks


def check_venv_import(settings: Settings) -> list[Check]:
    """The systemd units call .venv/bin/cube directly; it must import cube from any cwd.

    `uv run` masks a missing editable install because the checkout is on the
    path; a timer run from / is not so lucky (laptop worker failed this way).
    """
    python = settings.root / ".venv" / "bin" / "python"
    if not python.exists():
        return [Check("venv:import", False, f"{python} missing (uv sync --all-extras)", "warn")]
    try:
        completed = subprocess.run(
            [str(python), "-c", "import cube"],
            cwd="/",
            env={"HOME": os.environ.get("HOME", ""), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Check("venv:import", False, f"could not run {python}: {exc}")]
    if completed.returncode:
        return [
            Check(
                "venv:import",
                False,
                "cube not importable from the venv outside the checkout; "
                "fix: uv sync --all-extras --reinstall-package borg-cube",
            )
        ]
    return [Check("venv:import", True, "editable install present", "info")]


def check_openrouter_key(settings: Settings) -> list[Check]:
    """Tiers that name OpenRouter models are dead without a key; say so before a run falls back."""
    uses = [
        f"{tier}: {entry.runner_name} {entry.model}"
        for tier, entries in settings.tiers.items()
        for entry in entries
        if uses_openrouter(entry.runner_name)
    ]
    if not uses:
        return []
    if settings.env.get("OPENROUTER_API_KEY"):
        return [Check("openrouter:key", True, f"key present; {len(uses)} tier entries", "info")]
    return [
        Check(
            "openrouter:key",
            False,
            f"OPENROUTER_API_KEY empty in .env; {len(uses)} tier entries (first: {uses[0]}) "
            "are skipped and runs fall back to Claude or Codex",
            severity="warn",
        )
    ]


def check_harness_providers(settings: Settings) -> list[Check]:
    """Every agentic harness pointed at a non-native provider must be usable (ADR-0016).

    On the orchestration host a broken harness provider is an error: the tier falls
    through to chat-only entries and tool work silently stops happening. Anywhere
    else it is a warning, because laptops are thin clients.
    """
    entries = [
        entry
        for entries in settings.tiers.values()
        for entry in entries
        if entry.provider == "openrouter"
    ]
    if not entries:
        return [
            Check(
                "harness:openrouter",
                True,
                "no agentic harness routed at OpenRouter",
                severity="info",
            )
        ]
    severity = "error" if is_orchestration_host(settings) else "warn"
    has_key = bool(settings.env.get("OPENROUTER_API_KEY"))
    checks: list[Check] = [
        Check(
            "harness:openrouter:key",
            has_key,
            f"OPENROUTER_API_KEY in .env; {len(entries)} harness tier entries"
            if has_key
            else f"OPENROUTER_API_KEY empty in .env; {len(entries)} harness tier entries "
            "cannot run and every tool-capable route falls through",
            severity="info" if has_key else severity,
        )
    ]
    for harness in sorted({entry.runner for entry in entries}):
        binary = RUNNER_BINARIES.get(harness, harness)
        path = _which(binary)
        checks.append(
            Check(
                f"harness:openrouter:{harness}",
                path is not None,
                f"{binary} at {path}" if path else f"{binary} not on PATH",
                severity=severity if path is None else "info",
            )
        )
    config_parent = settings.state_dir() / "harness"
    writable = os.access(config_parent if config_parent.exists() else config_parent.parent, os.W_OK)
    checks.append(
        Check(
            "harness:openrouter:config-dir",
            writable,
            f"{config_parent} writable"
            if writable
            else f"{config_parent} is not writable; Claude Code needs its own CLAUDE_CONFIG_DIR",
            severity=severity if not writable else "info",
        )
    )
    if _codex_openrouter_entries(settings):
        checks.extend(
            check_codex_openrouter_profile(Path("~/.codex/config.toml").expanduser(), severity)
        )
    return checks


def run_all(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    for fn in (
        check_host,
        check_beads,
        check_paths,
        check_project_paths,
        check_secrets,
        check_contacts,
        check_roles,
        check_agents,
        check_agent_topics,
        check_open_endpoints,
        check_course_sources,
        check_corpus_verify_timer,
        check_literature_watch,
        check_decisions_policy,
        check_state,
        check_openrouter_free,
    ):
        checks.extend(fn(settings))
    checks.extend(check_binaries())
    checks.extend(check_venv_import(settings))
    checks.extend(check_openrouter_key(settings))
    checks.extend(check_harness_providers(settings))
    checks.extend(check_local_endpoint(settings))
    checks.extend(check_hermes_worker_profile(settings))
    checks.extend(check_codex_profile(settings))
    # `codex:openrouter-profile` is reported by both the harness and the codex check;
    # the cockpit wants one row per check name.
    seen: set[str] = set()
    unique: list[Check] = []
    for check in checks:
        if check.name in seen:
            continue
        seen.add(check.name)
        unique.append(check)
    return unique


def summarize(checks: list[Check]) -> tuple[int, int]:
    errors = sum(1 for c in checks if not c.ok and c.severity == "error")
    warns = sum(1 for c in checks if not c.ok and c.severity == "warn")
    return errors, warns
