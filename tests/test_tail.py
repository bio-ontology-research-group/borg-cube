from __future__ import annotations

import json
from pathlib import Path

import pytest

from cube.cli import main
from cube.commands import tail


def _event(seq: int, kind: str, ts: str = "2026-09-02T10:00:00+03:00") -> dict[str, object]:
    return {"ts": ts, "seq": seq, "event": kind, "session": "test", "title": f"event {seq}"}


def _write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def test_tail_missing_file_is_empty(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--root", str(repo), "tail", "--json"]) == 0
    assert capsys.readouterr().out == ""


def test_tail_unreadable_file_exits_nonzero(
    repo: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    events_path = repo / "state" / "events.jsonl"
    _write_events(events_path, [_event(1, "error")])
    original_read_bytes = Path.read_bytes

    def deny_events(path: Path) -> bytes:
        if path == events_path:
            raise PermissionError("permission denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deny_events)

    assert main(["--root", str(repo), "tail", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read" in captured.err


def test_tail_filters_limits_and_prints_json_lines(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    events_path = repo / "state" / "events.jsonl"
    events = [
        _event(1, "start", "2026-09-01T10:00:00+03:00"),
        _event(2, "error"),
        _event(3, "attention"),
        _event(4, "error"),
    ]
    _write_events(events_path, events)
    assert (
        main(
            [
                "--root",
                str(repo),
                "tail",
                "--json",
                "--since",
                "2026-09-02T00:00:00+03:00",
                "--kind",
                "error,attention",
                "--limit",
                "2",
            ]
        )
        == 0
    )
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["seq"] for line in lines] == [3, 4]


def test_follow_events_handles_truncation_and_rotation(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.jsonl"
    _write_events(path, [_event(1, "start")])
    sleeps = 0

    def on_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 1:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_event(2, "attention")) + "\n")

    monkeypatch.setattr(tail.time, "sleep", on_sleep)
    stream = tail.follow_events(path)
    assert next(stream)["seq"] == 2

    _write_events(path, [_event(3, "error")])
    assert next(stream)["seq"] == 3

    rotated = tmp_path / "events.jsonl.1"
    path.rename(rotated)
    _write_events(path, [_event(4, "finished")])
    assert next(stream)["seq"] == 4


def test_direct_notify_uses_cockpit_event_schema(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "--root",
                str(repo),
                "notify",
                "--kind",
                "error",
                "--title",
                "Verification failed",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["event"] == "error" and payload["severity"] == "error"
    assert "kind" not in payload


def test_tail_filters_by_bead_and_run(repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    events_path = repo / "state" / "events.jsonl"
    rows = [_event(1, "start"), _event(2, "tool"), _event(3, "finished")]
    rows[0]["bead"] = rows[1]["bead"] = "cube-7"
    rows[0]["run_id"] = "r-1"
    rows[1]["run_id"] = "r-2"
    _write_events(events_path, rows)
    assert main(["--root", str(repo), "tail", "--json", "--bead", "cube-7"]) == 0
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["seq"] for row in out] == [1, 2]
    assert main(["--root", str(repo), "tail", "--json", "--bead", "cube-7", "--run", "r-2"]) == 0
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["seq"] for row in out] == [2]
