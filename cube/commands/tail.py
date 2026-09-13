"""`cube tail`: read or follow the cockpit event log."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.commands import Helpers
from cube.config import Settings

POLL_SECONDS = 0.2
FileIdentity = tuple[int, int]


def parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp: {value}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _parse_line(raw: bytes, path: Path) -> dict[str, Any] | None:
    if not raw.strip():
        return None
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        print(f"cube tail: skipped malformed line in {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(value, dict):
        print(f"cube tail: skipped non-object line in {path}", file=sys.stderr)
        return None
    return value


def _matches(
    event: dict[str, Any],
    since: datetime | None,
    kinds: set[str],
    *,
    bead: str | None = None,
    run: str | None = None,
) -> bool:
    kind = str(event.get("event") or event.get("kind") or "")
    if kinds and kind not in kinds:
        return False
    if bead and str(event.get("bead") or "") != bead:
        return False
    if run and str(event.get("run_id") or "") != run:
        return False
    if since is None:
        return True
    raw = event.get("ts")
    if not isinstance(raw, str):
        return False
    try:
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp >= since


def read_events(
    path: Path,
    *,
    since: datetime | None = None,
    kinds: set[str] | None = None,
    bead: str | None = None,
    run: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read a filtered snapshot. A missing log is an empty snapshot."""
    try:
        raw_lines = path.read_bytes().splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        print(f"cube tail: cannot read {path}: {exc}", file=sys.stderr)
        raise
    selected = [
        event
        for raw in raw_lines
        if (event := _parse_line(raw, path)) is not None
        and _matches(event, since, kinds or set(), bead=bead, run=run)
    ]
    if limit is None:
        return selected
    return selected[-limit:] if limit else []


def _open_snapshot(path: Path) -> tuple[bytes, int, FileIdentity | None]:
    try:
        with path.open("rb") as handle:
            data = handle.read()
            file_stat = os.fstat(handle.fileno())
    except FileNotFoundError:
        return b"", 0, None
    except OSError as exc:
        print(f"cube tail: cannot read {path}: {exc}", file=sys.stderr)
        return b"", 0, None
    return data, len(data), (file_stat.st_dev, file_stat.st_ino)


def _complete_lines(data: bytes) -> tuple[list[bytes], bytes]:
    parts = data.split(b"\n")
    if data.endswith(b"\n"):
        return parts[:-1], b""
    return parts[:-1], parts[-1]


def follow_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield new events while following a path across creation, truncation and rotation."""
    initial, offset, identity = _open_snapshot(path)
    _, pending = _complete_lines(initial)
    while True:
        try:
            file_stat = path.stat()
        except FileNotFoundError:
            time.sleep(POLL_SECONDS)
            continue
        except OSError as exc:
            print(f"cube tail: cannot stat {path}: {exc}", file=sys.stderr)
            time.sleep(POLL_SECONDS)
            continue
        current = (file_stat.st_dev, file_stat.st_ino)
        if identity != current or file_stat.st_size < offset:
            identity = current
            offset = 0
            pending = b""
        if file_stat.st_size > offset:
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    chunk = handle.read()
            except (FileNotFoundError, OSError):
                time.sleep(POLL_SECONDS)
                continue
            offset += len(chunk)
            lines, pending = _complete_lines(pending + chunk)
            for raw in lines:
                if event := _parse_line(raw, path):
                    yield event
        time.sleep(POLL_SECONDS)


def _emit_event(event: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
        return
    kind = event.get("event") or event.get("kind") or "-"
    session = event.get("session") or event.get("run_id") or "-"
    title = event.get("title") or ""
    print(f"{event.get('ts') or '-'}  {kind}  {session}  {title}".rstrip(), flush=True)


def cmd_tail(args: argparse.Namespace, settings: Settings) -> int:
    path = settings.dirs["state"] / "events.jsonl"
    kinds = {kind.strip() for value in args.kind for kind in value.split(",") if kind.strip()}
    initial_limit = args.limit if args.limit is not None else (0 if args.follow else 50)
    try:
        initial = read_events(
            path, since=args.since, kinds=kinds, limit=initial_limit, bead=args.bead, run=args.run
        )
    except OSError:
        return 1
    for event in initial:
        _emit_event(event, args.json)
    if not args.follow:
        return 0
    try:
        for event in follow_events(path):
            if _matches(event, args.since, kinds, bead=args.bead, run=args.run):
                _emit_event(event, args.json)
    except KeyboardInterrupt:
        return 0
    return 0


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit must be non-negative")
    return parsed


def register(sub: Any, helpers: Helpers) -> None:
    sp = sub.add_parser("tail", help="read or follow state/events.jsonl")
    sp.add_argument("--follow", "-f", action="store_true", help="wait for and print new events")
    sp.add_argument("--since", type=parse_iso, help="only events at or after this ISO timestamp")
    sp.add_argument("--kind", action="append", default=[], help="event kind (repeatable)")
    sp.add_argument("--bead", help="only events about this bead (cockpit watch)")
    sp.add_argument("--run", help="only events of this run id")
    sp.add_argument(
        "--limit",
        type=_nonnegative,
        help="initial event count (default: 50, or 0 with -f)",
    )
    helpers.add_json(sp)
    sp.set_defaults(fn=cmd_tail)
