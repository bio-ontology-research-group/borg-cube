"""`cube decisions`, `cube question new`, `cube decide`: how agents ask Robert.

`cube decisions --json` is the single list the cockpit shows; `cube question new`
is the one command an agent runs to ask something; `cube decide` records Robert's
answer and routes it back to the asker.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from typing import Any

from cube.beads import BeadsError
from cube.commands import Helpers
from cube.config import Settings
from cube.decisions import (
    DecisionError,
    apply_policy,
    ask,
    decide,
    decide_from_reply,
    decisions_payload,
    decisions_text,
)


def cmd_decisions(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    payload = decisions_payload(settings, helpers.beads(settings, True))
    helpers.emit(args, payload, decisions_text(payload))
    return 0


def cmd_decisions_apply_policy(
    args: argparse.Namespace, settings: Settings, helpers: Helpers
) -> int:
    """Answer by hand what the decisions patrol would answer at its next tick."""
    beads = helpers.beads(settings, args.dry_run)
    try:
        rows = apply_policy(settings, beads, dry_run=args.dry_run)
    except (DecisionError, BeadsError) as exc:
        print(f"cube decisions apply-policy: {exc}", file=sys.stderr)
        return 2
    answered = [row for row in rows if row.get("answered")]
    data = {
        "dry_run": args.dry_run,
        "answered": answered,
        "waiting": [row for row in rows if not row.get("answered")],
        "commands": beads.logged_commands(),
    }
    lines = [
        f"{'DRY-RUN ' if args.dry_run else ''}auto-answered {len(answered)}, "
        f"{len(rows) - len(answered)} wait for Robert"
    ]
    lines += [f"  {row['id']:<12} {row.get('answer'):<8} {row.get('note')}" for row in answered]
    helpers.emit(args, data, "\n".join(lines))
    return 0


def cmd_question_new(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, args.dry_run)
    options = [part.strip() for part in (args.options or "").split(",") if part.strip()]
    try:
        data = ask(
            settings,
            beads,
            sender=args.sender,
            text=args.text,
            options=options or None,
            bead=args.bead,
            epic=args.epic,
            run_id=os.environ.get("CUBE_RUN_ID"),
            dry_run=args.dry_run,
            critical=args.critical,
        )
    except (DecisionError, BeadsError) as exc:
        print(f"cube question new: {exc}", file=sys.stderr)
        return 2
    data["commands"] = beads.logged_commands()
    decider = "Robert" if data.get("decider", "robert") == "robert" else "the coordinator"
    text = (
        f"{'DRY-RUN ' if args.dry_run else ''}"
        f"{'asked' if data['created'] else 'already asked'} {decider}: "
        f"{data['bead'] or '(planned)'}"
    )
    helpers.emit(args, data, text)
    return 0


def cmd_decide(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    beads = helpers.beads(settings, args.dry_run)
    if not args.id and not args.reply:
        print("cube decide: give a decision id, or --reply '<Robert's message>'", file=sys.stderr)
        return 2
    try:
        if args.reply:
            # Robert, 2026-09-07: his Mattermost DM reply, relayed verbatim by hermes-ws.
            data = decide_from_reply(settings, beads, args.reply, dry_run=args.dry_run)
        else:
            data = decide(
                settings,
                beads,
                args.id,
                choice=args.choice,
                text=args.text,
                dry_run=args.dry_run,
            )
    except (DecisionError, BeadsError, ValueError) as exc:
        print(f"cube decide: {exc}", file=sys.stderr)
        return 2
    data["commands"] = beads.logged_commands()
    if data.get("relay"):
        helpers.emit(
            args,
            data,
            f"{data['from']} runs on {data['relay']}: {shlex.join(data['command'])}",
        )
        return 3
    helpers.emit(
        args,
        data,
        f"{'DRY-RUN ' if args.dry_run else ''}answered {data['id']} "
        f"({data['kind']} from {data['from']}): {data['answer']}",
    )
    return 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("decisions", help="everything waiting for Robert's answer")
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_decisions(a, s, helpers))
    decision_cmds = sp.add_subparsers(dest="decisions_cmd")
    policy = decision_cmds.add_parser(
        "apply-policy", help="answer the decisions cube.yaml decisions.policy covers"
    )
    helpers.add_json(policy)
    helpers.add_dry(policy)
    policy.set_defaults(fn=lambda a, s: cmd_decisions_apply_policy(a, s, helpers))

    sp = sub.add_parser("question", help="ask Robert a question and stop")
    commands = sp.add_subparsers(dest="question_cmd", required=True)
    new = commands.add_parser("new", help="file a question for Robert")
    new.add_argument("--from", dest="sender", required=True, help="agent:NAME or role:NAME")
    new.add_argument("--text", required=True, help="the question, in one or two sentences")
    new.add_argument("--options", help="comma separated choices; omit for a free-text answer")
    new.add_argument("--bead", help="the bead this question is about")
    new.add_argument("--epic", help="the goal or pipeline epic this question belongs to")
    new.add_argument(
        "--critical",
        choices=["security", "privacy"],
        help="what makes this Robert's (ADR-0027); without it the coordinator answers",
    )
    helpers.add_json(new)
    helpers.add_dry(new)
    new.set_defaults(fn=lambda a, s: cmd_question_new(a, s, helpers))

    sp = sub.add_parser("decide", help="answer one pending decision")
    sp.add_argument("id", nargs="?", help="bead id or approval id from `cube decisions`")
    sp.add_argument("--choice", help="one of the decision's options")
    sp.add_argument("--text", help="a free-text answer")
    sp.add_argument(
        "--reply",
        help="Robert's Mattermost reply as written, e.g. 'cube-8xow approve' (hermes-ws)",
    )
    helpers.add_json(sp)
    helpers.add_dry(sp)
    sp.set_defaults(fn=lambda a, s: cmd_decide(a, s, helpers))
