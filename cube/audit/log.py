"""state/audit.jsonl: one JSON line per engine action; never rewritten."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def audit(state_dir: Path, action: str, **fields: Any) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    line: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "action": action,
        "pid": os.getpid(),
        "actor": os.environ.get("CUBE_ACTOR") or os.environ.get("USER") or "cube",
    }
    line.update(fields)
    with (state_dir / "audit.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    return line


def read_audit(state_dir: Path, limit: int = 200) -> list[dict[str, Any]]:
    path = state_dir / "audit.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
