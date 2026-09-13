"""Ledger sync between hosts: one ``bd dolt pull`` or ``bd dolt push`` per tick.

The laptop and ws share no ssh route (cube.yaml hosts); the only path between
their ledgers is the Dolt remote on the git remote (cube-24ip). The laptop
worker and the ws scheduler both pull before dispatching and push after, so a
liaison answer written on the laptop reaches the agent on ws that asked, and a
request filed on ws reaches the laptop. Without this the two ledgers diverge
silently, as they did from 2026-09-09 to 2026-09-11 (cube-in1).
"""

from __future__ import annotations

import sys
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.notify import append_event, make_event


def sync_ledger(
    settings: Settings, beads: Beads, direction: str, *, host: str, dry_run: bool
) -> dict[str, Any]:
    """One ``bd dolt pull`` or ``bd dolt push``; a failure is an event, never silent.

    The laptop and ws share no ssh route (cube.yaml hosts); the only path between
    their ledgers is the Dolt remote on the git remote (cube-24ip). Every worker
    tick pulls before dispatching and pushes after, so a liaison answer written on
    the laptop reaches the agent on ws that asked, and a request filed on ws
    reaches the laptop. When the remote is unreachable the tick still runs on the
    local ledger and the failure lands in state/events.jsonl and on stderr.
    """
    if dry_run:
        return {"direction": direction, "ok": True, "dry_run": True}
    result = beads.dolt_pull() if direction == "pull" else beads.dolt_push()
    if result.returncode != 0 and direction == "push":
        # The other host pushed between this tick's pull and push, so the remote
        # moved and Dolt rejected a non-fast-forward (three ticks on ws on
        # 2026-09-08). One more pull, one more push; only then is it a failure.
        if beads.dolt_pull().returncode == 0:
            result = beads.dolt_push()
    ok = result.returncode == 0
    if not ok:
        detail = (result.stderr or result.stdout).strip()[-500:]
        print(f"cube worker: bd dolt {direction} failed on {host}: {detail}", file=sys.stderr)
        append_event(
            settings.state_dir(),
            make_event(
                "error",
                source="worker",
                title=f"ledger sync: bd dolt {direction} failed on {host}",
                body=detail,
                data={"kind": "ledger.sync.failed", "direction": direction, "host": host},
            ),
        )
    return {
        "direction": direction,
        "ok": ok,
        "detail": "" if ok else (result.stderr or result.stdout).strip()[-500:],
    }
