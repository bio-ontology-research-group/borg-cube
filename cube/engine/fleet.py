"""`cube fleet`: tmux sessions on this host joined with the event log and live leases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cube.config import Settings
from cube.engine import lease as leases
from cube.runners.base import Exec, default_exec

TMUX_FORMAT = "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}"


def adopted_sessions(state_dir: Path) -> list[dict[str, Any]]:
    """Read adopted tmux metadata, accepting early list and mapping shapes."""
    path = state_dir / "sessions.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw: Any = data.get("sessions") if isinstance(data, dict) else data
    if isinstance(raw, dict):
        raw = [dict(value, session=key) for key, value in raw.items() if isinstance(value, dict)]
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict) and item.get("session")]


def record_adopted_session(state_dir: Path, record: dict[str, Any]) -> None:
    """Upsert one adopted tmux session in the cockpit's persistent state."""
    state_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        item for item in adopted_sessions(state_dir) if item.get("session") != record["session"]
    ]
    rows.append(dict(record))
    path = state_dir / "sessions.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"sessions": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def tmux_sessions(exec_fn: Exec | None = None) -> list[dict[str, Any]]:
    exec_fn = exec_fn or default_exec
    res = exec_fn(
        ["tmux", "ls", "-F", TMUX_FORMAT], cwd=Path.cwd(), env={}, timeout=10.0, stdin_devnull=True
    )
    if res.returncode != 0:
        return []
    out: list[dict[str, Any]] = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        created = None
        if len(parts) > 1 and parts[1].isdigit():
            created = datetime.fromtimestamp(int(parts[1]), UTC).isoformat(timespec="seconds")
        out.append(
            {
                "name": parts[0],
                "tmux": parts[0],
                "created": created,
                "attached": bool(len(parts) > 2 and parts[2] not in ("", "0")),
                "windows": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
            }
        )
    return out


def last_events(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Last event per session name and per run id."""
    path = state_dir / "events.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines()[-5000:]:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        for key in (ev.get("session"), ev.get("run_id")):
            if key:
                out[str(key)] = ev
    return out


def fleet(settings: Settings, *, exec_fn: Exec | None = None) -> dict[str, Any]:
    state_dir = settings.state_dir()
    events = last_events(state_dir)
    adopted = {str(item["session"]): item for item in adopted_sessions(state_dir)}
    sessions: list[dict[str, Any]] = []
    for s in tmux_sessions(exec_fn):
        name = str(s["name"])
        short = name.removeprefix("cube/")
        ev = events.get(short) or events.get(name) or {}
        adopted_record = adopted.get(name) or adopted.get(short)
        sessions.append(
            {
                "name": short,
                "tmux": name,
                "kind": "run"
                if short.startswith("run-")
                else ("cube" if name.startswith("cube/") else "other"),
                "started": s.get("created"),
                "attached": s.get("attached"),
                "last_event": ev.get("event"),
                "last_event_ts": ev.get("ts"),
                "resume_id": (
                    adopted_record.get("resume_id") if adopted_record else ev.get("resume_id")
                ),
                "run_id": ev.get("run_id"),
                "bead": adopted_record.get("bead") if adopted_record else ev.get("bead"),
                "project": adopted_record.get("project") if adopted_record else None,
                "cwd": adopted_record.get("cwd") if adopted_record else None,
                "runner": adopted_record.get("runner") if adopted_record else None,
                "adopted": adopted_record is not None,
            }
        )
    live = [x.as_dict() for x in leases.live_leases(state_dir)]
    for lease in live:
        ev = events.get(f"run-{lease['run_id']}") or events.get(str(lease["run_id"])) or {}
        lease["last_event"] = ev.get("event")
        lease["last_event_ts"] = ev.get("ts")
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": settings.host,
        "sessions": sessions,
        "leases": live,
        "kill": (state_dir / "KILL").exists(),
    }
