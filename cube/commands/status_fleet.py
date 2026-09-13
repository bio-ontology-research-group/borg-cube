"""`cube fleet --json`: tmux sessions on this host and live leases (INTERFACE.md sessions)."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Any

from cube import __version__
from cube.commands import Helpers
from cube.commands.budget import budget_status
from cube.commands.doctor_cockpit import git_version
from cube.config import Settings
from cube.engine.attention import incident_data
from cube.engine.fleet import fleet
from cube.hosts import peer_status


def cmd_fleet(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    data = fleet(settings)
    lines = [
        f"{s['tmux']}: {s['last_event'] or '-'} {s['last_event_ts'] or ''}"
        for s in data["sessions"]
    ]
    lines += [
        f"lease {x['bead']}: {x['role']} run {x['run_id']} until {x['expires']}"
        for x in data["leases"]
    ]
    helpers.emit(args, data, "\n".join(lines) or "no cube sessions or leases on this host")
    return 0


def cmd_drill_start(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from cube.beads import BeadsError
    from cube.fleet_drill import start

    requested = [name.strip() for name in (args.agents or "").split(",") if name.strip()]
    beads = helpers.beads(settings, args.dry_run)
    try:
        data = start(settings, beads, agents=requested or None)
    except (BeadsError, ValueError) as exc:
        print(f"cube fleet drill start: {exc}", file=sys.stderr)
        return 2
    verb = "reused" if data["reused"] else ("would create" if data["dry_run"] else "created")
    helpers.emit(
        args,
        data,
        f"{verb} {data['bead'] or data['xid']} for {', '.join(data['agents'])}\n\n{data['body']}",
    )
    return 0


def cmd_drill_status(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from cube.beads import BeadsError
    from cube.fleet_drill import status as drill_status
    from cube.fleet_drill import status_text

    day = date.fromisoformat(args.date) if args.date else None
    try:
        data = drill_status(settings, helpers.beads(settings, True), bead=args.bead, day=day)
    except (BeadsError, ValueError) as exc:
        print(f"cube fleet drill status: {exc}", file=sys.stderr)
        return 2
    helpers.emit(args, data, status_text(data))
    return 0


def cmd_drill_run(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """Start the drill and run the coordinator's workday now so the tells go out."""
    from cube.agents import AgentError
    from cube.beads import BeadsError
    from cube.fleet_drill import start, status_text
    from cube.fleet_drill import status as drill_status
    from cube.patrols.agent_workday import AgentWorkdayPatrol

    beads = helpers.beads(settings, args.dry_run)
    try:
        started = start(settings, beads)
        workday = AgentWorkdayPatrol("coordinator").run(settings, dry_run=args.dry_run, beads=beads)
        data = drill_status(settings, helpers.beads(settings, True), bead=started["bead"])
    except (AgentError, BeadsError, ValueError) as exc:
        print(f"cube fleet drill run: {exc}", file=sys.stderr)
        return 2
    payload = {"start": started, "workday": workday.as_dict(), "status": data}
    helpers.emit(
        args,
        payload,
        f"drill {started['bead'] or started['xid']}; coordinator workday: "
        f"{workday.state}, runs={len(workday.runs)}\n\n{status_text(data)}",
    )
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """Keep the legacy status payload intact, adding contract summaries."""
    beads = helpers.beads(settings, True)
    try:
        sessions = list(fleet(settings).get("sessions", []))
    except Exception:  # noqa: BLE001 - status must not fail because fleet probing failed
        sessions = []
    incidents = incident_data(settings, beads)
    try:
        from cube.commands.projects import project_payload, projects_summary

        projects = projects_summary(
            project_payload(settings, helpers, today=date.today(), cache_only=True)["projects"]
        )
    except Exception:  # noqa: BLE001 - status must survive unavailable external sources
        projects = {"total": 0, "active": 0, "ending": 0, "ended": 0, "unknown": 0}
    budget = budget_status(settings)
    if not budget["swaps"]:
        # Keep the legacy empty status payload stable; active swaps are always
        # exposed for the cockpit banner.
        budget.pop("swaps")
    try:
        from cube.agents import agent_list

        agents = [
            {
                key: row[key]
                for key in ("name", "kind", "state", "pending_proposals", "inbox_unread")
            }
            for row in agent_list(settings, beads=beads)
        ]
    except Exception:  # noqa: BLE001 - status must survive malformed optional agent files
        agents = []
    checkout = git_version(settings.root)
    data = {
        "version": {
            "git": checkout.sha or "unknown",
            "dirty": bool(checkout.dirty),
            "commands": helpers.command_names(),
        },
        "host": settings.host,
        "peers": peer_status(settings),
        "root": str(settings.root),
        "beads": beads.available(),
        "sessions": sessions,
        "counts": {
            "running": len(sessions),
            "adopted": sum(bool(session.get("adopted")) for session in sessions),
        },
        "kill": (settings.state_dir() / "KILL").exists(),
        "budget": budget,
        "incidents": {
            "count": len(incidents["open"]),
            "highest": incidents["open"][0]["severity"] if incidents["open"] else None,
            "banner": incidents["banner"],
        },
        "projects": projects,
    }
    # Older isolated fixtures do not have an agents directory. Preserve their
    # established payload while every configured cube exposes the new key.
    if (settings.root / "agents").exists():
        data["agents"] = agents
    helpers.emit(
        args,
        data,
        f"cube {__version__} on {settings.host}; beads={'yes' if data['beads'] else 'no'}; "
        f"kill={'ON' if data['kill'] else 'off'}",
    )
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    status = sub.choices.get("status")
    if status is not None:
        status.set_defaults(fn=lambda args, settings: cmd_status(args, settings, helpers))
    sp = sub.add_parser("fleet", help="tmux sessions and live leases on this host")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_fleet(a, s, helpers))
    # `cube fleet` on its own keeps its old behaviour; the drill is a subcommand.
    fleet_sub = sp.add_subparsers(dest="fleet_cmd", required=False)
    from cube.commands.fleet import register_operations

    register_operations(fleet_sub, helpers)
    drill = fleet_sub.add_parser("drill", help="hello-world drill across the whole agent fleet")
    drill_sub = drill.add_subparsers(dest="drill_cmd", required=True)
    start = drill_sub.add_parser("start", help="create today's drill bead for the coordinator")
    start.add_argument("--agents", help="comma-separated roster (default: every loaded agent)")
    helpers.add_json(start)
    helpers.add_dry(start)
    start.set_defaults(fn=lambda a, s: cmd_drill_start(a, s, helpers))
    st = drill_sub.add_parser("status", help="deterministic drill report from bead and inboxes")
    st.add_argument("bead", nargs="?", help="drill bead id (default: today's drill)")
    st.add_argument("--date", help="drill date YYYY-MM-DD instead of today")
    helpers.add_json(st)
    st.set_defaults(fn=lambda a, s: cmd_drill_status(a, s, helpers))
    run = drill_sub.add_parser("run", help="start the drill and run the coordinator workday now")
    helpers.add_json(run)
    helpers.add_dry(run)
    run.set_defaults(fn=lambda a, s: cmd_drill_run(a, s, helpers))
