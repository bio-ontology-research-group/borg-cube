"""`cube run <role>`: the eight steps of doc/plan.md "Execution engine"."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.approvals import ApprovalStore
from cube.audit import audit
from cube.beads import Beads, BeadsError
from cube.config import ProjectRunnerProfile, Settings
from cube.contact import ContactPolicy
from cube.engine import lease as leases
from cube.engine import worktree as worktrees
from cube.engine.context import Context, build_context, label_value, privacy_allowed
from cube.engine.results import Applied, apply_result
from cube.hosts import is_orchestration_host
from cube.model import Privacy, Tier
from cube.notify import append_event, make_event
from cube.resources import LocalCapacityFull, load_limits, local_inference_slot
from cube.roles import Role, RoleError, assemble_prompt, load_role, result_schema
from cube.router import (
    Backoff,
    BudgetLedger,
    Queued,
    Refused,
    Route,
    budget_block,
    choose,
    effective_tier,
)
from cube.router.controls import TierState, entry_target
from cube.router.policy import open_endpoints_allowed
from cube.runners import Exec, HttpPost, RunContext, Runner, RunOutcome, default_exec, make_runner
from cube.runners.naming import harness_of, uses_local, uses_openrouter


class EngineError(RuntimeError):
    pass


@dataclass
class RunReport:
    ok: bool
    run_id: str
    role: str
    bead: str | None
    state: str  # dry-run|finished|invalid|error|queued|refused|killed|leased
    project: str | None = None
    runner: str | None = None
    model: str | None = None
    needs_tools: bool = False
    pid: int = field(default_factory=os.getpid)
    log: str | None = None
    tmux: str | None = None
    started: str = ""
    finished: str | None = None
    run_dir: str | None = None
    command: list[str] = field(default_factory=list)
    cwd: str | None = None
    runner_profile: dict[str, Any] | None = None
    pre_steps: list[str] = field(default_factory=list)
    prompt: str | None = None
    result: dict[str, Any] | None = None
    applied: dict[str, Any] | None = None
    session_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    equivalent_usd: float = 0.0
    estimated: bool = False
    error: str | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"r-{now.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(1)}"


def run_dir_for(settings: Settings, run_id: str, now: datetime | None = None) -> Path:
    now = now or datetime.now(UTC)
    return settings.runs_dir() / now.strftime("%Y-%m-%d") / run_id


def sessions_dir(state_dir: Path) -> Path:
    return state_dir / "sessions"


def stored_session(state_dir: Path, bead: str, runner: str) -> str | None:
    path = sessions_dir(state_dir) / f"{bead}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    resume_id = data.get("resume_id") or data.get("session_id") if isinstance(data, dict) else None
    if isinstance(data, dict) and data.get("runner") == runner and resume_id:
        return str(resume_id)
    return None


def store_session(
    state_dir: Path,
    bead: str,
    runner: str,
    session_id: str,
    run_id: str | None,
    *,
    adopted_session: str | None = None,
) -> None:
    d = sessions_dir(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{bead}.json").write_text(
        json.dumps(
            {
                "runner": runner,
                "session_id": session_id,
                "resume_id": session_id,
                "run_id": run_id,
                "adopted_session": adopted_session,
            },
            indent=1,
        ),
        encoding="utf-8",
    )


def _project_profile(
    settings: Settings, labels: list[str]
) -> tuple[str | None, ProjectRunnerProfile | None]:
    slug = label_value(labels, "project:")
    return slug, settings.projects.get(slug) if slug else None


def _profile_env(profile: ProjectRunnerProfile | None, cwd: Path) -> dict[str, str]:
    if profile is None:
        return {}
    pwd = str(cwd)
    return {
        key: value.replace("${PWD}", pwd).replace("$PWD", pwd) for key, value in profile.env.items()
    }


def _event(settings: Settings, event: str, report: RunReport, **data: Any) -> None:
    append_event(
        settings.state_dir(),
        make_event(
            event,
            source="cube",
            session=f"run-{report.run_id}",
            title=f"{report.role}{' ' + report.bead if report.bead else ''}: {report.state}"
            + (f": {report.error[:120]}" if report.error else ""),
            body=report.message or None,
            run_id=report.run_id,
            bead=report.bead,
            resume_id=report.session_id,
            data={"runner": report.runner, "model": report.model, **data},
        ),
    )


POLICY_BLOCK_RE = re.compile(
    r"(0 endpoints out of \d+ requested are available|guardrail restrictions and data policy|"
    r"Free model training violation)",
    re.IGNORECASE,
)


AUTH_BLOCK_RE = re.compile(
    r"(API key expired|Failed to authenticate|401 .*?(?:expired|invalid)|invalid_token|"
    r"No auth credentials found|User not found)",
    re.IGNORECASE,
)


def endpoint_auth_block(error: str | None) -> str | None:
    """The authentication reason when the provider rejected the key, else None."""
    if not error:
        return None
    match = AUTH_BLOCK_RE.search(error)
    return match.group(1) if match else None


def endpoint_policy_block(error: str | None) -> str | None:
    """The account-policy reason when a provider refused every endpoint, else None."""
    if not error:
        return None
    match = POLICY_BLOCK_RE.search(error)
    return match.group(1) if match else None


def derive_needs_tools(role: Role) -> bool:
    """Whether this role's work needs a tool-capable harness.

    A role with an allowlist, or one that may write in the workspace or drive a
    browser, cannot do its job through a plain chat completion (ADR-0016).
    """
    if role.permission_mode == "none":
        return False
    if role.permission_mode in {"workspace-write", "browser"}:
        return True
    return bool(role.allowed_tools)


def _roots_host(settings: Settings, agent_name: str | None) -> str:
    host = settings.host
    if agent_name:
        from cube.agents import AgentError, load_agent  # noqa: PLC0415

        try:
            host = load_agent(settings.root, agent_name, validate_role=False).host
        except (AgentError, OSError):
            pass
    return host


def _read_roots(settings: Settings, role: Role, agent_name: str | None) -> list[Path]:
    """The readable directories a `read_roots: host` role gets (ADR-0027)."""
    if role.read_roots != "host":
        return []
    return settings.readable_dirs(_roots_host(settings, agent_name))


def _deny_roots(settings: Settings, role: Role, agent_name: str | None) -> list[Path]:
    """The directories that stay closed for a `read_roots: host` role (deny wins)."""
    if role.read_roots != "host":
        return []
    return settings.unreadable_dirs(_roots_host(settings, agent_name))


def run_timeout_seconds(
    role_timeout: float, runner: str, local_minutes: int, runtime_minutes: int | None
) -> float:
    """Walltime for one run: the role's timeout, raised to the central local ceiling
    for any run on the group's own endpoint, then capped by an explicit allocation.

    The local floor used to apply to Hermes only. The laptop liaison runs
    ``claude@local`` on the same 33 tokens/s endpoint and hit the role's 900 s
    twice in a row with no result (r-20260912-0800-d7, r-20260912-0820-9b).
    """
    timeout = role_timeout
    if uses_local(runner):
        timeout = max(timeout, local_minutes * 60)
    if runtime_minutes is not None:
        timeout = min(timeout, runtime_minutes * 60)
    return timeout


def execute(
    settings: Settings,
    role_name: str,
    *,
    bead: str | None = None,
    runner_name: str | None = None,
    model: str | None = None,
    resume: bool = False,
    dry_run: bool = False,
    prompt_text: str | None = None,
    beads: Beads | None = None,
    runner: Runner | None = None,
    exec_fn: Exec | None = None,
    http_post: HttpPost | None = None,
    available: Any = None,
    now: datetime | None = None,
    tier_override: Tier | None = None,
    needs_tools: bool | None = None,
    agent: str | None = None,
    runtime_minutes: int | None = None,
    respect_project_runner: bool = True,
) -> RunReport:
    now = now or datetime.now(UTC)
    run_id = new_run_id(now)
    state_dir = settings.state_dir()
    report = RunReport(
        ok=False,
        run_id=run_id,
        role=role_name,
        bead=bead,
        state="error",
        started=now.isoformat(timespec="seconds"),
        tmux=None,
    )
    if runtime_minutes is not None and (
        isinstance(runtime_minutes, bool)
        or not isinstance(runtime_minutes, int)
        or not 1 <= runtime_minutes <= load_limits(settings).local_run_timeout_minutes
    ):
        report.state, report.error = "refused", "runtime allocation exceeds central limits"
        return report

    if (state_dir / "KILL").exists():
        report.state, report.error = "killed", "state/KILL present; nothing starts"
        audit(state_dir, "run.refused", run_id=run_id, role=role_name, bead=bead, reason="KILL")
        return report

    try:
        role = load_role(settings.root, role_name)
    except RoleError as exc:
        report.state, report.error = "refused", str(exc)
        return report
    report.warnings += role.lint_warnings
    if (
        settings.fleet_enabled
        and role.name not in {"sysadmin", "liaison"}
        and role.runtime != "python"
    ):
        role = role.model_copy(
            update={
                "permission_mode": "workspace-write",
                "allowed_tools": [
                    "Read",
                    "Grep",
                    "Glob",
                    "WebFetch",
                    "WebSearch",
                    "Bash",
                    "Edit",
                    "Write",
                ],
            }
        )
    if role.runtime == "python" and not runner_name:
        report.state, report.error = (
            "refused",
            f"role {role_name} is a python role, not a model run",
        )
        return report

    beads = beads or Beads(
        bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run, actor=f"cube/{role_name}"
    )
    if dry_run:
        beads.dry_run = True

    # context first: it tells us the bead's privacy and tier
    ctx: Context = build_context(settings, beads, role, bead, prompt_text=prompt_text)
    agent = agent or label_value(ctx.labels, "agent:")
    # Agent memory and source access can be more private than the work bead.
    # This floor also applies to inbox-only runs without a bead.
    if agent and (settings.root / "agents" / f"{agent}.yaml").is_file():
        from cube.agents import load_agent
        from cube.engine.context import PRIVACY_RANK

        agent_privacy = load_agent(settings.root, agent).privacy_default
        if PRIVACY_RANK[agent_privacy] > PRIVACY_RANK[ctx.privacy]:
            ctx.privacy = agent_privacy
    report.warnings += ctx.warnings
    project_slug, project_profile = _project_profile(settings, ctx.labels)
    report.project = project_slug
    if settings.fleet_enabled:
        settings.budget.daily_total_usd = load_limits(settings).daily_cost_usd
    budget_ledger = BudgetLedger(state_dir, settings)
    block = budget_block(settings, budget_ledger, ctx.labels, now=now)
    if block is not None:
        report.state = "refused"
        report.error = f"{block.reason} {block.target}: used ${block.used:.4f} of ${block.cap:.4f}"
        if settings.fleet_enabled:
            report.message = "queued until budget resets or Robert changes the central limit"
            return report
        report.message = "budget ceiling requires Robert review"
        alert_key = f"{now.date().isoformat()}:{block.reason}:{block.target}"
        if budget_ledger.claim_alert(alert_key, apply=not dry_run) and not dry_run:
            event = make_event(
                "attention",
                source="cube",
                session=f"run-{run_id}",
                title=f"{block.reason} ceiling reached for {block.target}",
                body=(
                    f"{block.reason} ceiling for {block.target}: "
                    f"used ${block.used:.4f}, cap ${block.cap:.4f}. No run was started."
                ),
                run_id=run_id,
                bead=bead,
                data={
                    "kind": "budget",
                    "needs": "robert",
                    "reason": block.reason,
                    "target": block.target,
                    "used": block.used,
                    "cap": block.cap,
                },
            )
            event["ts"] = now.isoformat(timespec="seconds")
            event["severity"] = "high"
            append_event(state_dir, event)
        audit(
            state_dir,
            "run.refused",
            run_id=run_id,
            role=role_name,
            bead=bead,
            reason=report.error,
        )
        return report
    checkout_root = settings.root
    if project_profile is not None:
        checkout_root = project_profile.checkout_path(settings.root)
        report.runner_profile = project_profile.effective(settings.root)
        report.pre_steps = list(project_profile.pre)
        if project_profile.remote:
            report.state = "refused"
            report.error = f"project {project_slug} is marked remote and cannot run on this host"
            return report
        if not checkout_root.is_dir():
            report.state = "refused"
            report.error = f"project {project_slug} checkout does not exist: {checkout_root}"
            return report
    privacy = ctx.privacy
    if not privacy_allowed(role, privacy):
        report.state = "refused"
        report.error = (
            f"bead privacy {privacy.value} exceeds role privacy_max {role.privacy_max.value}"
        )
        audit(
            state_dir, "run.refused", run_id=run_id, role=role_name, bead=bead, reason=report.error
        )
        return report

    wants_tools = derive_needs_tools(role) if needs_tools is None else needs_tools
    report.needs_tools = wants_tools
    try:
        tier = effective_tier(tier_override or role.tier, ctx.tier_label)
        route: Route = choose(
            settings,
            tier,
            privacy=privacy,
            requested_runner=(
                runner_name
                if runner_name == "stub"
                or project_profile is None
                or not respect_project_runner
                # Privacy wins over the project harness: a local-only run (the
                # laptop liaison on project:flopo) must not be refused because
                # the project prefers Codex (cube-in1, 2026-09-12).
                or privacy == Privacy.local_only
                else project_profile.runner
            ),
            requested_model=model or role.model,
            available=available,
            budget=budget_ledger,
            backoff=Backoff(state_dir),
            labels=ctx.labels,
            now=now,
            role=role.name,
            needs_tools=wants_tools,
            agent=agent,
        )
    except Refused as exc:
        report.state, report.error = "refused", str(exc)
        audit(state_dir, "run.refused", run_id=run_id, role=role_name, bead=bead, reason=str(exc))
        return report
    except Queued as exc:
        report.state, report.error = "queued", str(exc)
        report.message = "bead waits; no downgrade, no leak"
        # Robert, 2026-09-07: a queued bead is not an alarm; the marshal retries.
        _event(settings, "queued", report, tier=tier.value)
        audit(state_dir, "run.queued", run_id=run_id, role=role_name, bead=bead, reason=str(exc))
        return report
    report.runner, report.model = route.runner, route.model
    if role.name in {"sysadmin", "liaison"} and harness_of(route.runner) not in {"claude", "stub"}:
        report.state, report.error = (
            "refused",
            "restricted roles require the bounded Claude harness",
        )
        return report
    if (
        project_profile is not None
        and harness_of(route.runner) == "codex"
        and project_profile.sandbox == "danger-full-access"
        and not is_orchestration_host(settings)
    ):
        actual_host = os.uname().nodename
        report.state = "refused"
        report.error = (
            "sandbox danger-full-access is restricted to orchestration host "
            f"{settings.host}; current host is {actual_host}"
        )
        audit(
            state_dir,
            "run.refused",
            run_id=run_id,
            role=role_name,
            bead=bead,
            reason=report.error,
        )
        return report

    run_dir = run_dir_for(settings, run_id, now)
    resume_id = (
        stored_session(state_dir, bead, route.runner)
        if (resume and bead and role.name not in {"sysadmin", "liaison"})
        else None
    )
    worktree: Path | None = None
    timeout_seconds = run_timeout_seconds(
        role.timeout_seconds,
        route.runner,
        load_limits(settings).local_run_timeout_minutes,
        runtime_minutes,
    )
    lease = None
    if bead and not dry_run:
        try:
            lease = leases.acquire(
                state_dir,
                bead,
                run_id=run_id,
                role=role_name,
                ttl_seconds=timeout_seconds + 600,
                tier=tier.value,
                now=now,
            )
        except leases.LeaseHeld as exc:
            report.state, report.error = "leased", str(exc)
            audit(
                state_dir, "run.refused", run_id=run_id, role=role_name, bead=bead, reason=str(exc)
            )
            return report
        try:
            beads.claim(bead)
        except BeadsError as exc:
            report.warnings.append(f"bd claim failed: {exc}")
    use_worktree = (
        bead
        and worktrees.needs_worktree(role, ctx.labels)
        and (project_profile is None or project_profile.cwd == "worktree")
    )
    if bead and use_worktree:
        worktrees_dir = project_profile.worktrees_path(settings.root) if project_profile else None
        if dry_run:
            worktree = worktrees.worktree_path(checkout_root, bead, worktrees_dir)
        else:
            try:
                worktree = worktrees.create(
                    checkout_root,
                    bead,
                    exec_fn,
                    worktrees_dir=worktrees_dir,
                )
            except worktrees.WorktreeError as exc:
                if project_profile is None:
                    report.warnings.append(str(exc))
                    worktree = None
                else:
                    report.state, report.error = "error", str(exc)
                    if lease:
                        leases.release(state_dir, bead, run_id)
                    audit(
                        state_dir,
                        "run.refused",
                        run_id=run_id,
                        role=role_name,
                        bead=bead,
                        reason=report.error,
                    )
                    return report
        if worktree:
            ctx = build_context(
                settings, beads, role, bead, prompt_text=prompt_text, worktree=worktree
            )

    prompt = assemble_prompt(role, ctx.text, root=settings.root, skill_paths=ctx.skill_paths)
    session = f"{role_name}-{bead}" if bead else f"run-{run_id}"
    effective_cwd = worktree or checkout_root
    profile_env = _profile_env(project_profile, effective_cwd)
    profile_env["CUBE_PRIVACY"] = privacy.value
    if uses_local(route.runner) and harness_of(route.runner) == "hermes":
        profile_env["CUBE_LOCAL_MAX_TURNS"] = str(load_limits(settings).local_max_turns)
    if settings.fleet_enabled:
        identity = "ontologist" if agent == "ontology" else (agent or role.name)
        author = f"Robert Hoehndorf (BORG Cube Fleet: {identity})"
        profile_env.update(
            {
                "GIT_AUTHOR_NAME": author,
                "GIT_COMMITTER_NAME": author,
                "GIT_AUTHOR_EMAIL": "leechuck@leechuck.de",
                "GIT_COMMITTER_EMAIL": "leechuck@leechuck.de",
            }
        )
    if settings.fleet_enabled or role.name in {"liaison", "sysadmin"}:
        profile_env.update(
            {
                "CUBE_AGENT": agent or role.name,
                "CUBE_ROOT": str(settings.root),
                "CUBE_HOST": settings.host,
            }
        )
    if report.runner_profile is not None:
        report.runner_profile["effective_cwd"] = str(effective_cwd)
        report.runner_profile["env"] = profile_env
    rctx = RunContext(
        run_id=run_id,
        role=role,
        prompt=ctx.text or (prompt_text or f"Act as {role_name}."),
        system_prompt=assemble_prompt(role, "", root=settings.root, skill_paths=ctx.skill_paths),
        cwd=effective_cwd,
        run_dir=run_dir,
        state_dir=state_dir,
        model=route.model,
        profile=route.profile,
        open_data=open_endpoints_allowed(settings, role=role.name, agent=agent, labels=ctx.labels),
        read_roots=_read_roots(settings, role, agent),
        deny_roots=_deny_roots(settings, role, agent),
        sandbox=(
            project_profile.sandbox
            if project_profile and harness_of(route.runner) == "codex"
            else None
        ),
        resume_id=resume_id,
        bead=bead,
        session=session,
        timeout=timeout_seconds,
        schema=result_schema(),
        env=profile_env,
        dry_run=dry_run,
    )
    runner = runner or make_runner(route.runner, settings, exec_fn=exec_fn, http_post=http_post)
    report.command = runner.command(rctx)
    report.cwd = str(effective_cwd)
    report.session_id = resume_id
    report.run_dir = str(run_dir)
    report.log = str(run_dir / "stdout.jsonl")

    if dry_run:
        report.state, report.ok = "dry-run", True
        report.prompt = prompt
        profile_text = (
            f"; effective profile {json.dumps(report.runner_profile, sort_keys=True)}"
            if report.runner_profile
            else ""
        )
        report.message = (
            f"would run {route.runner} ({route.reason}){profile_text}; nothing executed"
        )
        if lease:
            leases.release(state_dir, bead or "", run_id)
        return report

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    meta: dict[str, Any] = {
        "run_id": run_id,
        "agent": agent,
        "role": role_name,
        "bead": bead,
        "project": project_slug,
        "tier": tier.value,
        "runner": route.runner,
        "model": route.model,
        "profile": route.profile,
        "route_reason": route.reason,
        "needs_tools": route.needs_tools,
        "privacy": privacy.value,
        "started": report.started,
        "pid": os.getpid(),
        "session": session,
        "resume_id": resume_id,
        "cwd": str(effective_cwd),
        "worktree": str(worktree) if worktree else None,
        "runner_profile": report.runner_profile,
        "pre_steps": report.pre_steps,
        "command": report.command,
        "state": "running",
        "timeout_seconds": timeout_seconds,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    _event(settings, "start", report, tier=tier.value)
    audit(state_dir, "run.start", run_id=run_id, role=role_name, bead=bead, runner=route.runner)

    pre_step_results: list[dict[str, Any]] = []
    pre_exec = exec_fn or default_exec
    for number, step in enumerate(report.pre_steps, start=1):
        pre_command = ["/bin/sh", "-lc", step]
        pre_result = pre_exec(
            pre_command,
            cwd=effective_cwd,
            env=rctx.process_env(),
            timeout=rctx.timeout,
            stdin_devnull=True,
        )
        pre_step_results.append(
            {
                "step": step,
                "command": pre_command,
                "exit_code": pre_result.returncode,
                "stdout": pre_result.stdout,
                "stderr": pre_result.stderr,
            }
        )
        if pre_result.returncode == 0:
            continue
        report.finished = datetime.now(UTC).isoformat(timespec="seconds")
        report.state = "error"
        report.error = (
            f"project {project_slug} pre-step {number}/{len(report.pre_steps)} failed "
            f"with exit {pre_result.returncode}: {step}"
        )
        report.message = (pre_result.stderr or pre_result.stdout).strip()[:500]
        meta.update(
            {
                "state": report.state,
                "finished": report.finished,
                "pre_step_results": pre_step_results,
                "error": report.error,
            }
        )
        (run_dir / "pre-steps.json").write_text(
            json.dumps(pre_step_results, indent=1), encoding="utf-8"
        )
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        if lease:
            leases.release(state_dir, bead or "", run_id)
        _event(
            settings,
            "error",
            report,
            pre_step=step,
            pre_step_number=number,
            exit_code=pre_result.returncode,
        )
        audit(
            state_dir,
            "run.finish",
            run_id=run_id,
            role=role_name,
            bead=bead,
            runner=route.runner,
            state=report.state,
            exit_code=pre_result.returncode,
            error=report.error,
        )
        return report
    if pre_step_results:
        meta["pre_step_results"] = pre_step_results
        (run_dir / "pre-steps.json").write_text(
            json.dumps(pre_step_results, indent=1), encoding="utf-8"
        )

    outcome: RunOutcome
    try:
        with local_inference_slot(settings, route.runner):
            outcome = runner.run(rctx)
    except LocalCapacityFull as exc:
        report.state, report.error = "queued", str(exc)
        report.finished = datetime.now(UTC).isoformat(timespec="seconds")
        meta.update(state=report.state, error=report.error, finished=report.finished)
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        if lease:
            leases.release(state_dir, bead or "", run_id)
        _event(settings, "queued", report, tier=tier.value)
        audit(state_dir, "run.queued", run_id=run_id, role=role_name, bead=bead, reason=str(exc))
        return report
    except Exception as exc:  # noqa: BLE001 - always release the lease and record the error
        outcome = RunOutcome("", None, None, {}, 1, str(exc), report.command, error=str(exc))
    finished = datetime.now(UTC)
    report.finished = finished.isoformat(timespec="seconds")
    report.session_id = outcome.session_id
    report.usage = outcome.usage

    _write_outputs(run_dir, outcome)
    record = budget_ledger.record(
        route.tier,
        runner=route.runner,
        model=route.model,
        usage=outcome.usage,
        cost_usd=outcome.cost_usd,
        labels=ctx.labels,
        now=now,
    )
    report.cost_usd = float(record["cost_usd"])
    report.equivalent_usd = float(record["equivalent_usd"])
    report.estimated = bool(record["estimated"])
    if record.get("warning"):
        report.warnings.append(str(record["warning"]))
    backoff = Backoff(state_dir)
    policy_block = endpoint_policy_block(outcome.error)
    auth_block = endpoint_auth_block(outcome.error)
    if auth_block and uses_openrouter(route.runner):
        # The OpenRouter key is expired or invalid: every OpenRouter entry in
        # every tier fails the same way. Disable them for an hour so nothing
        # keeps retrying (every run since 11:06 UTC on 2026-09-05 failed with
        # "401 API key expired") and tell Robert once per hour, not per run.
        tier_state = TierState(state_dir)
        first = True
        for tier_name, entries in settings.tiers.items():
            for entry in entries:
                if not uses_openrouter(entry.runner_name):
                    continue
                target = entry_target(entry.runner_name, entry.model)
                if tier_state.control(entry.runner_name, entry.model, now) is not None:
                    first = False
                tier_state.disable(
                    target,
                    until=now + timedelta(hours=1),
                    reason=f"openrouter auth: {auth_block}",
                )
                report.warnings.append(f"{tier_name}: {target} disabled for 1h: openrouter auth")
        if first:
            event = make_event(
                "attention",
                source="router",
                session="cube",
                title=(
                    f"OpenRouter rejects the API key ({auth_block}). Create a new key at "
                    "openrouter.ai and put it in .env on ws and the laptop; every "
                    "OpenRouter entry is disabled for an hour and retried after."
                ),
                data={"kind": "budget", "runner": route.runner, "model": route.model},
            )
            event["severity"] = "high"
            append_event(state_dir, event)
    elif policy_block and uses_openrouter(route.runner) and route.model:
        # The OpenRouter account's data policy excludes this model's endpoints
        # (free models that train on inputs). Retrying is pointless: disable the
        # entry for a day so the tier falls through, and tell Robert once.
        target = entry_target(route.runner, route.model)
        TierState(state_dir).disable(
            target,
            until=now + timedelta(hours=24),
            reason=f"openrouter data policy: {policy_block}",
        )
        report.warnings.append(f"{target} disabled for 24h: openrouter data policy")
        append_event(
            state_dir,
            make_event(
                "attention",
                source="router",
                session="cube",
                title=(
                    f"OpenRouter refuses {route.model}: account data policy excludes it. "
                    "Allow free endpoints in the OpenRouter privacy settings, or leave it "
                    "disabled (tier falls through to paid entries)."
                ),
                data={"kind": "budget", "runner": route.runner, "model": route.model},
            ),
        )
    elif outcome.rate_limited or (uses_local(route.runner) and outcome.exit_code == 124):
        timed_out = outcome.exit_code == 124
        until = backoff.record_failure(
            route.runner,
            model=route.model,
            error=outcome.error or "rate limited",
            now=finished if timed_out else now,
        )
        report.warnings.append(
            f"{route.runner} {'timed out' if timed_out else 'rate limited'}; "
            f"backing off until {until.isoformat()}"
        )
    elif outcome.exit_code == 0:
        backoff.record_success(route.runner, route.model)
    if bead and outcome.session_id:
        store_session(state_dir, bead, route.runner, outcome.session_id, run_id)
        try:
            beads.comment(
                bead, f"[{role_name} {run_id}] {route.runner} session {outcome.session_id}"
            )
        except BeadsError as exc:
            report.warnings.append(f"session comment failed: {exc}")

    applied: Applied | None = None
    if outcome.checkpoint_only and outcome.result is not None and not outcome.error:
        # No artifact, action, close, escalation or review verdict from malformed output.
        report.state, report.ok = "checkpoint", False
        report.message = outcome.result.summary
        report.warnings.append("Incomplete response preserved; task remains open")
        if bead:
            try:
                beads.comment(bead, f"[{role_name} {run_id}] {report.message}; see {run_dir}")
            except BeadsError as exc:
                report.warnings.append(f"checkpoint comment failed: {exc}")
    elif outcome.result is not None and not outcome.error:
        report.result = outcome.result.model_dump(mode="json")
        applied = apply_result(
            settings,
            beads,
            role,
            bead,
            ctx.bead,
            outcome.result,
            run_id=run_id,
            run_dir=run_dir,
            policy=ContactPolicy(settings.root / "contacts.yaml"),
            store=ApprovalStore(state_dir),
            privacy=privacy,
            now=finished,
            agent=agent,
        )
        report.applied = applied.as_dict()
        report.state, report.ok = "finished", True
        report.message = outcome.result.summary
    else:
        report.error = outcome.error or f"runner exited {outcome.exit_code}"
        report.state = "invalid" if outcome.exit_code == 0 and outcome.raw_text else "error"
        report.message = outcome.stderr.strip()[:500]
        if bead:
            try:
                beads.comment(
                    bead,
                    f"[{role_name} {run_id}] {report.state}: {report.error[:300]}; no state change "
                    f"(see {run_dir})",
                )
            except BeadsError as exc:
                report.warnings.append(f"error comment failed: {exc}")

    meta.update(
        {
            "state": report.state,
            "finished": report.finished,
            "exit_code": outcome.exit_code,
            "session_id": outcome.session_id,
            "usage": outcome.usage,
            "cost_usd": outcome.cost_usd,
            "billed_cost_usd": report.cost_usd,
            "equivalent_usd": report.equivalent_usd,
            "estimated": report.estimated,
            "rate_limited": outcome.rate_limited,
            "error": report.error,
            "applied": report.applied,
            "warnings": report.warnings,
        }
    )
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")

    if lease:
        leases.release(state_dir, bead or "", run_id)
    closed_now = list((applied.closed if applied else None) or [])
    if applied and applied.verdict:
        closed_now += list(applied.verdict.get("closed") or [])
    if (
        bead
        and not dry_run
        and bead not in closed_now
        and (
            report.state in {"error", "invalid", "checkpoint"}
            or (report.state == "finished" and not (applied and applied.review_bead))
        )
    ):
        # The claim made at dispatch would otherwise keep the bead out of bd ready
        # forever; give it back so the marshal or scheduler retries after the
        # runner backoff. A finished run that left its bead open (checkpoint,
        # goal with open children, close refused) is the same case: on
        # 2026-09-09 two such beads stayed in_progress for two days (cube-in1).
        # A bead handed to a reviewer keeps its claim; the review bead blocks it.
        # Only a bead still claimed is released: a verdict or pipeline step may
        # have closed it directly without listing it, and reopening a closed
        # review bead re-dispatched it in a loop (pipeline rehearsal).
        try:
            if str(beads.show(bead).get("status") or "") == "in_progress":
                beads.unclaim(bead)
        except BeadsError as exc:
            report.warnings.append(f"could not unclaim {bead}: {exc}")
    _event(
        settings,
        "checkpoint" if outcome.checkpoint_only else "finished" if report.ok else "error",
        report,
    )
    if applied and (applied.escalations or applied.approvals):
        _event(
            settings,
            "attention",
            report,
            escalations=applied.escalations,
            approvals=applied.approvals,
        )
    audit(
        state_dir,
        "run.finish",
        run_id=run_id,
        role=role_name,
        bead=bead,
        runner=route.runner,
        state=report.state,
        exit_code=outcome.exit_code,
        session_id=outcome.session_id,
        error=report.error,
    )
    return report


def _write_outputs(run_dir: Path, outcome: RunOutcome) -> None:
    raw = outcome.raw_text or ""
    is_jsonl = raw.lstrip().startswith("{") or raw.lstrip().startswith("[")
    (run_dir / ("stdout.jsonl" if is_jsonl else "stdout.txt")).write_text(raw, encoding="utf-8")
    if outcome.stderr:
        (run_dir / "stderr.txt").write_text(outcome.stderr, encoding="utf-8")
    if outcome.result is not None:
        (run_dir / "result.json").write_text(
            outcome.result.model_dump_json(indent=1), encoding="utf-8"
        )


def list_runs(settings: Settings, limit: int = 20) -> list[dict[str, Any]]:
    runs_root = settings.dirs["runs"]
    if not runs_root.exists():
        return []
    metas: list[dict[str, Any]] = []
    for meta_path in sorted(runs_root.glob("*/*/meta.json"), reverse=True):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            data["path"] = str(meta_path.parent)
            metas.append(data)
        if len(metas) >= limit:
            break
    return metas
