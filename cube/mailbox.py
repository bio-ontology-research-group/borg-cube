"""Locked, durable JSONL mailboxes with explicit message acknowledgements.

All users of a mailbox must use this module, including readers. The sibling
lock file stays in place when the mailbox is atomically replaced.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


@contextmanager
def _locked(path: Path, *, exclusive: bool) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(descriptor)


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    occurrences: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Mailbox {path} contains a non-object record")
        if not row.get("id"):
            canonical = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            occurrences[digest] += 1
            row["id"] = f"legacy-{digest}-{occurrences[digest]}"
        rows.append(row)
    return rows


def _save(path: Path, rows: list[dict[str, Any]]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def read(path: Path, unread_only: bool = False) -> list[dict[str, Any]]:
    """Read a snapshot; legacy records receive stable IDs until first write.

    Invalid JSON fails explicitly so a subsequent write cannot discard data.
    """
    with _locked(path, exclusive=False):
        return [row for row in _load(path) if not unread_only or not row.get("read")]


def append(
    path: Path, text: str, sender: str = "robert", delivered: bool = False
) -> dict[str, Any]:
    """Append once per unread sender/text pair; persist legacy IDs on writes."""
    with _locked(path, exclusive=True):
        rows = _load(path)
        for row in rows:
            if not row.get("read") and row.get("from") == sender and row.get("text") == text:
                return {**row, "duplicate": True}
        record = {
            "id": str(uuid4()),
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "from": sender,
            "text": text,
            "read": False,
            "delivered": delivered,
        }
        rows.append(record)
        _save(path, rows)
        return record


def acknowledge(path: Path, ids: list[str]) -> None:
    """Mark only the supplied snapshot IDs read, preserving later arrivals."""
    if not ids:
        return
    selected = set(ids)
    with _locked(path, exclusive=True):
        rows = _load(path)
        changed = False
        for row in rows:
            if row["id"] in selected and not row.get("read"):
                row["read"] = True
                changed = True
        if changed:
            _save(path, rows)
