"""The bounded autonomous loop for a named standing agent.

This is intentionally a direct command patrol, not a model cron registry entry:
the systemd timer invokes ``cube agent workday`` and this module verifies resources
before every engine invocation.
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO, Any, Literal

from cube.agents import (
    Agent,
    AgentError,
    agent_context,
    append_journal,
    append_memory_note,
    append_reading,
    file_proposal,
    journal_entries,
    load_agent,
    mark_inbox_read,
    record_workday_start,
    resource_approval_bead,
    resource_usage,
    save_resource_usage,
    step_decision,
)
from cube.agents.coordinator import (
    IDLE_STEP_TITLE,
    management_context,
    management_due,
    record_management_review,
)
from cube.agents.sysadmin import SERVER_REVIEW_TITLE, server_review_context, write_infra_briefing
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine.context import bead_labels
from cube.engine.run import RunReport, execute
from cube.model import BeadHeader, Privacy, Provenance, Tier
from cube.notify import append_event, make_event
from cube.patrols.base import PatrolReport
from cube.router import record_agent_spend
from cube.runners import Runner


@dataclass
class WorkdayResult:
    agent: str
    dry_run: bool
    state: str = "finished"
    inbox_read: int = 0
    assigned_beads: list[str] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[str | None] = field(default_factory=list)
    journal: str | None = None
    resources: dict[str, Any] = field(default_factory=dict)
    goals_reviewed: int = 0
    monday_briefing: str | None = None
    answers: list[dict[str, Any]] = field(default_factory=list)
    # Robert, 2026-09-08 (ADR-0027): where each liaison request stood at the gate.
    gates: list[dict[str, Any]] = field(default_factory=list)
    pipeline_reviews: list[dict[str, Any]] = field(default_factory=list)
    management_review: str | None = None
    literature: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TOOL_STEPS = frozenset({IDLE_STEP_TITLE, SERVER_REVIEW_TITLE})

# Robert, 2026-09-07 (ADR-0025): a request the deterministic mail path cannot
# answer becomes a model step on the laptop. The step is the only place the
# answer leaves the laptop, so the prompt names the whole protocol.
LIAISON_LOOKUP_PROMPT = (
    "You are the laptop liaison answering one kind:request bead on Robert's laptop with "
    "a read-only lookup (ADR-0027). You may read only the readable directories listed "
    "below: the Read tool works inside them and nowhere else, and `cube lookup ls|find|"
    "grep|head|git-log <path>` lists, searches and quotes files under them (it refuses any "
    "other path). Never contact anyone, never change a file, never read mail, ~/pa, ~/org "
    "or memories in this run: if the answer needs them, comment that on the bead and stop; "
    "the request then waits for Robert's approval. Record the answer on the bead itself, "
    "because the shared Beads ledger is the only channel back to ws: run bd comment <id> "
    "with an 'answer:' block holding one source-backed statement per line (path:line or "
    "commit), then bd close <id> --reason 'Liaison recorded a source-backed answer.' when "
    "the request is answered in full. If a path is missing, comment the exact path you "
    "tried and leave the bead open. An artifact too large for a comment goes to ws with "
    "cube drop <id> <file> --apply; a git checkout with cube drop <id> <path> --repo --apply."
)
"""The autonomous liaison step: reads bounded to hosts.laptop.readable (ADR-0027)."""

LIAISON_REQUEST_PROMPT = (
    "You are the laptop liaison answering one kind:request bead on Robert's laptop. "
    "Robert approved this read (ADR-0027). "
    "Read only the local sources the request names (files under ~/pa, ~/org, "
    "~/Public/software, ~/Documents, notmuch mail through the personal-assistant and "
    "email-contacts skills). Never contact anyone and never change a file. "
    "Record the answer on the bead itself, because the shared Beads ledger is the only "
    "channel back to ws: run bd comment <id> with an 'answer:' block holding one "
    "source-backed statement per line (path:line, Message-ID, or commit), then bd close "
    "<id> --reason 'Liaison recorded a source-backed answer.' when the request is "
    "answered in full. If the answer would carry grades, contracts, visas, personnel or "
    "health details, do not write them anywhere: comment only that the answer must stay "
    "on the laptop and add the label needs:robert with bd label add <id> needs:robert. "
    "If a source is missing, comment the exact path or query you tried and leave the "
    "bead open. An artifact too large for a comment (a drafted report, a table, a PDF) "
    "goes to ws with cube drop <id> <file> --apply, which pushes it over ssh into the ws "
    "drop directory and comments the path and sha256 on the bead; never paste it. "
    "A git checkout the request names goes with cube drop <id> <path> --repo --apply "
    "(bundle of every ref, uncommitted patch, manifest), so a ws agent continues from "
    "the laptop's state."
)
"""The approved liaison step: every named local source, as before ADR-0027."""
LIAISON_LOOKUP_ROLE = "liaison"
LIAISON_APPROVED_ROLE = "liaison"


def _step_needs_tools(step: dict[str, Any]) -> bool | None:
    """True for a daily review, a step's own flag when set, else derive from the role."""
    if str(step.get("title") or "") in TOOL_STEPS:
        return True
    flag = step.get("needs_tools")
    return bool(flag) if isinstance(flag, bool) else None


