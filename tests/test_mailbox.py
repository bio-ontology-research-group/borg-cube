from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

from cube import mailbox


def test_snapshot_ack_preserves_later_arrival(tmp_path: Path) -> None:
    path = tmp_path / "inbox.jsonl"
    first = mailbox.append(path, "first")
    UUID(first["id"])
    snapshot = mailbox.read(path, unread_only=True)
    later = mailbox.append(path, "later")
    mailbox.acknowledge(path, [row["id"] for row in snapshot])
    assert mailbox.read(path, unread_only=True) == [later]
    mailbox.acknowledge(path, [first["id"], "unknown"])
    assert mailbox.read(path, unread_only=True) == [later]


def test_concurrent_append_and_ack(tmp_path: Path) -> None:
    path = tmp_path / "inbox.jsonl"
    original = mailbox.append(path, "original")
    barrier = Barrier(9)

    def append(index: int) -> None:
        barrier.wait()
        mailbox.append(path, f"arrival {index}")

    def acknowledge() -> None:
        barrier.wait()
        mailbox.acknowledge(path, [original["id"]])

    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [pool.submit(append, index) for index in range(8)]
        futures.append(pool.submit(acknowledge))
        for future in futures:
            future.result()
    assert len(mailbox.read(path)) == 9
    assert {row["text"] for row in mailbox.read(path, True)} == {
        f"arrival {index}" for index in range(8)
    }


def test_concurrent_duplicates_and_redelivery(tmp_path: Path) -> None:
    path = tmp_path / "inbox.jsonl"
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: mailbox.append(path, "same", "researcher"), range(24)))
    assert sum(bool(row.get("duplicate")) for row in results) == 23
    assert len({row["id"] for row in results}) == 1
    assert len(mailbox.read(path)) == 1
    mailbox.append(path, "same", "other researcher")
    mailbox.acknowledge(path, [results[0]["id"]])
    new = mailbox.append(path, "same", "researcher")
    assert new["id"] != results[0]["id"]
    assert len(mailbox.read(path, True)) == 2


def test_legacy_ids_survive_migration_with_identical_rows(tmp_path: Path) -> None:
    path = tmp_path / "inbox.jsonl"
    legacy = {"ts": "old", "from": "robert", "text": "repeat", "read": False}
    path.write_text((json.dumps(legacy) + "\n") * 2, encoding="utf-8")
    before = mailbox.read(path)
    assert before == mailbox.read(path)
    assert before[0]["id"] != before[1]["id"]
    mailbox.acknowledge(path, [before[0]["id"]])
    after = mailbox.read(path)
    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert mailbox.read(path, True) == [before[1]]
    assert all("id" in json.loads(line) for line in path.read_text().splitlines())
    mailbox.append(path, "new")
    assert mailbox.read(path)[:2] == after


def test_corruption_is_not_silently_discarded(tmp_path: Path) -> None:
    path = tmp_path / "inbox.jsonl"
    raw = '{"text":"valid"}\nbroken\n'
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        mailbox.append(path, "new")
    assert path.read_text() == raw


def test_missing_mailbox(tmp_path: Path) -> None:
    path = tmp_path / "new" / "inbox.jsonl"
    assert mailbox.read(path) == []
    mailbox.acknowledge(path, ["absent"])
    assert not path.exists()
