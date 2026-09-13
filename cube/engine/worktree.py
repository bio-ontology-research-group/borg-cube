"""Git worktrees for code beads, with an optional project-owned directory."""

from __future__ import annotations

from pathlib import Path

from cube.roles import Role
from cube.runners.base import Exec, default_exec

CODE_LABELS = {"kind:program", "kind:experiment", "kind:code"}


class WorktreeError(RuntimeError):
    pass


def worktree_path(root: Path, bead: str, worktrees_dir: Path | None = None) -> Path:
    base = worktrees_dir or root / ".cube" / "wt"
    if not base.is_absolute():
        base = root / base
    return base / bead


def branch_name(bead: str) -> str:
    return f"cube/{bead}"


def needs_worktree(role: Role, labels: list[str]) -> bool:
    """Roles that edit files, on code beads (or the programmer always)."""
    if role.permission_mode != "workspace-write":
        return False
    if role.name == "programmer":
        return True
    return any(label in CODE_LABELS for label in labels)


def _git(root: Path, args: list[str], exec_fn: Exec) -> tuple[int, str]:
    res = exec_fn(["git", *args], cwd=root, env={}, timeout=120.0, stdin_devnull=True)
    return res.returncode, (res.stdout + res.stderr).strip()


def create(
    root: Path,
    bead: str,
    exec_fn: Exec | None = None,
    *,
    worktrees_dir: Path | None = None,
) -> Path:
    exec_fn = exec_fn or default_exec
    path = worktree_path(root, bead, worktrees_dir)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = branch_name(bead)
    rc, out = _git(root, ["rev-parse", "--verify", "--quiet", branch], exec_fn)
    if rc == 0:
        rc, out = _git(root, ["worktree", "add", str(path), branch], exec_fn)
    else:
        rc, out = _git(root, ["worktree", "add", str(path), "-b", branch], exec_fn)
    if rc != 0:
        raise WorktreeError(f"git worktree add failed for {bead}: {out}")
    return path


def remove(
    root: Path,
    bead: str,
    exec_fn: Exec | None = None,
    *,
    force: bool = False,
    worktrees_dir: Path | None = None,
) -> bool:
    exec_fn = exec_fn or default_exec
    path = worktree_path(root, bead, worktrees_dir)
    if not path.exists():
        return False
    args = ["worktree", "remove", str(path)]
    if force:
        args.append("--force")
    rc, out = _git(root, args, exec_fn)
    if rc != 0:
        raise WorktreeError(f"git worktree remove failed for {bead}: {out}")
    return True