def daily_review_title(agent: Agent) -> str | None:
    """The once a day review this agent owes, or None."""
    if agent.kind == "coordinator":
        return IDLE_STEP_TITLE
    if agent.role == "sysadmin":
        return SERVER_REVIEW_TITLE
    return None


def daily_review_context(agent: Agent, settings: Settings, ledger: Beads, *, now: datetime) -> str:
    if agent.kind == "coordinator":
        return management_context(settings, ledger, now=now)
    return server_review_context(settings, ledger, now=now)


BEAD_RUNS_FILE = "bead-runs.json"


def bead_runs_path(settings: Settings, agent: Agent | str) -> Path:
    name = agent if isinstance(agent, str) else agent.name
    return settings.state_dir() / "agents" / name / BEAD_RUNS_FILE


def bead_runs(settings: Settings, agent: Agent | str) -> dict[str, dict[str, Any]]:
    """``{bead_id: {"run_id", "ts"}}`` for the agent's last successful run per bead."""
    path = bead_runs_path(settings, agent)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def record_bead_run(
    settings: Settings,
    agent: Agent | str,
    bead_id: str,
    run_id: str,
    now: datetime,
    *,
    ok: bool = True,
    seen: str | None = None,
) -> None:
    """Remember the agent's last run on a bead.

    ``seen`` is the bead's ``updated_at`` read back after the run, so the run's
    own summary comment never counts as a change that brings the bead back.
    A failed run (``ok=False``) is remembered too: it is retried the next day,
    not the next hour.
    """
    path = bead_runs_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bead_runs(settings, agent)
    record = {"run_id": run_id, "ts": now.isoformat(timespec="seconds"), "ok": ok}
    if seen:
        record["seen"] = seen
    data[bead_id] = record
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def bead_seen_stamp(ledger: Beads, bead_id: str) -> str | None:
    """The bead's ``updated_at`` right now (None when the ledger cannot say)."""
    if not ledger.available():
        return None
    try:
        updated = _bead_updated(ledger.show(bead_id))
    except BeadsError:
        return None
    return updated.isoformat(timespec="seconds") if updated else None


def waiting_on_review(issue: dict[str, Any], issues: list[dict[str, Any]] | None = None) -> bool:
    """True when the bead's work is filed and a reviewer, Robert or a blocker owns the next move.

    A bead labelled ``review:pending`` or ``review:revise`` already has its result
    on the ledger; the review gate (another role) or its follow-up bead decides.
    A bead with an open ``blocks`` dependency is not ready for anyone.

    ``bd list --json`` records a dependency as ``{"type": "blocks" | "parent-child" |
    ..., "depends_on_id": ...}`` without a status. Reading that record as an open
    blocker made every child bead (its parent link) look blocked, so no twin, the
    liaison or any expert ever worked a child bead from its workday (cube-in1,
    2026-09-12). The blocker's status is looked up in ``issues`` when given;
    unknown status is not a block (``bd ready`` is the authority on that).
    """
    labels = bead_labels(issue)
    if "review:pending" in labels or "review:revise" in labels:
        return True
    by_id = {str(row.get("id") or ""): row for row in issues or []}
    for dep in issue.get("dependencies") or []:
        if not isinstance(dep, dict):
            continue
        kind = dep.get("dependency_type") or dep.get("type") or "blocks"
        if kind != "blocks":
            continue
        status = dep.get("status")
        if status is None:
            target = by_id.get(str(dep.get("depends_on_id") or dep.get("id") or ""))
            if target is None:
                continue
            status = target.get("status")
        if str(status or "open") not in {"closed", "done"}:
            return True
    return False


def _bead_updated(issue: dict[str, Any]) -> datetime | None:
    for key in ("updated_at", "updated"):
        raw = issue.get(key)
        if isinstance(raw, str) and raw:
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


