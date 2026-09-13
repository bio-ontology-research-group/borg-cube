"""Bounded host probes for status, doctor, and relay commands."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cube.config import HostEntry, Settings

SSH_TIMEOUT_SECONDS = 10
RELAY_TIMEOUT_SECONDS = 120
REMOTE_PATH_PREFIX = "PATH=$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"


@dataclass(frozen=True)
class Peer:
    name: str
    reachable: bool
    sha: str | None = None
    lag_commits: int | None = None
    # "ssh" when this host can probe the peer; "none" when the peer has no ssh
    # route from here and only pulls and relays on its own (the laptop from ws).
    route: str = "ssh"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelayResult:
    host: str
    reachable: bool
    queued: bool
    command: list[str]
    result: Any = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ssh(
    command: list[str], *, timeout: int = SSH_TIMEOUT_SECONDS + 2
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )


def _ssh_command(destination: str, remote: str) -> list[str]:
    return [
        "ssh",
        "-T",
        "-o",
        f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
        "-o",
        "BatchMode=yes",
        destination,
        "--",
        remote,
    ]


def probe_peer(name: str, entry: HostEntry, root: Path) -> Peer:
    """Probe one peer without prompting or waiting beyond the bounded SSH timeout."""
    if not entry.ssh:
        return Peer(name=name, reachable=False, route="none")
    remote = " && ".join(
        (
            shlex.join(["git", "-C", str(root), "rev-parse", "--short", "HEAD"]),
            shlex.join(["git", "-C", str(root), "rev-list", "--count", "HEAD..@{upstream}"]),
        )
    )
    try:
        completed = _ssh(_ssh_command(entry.ssh, remote))
    except (OSError, subprocess.TimeoutExpired):
        return Peer(name=name, reachable=False)
    if completed.returncode:
        return Peer(name=name, reachable=False)
    lines = completed.stdout.splitlines()
    if not lines or not lines[0].strip():
        return Peer(name=name, reachable=False)
    try:
        lag = int(lines[1].strip()) if len(lines) > 1 else None
    except ValueError:
        lag = None
    return Peer(name=name, reachable=True, sha=lines[0].strip(), lag_commits=lag)


def is_orchestration_host(settings: Settings) -> bool:
    """Whether this machine is the configured orchestration host (ws), not a thin client."""
    actual = os.uname().nodename.split(".", 1)[0]
    return actual == settings.host.split(".", 1)[0]


def peer_status(settings: Settings) -> list[dict[str, Any]]:
    """Return the stable status payload for every configured peer."""
    return [
        probe_peer(name, entry, settings.root).as_dict()
        for name, entry in settings.hosts.items()
        if name != settings.host
    ]


def relay(
    settings: Settings,
    target: str,
    cube_args: list[str],
    *,
    dry_run: bool = False,
) -> RelayResult:
    """Run one non-interactive cube command remotely, or leave it for Beads sync."""
    entry = settings.hosts.get(target)
    if entry is None:
        return RelayResult(target, False, True, [], error=f"unknown host {target!r}")
    if not entry.ssh:
        return RelayResult(target, False, True, [], error="peer has no SSH route")
    # Non-interactive ssh has no login PATH, so name the checkout's own cube
    # binary; the checkout lives at the same path on every host.
    remote_args = [
        str(settings.root / ".venv" / "bin" / "cube"),
        "--root",
        str(settings.root),
        *cube_args,
    ]
    if "--json" not in remote_args:
        remote_args.append("--json")
    # Non-interactive ssh also lacks the login PATH for bd, uv and the runners,
    # so prefix the same PATH the systemd units use.
    command = _ssh_command(entry.ssh, REMOTE_PATH_PREFIX + " " + shlex.join(remote_args))
    if dry_run:
        return RelayResult(target, False, True, command, error="dry run")
    try:
        completed = _ssh(command, timeout=RELAY_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RelayResult(target, False, True, command, error=str(exc))
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        return RelayResult(
            target,
            False,
            True,
            command,
            error=detail or f"ssh exited {completed.returncode}",
        )
    try:
        payload: Any = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError:
        payload = completed.stdout.strip()
    return RelayResult(target, True, False, command, result=payload)


# Robert, 2026-09-08 (ADR-0026): artifacts leave the laptop by push only. The
# bead carries the pointer and the checksum; the bytes travel over the existing
# ssh route into the receiving host's drop directory and never through Beads.
FORBIDDEN_DROP_NAMES = (".env", "auth.json")
FORBIDDEN_DROP_PREFIXES = ("password",)
Exec = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class DropResult:
    host: str
    bead: str
    source: str
    remote_path: str | None
    sha256: str | None
    bytes: int | None
    delivered: bool
    commands: list[list[str]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def forbidden_drop_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in FORBIDDEN_DROP_NAMES or lowered.startswith(FORBIDDEN_DROP_PREFIXES)


def drop_file(
    settings: Settings,
    target: str,
    bead_id: str,
    path: Path,
    *,
    beads: Any,
    dry_run: bool = True,
    exec_fn: Exec | None = None,
    origin: str | None = None,
) -> DropResult:
    """Push one file to ``target``'s drop directory and comment the pointer on the bead.

    Refuses a local-only bead, a secret-looking file name, a host without ssh or
    a drop directory. The remote checksum must equal the local one before the
    bead is told; a mismatch or an unreachable host is an error, never a silent
    skip. ``dry_run`` computes the checksum and prints the commands only.
    """
    run = exec_fn or (lambda cmd: _ssh(cmd, timeout=RELAY_TIMEOUT_SECONDS))
    entry = settings.hosts.get(target)

    def failed(error: str, commands: list[list[str]] | None = None) -> DropResult:
        return DropResult(
            target, bead_id, str(path), None, None, None, False, commands or [], error
        )

    if entry is None:
        return failed(f"unknown host {target!r}")
    if not entry.ssh:
        return failed(f"host {target} has no ssh route")
    if not entry.drop:
        return failed(f"host {target} has no drop directory (cube.yaml hosts.{target}.drop)")
    if not path.is_file():
        return failed(f"not a file: {path}")
    if forbidden_drop_name(path.name):
        return failed(f"refusing to drop a secret-looking file: {path.name}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", bead_id):
        return failed(f"not a bead id: {bead_id!r}")
    try:
        bead = beads.show(bead_id)
    except Exception as exc:  # noqa: BLE001 - the ledger's own message is the evidence
        return failed(f"bead {bead_id}: {exc}")
    if not bead:
        return failed(f"bead {bead_id} not found")
    labels = [str(label) for label in (bead.get("labels") or [])]
    if "privacy:local-only" in labels:
        return failed(f"bead {bead_id} is privacy:local-only; nothing leaves this host")
    sha = _sha256(path)
    size = path.stat().st_size
    remote_dir = f"{entry.drop.rstrip('/')}/{bead_id}"
    remote_path = f"{remote_dir}/{path.name}"
    commands = [
        # install -d sets 700 on the drop root too; mkdir -p -m would leave the
        # parent at the remote umask.
        _ssh_command(
            entry.ssh,
            shlex.join(["install", "-d", "-m", "700", entry.drop.rstrip("/"), remote_dir]),
        ),
        [
            "rsync",
            "-a",
            "--chmod=F600,D700",
            "-e",
            f"ssh -o ConnectTimeout={SSH_TIMEOUT_SECONDS} -o BatchMode=yes",
            str(path),
            f"{entry.ssh}:{remote_path}",
        ],
        _ssh_command(entry.ssh, shlex.join(["sha256sum", remote_path])),
    ]
    origin = origin or os.uname().nodename.split(".", 1)[0]
    note = f"artifact: {target}:{remote_path} sha256 {sha} bytes {size} pushed from {origin}"
    if dry_run:
        return DropResult(
            target, bead_id, str(path), remote_path, sha, size, False, commands, "dry run"
        )
    for command in commands[:2]:
        try:
            completed = run(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return failed(str(exc), commands=commands)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            return failed(
                detail or f"{command[0]} exited {completed.returncode}", commands=commands
            )
    try:
        verify = run(commands[2])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return failed(str(exc), commands=commands)
    remote_sha = verify.stdout.split()[0] if verify.stdout.split() else ""
    if verify.returncode or remote_sha != sha:
        return failed(
            f"checksum mismatch after push: local {sha}, remote {remote_sha or '(none)'}",
            commands=commands,
        )
    beads.comment(bead_id, note)
    return DropResult(target, bead_id, str(path), remote_path, sha, size, True, commands)


# Robert, 2026-09-08: FLOPO lives on the laptop first. A ws agent continues
# from the laptop's state, so the liaison ships the checkout as a git bundle
# (every ref), the uncommitted diff as a patch, and a manifest; the working
# tree's data (60G in flopoontology) never travels.
class DropError(RuntimeError):
    """A refused or failed drop; the message is the evidence."""


@dataclass(frozen=True)
class PushedFile:
    remote_path: str
    sha256: str
    bytes: int


def _push_commands(entry: HostEntry, path: Path, remote_dir: str) -> list[list[str]]:
    assert entry.ssh and entry.drop
    remote_path = f"{remote_dir}/{path.name}"
    return [
        _ssh_command(
            entry.ssh,
            shlex.join(["install", "-d", "-m", "700", entry.drop.rstrip("/"), remote_dir]),
        ),
        [
            "rsync",
            "-a",
            "--chmod=F600,D700",
            "-e",
            f"ssh -o ConnectTimeout={SSH_TIMEOUT_SECONDS} -o BatchMode=yes",
            str(path),
            f"{entry.ssh}:{remote_path}",
        ],
        _ssh_command(entry.ssh, shlex.join(["sha256sum", remote_path])),
    ]


def _push_one(entry: HostEntry, path: Path, remote_dir: str, run: Exec) -> PushedFile:
    """Push one file and verify its checksum on the far side; raise DropError otherwise."""
    sha = _sha256(path)
    commands = _push_commands(entry, path, remote_dir)
    for command in commands[:2]:
        try:
            completed = run(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DropError(str(exc)) from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise DropError(detail or f"{command[0]} exited {completed.returncode}")
    try:
        verify = run(commands[2])
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DropError(str(exc)) from exc
    remote_sha = verify.stdout.split()[0] if verify.stdout.split() else ""
    if verify.returncode or remote_sha != sha:
        raise DropError(
            f"checksum mismatch after push of {path.name}: local {sha}, "
            f"remote {remote_sha or '(none)'}"
        )
    return PushedFile(f"{remote_dir}/{path.name}", sha, path.stat().st_size)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed argv, local repository
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=RELAY_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode:
        raise DropError(
            f"git {' '.join(args)} in {repo}: {(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout


def bundle_repository(repo: Path, out_dir: Path) -> list[Path]:
    """Write ``<name>.bundle``, ``<name>.uncommitted.patch`` and ``<name>.manifest.txt``.

    The bundle carries every ref, so the receiver can ``git fetch <bundle>
    <branch>``; the patch is ``git diff HEAD --binary`` (tracked changes only);
    the manifest names HEAD, the branch, its upstream and lag, the status and
    the untracked files, so the receiver knows what it did and did not get.
    """
    if not (repo / ".git").exists():
        raise DropError(f"not a git repository: {repo}")
    name = repo.name
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / f"{name}.bundle"
    _git(repo, "bundle", "create", str(bundle), "--all")
    patch = out_dir / f"{name}.uncommitted.patch"
    patch.write_text(_git(repo, "diff", "HEAD", "--binary"), encoding="utf-8")
    head = _git(repo, "rev-parse", "HEAD").strip()
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    try:
        upstream = _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}").strip()
        ahead = _git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip()
    except DropError:
        upstream, ahead = "(none)", "?"
    status = _git(repo, "status", "--short")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    manifest = out_dir / f"{name}.manifest.txt"
    manifest.write_text(
        f"repository: {repo}\nhead: {head}\nbranch: {branch}\nupstream: {upstream}\n"
        f"ahead_of_upstream: {ahead}\nbundle: {bundle.name} (git bundle create --all)\n"
        f"patch: {patch.name} (git diff HEAD --binary; tracked changes only)\n"
        f"receive: git fetch {bundle.name} {branch} && git checkout -B {branch} FETCH_HEAD"
        f" && git apply {patch.name}\n\nstatus --short:\n{status}\n"
        f"untracked (not shipped):\n{untracked}",
        encoding="utf-8",
    )
    return [bundle, patch, manifest]


def drop_repository(
    settings: Settings,
    target: str,
    bead_id: str,
    repo: Path,
    *,
    beads: Any,
    dry_run: bool = True,
    exec_fn: Exec | None = None,
    origin: str | None = None,
    work_dir: Path | None = None,
) -> DropResult:
    """Bundle a git checkout and push bundle, patch and manifest to the drop directory.

    Same refusals as ``drop_file``; one bead comment names all three artifacts
    with their checksums and how to receive them.
    """
    run = exec_fn or (lambda cmd: _ssh(cmd, timeout=RELAY_TIMEOUT_SECONDS))

    def failed(error: str, commands: list[list[str]] | None = None) -> DropResult:
        return DropResult(
            target, bead_id, str(repo), None, None, None, False, commands or [], error
        )

    entry = settings.hosts.get(target)
    if entry is None:
        return failed(f"unknown host {target!r}")
    if not entry.ssh:
        return failed(f"host {target} has no ssh route")
    if not entry.drop:
        return failed(f"host {target} has no drop directory (cube.yaml hosts.{target}.drop)")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", bead_id):
        return failed(f"not a bead id: {bead_id!r}")
    try:
        bead = beads.show(bead_id)
    except Exception as exc:  # noqa: BLE001 - the ledger's own message is the evidence
        return failed(f"bead {bead_id}: {exc}")
    if not bead:
        return failed(f"bead {bead_id} not found")
    if "privacy:local-only" in [str(label) for label in (bead.get("labels") or [])]:
        return failed(f"bead {bead_id} is privacy:local-only; nothing leaves this host")
    try:
        out_dir = work_dir or (settings.state_dir() / "drop" / bead_id)
        artifacts = bundle_repository(repo, out_dir)
    except DropError as exc:
        return failed(str(exc))
    remote_dir = f"{entry.drop.rstrip('/')}/{bead_id}"
    commands = [cmd for path in artifacts for cmd in _push_commands(entry, path, remote_dir)]
    bundle = artifacts[0]
    if dry_run:
        return DropResult(
            target,
            bead_id,
            str(repo),
            f"{remote_dir}/{bundle.name}",
            _sha256(bundle),
            bundle.stat().st_size,
            False,
            commands,
            "dry run",
        )
    pushed: list[PushedFile] = []
    try:
        for path in artifacts:
            pushed.append(_push_one(entry, path, remote_dir, run))
    except DropError as exc:
        return failed(str(exc), commands=commands)
    manifest_lines = artifacts[2].read_text(encoding="utf-8").splitlines()
    summary = "; ".join(
        line for line in manifest_lines if line.startswith(("branch:", "head:", "ahead_"))
    )
    origin = origin or os.uname().nodename.split(".", 1)[0]
    beads.comment(
        bead_id,
        f"repository {repo.name} pushed from {origin} ({summary}); receive as in the manifest.\n"
        + "\n".join(
            f"artifact: {target}:{item.remote_path} sha256 {item.sha256} bytes {item.bytes}"
            for item in pushed
        ),
    )
    return DropResult(
        target,
        bead_id,
        str(repo),
        pushed[0].remote_path,
        pushed[0].sha256,
        pushed[0].bytes,
        True,
        commands,
    )
