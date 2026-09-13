"""`cube agent`: named standing-agent conversations and bounded workdays."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.agents import (
    Agent,
    AgentError,
    agent_context,
    agent_list,
    agent_path,
    agent_summary,
    append_inbox,
    context_path,
    inbox_path,
    journal_entries,
    load_agent,
    read_inbox,
    save_session,
    session,
    state_dir,
)
from cube.agents.scaffold import AgentScaffoldSpec, render_agent_files, scaffold_agent
from cube.beads import BeadsError
from cube.commands import Helpers
from cube.config import Settings
from cube.model import BeadHeader, Privacy, Provenance
from cube.patrols.agent_workday import AgentWorkdayPatrol
from cube.runners import RUNNER_NAMES


def _tmux(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Small seam for tests.  No untrusted shell text is executed here."""
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, "", "tmux: not found")


TELL_SUBMIT_DELAY = 0.5


def _tmux_live(name: str) -> bool:
    return _tmux(["tmux", "has-session", "-t", name]).returncode == 0


def _agent(settings: Settings, name: str | None) -> Agent:
    return load_agent(settings.root, name or "coordinator")


def _talk_command(settings: Settings, agent: Agent, context_file: Path) -> list[str]:
    saved = session(settings, agent)
    resume_id = saved.get("resume_id") or saved.get("session_id")
    if agent.runtime == "claude":
        command = ["claude", "--append-system-prompt-file", str(context_file)]
        if resume_id:
            command += ["--resume", str(resume_id)]
        return command
    if agent.runtime == "codex":
        command = ["codex"]
        if resume_id:
            command += ["resume", str(resume_id)]
        return command
    return ["hermes", "chat"]


