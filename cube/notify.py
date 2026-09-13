"""Event sink: agents, hooks and patrols append to state/events.jsonl; the cockpit tails it.

Line shape is the contract in emacs/INTERFACE.md:
{"ts","seq","source","session","event","severity","title","body_file","run_id","bead","resume_id","data"}
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVENTS = (
    "start",
    "prompt",
    "tool",
    "stop",
    "notification",
    "end",
    "attention",
    "finished",
    "error",
    "approval",
    "queued",
    "goal",
)
SEVERITY = {
    "start": "info",
    "prompt": "info",
    "tool": "info",
    "stop": "info",
    "end": "info",
    "finished": "info",
    "queued": "info",
    "goal": "info",
    "notification": "attention",
    "attention": "attention",
    "approval": "attention",
    "error": "error",
}
# Robert, 2026-09-07: one message per problem. A repeat of the same source, session
# and title inside this window is still logged but carries ``muted: true``; the
# cockpit shows no desktop notification for it. Applies to the loud events only.
MUTED_EVENTS = {"notification", "attention", "approval", "error"}
MUTE_REPEAT_SECONDS = 24 * 3600
CLAUDE_HOOK_EVENTS = {
    "SessionStart": "start",
    "UserPromptSubmit": "prompt",
    "Notification": "notification",
    "Stop": "stop",
    "SessionEnd": "end",
    "PreToolUse": "tool",
    "PostToolUse": "tool",
}
BODY_INLINE_LIMIT = 200
# tool_input keys worth a title, per tool: what the cockpit shows while a run works.
TOOL_TITLE_KEYS = ("file_path", "command", "pattern", "query", "url", "path", "notebook_path")


def tool_title(payload: dict[str, Any]) -> str:
    """One line for a PreToolUse/PostToolUse hook: ``Read cube/foo.py``, ``Bash ls -la``."""
    tool = str(payload.get("tool_name") or "tool")
    tool_input = payload.get("tool_input")
    detail = ""
    if isinstance(tool_input, dict):
        for key in TOOL_TITLE_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                detail = " ".join(value.strip().split())
                break
        if not detail and tool_input.get("description"):
            detail = str(tool_input["description"])
    if len(detail) > 120:
        detail = detail[:117] + "..."
    return f"{tool} {detail}".strip()


def make_event(
    event: str,
    *,
    source: str = "cube",
    session: str | None = None,
    title: str | None = None,
    body: str | None = None,
    run_id: str | None = None,
    bead: str | None = None,
    resume_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event not in EVENTS:
        event = "attention" if event in {"permission", "running"} else "notification"
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "seq": None,
        "source": source,
        "session": session,
        "event": event,
        "severity": SEVERITY.get(event, "info"),
        "title": title,
        "body": body,
        "body_file": None,
        "run_id": run_id,
        "bead": bead,
        "resume_id": resume_id,
        "data": data or {},
    }


def _next_seq(state_dir: Path) -> int:
    counter = state_dir / "events.seq"
    try:
        n = int(counter.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        n = 0
    n += 1
    counter.write_text(str(n), encoding="utf-8")
    return n


def _recent_path(state_dir: Path) -> Path:
    return state_dir / "events-recent.json"


def _load_recent(state_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_recent_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_recent(state_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".events-recent-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, _recent_path(state_dir))


def mute_key(event: dict[str, Any]) -> str | None:
    """The repeat key of a loud event, or None when the event never mutes."""
    if event.get("event") not in MUTED_EVENTS or not event.get("title"):
        return None
    return "\x1f".join(str(event.get(k) or "") for k in ("event", "source", "session", "title"))


def mark_repeat(
    state_dir: Path,
    event: dict[str, Any],
    *,
    now: datetime | None = None,
    window: int = MUTE_REPEAT_SECONDS,
) -> dict[str, Any]:
    """Set ``muted`` on EVENT when the same loud message was logged within the window.

    ``state/events-recent.json`` remembers the first sequence number and time per
    key; the file is pruned to the window on every write.
    """
    key = mute_key(event)
    if key is None:
        return event
    now = now or datetime.now(UTC)
    recent = _load_recent(state_dir)
    fresh: dict[str, dict[str, Any]] = {}
    for k, v in recent.items():
        try:
            first = datetime.fromisoformat(str(v.get("ts")))
        except (TypeError, ValueError):
            continue
        if (now - first).total_seconds() < window:
            fresh[k] = v
    prior = fresh.get(key)
    if prior is not None:
        event["muted"] = True
        prior["repeats"] = int(prior.get("repeats") or 0) + 1
        event.setdefault("data", {})["repeat_of"] = prior.get("seq")
    else:
        fresh[key] = {"ts": now.isoformat(timespec="seconds"), "seq": event.get("seq")}
    _save_recent(state_dir, fresh)
    return event


def append_event(state_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one event; long bodies go to state/bodies/<seq>.md and the line carries body_file.

    Loud events that repeat a recent title are logged with ``muted: true``
    (``mark_repeat``) so the cockpit tells Robert once, not hourly.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    event.setdefault("ts", datetime.now(UTC).isoformat(timespec="seconds"))
    seq = _next_seq(state_dir)
    event["seq"] = seq
    mark_repeat(state_dir, event)
    body = event.pop("body", None)
    if body and len(body) > BODY_INLINE_LIMIT:
        bodies = state_dir / "bodies"
        bodies.mkdir(exist_ok=True)
        (bodies / f"{seq}.md").write_text(body, encoding="utf-8")
        event["body_file"] = f"state/bodies/{seq}.md"
    elif body:
        event.setdefault("data", {})["body"] = body
    with (state_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def write_attention(state_dir: Path, items: list[dict[str, Any]]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "items": items}
    fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".attention-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, state_dir / "attention.json")


def event_from_claude_hook(payload: dict[str, Any], session: str | None = None) -> dict[str, Any]:
    """Map a Claude Code hook payload (stdin JSON) to an events.jsonl line."""
    name = str(payload.get("hook_event_name") or payload.get("event") or "unknown")
    event = CLAUDE_HOOK_EVENTS.get(name, "notification")
    message = str(payload.get("message") or "")
    if event == "tool":
        title = tool_title(payload)
    else:
        title = payload.get("title") or (
            "permission needed"
            if event == "notification" and "permission" in message.lower()
            else name
        )
    data: dict[str, Any] = {"hook": name}
    if event == "tool":
        data["tool"] = payload.get("tool_name")
        data["phase"] = "pre" if name == "PreToolUse" else "post"
    return make_event(
        event,
        source="claude",
        session=session
        or os.environ.get("CUBE_SESSION")
        or Path(str(payload.get("cwd") or ".")).name,
        title=str(title),
        body=message or None,
        run_id=os.environ.get("CUBE_RUN_ID"),
        bead=os.environ.get("CUBE_BEAD"),
        resume_id=str(payload["session_id"]) if payload.get("session_id") else None,
        data=data,
    )


def read_hook_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"message": raw[:2000]}
    return data if isinstance(data, dict) else {"message": str(data)[:2000]}
