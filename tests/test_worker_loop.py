"""cube worker --loop keeps ticking until the kill switch; --once (the default) ticks once."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import cube.commands.worker as worker
from cube.beads import Beads
from cube.cli import main


def _plan(killed: bool) -> SimpleNamespace:
    body = {"killed": killed, "dispatched": [], "skipped": [], "expired": []}
    return SimpleNamespace(killed=killed, as_dict=lambda: dict(body))


def _patch_tick(monkeypatch: pytest.MonkeyPatch, kill_after: int) -> dict[str, int]:
    calls = {"ticks": 0, "sleeps": 0}

    def fake_tick(*_args: object, **_kwargs: object) -> SimpleNamespace:
        calls["ticks"] += 1
        return _plan(killed=calls["ticks"] >= kill_after)

    monkeypatch.setattr(worker, "tick", fake_tick)
    monkeypatch.setattr(
        worker.time, "sleep", lambda _s: calls.__setitem__("sleeps", calls["sleeps"] + 1)
    )
    return calls


def test_loop_ticks_until_kill(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_tick(monkeypatch, kill_after=3)
    main(["--root", str(repo), "worker", "--loop", "--interval", "1", "--dry-run"])
    assert calls["ticks"] == 3, "--loop must keep ticking until the kill switch appears"
    assert calls["sleeps"] == 2


def test_once_is_the_default(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_tick(monkeypatch, kill_after=99)
    assert main(["--root", str(repo), "worker", "--dry-run"]) == 0
    assert calls == {"ticks": 1, "sleeps": 0}


def test_worker_host_option_reaches_marshal(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def fake_tick(*_args: object, **kwargs: object) -> SimpleNamespace:
        seen.append(kwargs.get("host") if isinstance(kwargs.get("host"), str) else None)
        return _plan(killed=False)

    monkeypatch.setattr(worker, "tick", fake_tick)

    assert main(["--root", str(repo), "worker", "--once", "--host", "laptop", "--dry-run"]) == 0
    assert seen == ["laptop"]


def test_worker_fails_loudly_when_bd_is_missing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("cube.beads.Beads.available", lambda self: False)
    ticks = _patch_tick(monkeypatch, kill_after=99)
    assert main(["--root", str(repo), "worker", "--once", "--dry-run"]) == 2
    assert "bd not found" in capsys.readouterr().err
    assert ticks == {"ticks": 0, "sleeps": 0}


def test_every_tick_pulls_the_ledger_first_and_pushes_after(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cube-24ip: the laptop and ws share only the Dolt remote; nothing synced it.

    A liaison answer written on the laptop reached ws never. Every worker tick
    now pulls before dispatching and pushes after, on both hosts.
    """
    order: list[str] = []

    def fake_tick(*_args: object, **_kwargs: object) -> SimpleNamespace:
        order.append("tick")
        return _plan(killed=False)

    monkeypatch.setattr(worker, "tick", fake_tick)
    monkeypatch.setattr(Beads, "available", lambda self: True)
    monkeypatch.setattr(
        Beads,
        "dolt_pull",
        lambda self: (order.append("pull"), SimpleNamespace(returncode=0, stdout="", stderr=""))[1],
    )
    monkeypatch.setattr(
        Beads,
        "dolt_push",
        lambda self: (order.append("push"), SimpleNamespace(returncode=0, stdout="", stderr=""))[1],
    )
    assert main(["--root", str(repo), "worker", "--once", "--host", "laptop"]) == 0
    assert order == ["pull", "tick", "push"]

    order.clear()
    assert main(["--root", str(repo), "worker", "--once", "--no-sync"]) == 0
    assert order == ["tick"]


def test_a_failed_sync_is_an_event_not_a_silent_tick(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    monkeypatch.setattr(worker, "tick", lambda *a, **k: _plan(killed=False))
    monkeypatch.setattr(Beads, "available", lambda self: True)
    monkeypatch.setattr(
        Beads,
        "dolt_pull",
        lambda self: SimpleNamespace(returncode=1, stdout="", stderr="remote unreachable"),
    )
    monkeypatch.setattr(
        Beads, "dolt_push", lambda self: SimpleNamespace(returncode=0, stdout="", stderr="")
    )
    assert main(["--root", str(repo), "worker", "--once"]) == 0
    err = capsys.readouterr().err
    assert "bd dolt pull failed" in err and "remote unreachable" in err
    events = [
        json.loads(line)
        for line in (repo / "state" / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    failed = [e for e in events if (e.get("data") or {}).get("kind") == "ledger.sync.failed"]
    assert failed and failed[0]["event"] == "error" and "pull" in failed[0]["title"]


def test_a_rejected_push_pulls_once_and_pushes_again(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ws, 2026-09-08: the laptop pushed between pull and push; Dolt rejected the
    non-fast-forward three ticks in a row and each was an error in the cockpit."""
    order: list[str] = []
    pushes = iter([1, 0])

    monkeypatch.setattr(
        worker, "tick", lambda *a, **k: (order.append("tick"), _plan(killed=False))[1]
    )
    monkeypatch.setattr(Beads, "available", lambda self: True)
    monkeypatch.setattr(
        Beads,
        "dolt_pull",
        lambda self: (order.append("pull"), SimpleNamespace(returncode=0, stdout="", stderr=""))[1],
    )
    monkeypatch.setattr(
        Beads,
        "dolt_push",
        lambda self: (
            order.append("push"),
            SimpleNamespace(returncode=next(pushes), stdout="", stderr="non-fast-forward"),
        )[1],
    )
    assert main(["--root", str(repo), "worker", "--once"]) == 0
    assert order == ["pull", "tick", "push", "pull", "push"]
    assert "dolt push failed" not in capsys.readouterr().err
