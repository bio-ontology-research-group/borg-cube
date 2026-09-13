"""Keep new-goal intake out of the model loop. No Hermes source patch needed."""
# ruff: noqa: N999

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

# Site-specific ids come from the environment (the systemd unit and hermes
# profile export them from .env); the hook fails closed when they are missing.
ROOT = Path(os.environ.get("CUBE_ROOT", "~/Public/software/borg-cube")).expanduser()
ROBERT = os.environ.get("CUBE_MM_OWNER_ID", "")
DM = os.environ.get("CUBE_MM_DM_CHANNEL", "")
POLICY = """For Robert's research/project/group instructions, goal intake takes precedence
over domain skills. Relay the exact request to the Cube coordinator, acknowledge
once with the saved id, and end the chat turn. Never investigate an ontology,
inspect project checkouts, search old sessions, or run research inside this DM
when the request is a goal. Background workers own the research. Do not invent
deadlines. Laptop files use the liaison and push route, never SSH from ws.
For ordinary chat use at most two tool calls before answering or handing off.
No progress heartbeat spam. Never claim queued work has already run."""


def register(ctx):
    tickets = {}

    def before(event, **kwargs):
        source = event.source
        if (
            getattr(source.platform, "value", source.platform) != "mattermost"
            or source.user_id != ROBERT
            or source.chat_id != DM
            or source.chat_type != "dm"
            or not re.match(r"(?i)^new goal\s*:", event.text.strip())
        ):
            return None
        # This hook precedes Hermes auth; bind it to immutable sender AND DM ids.
        # The slash handler takes an opaque one-use ticket, never client JSON.
        now = time.monotonic()
        for key in list(tickets):
            if now - tickets[key][0] > 300:
                del tickets[key]
        ticket = uuid.uuid4().hex
        tickets[ticket] = (now, {"post": event.message_id, "text": event.text.strip()})
        return {"action": "rewrite", "text": "/cube-intake " + ticket}

    async def intake(ticket):
        saved = tickets.pop(ticket.strip(), None)
        if saved is None or time.monotonic() - saved[0] > 300:
            return "Send New goal: followed by your request in your DM with Hermes."
        try:
            proc = await asyncio.create_subprocess_exec(
                str(ROOT / ".venv/bin/python"),
                "-m",
                "cube.gateway_intake",
                cwd=str(ROOT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "PATH": ":".join(
                        [str(Path("~/.local/bin").expanduser()), os.environ.get("PATH", "")]
                    ),
                },
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(json.dumps(saved[1]).encode()), timeout=30
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return "Goal intake timed out. It may be saved; retry the same post safely."
            if proc.returncode:
                return (
                    "Goal intake failed. Please check Cube intake before resubmitting; "
                    "omit credentials and grades/HR details."
                )
            bead = json.loads(stdout)["bead"]
            # systemd coalesces concurrent starts. A small retry timer checks the
            # durable inbox if a message arrives during an active workday.
            wake = await asyncio.create_subprocess_exec(
                "systemctl",
                "--user",
                "start",
                "--no-block",
                "cube-goal-coordinator.service",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                code = await asyncio.wait_for(wake.wait(), timeout=3)
            except TimeoutError:
                wake.kill()
                await wake.wait()
                code = 1
            if code:
                return (
                    f"Recorded as {bead} for the coordinator. Background dispatch is unavailable; "
                    "the request is safely queued."
                )
            return (
                f"Recorded as {bead} and queued for the coordinator. "
                "Research runs in the background; no progress-message flood."
            )
        except Exception:
            # Never fall through to an LLM or expose command output/credentials.
            return "Goal intake encountered an error. Please check Cube intake before resubmitting."

    ctx.register_hook("pre_gateway_dispatch", before)
    ctx.register_command(
        "cube-intake", intake, description="Record a research goal without a model call"
    )
    ctx.register_system_prompt_section("cube.goal-intake", POLICY)
