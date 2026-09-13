"""`cube worker --slots N --once|--loop [--dry-run]`: the Marshal loop."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from cube.commands import Helpers
from cube.config import Settings
from cube.engine.marshal import tick
from cube.ledger_sync import sync_ledger

__all__ = ["cmd_worker", "register", "sync_ledger"]


def _slots(settings: Settings, n: int | None) -> dict[str, int]:
    slots = dict(settings.slots)
    if n is not None:
        total = max(0, n)
        # cap every tier at the requested total; the tiers still bound each other
        slots = {k: min(v, total) for k, v in slots.items()}
    return slots


def cmd_worker(args: argparse.Namespace, settings: Settings, helpers: Helpers) -> int:
    worker_host = args.host or settings.host
    if settings.hosts and worker_host not in settings.hosts:
        print(f"cube worker: unknown host {worker_host!r}", file=sys.stderr)
        return 2
    beads = helpers.beads(settings, args.dry_run)
    if not beads.available():
        # A silent "dispatched 0" from a timer whose PATH lacks bd hid a stalled
        # pipeline for an hour; fail loudly instead.
        print(
            f"cube worker: bd not found ({settings.beads.bin}); check PATH in the systemd unit",
            file=sys.stderr,
        )
        return 2
    ticks: list[dict[str, Any]] = []
    syncs: list[dict[str, Any]] = []
    while True:
        if not args.no_sync:
            syncs.append(
                sync_ledger(settings, beads, "pull", host=worker_host, dry_run=args.dry_run)
            )
        plan = tick(
            settings,
            beads,
            slots=_slots(settings, args.slots),
            max_dispatch=args.slots,
            dry_run=args.dry_run,
            host=worker_host,
        )
        ticks.append(plan.as_dict())
        if not args.no_sync:
            syncs.append(
                sync_ledger(settings, beads, "push", host=worker_host, dry_run=args.dry_run)
            )
        # --once is the default; --loop keeps ticking until the kill switch appears
        if plan.killed or not args.loop:
            break
        time.sleep(args.interval)
    last = ticks[-1]
    failed_syncs = [s for s in syncs if not s["ok"]]
    text = (
        "KILL present; worker stopped"
        if last["killed"]
        else f"{'DRY-RUN ' if args.dry_run else ''}dispatched {len(last['dispatched'])}, "
        f"skipped {len(last['skipped'])}, expired {len(last['expired'])} lease(s)"
        + (f"; ledger sync failed {len(failed_syncs)}x" if failed_syncs else "")
    )
    helpers.emit(
        args, {"ok": not last["killed"], "ticks": ticks, "last": last, "syncs": syncs}, text
    )
    return 6 if last["killed"] else 0


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("worker", help="marshal: dispatch ready beads into free slots")
    sp.add_argument("--slots", type=int, help="max dispatches per tick (default: cube.yaml slots)")
    sp.add_argument("--host", help="dispatch this host's beads (default: settings.host)")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="one tick (default)")
    g.add_argument("--loop", action="store_true", help="tick every --interval seconds until KILL")
    sp.add_argument("--interval", type=int, default=1800, help="seconds between ticks (--loop)")
    sp.add_argument("--dry-run", dest="dry_run", action="store_true", help="plan only")
    sp.add_argument(
        "--no-sync",
        dest="no_sync",
        action="store_true",
        help="skip bd dolt pull before and bd dolt push after each tick",
    )
    helpers.add_json(sp)
    sp.set_defaults(fn=lambda a, s: cmd_worker(a, s, helpers))
