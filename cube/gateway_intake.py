"""Model-free goal intake for the Mattermost gateway; research runs separately."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from cube.agents import append_inbox, append_journal, load_agent, mark_inbox_read, read_inbox
from cube.beads import Beads
from cube.config import Settings, load_settings
from cube.engine import execute
from cube.engine.context import privacy_filter
from cube.fleet_github import _lock, _safe, _save
from cube.model import BeadHeader, Provenance


def accept(settings: Settings, post: str, text: str, *, beads: Beads | None = None) -> str:
    """Save verbatim public/internal goal intent, with a stable post-id receipt.

    This is an intake request, not an invented dated GoalHeader. The coordinator
    owns decomposition and any missing scope/date questions. No model or send.
    """
    if not re.fullmatch(r"[a-z0-9]{26}", post) or not re.match(r"(?i)^new goal\s*:", text):
        raise ValueError("Expected a Mattermost post id and New goal: message")
    if len(text) > 20000 or not text.split(":", 1)[1].strip():
        raise ValueError("Goal is empty or too long")
    _safe(text)
    if privacy_filter(text)[1]:
        raise ValueError("Remove grades/HR details from the goal request")
    directory = settings.state_dir() / "gateway-intake"
    ledger = beads or Beads(cwd=settings.root)
    with _lock(directory):
        receipt = directory / f"{post}.json"
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["text"] != text:
                raise ValueError("Edited goal post: send a new message for the changed request")
            return str(saved["bead"])
        xid = f"mattermost-goal:{post}"
        existing = ledger.find_by_xid(xid)
        bead = (
            str(existing["id"])
            if existing
            else ledger.create(
                "Goal intake: " + text.split(":", 1)[1].strip().replace("\n", " ")[:110],
                header=BeadHeader(
                    xid=xid,
                    provenance=[
                        Provenance(
                            source="Mattermost",
                            permalink=f"https://borg.bio2vec.net/_redirect/pl/{post}",
                            locator=post,
                        )
                    ],
                ),
                body=text,
                labels=["kind:request", "agent:coordinator", "intake:goal", "privacy:internal"],
                priority=1,
            )
        )
        if not bead:
            raise ValueError("Goal intake could not be saved")
        agent = load_agent(settings.root, "coordinator")
        message = (
            f"New goal intake {bead}; source Mattermost post {post}.\n\n{text}\n\n"
            "Record and decompose this goal into bounded sourced work. Do not invent a deadline. "
            "For laptop-only sources use the liaison and push route, never ws-to-laptop SSH. "
            "Assign owners, an independent reviewer, and a stable private fleet repository. "
            "The gateway has acknowledged receipt; do not send another receipt or progress chatter."
        )
        # A retry after inbox append but before receipt save must not duplicate
        # even a message the coordinator has already acknowledged.
        if not any(row.get("text") == message for row in read_inbox(settings.root, agent)):
            append_inbox(settings.root, agent, message, sender="robert")
        _save(receipt, {"bead": bead, "text": text, "post": post})
        return bead


def dispatch(settings: Settings) -> dict[str, str | None]:
    """One goal-specific local turn, not the general management workday."""
    agent = load_agent(settings.root, "coordinator")
    for row in read_inbox(settings.root, agent, unread_only=True):
        match = re.match(r"New goal intake (cube-[a-z0-9]+);", row.get("text", ""))
        if not match or row.get("from") != "robert":
            continue
        bead = match[1]
        model = next(
            entry.model
            for entry in settings.tiers.get("local", [])
            if entry.runner_name == "hermes@local" and entry.model
        )
        report = execute(
            settings,
            "group-leader",
            bead=bead,
            runner_name="hermes@local",
            model=model,
            agent="coordinator",
            prompt_text=(
                "Handle only this saved goal intake, not general management. "
                "The gateway has already acknowledged it; do not send another acknowledgment. "
                "Within this bounded turn produce a sourced implementation plan artifact, "
                "owner/reviewer assignments, acceptance checks and first actionable handoffs. "
                "Do not inspect project files or old sessions. The intake body is the mandate. "
                "No invented target date: record deadline unspecified. "
                "Laptop sources require cube request liaison and a push, never SSH from ws. "
                "Do not change services or launch the full research workload. "
                "Return RunResult JSON and inline artifact content even if tools are unavailable."
            ),
        )
        if report.ok:
            append_journal(
                settings.root,
                agent,
                body=report.message or "Goal handoff recorded",
                sources=[f"bead:{bead}", f"runs/{report.run_id}"],
            )
            mark_inbox_read(settings.root, agent, [str(row["id"])])
        return {"bead": bead, "run_id": report.run_id, "state": report.state, "error": report.error}
    return {"state": "idle"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", action="store_true")
    args = parser.parse_args()
    settings = load_settings(Path.cwd())
    if args.dispatch:
        print(json.dumps(dispatch(settings)))
        return
    data = json.load(sys.stdin)
    bead = accept(settings, data["post"], data["text"])
    print(json.dumps({"bead": bead}))


if __name__ == "__main__":
    main()
