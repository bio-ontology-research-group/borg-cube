"""Fleet budgets, Slurm work, documentation and checked system execution."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.config import Settings


def run(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    from cube import compute, fleet_github, resources, sysops
    from cube.fleet_delivery import deliver_outbox

    try:
        data: Any
        op = args.fleet_cmd
        agent = os.environ.get("CUBE_AGENT") or getattr(args, "agent", None)
        if op == "limits":
            if args.set:
                if agent and agent != "hermes-ws":
                    raise ValueError("only Robert or his Mattermost agent changes central limits")
                data = resources.update_limits(
                    settings, json.loads(args.set), args.evidence, dry_run=args.dry_run
                )
            else:
                data = {
                    "limits": resources.load_limits(settings).model_dump(),
                    "usage": resources.read_usage(settings),
                }
        elif op == "submit":
            if not agent:
                raise ValueError("name the researcher with --agent")
            data = compute.submit(
                settings,
                agent,
                args.target,
                Path(args.script),
                args.workdir,
                json.loads(args.needs),
                dry_run=args.dry_run,
            )
        elif op == "job":
            data = compute.status(settings, args.reservation, dry_run=args.dry_run)
        elif op == "publish":
            data = fleet_github.publish_pending(settings, dry_run=args.dry_run)
        elif op == "outbox":
            data = deliver_outbox(settings, dry_run=args.dry_run)
        elif op == "enact":
            data = sysops.execute(settings, args.id, dry_run=args.dry_run)
        elif op in {"issue", "pr"}:
            body = Path(args.body_file).read_text(encoding="utf-8")
            if op == "issue":
                data = fleet_github.create_issue(
                    settings, args.repo, args.title, body, args.evidence, dry_run=args.dry_run
                )
            else:
                data = fleet_github.create_pr(
                    settings,
                    args.repo,
                    args.title,
                    body,
                    args.head,
                    base=args.base,
                    evidence=args.evidence,
                    dry_run=args.dry_run,
                )
        else:
            if not agent:
                raise ValueError("name the researcher with --agent")
            files = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            data = fleet_github.queue_checkpoint(
                settings,
                agent,
                args.repo,
                args.branch,
                files,
                args.message,
                args.evidence,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                data["publications"] = fleet_github.publish_checkpoints(settings, dry_run=False)
        helpers.emit(args, data, None)
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 2


def register_operations(commands: Any, helpers: Helpers) -> None:
    limits = commands.add_parser("limits", help="central limits and aggregate usage")
    limits.add_argument("--set", help="JSON mapping of changed limits")
    limits.add_argument(
        "--evidence", default="", help="Robert's instruction or Mattermost permalink"
    )
    submit = commands.add_parser("submit", help="submit a bounded Slurm job")
    submit.add_argument("target", choices=["ibex", "dragon", "unimatrix01"])
    submit.add_argument("script")
    submit.add_argument("--agent")
    submit.add_argument("--workdir", required=True)
    submit.add_argument(
        "--needs",
        required=True,
        help="JSON: cpus, memory_gib, gpus, walltime_hours, expected_output_gib",
    )
    job = commands.add_parser("job", help="refresh one recorded Slurm job")
    job.add_argument("reservation")
    publish = commands.add_parser("publish", help="publish queued research records")
    outbox = commands.add_parser("outbox", help="deliver and acknowledge Robert's pending messages")
    enact = commands.add_parser("enact", help="execute an already approved immutable bundle")
    enact.add_argument("id")
    issue = commands.add_parser("issue", help="file an evidenced bug in borg-cube-fleet")
    pr = commands.add_parser("pr", help="open a reviewed improvement as a fleet draft PR")
    for item in (issue, pr):
        item.add_argument("repo")
        item.add_argument("--title", required=True)
        item.add_argument("--body-file", required=True)
        item.add_argument("--evidence", action="append", required=True)
    pr.add_argument("--head", required=True)
    pr.add_argument("--base", default="main")
    files = commands.add_parser(
        "document", help="queue and push a checkpoint, creating a private project repo if needed"
    )
    files.add_argument("repo")
    files.add_argument(
        "manifest", help="JSON object mapping repository paths to UTF-8 file contents"
    )
    files.add_argument("--agent")
    files.add_argument("--branch", default="main")
    files.add_argument("--message", required=True)
    files.add_argument("--evidence", action="append", required=True)
    for item in (limits, submit, job, publish, outbox, enact, issue, pr, files):
        helpers.add_json(item)
        helpers.add_dry(item)
        item.set_defaults(fn=lambda a, s: run(a, s, helpers))