def worked_since_update(
    done: dict[str, dict[str, str]], issue: dict[str, Any], now: datetime
) -> bool:
    """True when the agent already ran this bead and nobody changed it since.

    A finished run leaves the bead with the review gate: it comes back only when
    someone else comments, labels or answers it (``updated_at`` after the stamp
    the patrol read back after its own run). A failed run is retried the next
    day. Without a usable ``updated_at`` the rule is one run per bead.
    """
    record = done.get(str(issue.get("id") or ""))
    if not record:
        return False
    try:
        ran = datetime.fromisoformat(str(record.get("ts")))
    except ValueError:
        return False
    if ran.tzinfo is None:
        ran = ran.replace(tzinfo=UTC)
    ok = record.get("ok", True) is not False
    if not ok and ran.date() != now.date():
        # A failed run is retried the next day; a finished one waits for a change.
        return False
    seen = ran
    raw_seen = record.get("seen")
    if isinstance(raw_seen, str) and raw_seen:
        try:
            seen = datetime.fromisoformat(raw_seen)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=UTC)
        except ValueError:
            seen = ran
    updated = _bead_updated(issue)
    return updated is None or updated <= max(ran, seen)


def _step_from_bead(bead: dict[str, Any]) -> dict[str, Any]:
    """Read a small declared ``needs`` mapping from a bead, never infer resources from prose."""
    raw = bead.get("needs")
    needs = dict(raw) if isinstance(raw, dict) else {"compute_target": "ws"}
    return {
        "title": str(bead.get("title") or bead.get("id") or "assigned work"),
        "needs": needs,
        "bead": bead.get("id"),
    }


