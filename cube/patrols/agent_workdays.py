"""``cube patrol agent-workday``: run every standing agent's bounded workday.

The systemd timer ``cube-patrol-agent-workday.timer`` checks every five minutes.
Agents whose ``workday.cron`` is ``hourly`` become due hourly (24/7 agents such
as the coordinator, which checks its inbox each hour); ``HH:MM`` agents run once
a day from that local time on. Each agent runs through
:class:`cube.patrols.agent_workday.AgentWorkdayPatrol` with its own limits; one
agent failing never stops the others, and the report carries every per-agent
result so the dashboard can show what happened.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

from cube.agents import AgentError, last_workday_start, load_all_agents, workday_due
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.patrols.base import PatrolReport, register


class AgentWorkdaysPatrol:
    name = "agent_workday"

    def __init__(
        self,
        *,
        runner_name: str | None = None,
        only: list[str] | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> None:
        self.runner_name = runner_name
        self.only = set(only or [])
        self.force = force
        self.now = now

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(name=self.name, today=today, dry_run=dry_run)
        agents, load_errors = load_all_agents(settings.root)
        for agent_name, message in sorted(load_errors.items()):
            report.warnings.append(f"{agent_name}: {message}")
        results: dict[str, dict[str, Any]] = {}
        now = self.now or datetime.now(UTC)
        due: list[str] = []
        for agent_name in sorted(agents):
            if self.only and agent_name not in self.only:
                continue
            agent = agents[agent_name]
            agent_host = getattr(agent, "host", None)
            if agent_host and agent_host != settings.host and not self.only:
                # The laptop liaison runs on the laptop (its mail, files and
                # calendar live there); ws never plays it, whatever its beads say.
                results[agent_name] = {
                    "agent": agent_name,
                    "state": "off-host",
                    "host": agent_host,
                }
                continue
            workday = getattr(agent, "workday", None)
            if workday is not None and not self.force and not self.only:
                if not workday_due(agent, now, last_workday_start(settings, agent)):
                    results[agent_name] = {
                        "agent": agent_name,
                        "state": "not-due",
                        "cron": workday.cron,
                    }
                    continue
            due.append(agent_name)

        def play(agent_name: str) -> dict[str, Any]:
            patrol = AgentWorkdayPatrol(agent_name, runner_name=self.runner_name)
            try:
                result = patrol.run(settings, today, dry_run, beads=beads)
            except (AgentError, BeadsError, OSError, ValueError) as exc:
                return {"agent": agent_name, "state": "failed", "error": str(exc)}
            return result.as_dict()

        if settings.fleet_enabled and not self.runner_name:
            from cube.resources import schedule_local_workdays
            from cube.runners.naming import uses_local

            local = []
            for name in due:
                agent = agents[name]
                override = getattr(agent, "runner", None)
                # Keep coordination and fixed sysadmin diagnosis responsive.
                # If either routes locally, the engine's physical cap still applies.
                if getattr(agent, "role", None) in {"group-leader", "sysadmin", "concierge"}:
                    continue
                if override and not uses_local(override):
                    continue
                tier = getattr(agent, "tier", "plan")
                candidates = settings.tiers.get(str(tier), [])
                if (override and uses_local(override)) or any(
                    uses_local(entry.runner_name) for entry in candidates
                ):
                    local.append(name)
            selected = set(schedule_local_workdays(settings, local, dry_run=dry_run))
            for name in local:
                if name not in selected:
                    results[name] = {
                        "agent": name,
                        "state": "scheduled",
                        "reason": "waiting for fair local inference turn",
                    }
            due = [name for name in due if name not in local or name in selected]
            report.data["local_schedule"] = {
                "selected": sorted(selected),
                "waiting": len(local) - len(selected),
            }

        # Robert, 2026-09-07: the agents work side by side, as many at once as the
        # plan tier has slots. One coordinator step of twenty minutes no longer
        # holds every other agent back until the next tick; each agent still
        # takes its own workday lock, so nothing runs twice.
        workers = max(1, min(len(due) or 1, int(settings.slots.get("plan", 1))))
        if workers == 1:
            played = [(name, play(name)) for name in due]
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="workday") as pool:
                played = list(zip(due, pool.map(play, due), strict=True))
        for agent_name, result in played:
            results[agent_name] = result
            if result.get("state") == "failed":
                report.warnings.append(f"{agent_name}: {result.get('error')}")
            if result.get("state") == "killed":
                report.paused = True
        results = {name: results[name] for name in sorted(results)}
        report.data["workdays"] = results
        states = ", ".join(f"{k}={v.get('state')}" for k, v in results.items()) or "no agents"
        report.summary = f"agent workdays: {states}"
        report.failed = bool(report.warnings) and not results
        return report


register(AgentWorkdaysPatrol, "agent_workday")
