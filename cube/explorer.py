"""Read-only fleet projections and bounded, asynchronous workday requests."""

from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.agents import append_inbox, load_agent, load_all_agents
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.disclosure import release_text
from cube.engine.context import bead_labels
from cube.model import BeadHeader, Privacy

MAX_FILE = 8_000_000
MAX_RUNS = 10000
MEMORIES = ("journal.md", "reading.md", "ideas.md", "open-questions.md")
NUMBERS = (
    "run_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost_usd",
    "equivalent_usd",
    "duration_seconds",
    "usage_missing",
)


def read_text(path: Path, root: Path, limit: int = MAX_FILE) -> str:
    """Never traverse symlinks out of the owned data tree or read unbounded files."""
    try:
        if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def read_object(path: Path, root: Path) -> dict[str, Any]:
    try:
        data = json.loads(read_text(path, root))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def event_lines(path: Path, root: Path) -> Iterator[str]:
    """Stream bounded JSONL records, including logs larger than one JSON document."""
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return
        with path.open("rb") as stream:
            size = path.stat().st_size
            if size > 64_000_000:
                stream.seek(size - 64_000_000)
                stream.readline(MAX_FILE + 1)
            while chunk := stream.readline(MAX_FILE + 1):
                if len(chunk) > MAX_FILE:
                    while chunk and not chunk.endswith(b"\n"):
                        chunk = stream.readline(MAX_FILE + 1)
                    continue
                try:
                    yield chunk.decode("utf-8")
                except UnicodeError:
                    continue
    except OSError:
        return


def stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def number(value: Any) -> float:
    if isinstance(value, bool):
        return 0
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else 0
    except (ValueError, TypeError):
        return 0


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {key: sum(number(row.get(key)) for row in rows) for key in NUMBERS}
    known = [row for row in rows if row.get("api_calls") is not None]
    out["api_calls"] = sum(int(row["api_calls"]) for row in known) if known else None
    out["api_calls_missing"] = len(rows) - len(known)
    return out


