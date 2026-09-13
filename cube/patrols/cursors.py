"""state/cursors.json: one record per patrol so reruns are idempotent.

A cursor stores when the patrol last ran, which xids it already reported (so attention
events are not repeated) and patrol-specific keys such as the last processed event time.
"""

from __future__ import annotations

import json
import os
import tempfile
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any


def cursors_path(state_dir: Path) -> Path:
    return state_dir / "cursors.json"


def load_cursors(state_dir: Path) -> dict[str, dict[str, Any]]:
    path = cursors_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}


def load_cursor(state_dir: Path, name: str) -> dict[str, Any]:
    return load_cursors(state_dir).get(name, {})


def save_cursor(state_dir: Path, name: str, data: dict[str, Any]) -> Path:
    """Lock, merge and atomically replace ``name`` while keeping other patrol records."""
    state_dir.mkdir(parents=True, exist_ok=True)
    target = cursors_path(state_dir)
    lock_fd = os.open(state_dir / ".cursors.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        flock(lock_fd, LOCK_EX)
        cursors = load_cursors(state_dir)
        cursors[name] = data
        fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".cursors-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cursors, fh, ensure_ascii=False, indent=1, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
    finally:
        flock(lock_fd, LOCK_UN)
        os.close(lock_fd)
    return target
