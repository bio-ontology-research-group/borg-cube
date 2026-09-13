"""Acknowledged, batched delivery to Robert's configured Mattermost DM."""

from __future__ import annotations

import fcntl
import os
import subprocess
from collections.abc import Callable
from typing import Any

from cube.agents import inbox_path, load_agent
from cube.config import Settings
from cube.disclosure import release_text
from cube.mailbox import acknowledge, read


def deliver_outbox(
    settings: Settings, *, dry_run: bool = True, exec_fn: Callable[..., Any] | None = None
) -> dict[str, Any]:
    agent = load_agent(settings.root, "hermes-ws", validate_role=False)
    if settings.host != agent.host:
        raise ValueError("the Mattermost outbox runs on its owning host")
    profile = settings.hermes.profiles.get("hermes-ws")
    if profile is None or not profile.home_channel:
        raise ValueError("configure hermes.profiles.hermes-ws.home_channel as Robert's DM")
    lock = settings.state_dir() / "fleet-outbox.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        rows = read(inbox_path(settings.root, agent), unread_only=True)
        if not rows:
            return {"status": "empty", "messages": 0}
        selected = []
        chunks = []
        length = 0
        for row in rows:
            text = release_text(str(row.get("text", "")), personal_source=True)
            if len(text) > 13000:
                text = (
                    text[:12500]
                    + "\n[Full detail is available with cube agent inbox hermes-ws --json.]"
                )
            if length + len(text) > 14000:
                break
            selected.append(str(row["id"]))
            chunks.append(text)
            length += len(text) + 2
        message = "\n\n".join(chunks)
        if dry_run:
            return {
                "status": "dry-run",
                "messages": len(selected),
                "text": message,
                "ids": selected,
            }
        proc = (exec_fn or subprocess.run)(
            ["hermes", "send", "--to", f"mattermost:{profile.home_channel}", "--message", message],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "status": "failed",
                "messages": 0,
                "reason": "delivery failed; messages retained",
            }
        acknowledge(inbox_path(settings.root, agent), selected)
        return {"status": "sent", "messages": len(selected), "ids": selected}
    finally:
        os.close(fd)
