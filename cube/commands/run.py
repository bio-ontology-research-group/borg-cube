"""`cube run <role> [--bead ID] [--runner X] [--resume] [--dry-run] [--prompt TEXT] --json`."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine import execute
from cube.runners import RUNNER_NAMES

EXIT = {"finished": 0, "dry-run": 0, "queued": 4, "refused": 3, "leased": 5, "killed": 6}


def _text(report: dict[str, Any]) -> str:
    lines = [
        f"run {report['run_id']} role={report['role']} bead={report.get('bead') or '-'} "
        f"runner={report.get('runner') or '-'} model={report.get('model') or '-'} "
        f"tools={'yes' if report.get('needs_tools') else 'no'} state={report['state']}"
    ]
    if report.get("command"):
        lines.append("command: " + " ".join(shlex.quote(str(c)) for c in report["command"]))
    if report.get("error"):
        lines.append(f"error: {report['error']}")
    if report.get("message"):
        lines.append(report["message"])
    for w in report.get("warnings") or []:
        lines.append(f"warning: {w}")
    if report.get("applied"):
        lines.append("applied: " + str(report["applied"]))
    if report.get("prompt"):
        lines.append("\n--- prompt ---\n" + str(report["prompt"]))
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    if args.attach and not args.dry_run:
        name = f"cube/run-{args.role}" + (f"-{args.bead}" if args.bead else "")
        inner = [sys.executable, "-m", "cube.cli", "--root", str(settings.root), "run", args.role]
        if args.bead:
            inner += ["--bead", args.bead]
        if args.runner:
            inner += ["--runner", args.runner]
        if args.resume:
            inner.append("--resume")
        cmd = ["tmux", "new-session", "-d", "-s", name, " ".join(shlex.quote(x) for x in inner)]
        proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603 - fixed argv
        data = {"ok": proc.returncode == 0, "tmux": name, "command": cmd, "stderr": proc.stderr}
        helpers.emit(args, data, f"started tmux session {name}" if data["ok"] else proc.stderr)
        return 0 if data["ok"] else 1
    report = execute(
        settings,
        args.role,
        bead=args.bead,
        runner_name=args.runner,
        model=args.model,
        resume=args.resume,
        dry_run=args.dry_run,
        prompt_text=args.prompt,
        needs_tools=args.needs_tools,
    )
    data = report.as_dict()
    if not args.json:
        pass
    elif not args.show_prompt:
        data.pop("prompt", None)
    helpers.emit(args, data, _text(data if args.show_prompt else {**data, "prompt": None}))
    return EXIT.get(report.state, 1)


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("run", help="run a role headless on a bead (writes runs/<date>/<run-id>/)")
    sp.add_argument("role")
    sp.add_argument("--bead", help="bead id to claim and work on")
    sp.add_argument("--runner", choices=RUNNER_NAMES, help="force a runner (stub for tests)")
    sp.add_argument("--model", help="model override within the tier")
    sp.add_argument("--resume", action="store_true", help="resume the bead's stored session")
    sp.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print the chosen command and prompt; run nothing",
    )
    sp.add_argument("--prompt", help="extra instruction appended to the context")
    sp.add_argument(
        "--needs-tools",
        dest="needs_tools",
        action="store_true",
        default=None,
        help="route only to a tool-capable harness (default: derived from the role)",
    )
    sp.add_argument(
        "--no-needs-tools",
        dest="needs_tools",
        action="store_false",
        help="allow chat-only runners even when the role has tools",
    )
    sp.add_argument("--attach", action="store_true", help="run inside tmux cube/run-<...>")
    sp.add_argument(
        "--show-prompt",
        dest="show_prompt",
        action="store_true",
        help="include the assembled prompt in the output",
    )
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_run(a, s, helpers))
