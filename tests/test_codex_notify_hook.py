"""emacs/bin/cube-codex-notify turns a Codex notify payload into a cube event."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "emacs" / "bin" / "cube-codex-notify"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_wrapper_writes_stop_event(repo: Path) -> None:
    env = dict(
        os.environ,
        CUBE_ROOT=str(repo),
        CUBE_PROGRAM=f"{sys.executable} -m cube.cli",
        CUBE_SESSION="cube/km-codex",
    )
    # CUBE_PROGRAM must be one executable: use a tiny shim
    shim = repo / "cube-shim"
    shim.write_text(f'#!/bin/sh\nexec {sys.executable} -m cube.cli "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    env["CUBE_PROGRAM"] = str(shim)
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "abc",
        "cwd": "/x",
        "last-assistant-message": "done",
    }
    proc = subprocess.run(
        [str(HOOK), json.dumps(payload)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    events = (repo / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    last = json.loads(events[-1])
    assert last["event"] == "stop" and last["session"] == "cube/km-codex"
    assert last["title"] == "Codex finished its turn"


def test_wrapper_exits_zero_without_payload() -> None:
    proc = subprocess.run([str(HOOK)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