def _request_step(bead: dict[str, Any], deferred: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A liaison request the deterministic path deferred carries the protocol prompt.

    Robert, 2026-09-08 (ADR-0027): a readable lookup runs as the `liaison` role with
    reads bounded to the readable directories; an approved read of anything else
    runs as the `senior` role with the full protocol prompt.
    """
    step = _step_from_bead(bead)
    entry = deferred.get(str(bead.get("id") or ""))
    if entry is None:
        return step
    if entry.get("scope") == "readable":
        roots = ", ".join(str(root) for root in entry.get("roots") or []) or "none"
        step["prompt_text"] = LIAISON_LOOKUP_PROMPT + f"\n\nReadable directories: {roots}."
        step["role"] = LIAISON_LOOKUP_ROLE
    else:
        step["prompt_text"] = (
            LIAISON_REQUEST_PROMPT
            + f"\n\nThe deterministic mail path did not answer this request: {entry.get('reason')}."
        )
        step["role"] = LIAISON_APPROVED_ROLE
    step["needs_tools"] = True
    return step


def _inbox_steps(
    inbox: list[dict[str, Any]], assigned: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Steps for an inbox-only pass: answer the unread mail, then the beads it names."""
    steps: list[dict[str, Any]] = []
    if inbox:
        steps.append(
            {
                "title": f"answer {len(inbox)} unread inbox message(s)",
                "needs": {"compute_target": "ws"},
            }
        )
    text = " ".join(str(row.get("text") or "") for row in inbox)
    for issue in assigned:
        bead_id = str(issue.get("id") or "")
        if bead_id and bead_id in text:
            steps.append(_step_from_bead(issue))
    return steps


def _now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _digest_like(artifact: dict[str, Any]) -> bool:
    kind = str(artifact.get("kind") or "").lower()
    name = Path(str(artifact.get("path") or "")).name.lower()
    return (
        kind == "literature-digest"
        or ("digest" in kind or "digest" in name)
        and (name.endswith(".json") or not name)
    )


def digest_artifact(runs: list[dict[str, Any]], root: Path | None = None) -> str | None:
    """The content of the last literature digest a run returned.

    Inline ``content`` wins. A Hermes worker with file tools saves the digest to
    disk instead (``runs/<run>/literature-digest.json`` twice on 2026-09-12) and
    returns only the path; that file is read when ``root`` is given, so the
    briefing gets written and the candidates count as summarised.
    """
    for run in reversed(runs):
        result = run.get("result")
        if not isinstance(result, dict):
            continue
        run_dir = Path(str(run.get("run_dir") or "")) if run.get("run_dir") else None
        for artifact in result.get("artifacts") or []:
            if not isinstance(artifact, dict) or not _digest_like(artifact):
                continue
            content = artifact.get("content")
            if content:
                return str(content)
            raw = str(artifact.get("path") or "")
            if not raw or root is None:
                continue
            candidates = [Path(raw)] if Path(raw).is_absolute() else [root / raw]
            if run_dir is not None and not Path(raw).is_absolute():
                candidates.append(run_dir / Path(raw).name)
            for path in candidates:
                try:
                    if path.is_file() and path.resolve().is_relative_to(root.resolve()):
                        return path.read_text(encoding="utf-8")
                except OSError:
                    continue
    return None


def apply_literature_result(
    settings: Settings,
    ledger: Beads,
    result: WorkdayResult,
    candidates: list[dict[str, Any]],
    day: date,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Validate the digest artifact, write the briefing, and file the day's reading list."""
    from cube import literature as lit  # noqa: PLC0415

    out: dict[str, Any] = {
        "date": day.isoformat(),
        "candidates": len(candidates),
        "entries": 0,
        "errors": [],
        "digest": None,
        "bead": None,
        "reading": 0,
    }
    content = digest_artifact(result.runs, settings.root)
    if content is None:
        out["errors"] = ["no literature-digest artifact returned"]
        result.blocked.append({"step": "literature digest", "reason": out["errors"][0]})
        return out
    try:
        artifact = lit.parse_artifact(content)
        entries, errors = lit.validate_digest(
            artifact, candidates, limit=settings.literature_watch.max_summaries_per_day
        )
    except lit.LiteratureError as exc:
        out["errors"] = [str(exc)]
        result.blocked.append({"step": "literature digest", "reason": str(exc)})
        return out
    out["entries"] = len(entries)
    out["errors"] = errors
    md_path, json_path = lit.digest_paths(settings, day)
    out["digest"] = str(md_path)
    if dry_run:
        return out
    counts = {"candidates": len(candidates), "entries": len(entries), "rejected": len(errors)}
    lit.write_digest(settings, day, entries, counts)
    lit.mark_summarised(settings, day, [str(row.get("id")) for row in candidates])
    context = lit.build_context(settings, beads=ledger)
    out["bead"] = lit.reading_list_bead(
        ledger,
        day,
        entries,
        digest_json=json_path,
        attention=lit.needs_robert(entries, context, day),
    )
    records = lit.reading_records(entries, lit.agents_by_topic(settings.root))
    if settings.fleet_enabled:
        from cube.research import literature_handoffs

        literature_handoffs(settings, records)
    for record in records:
        try:
            append_reading(
                settings.root,
                load_agent(settings.root, record["agent"]),
                identifier=record["identifier"],
                note=record["note"],
                source=record["source"],
            )
            out["reading"] += 1
        except (AgentError, OSError) as exc:
            result.blocked.append({"step": f"reading {record['agent']}", "reason": str(exc)})
    return out


def workday_lock_path(settings: Settings, agent_name: str) -> Path:
    return settings.state_dir() / "agents" / agent_name / "workday.lock"


def workday_lock(settings: Settings, agent_name: str) -> IO[str] | None:
    """Take the agent's workday lock without waiting; None when another run holds it."""
    path = workday_lock_path(settings, agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class AgentWorkdayPatrol:
    """Run at most the declared bounded steps for one agent."""

    name = "agent_workday"

    def __init__(
        self,
        name: str,
        *,
        steps: list[dict[str, Any]] | None = None,
        runner: Runner | None = None,
        runner_name: str | None = None,
        now: datetime | None = None,
        bead: str | None = None,
        inbox_only: bool = False,
    ):
        self.agent_name = name
        self.steps = steps
        self.runner = runner
        self.runner_name = runner_name
        self.now = now
        self.bead = bead
        self.inbox_only = inbox_only

    def run(
        self,
        settings: Settings,
        today: date | None = None,
        dry_run: bool = True,
        *,
        beads: Beads | None = None,
    ) -> WorkdayResult:
        now = _now(self.now)
        agent = load_agent(settings.root, self.agent_name)
        if (settings.state_dir() / "KILL").exists():
            return WorkdayResult(agent.name, dry_run, state="killed")
        if (settings.state_dir() / "agents" / agent.name / "PAUSED").exists():
            return WorkdayResult(agent.name, dry_run, state="paused")
        # One workday per agent at a time: the hourly timer and a manual
        # `cube agent workday NAME --now` must never run the same review twice.
        lock = workday_lock(settings, agent.name)
        if lock is None:
            return WorkdayResult(agent.name, dry_run, state="busy")
        try:
            return self._run_locked(settings, agent, today, dry_run, beads=beads, now=now)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    def _run_locked(
        self,
        settings: Settings,
        agent: Agent,
        today: date | None,
        dry_run: bool,
        *,
        beads: Beads | None,
        now: datetime,
    ) -> WorkdayResult:
        ledger = beads or Beads(
            bin=settings.beads.bin,
            cwd=settings.root,
            dry_run=dry_run,
            actor=f"cube/agent-{agent.name}",
        )
        if dry_run:
            ledger.dry_run = True
        result = WorkdayResult(
            agent.name, dry_run, resources=resource_usage(settings, agent, now=now)
        )
        inbox = __import__("cube.agents", fromlist=["read_inbox"]).read_inbox(
            settings.root, agent, unread_only=True
        )
        result.inbox_read = len(inbox)
        issues: list[dict[str, Any]] = []
        if ledger.available():
            try:
                issues = ledger.list_issues("--all")
            except BeadsError:
                issues = []
        assigned = [
            issue
            for issue in issues
            if f"agent:{agent.name}" in bead_labels(issue)
            and str(issue.get("status", "open")) not in {"closed", "done"}
            # A bead waiting on Robert (the agent's own proposal or approval
            # request) is not work for the agent; it must not become a step.
            and "needs:robert" not in bead_labels(issue)
            # Filed work waits for its reviewer (another role) or its blocker;
            # the hourly tick never plays it again (cube-1sbx).
            and not waiting_on_review(issue, issues)
            and (self.bead is None or str(issue.get("id") or "") == self.bead)
        ]
        result.assigned_beads = [str(issue.get("id")) for issue in assigned if issue.get("id")]
        handled_requests: set[str] = set()
        # A request the deterministic path could not answer, with the reason the
        # model step gets told (ADR-0025); it is a run, not a blocked entry.
        deferred_requests: dict[str, dict[str, Any]] = {}
        if agent.name == "liaison" and not self.inbox_only:
            from cube.agents.liaison import (  # noqa: PLC0415
                SCOPE_MAIL,
                SCOPE_READABLE,
                LiaisonError,
                answer_mail_request,
                gate_request,
            )

            for issue in assigned[: agent.workday.max_runs]:
                labels = bead_labels(issue)
                if "kind:request" not in labels:
                    continue
                bead_id = str(issue.get("id") or "")
                # Robert, 2026-09-08 (ADR-0027): a read beyond the readable
                # directories waits for his yes; the gate labels it once and the
                # decisions patrol on ws announces it.
                gate = gate_request(settings, ledger, issue, dry_run=dry_run)
                result.gates.append(gate)
                scope = gate["scope"]
                if gate.get("waiting"):
                    handled_requests.add(bead_id)
                    result.blocked.append(
                        {
                            "step": str(issue.get("title") or bead_id),
                            "bead": bead_id,
                            "reason": (
                                "waits for Robert's approval of a laptop read: "
                                + str(scope["reason"])
                            ),
                        }
                    )
                    continue
                if scope["scope"] == SCOPE_READABLE or settings.fleet_enabled:
                    deferred_requests[bead_id] = {"scope": SCOPE_READABLE, "roots": scope["roots"]}
                    continue
                if scope["scope"] != SCOPE_MAIL:
                    deferred_requests[bead_id] = {
                        "scope": scope["scope"],
                        "reason": "approved by Robert; not a mail request",
                    }
                    continue
                try:
                    answer = answer_mail_request(settings, ledger, issue, dry_run=dry_run)
                    result.answers.append(answer.as_dict())
                    result.resources["runs"] += 1
                    handled_requests.add(bead_id)
                except LiaisonError as exc:
                    deferred_requests[bead_id] = {"scope": SCOPE_MAIL, "reason": str(exc)}
        remaining = [
            issue for issue in assigned if str(issue.get("id") or "") not in handled_requests
        ]
        remaining_runs = max(0, agent.workday.max_runs - len(handled_requests))
        literature_day = now.date()
        literature_pending: list[dict[str, Any]] = []
        if self.steps is not None:
            steps = list(self.steps)
        elif agent.name == "literature" and not self.inbox_only:
            # The literature agent has one job and only when the deterministic
            # patrol left unsummarised candidates for today.
            from cube.literature import build_context, pending_candidates, summary_prompt

            literature_pending = pending_candidates(settings, literature_day)
            if literature_pending:
                context = build_context(settings, beads=ledger)
                steps = [
                    {
                        "title": (
                            f"summarise {len(literature_pending)} new preprint(s) for the group"
                        ),
                        "needs": {"compute_target": "ws"},
                        "prompt_text": summary_prompt(settings, literature_pending, context),
                        # A digest is one JSON answer; the bulk tier's chat models do it.
                        "needs_tools": False,
                    }
                ]
            else:
                steps = []
        elif self.inbox_only:
            # An inbox pass answers Robert first and then only the assigned beads
            # his unread messages actually name.  No default reading step.
            steps = _inbox_steps(inbox, remaining)
        else:
            # A bead the agent already worked today is not re-run every hour;
            # it comes back when someone changes it (comment, label, answer).
            done = bead_runs(settings, agent)
            steps = [
                _request_step(issue, deferred_requests)
                for issue in remaining
                if not worked_since_update(done, issue, now)
            ]
        management_step = False
        daily_title = daily_review_title(agent)
        if (
            daily_title
            and not self.inbox_only
            and agent.workday.max_runs
            and self.steps is None
            and management_due(settings, agent, now)
        ):
            # Once a day: the coordinator reviews the whole group (projects,
            # deadlines, goals, who is idle) and the sysadmin reviews the servers.
            steps.append(
                {
                    "title": daily_title,
                    "needs": {"compute_target": "ws"},
                    "prompt_text": daily_review_context(agent, settings, ledger, now=now),
                }
            )
            management_step = True
        if (
            not steps
            and not handled_requests
            and not self.inbox_only
            and agent.name != "literature"
            and agent.workday.max_runs
            and (inbox or not agent.workday.hourly)
        ):
            steps = [
                {
                    "title": "source-backed reading and workday planning",
                    "needs": {"compute_target": "ws"},
                }
            ]
        steps = steps[: min(remaining_runs, agent.workday.runs_per_tick)]
        if settings.fleet_enabled and not steps and not handled_requests and not self.inbox_only:
            from cube.research import exploration_step, is_researcher
            from cube.resources import reserve_research_run

            if is_researcher(agent):
                try:
                    reserve_research_run(
                        settings, agent.name, autonomous=True, dry_run=True, now=now
                    )
                    step = exploration_step(settings, ledger, agent, issues, now, dry_run=dry_run)
                    if step:
                        steps = [step]
                except ValueError as exc:
                    result.blocked.append({"step": "research budget", "reason": str(exc)})
        if self.inbox_only and not steps:
            result.state = "idle"
        if agent.workday.hourly and not steps and not inbox and not handled_requests:
            # A 24/7 agent with nothing waiting stays idle; the tick costs no tokens.
            result.state = "idle"
        for step in steps:
            research_reservation = None
            if settings.fleet_enabled:
                from cube.research import is_researcher
                from cube.resources import reserve_research_run

                if is_researcher(agent):
                    try:
                        research_reservation = reserve_research_run(
                            settings,
                            agent.name,
                            autonomous=bool(step.get("autonomous")),
                            dry_run=dry_run,
                            now=now,
                        )
                    except ValueError as exc:
                        result.blocked.append({"step": "research budget", "reason": str(exc)})
                        continue
            needs = step.get("needs")
            needs = dict(needs) if isinstance(needs, dict) else {}
            decision = step_decision(
                agent,
                needs,
                result.resources,
                step_title=str(step.get("title") or ""),
                consume=not dry_run,
                settings=settings,
            )
            if not decision.allowed:
                approval = resource_approval_bead(ledger, agent, step, decision, now=now)
                result.blocked.append(
                    {
                        "step": step.get("title"),
                        "decision": decision.as_dict(),
                        "approval_bead": approval,
                    }
                )
                continue
            # The engine remains the only model execution path.  A node005 step asks
            # the local tier via the router; no raw ssh ever appears here.
            pipeline_context = ""
            if step.get("bead"):
                try:
                    pipeline_bead = ledger.show(str(step["bead"]))
                    labels = bead_labels(pipeline_bead)
                    epic_id = next(
                        (label.split(":", 1)[1] for label in labels if label.startswith("goal:")),
                        None,
                    )
                    if epic_id and any(label.startswith("pipeline-stage:") for label in labels):
                        from cube.pipeline import stage_prompt  # noqa: PLC0415

                        pipeline_context = "\n\n## Pipeline stage\n\n" + stage_prompt(
                            settings,
                            ledger.show(epic_id),
                            pipeline_bead,
                            beads=ledger,
                        )
                except (BeadsError, ValueError):
                    pipeline_context = ""
            report: RunReport = execute(
                settings,
                str(step.get("role") or agent.role),
                agent=agent.name,
                bead=str(step["bead"]) if step.get("bead") else None,
                runner_name=(
                    self.runner_name or (self.runner.name if self.runner else None) or agent.runner
                ),
                model=agent.model,
                runner=self.runner,
                dry_run=dry_run,
                prompt_text=(
                    agent_context(settings, agent)
                    + "\n\n## Workday step\n\n"
                    + (str(step["prompt_text"]) + "\n\n" if step.get("prompt_text") else "")
                    + (
                        "Answer Robert's unread inbox before other work. A message from robert "
                        "arrived through Mattermost (hermes-ws): reply to it with "
                        'cube agent tell hermes-ws "<reply>" --from coordinator, short and '
                        "with the bead ids you filed. When a request needs "
                        "Robert's mail, files, memories, or calendar, file a kind:request for "
                        "the laptop liaison with cube request liaison, host:laptop, and a due "
                        "date, then wait for its answer bead instead of guessing. "
                        if agent.kind == "coordinator"
                        else ""
                    )
                    + f"Standing-agent workday step: {step.get('title', 'work')}. "
                    + f"Declared needs: {needs}. Keep results source-backed."
                    + pipeline_context
                ),
                now=now,
                tier_override=Tier.local if decision.resource_class == "gpu" else None,
                # A daily review plans and then does the work: it needs a harness
                # that can run cube, bd and shell commands, never a chat completion.
                needs_tools=_step_needs_tools(step),
            )
            result.runs.append(report.as_dict())
            if research_reservation and not dry_run and report.state == "queued":
                from cube.resources import cancel_unstarted_research

                cancel_unstarted_research(
                    settings, research_reservation["id"], report.error or "queued before inference"
                )
            if settings.fleet_enabled and not dry_run:
                from cube.fleet_github import queue_record

                payload = report.result or {}
                # Private laptop material never enters the publication queue.
                source_privacy = "local-only" if agent.name == "liaison" else agent.privacy_default
                if step.get("bead"):
                    source_bead = ledger.show(str(step["bead"]))
                    source_header = BeadHeader.parse(source_bead.get("description") or "")
                    if "privacy:local-only" in bead_labels(source_bead) or (
                        source_header and source_header.privacy == Privacy.local_only
                    ):
                        source_privacy = "local-only"
                try:
                    queue_record(
                        settings,
                        agent.name,
                        report.run_id,
                        str(payload.get("summary") or report.error or report.state),
                        privacy=str(source_privacy),
                        sources=[f"runs/{report.run_id}"],
                        dry_run=False,
                    )
                except ValueError:
                    queue_record(
                        settings,
                        agent.name,
                        report.run_id,
                        "Run recorded. Details withheld by publication screening.",
                        privacy="local-only",
                        dry_run=False,
                    )
            if report.ok and management_step and step.get("title") == daily_title:
                if not dry_run:
                    record_management_review(settings, agent, now)
                    if agent.role == "sysadmin":
                        # Robert, 2026-09-07: the review is hermes-ws's input for the
                        # daily ~infra-alerts report (ADR-0020).
                        write_infra_briefing(settings, report, now=now)
                result.management_review = daily_title
            if report.ok:
                result.resources["runs"] += 1
                result.resources["gpu_hours"] += decision.gpu_hours
                result.resources["spend_usd"] += decision.spend_usd
            else:
                result.blocked.append(
                    {"step": step.get("title"), "reason": report.error or report.state}
                )
            if step.get("bead") and not dry_run:
                # Read the bead back after the run so its own summary comment is
                # the stamp, not a change; a failed run is remembered for a day.
                bead_id = str(step["bead"])
                record_bead_run(
                    settings,
                    agent,
                    bead_id,
                    report.run_id,
                    now,
                    ok=report.ok,
                    seen=bead_seen_stamp(ledger, bead_id),
                )
        if agent.name == "literature" and literature_pending:
            result.literature = apply_literature_result(
                settings, ledger, result, literature_pending, literature_day, dry_run=dry_run
            )
        # References must be supplied as structured, source-backed records.  This keeps
        # model prose and unverified reading-list strings out of reading.md.
        if not dry_run:
            for step in steps:
                refs = step.get("reading", []) if isinstance(step.get("reading"), list) else []
                for ref in refs:
                    if isinstance(ref, dict):
                        try:
                            append_reading(
                                settings.root,
                                agent,
                                identifier=str(ref.get("identifier") or ""),
                                note=str(ref.get("note") or ""),
                                source=str(ref.get("source") or ""),
                            )
                        except AgentError as exc:
                            result.blocked.append({"step": step.get("title"), "reason": str(exc)})
                memory_targets: tuple[tuple[str, Literal["ideas.md", "open-questions.md"]], ...] = (
                    ("ideas", "ideas.md"),
                    ("questions", "open-questions.md"),
                )
                for field, filename in memory_targets:
                    notes = step.get(field, []) if isinstance(step.get(field), list) else []
                    for note in notes:
                        if isinstance(note, dict):
                            try:
                                append_memory_note(
                                    settings.root,
                                    agent,
                                    filename=filename,
                                    text=str(note.get("text") or ""),
                                    source=str(note.get("source") or ""),
                                )
                            except AgentError as exc:
                                result.blocked.append(
                                    {"step": step.get("title"), "reason": str(exc)}
                                )
        for step in steps:
            proposal = step.get("proposal")
            if isinstance(proposal, dict):
                try:
                    result.proposals.append(file_proposal(ledger, agent, proposal, now=now))
                except AgentError as exc:
                    result.blocked.append({"step": step.get("title"), "reason": str(exc)})
        if agent.kind == "coordinator" and not self.inbox_only:
            try:
                from cube.pipeline import review_open_pipelines  # noqa: PLC0415

                result.pipeline_reviews = review_open_pipelines(
                    settings, ledger, now=now, dry_run=dry_run
                )
            except Exception as exc:  # noqa: BLE001 - management must not stop the workday
                result.blocked.append({"step": "pipeline review", "reason": str(exc)})
            try:
                from cube.goals import read_goal_ledger

                goals, _ready, _blocked = read_goal_ledger(ledger)
                result.goals_reviewed = sum("kind:goal" in bead_labels(goal) for goal in goals)
                review_xid = f"agent:{agent.name}:goal-review:{now.date().isoformat()}"
                # One proposal per day: the hourly tick must not file it again
                # (fifteen copies reached Robert on 2026-09-04 and 2026-09-05).
                already_filed = bool(ledger.find_by_xid(review_xid)) if not dry_run else False
                if not dry_run and result.goals_reviewed and not already_filed:
                    goal_ids = [
                        str(goal.get("id")) for goal in goals if "kind:goal" in bead_labels(goal)
                    ]
                    review_id = ledger.create(
                        "Review coordinator goal decomposition and assignments",
                        header=BeadHeader(
                            xid=review_xid,
                            provenance=[
                                Provenance(source="cube goals --json", locator=goal_id)
                                for goal_id in goal_ids
                            ],
                            privacy=Privacy.internal,
                        ),
                        body=(
                            "Rationale: Coordinator review of current goals.\n"
                            "Resources requested: Robert review only.\n"
                            "Expected outcome: Reviewable decomposition and assignment "
                            "suggestions.\n"
                            "Kill criterion: Do not apply any assignment or decomposition "
                            "without Robert approval."
                        ),
                        labels=[
                            "kind:proposal",
                            "needs:robert",
                            "review-item",
                            f"agent:{agent.name}",
                        ],
                        acceptance="Robert reviews the proposed decomposition and assignments.",
                    )
                    result.proposals.append(review_id)
            except Exception as exc:  # noqa: BLE001 - a goals view must not stop the workday
                result.blocked.append({"step": "goals review", "reason": str(exc)})
            result.monday_briefing = f"agents/{agent.name}/memory/monday-briefing.md"
            if not dry_run:
                path = settings.root / result.monday_briefing
                # A fresh checkout or a reset fleet has no memory directory yet
                # (cube-goal-coordinator failed on this on 2026-09-09, cube-0rp).
                path.parent.mkdir(parents=True, exist_ok=True)
                pipeline_lines = (
                    "\n".join(
                        f"- Pipeline {row['epic']}: {row['stage']}; {row['next']}"
                        for row in result.pipeline_reviews
                    )
                    or "- No open research pipelines."
                )
                path.write_text(
                    f"# Monday briefing draft\n\nGenerated {now.isoformat(timespec='seconds')}.\n\n"
                    f"Goals reviewed: {result.goals_reviewed}.\n"
                    "Journal entries considered: "
                    f"{len(journal_entries(settings.root, agent, 5))}.\n"
                    "\n## Research pipelines\n\n"
                    f"{pipeline_lines}\n\n"
                    "Proposals require Robert review.\n",
                    encoding="utf-8",
                )
        if not dry_run:
            record_workday_start(settings, agent, now)
        if not dry_run and result.state != "idle":
            append_event(
                settings.state_dir(),
                make_event(
                    "start",
                    source="agent",
                    session=f"agent-{agent.name}",
                    title=f"{agent.title} workday started",
                ),
            )
            sources = [
                f"agents/{agent.name}.yaml",
                *[f"bead:{bid}" for bid in result.assigned_beads],
            ]
            append_journal(
                settings.root,
                agent,
                body=(
                    f"Workday processed {result.inbox_read} inbox message(s), "
                    f"ran {result.resources['runs']} "
                    f"step(s), and blocked {len(result.blocked)} step(s)."
                ),
                sources=sources,
                now=now,
            )
            # A message counts as read only once a step actually ran for it.  A
            # failed run (model outage, exhausted subscription) leaves the inbox
            # unread so the next workday or a manual `cube agent workday` retries.
            acted = bool(result.answers) or any(bool(run.get("ok")) for run in result.runs)
            if acted or not inbox:
                mark_inbox_read(settings.root, agent, [str(row["id"]) for row in inbox])
            else:
                result.blocked.append(
                    {
                        "step": "inbox",
                        "reason": f"{len(inbox)} inbox message(s) left unread: no step succeeded",
                    }
                )
            record_agent_spend(settings, agent.name, result, now=now)
            save_resource_usage(settings, agent, result.resources)
            if result.resources["runs"]:
                ledger.remember(
                    f"agent:{agent.name}: workday {now.date().isoformat()} "
                    f"ran {result.resources['runs']} source-backed step(s)",
                    key=f"agent:{agent.name}:{now.date().isoformat()}",
                )
            result.journal = f"agents/{agent.name}/memory/journal.md"
            append_event(
                settings.state_dir(),
                make_event(
                    "finished",
                    source="agent",
                    session=f"agent-{agent.name}",
                    title=f"{agent.title} workday finished",
                    data=result.as_dict(),
                ),
            )
            # Robert, 2026-09-07: blocked steps are in the finished event's data and
            # the journal; no hourly attention event for them.
        return result

    def patrol_report(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        """Adapter for callers that expect the general patrol report shape."""
        result = self.run(settings, today, dry_run, beads=beads)
        report = PatrolReport(self.name, today, dry_run, summary=result.state)
        report.data["agent_workday"] = result.as_dict()
        return report