def workday_busy(path: Path) -> bool:
    """The existing workday flock is authoritative; a leftover file is not busy."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


class Explorer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def _issues(self) -> tuple[list[dict[str, Any]], list[str]]:
        try:
            ledger = Beads(bin=self.settings.beads.bin, cwd=self.settings.root, dry_run=True)
            return ledger.list_issues("--all"), []
        except (BeadsError, OSError):
            return [], ["Work ledger unavailable; usage and memory remain browsable."]

    def _attribution(self, agents: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, str]:
        state = self.settings.dirs["state"]
        attribution: dict[str, str] = {}
        for name in agents:
            data = read_object(state / "agents" / name / "bead-runs.json", state)
            for row in data.values():
                if isinstance(row, dict) and row.get("run_id"):
                    attribution[str(row["run_id"])] = name
        # Finished workday events provide historical ownership, unlike current bead labels.
        for line in event_lines(state / "events.jsonl", state):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("source") != "agent":
                continue
            name = str(event.get("session", "")).removeprefix("agent-")
            event_data = event.get("data")
            if name not in agents or not isinstance(event_data, dict):
                continue
            event_runs = event_data.get("runs", [])
            if not isinstance(event_runs, list):
                continue
            for run in event_runs:
                if isinstance(run, dict) and run.get("run_id"):
                    attribution[str(run["run_id"])] = name
        return attribution

    def _runs(
        self, days: int, agents: dict[str, Any], issues: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        root = self.settings.dirs["runs"]
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=days - 1
        )
        owners = self._attribution(agents, issues)
        bead_owners = {}
        for issue in issues:
            labels = [label[6:] for label in bead_labels(issue) if label.startswith("agent:")]
            if len(labels) == 1:
                bead_owners[str(issue.get("id"))] = labels[0]
        paths = sorted(root.glob("*/*/meta.json"), reverse=True)
        warnings = (
            ["Run scan truncated to the newest 10,000 records."] if len(paths) > MAX_RUNS else []
        )
        rows = []
        for path in paths[:MAX_RUNS]:
            meta = read_object(path, root)
            start = stamp(meta.get("started"))
            if not start or start < cutoff:
                continue
            ident = str(meta.get("run_id") or path.parent.name)
            name = meta.get("agent") or owners.get(ident)
            ownership = "recorded"
            if not name:
                name = bead_owners.get(str(meta.get("bead")))
                ownership = "current bead label" if name else "unattributed"
            usage = meta.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            inp = number(usage.get("input_tokens", usage.get("prompt_tokens")))
            out = number(usage.get("output_tokens", usage.get("completion_tokens")))
            cache = number(
                usage.get(
                    "cache_read_input_tokens",
                    usage.get("cache_read_tokens", usage.get("cached_input_tokens")),
                )
            )
            write = number(
                usage.get("cache_creation_input_tokens", usage.get("cache_write_tokens"))
            )
            # Anthropic cache tokens are separate; Codex cached_input_tokens is a subset.
            total = number(usage["total_tokens"]) if "total_tokens" in usage else inp + out
            if "total_tokens" not in usage and (
                "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage
            ):
                total += cache + write
            finish = stamp(meta.get("finished"))
            protected = meta.get("privacy") == "local-only" or name == "liaison"
            result = {} if protected else read_object(path.parent / "result.json", root)
            summary = (
                "Protected work: details remain local."
                if protected
                else release_text(
                    str(result.get("summary") or meta.get("error") or "No summary recorded."),
                    personal_source=True,
                )
            )
            rows.append(
                {
                    "id": ident,
                    "agent": name,
                    "attribution": ownership,
                    "started": start.isoformat(),
                    "finished": finish.isoformat() if finish else None,
                    "state": meta.get("state", "unknown"),
                    "runner": meta.get("runner"),
                    "model": meta.get("model"),
                    "bead": meta.get("bead"),
                    "run_count": 1,
                    "input_tokens": int(inp),
                    "output_tokens": int(out),
                    "cache_read_tokens": int(cache),
                    "cache_write_tokens": int(write),
                    "total_tokens": int(total),
                    "api_calls": int(number(usage["api_calls"])) if "api_calls" in usage else None,
                    "cost_usd": number(meta.get("billed_cost_usd")),
                    "equivalent_usd": number(meta.get("equivalent_usd")),
                    "estimated": bool(meta.get("estimated")),
                    "duration_seconds": max(0, (finish - start).total_seconds()) if finish else 0,
                    "usage_missing": int(
                        not any(
                            k in usage
                            for k in (
                                "input_tokens",
                                "prompt_tokens",
                                "total_tokens",
                                "output_tokens",
                            )
                        )
                    ),
                    "summary": summary[:12000],
                    "source": str(path.relative_to(root)),
                }
            )
        return sorted(rows, key=lambda row: row["started"], reverse=True), warnings

    def status(self, name: str) -> tuple[str, bool, str]:
        agent = load_agent(self.settings.root, name)
        state = self.settings.dirs["state"]
        if (state / "KILL").exists():
            return "stopped", False, "Fleet kill switch is set."
        if agent.host != self.settings.host:
            return "remote", False, f"Runs on {agent.host}; ws never reaches into the laptop."
        if agent.name == "hermes-ws":
            return "gateway", False, "Managed by the Mattermost gateway, not a research workday."
        if (state / "agents" / name / "PAUSED").exists():
            return "paused", False, "Agent is paused; resume it through cube first."
        with self.lock:
            pending = self.jobs.get(name, {}).get("status") in {"queued", "running"}
        if pending or workday_busy(state / "agents" / name / "workday.lock"):
            return "busy", False, "A workday is already active."
        return "idle", True, "Start one bounded workday; budgets and approval gates still apply."

    def snapshot(self, days: int = 7, name: str | None = None) -> dict[str, Any]:
        if days not in {1, 7, 30}:
            raise ValueError("Choose 1, 7 or 30 days.")
        agents, errors = load_all_agents(self.settings.root)
        if name is not None and name not in agents:
            raise ValueError("Unknown agent.")
        issues, warnings = self._issues()
        runs, notes = self._runs(days, agents, issues)
        warnings += notes + [f"Agent configuration invalid: {key}" for key in errors]
        rows = []
        for key, agent in agents.items():
            own = [run for run in runs if run["agent"] == key]
            state, allowed, reason = self.status(key)
            rows.append(
                {
                    "name": key,
                    "title": agent.title,
                    "role": agent.role,
                    "host": agent.host,
                    "runtime": agent.runtime,
                    "state": state,
                    "can_trigger": allowed,
                    "reason": reason,
                    "latest_summary": own[0]["summary"]
                    if own
                    else "No runs recorded in this period.",
                    **metrics(own),
                }
            )
        timeline = []
        today = datetime.now(UTC).date()
        for offset in reversed(range(days)):
            day = (today - timedelta(days=offset)).isoformat()
            timeline.append(
                {"date": day, **metrics([run for run in runs if run["started"].startswith(day)])}
            )
        if name is None:
            return {
                "generated": datetime.now(UTC).isoformat(),
                "host": self.settings.host,
                "kill": (self.settings.dirs["state"] / "KILL").exists(),
                "agents": rows,
                "totals": metrics(runs),
                "timeline": timeline,
                "warnings": warnings,
                "unattributed_runs": sum(run["agent"] not in agents for run in runs),
            }
        agent = agents[name]
        from cube.explorer_hermes import gateway_usage

        gateway = gateway_usage(self.settings, days) if name == "hermes-ws" else None
        protected = name == "liaison" or str(agent.privacy_default) == "local-only"
        memories = []
        if not protected:
            for filename in MEMORIES:
                path = self.settings.root / agent.memory_dir / filename
                text = read_text(path, self.settings.root / "agents" / name, 2_000_000)
                if text:
                    memories.append(
                        {
                            "name": filename,
                            "text": release_text(text, personal_source=True)[-40000:],
                            "source": str(path.relative_to(self.settings.root)),
                        }
                    )
        tasks = []
        for issue in issues:
            labels = bead_labels(issue)
            if f"agent:{name}" in labels:
                header = BeadHeader.parse(str(issue.get("description") or ""))
                title = (
                    "Protected task"
                    if "privacy:local-only" in labels
                    or protected
                    or (header and header.privacy == Privacy.local_only)
                    else release_text(str(issue.get("title", "")), personal_source=True)
                )
                tasks.append({"id": issue.get("id"), "title": title, "status": issue.get("status")})
        with self.lock:
            job = dict(self.jobs[name]) if name in self.jobs else None
        return {
            "agent": next(row for row in rows if row["name"] == name),
            "charter": release_text(
                read_text(self.settings.root / agent.charter, self.settings.root / "agents"),
                personal_source=True,
            ),
            "memories": memories,
            "runs": [run for run in runs if run["agent"] == name][:200],
            "tasks": tasks[:100],
            "trigger": job,
            "gateway_usage": gateway,
            "warnings": warnings
            + (["Liaison/private memory is not exported from the laptop."] if protected else []),
        }

    def trigger(self, name: str, message: str = "") -> dict[str, Any]:
        if len(message) > 4000 or release_text(message, personal_source=True) != message:
            raise ValueError("Instruction is too long or contains protected information.")
        with self.lock:
            _, allowed, reason = self.status(name)
            if not allowed:
                raise ValueError(reason)
            command = [
                sys.executable,
                "-m",
                "cube.cli",
                "--root",
                str(self.settings.root),
                "agent",
                "workday",
                name,
                "--apply",
                "--json",
            ]
            job = {
                "status": "queued",
                "agent": name,
                "requested": datetime.now(UTC).isoformat(),
                "command": command,
            }
            self.jobs[name] = job
            if message.strip():
                append_inbox(
                    self.settings.root,
                    load_agent(self.settings.root, name),
                    message.strip(),
                    sender="robert:explorer",
                )
            threading.Thread(target=self._launch, args=(name, command), daemon=True).start()
            return dict(job)

    def _launch(self, name: str, command: list[str]) -> None:
        with self.lock:
            self.jobs[name]["status"] = "running"
        # No shell and no model output sent directly to the browser. Workday owns
        # its lease, budgets, summaries, publication and protected-role dispatcher.
        try:
            result = subprocess.run(
                command,
                cwd=self.settings.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            status = "finished" if result.returncode == 0 else "failed"
        except OSError:
            status = "failed"
        with self.lock:
            self.jobs[name].update(status=status, finished=datetime.now(UTC).isoformat())
