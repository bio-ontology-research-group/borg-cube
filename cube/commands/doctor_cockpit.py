"""Cockpit-specific doctor checks for thin-client version skew."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cube.doctor import Check


@dataclass(frozen=True)
class GitVersion:
    """The minimum checkout identity the cockpit needs to compare."""

    sha: str | None
    dirty: bool | None
    error: str | None = None


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bounded version probe without allowing interactive input."""
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


def git_version(root: Path) -> GitVersion:
    """Return the short SHA and dirty state for ROOT, or a readable error."""
    try:
        sha_result = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root)
        if sha_result.returncode != 0:
            detail = (sha_result.stderr or sha_result.stdout).strip() or "not a git checkout"
            return GitVersion(None, None, detail)
        dirty_result = _run(["git", "status", "--porcelain"], cwd=root)
        if dirty_result.returncode != 0:
            detail = (dirty_result.stderr or dirty_result.stdout).strip() or "git status failed"
            return GitVersion(sha_result.stdout.strip(), None, detail)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitVersion(None, None, str(exc))
    return GitVersion(sha_result.stdout.strip(), bool(dirty_result.stdout.strip()))


def remote_git_version(host: str, root: Path) -> GitVersion:
    """Read a remote checkout identity over a non-interactive bounded ssh call."""
    remote = " && ".join(
        (
            shlex.join(["git", "-C", str(root), "rev-parse", "--short", "HEAD"]),
            shlex.join(["git", "-C", str(root), "status", "--porcelain"]),
        )
    )
    command = [
        "ssh",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "BatchMode=yes",
        host,
        "--",
        remote,
    ]
    try:
        result = _run(command)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitVersion(None, None, str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"ssh exited {result.returncode}"
        return GitVersion(None, None, detail)
    lines = result.stdout.splitlines()
    sha = lines[0].strip() if lines else None
    return GitVersion(sha or None, bool(lines[1:]))


def update_command(host: str, root: Path) -> str:
    """Return the exact safe command that updates ROOT on HOST."""
    return shlex.join(
        [
            "ssh",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            host,
            "--",
            shlex.join(["git", "-C", str(root), "pull", "--ff-only"]),
        ]
    )


def cockpit_check(root: Path, host: str) -> Check:
    """Compare this checkout with HOST and give the recovery command on skew."""
    local = git_version(root)
    if local.error:
        return Check("cockpit:version-skew", False, f"laptop git: {local.error}", severity="warn")
    remote = remote_git_version(host, root)
    if remote.error:
        return Check("cockpit:version-skew", False, f"{host} git: {remote.error}", severity="warn")
    if local.sha == remote.sha:
        return Check(
            "cockpit:version-skew",
            True,
            f"laptop {local.sha}{' dirty' if local.dirty else ''}; "
            f"{host} {remote.sha}{' dirty' if remote.dirty else ''}",
            severity="info",
        )
    return Check(
        "cockpit:version-skew",
        False,
        f"laptop {local.sha}{' dirty' if local.dirty else ''}; "
        f"{host} {remote.sha}{' dirty' if remote.dirty else ''}; "
        f"update {host}: {update_command(host, root)}",
        severity="warn",
    )
