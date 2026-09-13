"""`cube request AGENT TEXT`: file source-backed work for a host-local agent."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from typing import Any

from cube.agents import AgentError, load_agent
from cube.agents.liaison import approval_labels, classify_request
from cube.commands import Helpers
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance
from cube.notify import append_event, make_event


def cmd_request(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = load_agent(settings.root, args.agent)
    except AgentError as exc:
        print(f"cube request: {exc}", file=sys.stderr)
        return 2
    host = args.host or agent.host
    if settings.hosts and host not in settings.hosts:
        print(f"cube request: unknown host {host!r}", file=sys.stderr)
        return 2
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    header = BeadHeader(
        xid=f"request:{agent.name}:{stamp}",
        provenance=[Provenance(source="cube request", locator="Robert request")],
        deadline=args.due,
        privacy=Privacy.internal,
    )
    labels = ["kind:request", f"agent:{agent.name}", f"host:{host}", "privacy:internal"]
    # Robert, 2026-09-08 (ADR-0027): a laptop read outside the readable directories
    # is his to approve; the request is filed already waiting, so the decisions
    # patrol announces it at its next tick instead of after the laptop's.
    scope = classify_request(args.text, settings, host=host) if agent.name == "liaison" else None
    if scope is not None:
        labels += approval_labels(scope)
    beads = helpers.beads(settings, args.dry_run)
    acceptance = f"{agent.name} records a source-backed answer and closes this request."
    if scope is not None and scope.needs_approval:
        acceptance = (
            "Robert approves the laptop read (ADR-0027); then "
            + acceptance[0].lower()
            + acceptance[1:]
        )
    bead_id = beads.create(
        f"Request for {agent.title}",
        header=header,
        body=f"Question: {args.text.strip()}",
        labels=labels,
        acceptance=acceptance,
    )
    if not args.dry_run:
        append_event(
            settings.state_dir(),
            make_event(
                "prompt",
                source="request",
                session=f"agent-{agent.name}",
                title=f"Request filed for {agent.name}",
                bead=bead_id,
                data={"host": host},
            ),
        )
    data = {
        "agent": agent.name,
        "host": host,
        "question": args.text,
        "due": args.due,
        "privacy": header.privacy.value,
        "labels": labels,
        "bead": bead_id,
        "dry_run": args.dry_run,
        "scope": scope.as_dict() if scope is not None else None,
        "commands": beads.logged_commands(),
    }
    waiting = (
        f" (waits for Robert's approval: {scope.reason})"
        if scope is not None and scope.needs_approval
        else ""
    )
    helpers.emit(
        args,
        data,
        f"{'DRY-RUN ' if args.dry_run else ''}request for {agent.name} on {host}: "
        f"{bead_id or '(planned)'}{waiting}",
    )
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    parser = sub.add_parser("request", help="file a request for a standing agent")
    parser.add_argument("agent")
    parser.add_argument("text")
    parser.add_argument("--due", type=date.fromisoformat)
    parser.add_argument("--host")
    helpers.add_json(parser)
    helpers.add_dry(parser)
    parser.set_defaults(fn=lambda a, s: cmd_request(a, s, helpers))
