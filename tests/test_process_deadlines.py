"""Real, synthetic child processes only: no models, remote jobs or real sends."""

import os
import sys
import time
from pathlib import Path

from cube.runners.base import default_exec


def test_timeout_reaps_sigterm_ignoring_tool_child(tmp_path):
    code = """
import os, signal, time
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print(os.getpid(), flush=True)
    time.sleep(30)
else:
    time.sleep(30)
"""
    started = time.monotonic()
    result = default_exec([sys.executable, "-c", code], cwd=tmp_path, env={}, timeout=0.4)
    assert result.timed_out and result.returncode == 124
    assert time.monotonic() - started < 5
    pid = int(result.stdout.strip())
    status = Path(f"/proc/{pid}/stat")
    # Orphan zombies await init's reaper, but cannot run or retain model sockets.
    try:
        state = status.read_text().split()[2]
    except (FileNotFoundError, ProcessLookupError):
        state = "gone"
    assert state in {"gone", "Z", "X"}


def test_normal_exit_and_nonzero_output_preserved(tmp_path):
    result = default_exec(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err',file=sys.stderr); sys.exit(7)",
        ],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=2,
    )
    assert result.returncode == 7 and not result.timed_out
    assert result.stdout == "out\n" and result.stderr == "err\n"