def _write_talk_context(settings: Settings, agent: Agent, text: str) -> Path:
    path = context_path(settings, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if agent.runtime == "codex":
        # Codex reads AGENTS.md from the agent working directory.  The file is
        # agent-local, not a replacement for the repository-wide AGENTS.md.
        (settings.root / "agents" / agent.name / "AGENTS.md").write_text(text, encoding="utf-8")
    return path


def cmd_list(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    data = agent_list(settings, beads=helpers.beads(settings, True))
    helpers.emit(
        args,
        data,
        "\n".join(f"{row['name']}: {row['state']} ({row['title']})" for row in data)
        or "no standing agents",
    )
    return 0


def cmd_show(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = _agent(settings, args.name)
    except AgentError as exc:
        print(f"cube agent show: {exc}", file=sys.stderr)
        return 2
    data = agent.model_dump(mode="json")
    data.update(
        {
            "charter_text": (settings.root / agent.charter).read_text(encoding="utf-8"),
            "journal": journal_entries(settings.root, agent),
            "inbox": read_inbox(settings.root, agent),
            "summary": agent_summary(settings, agent, beads=helpers.beads(settings, True)),
        }
    )
    helpers.emit(args, data, f"{agent.name}: {agent.title}")
    return 0


def cmd_new(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    name = args.name
    try:
        if agent_path(settings.root, name).exists():
            raise AgentError(f"agent already exists: {name}")
        default_skills = ["literature-review", "research-planning"]
        if args.kind != "expert":
            default_skills = ["literature-review"]
        spec = AgentScaffoldSpec(
            name=name,
            kind=args.kind,
            title=args.title,
            topics=args.topic,
            role=args.role,
            runtime=args.runtime,
            skills=[*default_skills, *args.skill],
            gpu_hours=args.gpu_hours,
            host=args.host,
            spend_usd=args.spend_usd,
        )
        files = render_agent_files(settings, spec)
        if not args.dry_run:
            scaffold_agent(settings, spec)
    except (AgentError, ValueError) as exc:
        print(f"cube agent new: {exc}", file=sys.stderr)
        return 2
    data = {
        "name": name,
        "dry_run": args.dry_run,
        "files": [str(settings.root / item) for item in files],
    }
    helpers.emit(args, data, "\n".join(data["files"]))
    return 0


def cmd_talk(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = _agent(settings, args.name)
        text = agent_context(settings, agent)
    except AgentError as exc:
        print(f"cube agent talk: {exc}", file=sys.stderr)
        return 2
    if agent.role in {"liaison", "sysadmin"} or agent.privacy_default == "local-only":
        print(
            "Restricted/private agents use cube agent workday with routed tools, "
            "not interactive sessions.",
            file=sys.stderr,
        )
        return 2
    ctx_path = context_path(settings, agent)
    tmux_name = f"cube/agent-{agent.name}"
    runtime_command = _talk_command(settings, agent, ctx_path)
    command = ["tmux", "new-session", "-d", "-s", tmux_name, shlex.join(runtime_command)]
    live = _tmux_live(tmux_name)
    if not args.dry_run and not live:
        _write_talk_context(settings, agent, text)
        proc = _tmux(command)
        if proc.returncode:
            print(proc.stderr.strip() or "could not start tmux", file=sys.stderr)
            return 1
        previous = session(settings, agent)
        save_session(
            settings,
            agent,
            {**previous, "runner": agent.runtime, "tmux": tmux_name, "context": str(ctx_path)},
        )
    attach_command = ["tmux", "attach-session", "-t", tmux_name]
    data = {
        "name": agent.name,
        "tmux": tmux_name,
        "attached": live,
        "dry_run": args.dry_run,
        "context_file": str(ctx_path),
        "command": command,
        "attach_command": attach_command if args.attach else None,
        "context": text if args.dry_run else None,
    }
    if args.attach and not args.dry_run:
        # The cockpit runs this inside a terminal: replace the process with the
        # tmux client so the agent's session is what the user sees and types into.
        sys.stdout.flush()
        os.execvp(attach_command[0], attach_command)
    helpers.emit(
        args,
        data,
        f"{'DRY-RUN ' if args.dry_run else ''}tmux: {tmux_name}\n"
        f"context: {ctx_path}\ncommand: {shlex.join(command)}"
        + (f"\nattach: {shlex.join(attach_command)}" if args.attach else ""),
    )
    return 0


def cmd_tell(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = _agent(settings, args.name)
    except AgentError as exc:
        print(f"cube agent tell: {exc}", file=sys.stderr)
        return 2
    tmux_name = str(session(settings, agent).get("tmux") or f"cube/agent-{agent.name}")
    live = _tmux_live(tmux_name)
    # Text and Enter go in two calls: Claude Code treats text followed by an
    # immediate newline as a paste and leaves the prompt unsubmitted.
    command = ["tmux", "send-keys", "-t", tmux_name, "-l", args.text]
    submit = ["tmux", "send-keys", "-t", tmux_name, "Enter"]
    if not args.dry_run:
        if args.redeliver:
            # The inbox already holds this message (the cockpit queued it and
            # then woke the agent); only type it into the live session.
            record = {"from": args.sender, "text": args.text, "read": False, "delivered": live}
        else:
            record = append_inbox(
                settings.root,
                agent,
                args.text,
                sender=args.sender,
                delivered=live,
            )
        if live:
            proc = _tmux(command)
            if proc.returncode:
                print(proc.stderr.strip() or "tmux delivery failed", file=sys.stderr)
                return 1
            time.sleep(TELL_SUBMIT_DELAY)
            proc = _tmux(submit)
            if proc.returncode:
                print(proc.stderr.strip() or "tmux submit failed", file=sys.stderr)
                return 1
    else:
        record = {"from": args.sender, "text": args.text, "read": False, "delivered": live}
    data = {
        "name": agent.name,
        "dry_run": args.dry_run,
        "inbox": str(inbox_path(settings.root, agent)),
        "delivery": record,
        "tmux_command": command if live else None,
    }
    helpers.emit(args, data, "queued for next workday" if not live else f"delivered to {tmux_name}")
    return 0


def cmd_workday(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        patrol = AgentWorkdayPatrol(args.name, runner_name=args.runner, bead=args.bead)
        result = patrol.run(
            settings, dry_run=args.dry_run, beads=helpers.beads(settings, args.dry_run)
        )
    except (AgentError, BeadsError) as exc:
        print(f"cube agent workday: {exc}", file=sys.stderr)
        return 2
    data = result.as_dict()
    helpers.emit(
        args,
        data,
        f"{result.agent}: {result.state}; runs={len(result.runs)} blocked={len(result.blocked)}",
    )
    return 0 if result.state in {"finished", "paused", "killed"} else 1


def _inbox_relay(settings: Settings, agent: Agent, args: argparse.Namespace) -> list[str] | None:
    """Return the command to run on the agent's own host, or None when this is it."""
    if agent.host == settings.host:
        return None
    command = ["cube", "agent", "inbox", agent.name]
    if args.now:
        command.append("--now")
    command.append("--apply" if not args.dry_run else "--dry-run")
    command.append("--json")
    return command


def cmd_inbox(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    """List an agent's inbox and, with ``--now --apply``, make it read the unread part."""
    try:
        agent = _agent(settings, args.name)
    except AgentError as exc:
        print(f"cube agent inbox: {exc}", file=sys.stderr)
        return 2
    relay = _inbox_relay(settings, agent, args)
    if relay is not None:
        helpers.emit(
            args,
            {"agent": agent.name, "relay": agent.host, "command": relay},
            f"{agent.name} runs on {agent.host}: {shlex.join(relay)}",
        )
        return 3
    messages = read_inbox(settings.root, agent)
    unread = [row for row in messages if not row.get("read")]
    data: dict[str, Any] = {
        "agent": agent.name,
        "host": agent.host,
        "dry_run": args.dry_run,
        "now": args.now,
        "path": str(inbox_path(settings.root, agent)),
        "messages": messages,
        "unread": len(unread),
        "workday": None,
    }
    if getattr(args, "drain", False):
        if settings.fleet_enabled and agent.name == "hermes-ws":
            from cube.fleet_delivery import deliver_outbox

            outcome = deliver_outbox(settings, dry_run=args.dry_run)
            if getattr(args, "json", False):
                helpers.emit(args, outcome, None)
            # Legacy no-agent cron posts stdout. Delivery already happened here.
            return 1 if outcome["status"] == "failed" else 0
        # Robert, 2026-09-07: the Hermes outbox cron prints what the fleet left for
        # Robert and marks it read; empty output means no Mattermost message.
        # Reading is not delivery. The gateway acknowledges IDs only after a post.
        data["drained"] = unread
        text = "\n\n".join(
            f"{row.get('from', '?')}: {row.get('text', '')}".strip() for row in unread
        )
        helpers.emit(args, data, text)
        return 0
    if args.now:
        try:
            patrol = AgentWorkdayPatrol(agent.name, runner_name=args.runner, inbox_only=True)
            result = patrol.run(
                settings, dry_run=args.dry_run, beads=helpers.beads(settings, args.dry_run)
            )
        except (AgentError, BeadsError) as exc:
            print(f"cube agent inbox: {exc}", file=sys.stderr)
            return 2
        data["workday"] = result.as_dict()
    lines = [f"{agent.name} inbox ({len(unread)} unread of {len(messages)})"]
    for row in messages:
        mark = " " if row.get("read") else "*"
        lines.append(f"{mark} {row.get('ts', '?')} {row.get('from', '?')}: {row.get('text', '')}")
    workday: dict[str, Any] | None = data["workday"]
    if workday is not None:
        lines.append("")
        lines.append(f"{'DRY-RUN ' if args.dry_run else ''}inbox pass: {workday['state']}")
        for run in workday["runs"]:
            route = f"{run.get('runner')} {run.get('model') or ''}".strip()
            lines.append(f"- step {run.get('role')} via {route}")
        for blocked in workday["blocked"]:
            lines.append(f"- blocked: {blocked.get('step')}: {blocked.get('reason', '')}")
    helpers.emit(args, data, "\n".join(lines))
    return 0


def cmd_report(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = _agent(settings, args.name)
    except AgentError as exc:
        print(f"cube agent report: {exc}", file=sys.stderr)
        return 2
    entries = journal_entries(settings.root, agent, limit=20 if args.week else 5)
    body = "# Weekly standing-agent report\n\n" + "\n\n".join(entries or ["No journal entries."])
    header = BeadHeader(
        xid=f"agent:{agent.name}:report:{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        provenance=[
            Provenance(source=f"agents/{agent.name}/memory/journal.md", locator="latest entries")
        ],
        privacy=Privacy.internal,
    )
    beads = helpers.beads(settings, args.dry_run)
    report_id = beads.create(
        f"Weekly report from {agent.title}",
        header=header,
        body=body,
        labels=["kind:report", "needs:robert", f"agent:{agent.name}"],
        acceptance="Robert has reviewed the report.",
    )
    data = {
        "agent": agent.name,
        "dry_run": args.dry_run,
        "report": report_id,
        "body": body,
        "commands": beads.logged_commands(),
    }
    helpers.emit(args, data, body)
    return 0


def cmd_pause_resume(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    try:
        agent = _agent(settings, args.name)
    except AgentError as exc:
        print(f"cube agent {args.agent_cmd}: {exc}", file=sys.stderr)
        return 2
    marker = state_dir(settings, agent) / "PAUSED"
    if not args.dry_run:
        marker.parent.mkdir(parents=True, exist_ok=True)
        if args.agent_cmd == "pause":
            marker.write_text(
                f"paused {datetime.now(UTC).isoformat(timespec='seconds')}\n", encoding="utf-8"
            )
        elif marker.exists():
            marker.unlink()
    data = {
        "agent": agent.name,
        "action": args.agent_cmd,
        "dry_run": args.dry_run,
        "state": "paused" if args.agent_cmd == "pause" else "idle",
    }
    helpers.emit(args, data, f"{'DRY-RUN ' if args.dry_run else ''}{args.agent_cmd} {agent.name}")
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("agent", help="talk to or run a named standing agent")
    commands = sp.add_subparsers(dest="agent_cmd", required=True)
    list_parser = commands.add_parser("list", help="list standing agents")
    helpers.add_json(list_parser)
    list_parser.set_defaults(fn=lambda a, s: cmd_list(a, s, helpers))
    show = commands.add_parser("show", help="show one agent")
    show.add_argument("name")
    helpers.add_json(show)
    show.set_defaults(fn=lambda a, s: cmd_show(a, s, helpers))
    new = commands.add_parser("new", help="scaffold a standing agent")
    new.add_argument("name")
    new.add_argument("--kind", choices=["expert", "coordinator"], required=True)
    new.add_argument("--title", required=True)
    new.add_argument("--topic", action="append", required=True)
    new.add_argument("--role", required=True)
    new.add_argument("--runtime", choices=["claude", "codex", "hermes"], required=True)
    new.add_argument("--skill", action="append", default=[], help="add an agent skill")
    new.add_argument("--gpu-hours", type=float, default=0)
    new.add_argument("--host", default="ws")
    new.add_argument("--spend-usd", type=float, default=0)
    helpers.add_json(new)
    helpers.add_dry(new)
    new.set_defaults(fn=lambda a, s: cmd_new(a, s, helpers))
    talk = commands.add_parser("talk", help="open or attach a persistent agent tmux session")
    talk.add_argument("name", nargs="?", default="coordinator")
    talk.add_argument(
        "--attach",
        action="store_true",
        help="after starting the session, replace this process with tmux attach (cockpit)",
    )
    helpers.add_json(talk)
    helpers.add_dry(talk)
    talk.set_defaults(fn=lambda a, s: cmd_talk(a, s, helpers))
    tell = commands.add_parser("tell", help="queue a message for a standing agent")
    tell.add_argument("name")
    tell.add_argument("text")
    tell.add_argument("--from", dest="sender", default="robert")
    tell.add_argument(
        "--redeliver",
        action="store_true",
        help="type an already queued message into the live session without appending it again",
    )
    helpers.add_json(tell)
    helpers.add_dry(tell)
    tell.set_defaults(fn=lambda a, s: cmd_tell(a, s, helpers))
    workday = commands.add_parser("workday", help="run an agent's bounded autonomous loop")
    workday.add_argument("name")
    workday.add_argument(
        "--now", action="store_true", help="run now instead of waiting for the timer"
    )
    workday.add_argument(
        "--runner", choices=RUNNER_NAMES, help="runner override, including stub for tests"
    )
    workday.add_argument("--bead", help="process only the selected assigned bead")
    helpers.add_json(workday)
    helpers.add_dry(workday)
    workday.set_defaults(fn=lambda a, s: cmd_workday(a, s, helpers))
    inbox = commands.add_parser("inbox", help="list an agent's inbox, or make it read it now")
    inbox.add_argument("name")
    inbox.add_argument(
        "--now", action="store_true", help="run an inbox-only workday instead of only listing"
    )
    inbox.add_argument(
        "--drain",
        action="store_true",
        help="print the unread messages as text and mark them read (the Hermes outbox)",
    )
    inbox.add_argument(
        "--runner", choices=RUNNER_NAMES, help="runner override, including stub for tests"
    )
    helpers.add_json(inbox)
    helpers.add_dry(inbox)
    inbox.set_defaults(fn=lambda a, s: cmd_inbox(a, s, helpers))
    report = commands.add_parser("report", help="render a standing-agent report bead")
    report.add_argument("name")
    report.add_argument("--week", action="store_true")
    helpers.add_json(report)
    helpers.add_dry(report)
    report.set_defaults(fn=lambda a, s: cmd_report(a, s, helpers))
    for action in ("pause", "resume"):
        parser = commands.add_parser(action, help=f"{action} an agent workday")
        parser.add_argument("name")
        helpers.add_json(parser)
        helpers.add_dry(parser)
        parser.set_defaults(fn=lambda a, s: cmd_pause_resume(a, s, helpers))
