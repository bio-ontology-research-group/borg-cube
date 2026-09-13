"""Read-only lookups bounded to a host's readable directories (ADR-0027).

Robert, 2026-09-08: the laptop liaison may list, search and quote files under
``hosts.laptop.readable`` (``~/Documents/papers``, ``~/Public/software``) on its
own; anything else waits for his approval. Claude Code bounds the Read tool by
path rule, but Grep and Glob are not path-bounded, so ``cube lookup`` is the
search: every operation resolves its path (symlinks included) and refuses one
that leaves the readable roots. Secret-shaped files are refused even inside.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cube.config import Settings
from cube.disclosure import release_text

MAX_ENTRIES = 200
MAX_MATCHES = 200
MAX_LINES = 200
MAX_LINE_CHARS = 400
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".work", ".cube"}
# Never quoted, listed or searched, whatever directory they are in (CLAUDE.md secrets rule).
SECRET_NAME = re.compile(
    r"^(?:\.env(?:\..*)?|auth\.json|password.*|.*\.pem|.*\.key|id_(?:rsa|ed25519|ecdsa)(?:\.pub)?|"
    r"\.git|\.netrc|\.authinfo(?:\.gpg)?|\.pgpass|.*htpasswd.*|.*token.*|.*secret.*|.*credentials?.*)$",
    re.IGNORECASE,
)


class LookupError(ValueError):
    """A lookup that must not run: outside the roots, missing, or a secret."""


@dataclass(frozen=True)
class Bounded:
    path: Path
    root: Path
    denied: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Roots:
    """Resolved readable roots and the resolved directories that stay closed."""

    readable: tuple[Path, ...]
    denied: tuple[Path, ...]


def _resolved(paths: list[Path], *, strict: bool) -> tuple[Path, ...]:
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve(strict=strict)
        except OSError:
            continue
        if resolved not in out:
            out.append(resolved)
    return tuple(out)


def readable_roots(settings: Settings, host: str | None = None) -> Roots:
    return Roots(
        readable=_resolved(settings.readable_dirs(host), strict=True),
        # A denied directory that does not exist is still denied by name.
        denied=_resolved(settings.unreadable_dirs(host), strict=False),
    )


def _under(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _denied(resolved: Path, denied: tuple[Path, ...]) -> Path | None:
    return next((base for base in denied if _under(resolved, base)), None)


def resolve_within(path_text: str, roots: Roots) -> Bounded:
    """PATH_TEXT resolved (symlinks followed) and proven to lie under a readable root."""
    if not roots.readable:
        raise LookupError("no readable directories are configured for this host")
    raw = Path(path_text).expanduser()
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise LookupError(f"no such path: {path_text}") from exc
    except OSError as exc:
        raise LookupError(f"cannot resolve {path_text}: {exc}") from exc
    if any(SECRET_NAME.match(part) for part in resolved.parts):
        raise LookupError("refused: path contains a secret-shaped component")
    closed = _denied(resolved, roots.denied) or _denied(raw.absolute(), roots.denied)
    if closed is not None:
        raise LookupError(
            f"refused: {path_text} is under {closed}, which stays closed; a read there "
            "needs Robert's approval (cube request liaison ..., ADR-0027)"
        )
    for root in roots.readable:
        if not _under(resolved, root):
            continue
        if any(SECRET_NAME.match(part) for part in resolved.relative_to(root).parts):
            raise LookupError(f"refused: {path_text} looks like a secret")
        return Bounded(resolved, root, roots.denied)
    listed = ", ".join(str(root) for root in roots.readable)
    raise LookupError(
        f"outside the readable directories ({listed}): {path_text}; a read there needs "
        "Robert's approval (cube request liaison ..., ADR-0027)"
    )


def _walk(bounded: Bounded) -> list[Path]:
    """Files under a bounded directory, never following directory symlinks."""
    if bounded.path.is_file():
        return [bounded.path]
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(bounded.path, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS
            and not SECRET_NAME.match(d)
            and _denied(here / d, bounded.denied) is None
        )
        for name in sorted(filenames):
            if SECRET_NAME.match(name):
                continue
            files.append(here / name)
    return files


def _inside(path: Path, root: Path, denied: tuple[Path, ...] = ()) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return (
        _under(resolved, root)
        and _denied(resolved, denied) is None
        and not any(SECRET_NAME.match(p) for p in resolved.relative_to(root).parts)
    )


def op_ls(bounded: Bounded, *, limit: int = MAX_ENTRIES) -> dict[str, Any]:
    if bounded.path.is_file():
        stat = bounded.path.stat()
        return {
            "path": str(bounded.path),
            "entries": [_entry(bounded.path, stat)],
            "truncated": False,
        }
    entries = []
    children = sorted(bounded.path.iterdir(), key=lambda p: p.name.lower())
    for child in children:
        if SECRET_NAME.match(child.name) or _denied(child, bounded.denied) is not None:
            continue
        try:
            stat = child.lstat()
        except OSError:
            continue
        entries.append(_entry(child, stat))
    return {
        "path": str(bounded.path),
        "entries": entries[:limit],
        "truncated": len(entries) > limit,
    }


def _entry(path: Path, stat: os.stat_result) -> dict[str, Any]:
    kind = "dir" if path.is_dir() else "link" if path.is_symlink() else "file"
    return {"name": path.name, "kind": kind, "size": int(stat.st_size)}


def op_find(
    bounded: Bounded, *, name: str | None = None, limit: int = MAX_ENTRIES
) -> dict[str, Any]:
    matches = [
        str(path) for path in _walk(bounded) if name is None or fnmatch.fnmatch(path.name, name)
    ]
    return {"path": str(bounded.path), "files": matches[:limit], "truncated": len(matches) > limit}


def op_grep(
    bounded: Bounded,
    pattern: str,
    *,
    include: str | None = None,
    ignore_case: bool = False,
    limit: int = MAX_MATCHES,
) -> dict[str, Any]:
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise LookupError(f"bad pattern: {exc}") from exc
    hits: list[dict[str, Any]] = []
    truncated = False
    for path in _walk(bounded):
        if include and not fnmatch.fnmatch(path.name, include):
            continue
        if not _inside(path, bounded.root, bounded.denied):
            continue
        try:
            with path.open("rb") as fh:
                head = fh.read(4096)
                if b"\0" in head:
                    continue
                fh.seek(0)
                content = fh.read(2_000_001)
                if len(content) > 2_000_000 or release_text(
                    content.decode("utf-8", errors="replace"), personal_source=True
                ).startswith("[withheld:"):
                    continue
                fh.seek(0)
                for number, raw in enumerate(fh, start=1):
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if regex.search(line):
                        hits.append(
                            {"file": str(path), "line": number, "text": line[:MAX_LINE_CHARS]}
                        )
                        if len(hits) >= limit:
                            truncated = True
                            break
        except OSError:
            continue
        if truncated:
            break
    return {"path": str(bounded.path), "pattern": pattern, "matches": hits, "truncated": truncated}


def op_head(bounded: Bounded, *, start: int = 1, lines: int = 60) -> dict[str, Any]:
    if not bounded.path.is_file():
        raise LookupError(f"not a file: {bounded.path}")
    if not _inside(bounded.path, bounded.root, bounded.denied):
        raise LookupError(f"outside the readable directories: {bounded.path}")
    lines = max(1, min(lines, MAX_LINES))
    start = max(1, start)
    out: list[str] = []
    with bounded.path.open("rb") as fh:
        content = fh.read(2_000_001)
        if len(content) > 2_000_000:
            raise LookupError("file too large for a bounded lookup")
        if release_text(content.decode("utf-8", errors="replace"), personal_source=True).startswith(
            "[withheld:"
        ):
            raise LookupError("source contains credentials or personal records; remains local")
        fh.seek(0)
        if b"\0" in fh.read(4096):
            raise LookupError(f"binary file: {bounded.path}")
        fh.seek(0)
        for number, raw in enumerate(fh, start=1):
            if number < start:
                continue
            if number >= start + lines:
                break
            out.append(
                f"{number}:{raw.decode('utf-8', errors='replace').rstrip(chr(10))[:MAX_LINE_CHARS]}"
            )
    return {"path": str(bounded.path), "start": start, "lines": out}


def op_git_log(bounded: Bounded, *, count: int = 20) -> dict[str, Any]:
    if not (bounded.path / ".git").exists():
        raise LookupError(f"not a git checkout: {bounded.path}")
    count = max(1, min(count, 100))
    cmd = [
        "git",
        "-C",
        str(bounded.path),
        "log",
        "--no-decorate",
        "--date=short",
        f"--max-count={count}",
        "--format=%h %ad %an: %s",
    ]
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LookupError(f"git log failed: {exc}") from exc
    if completed.returncode:
        raise LookupError((completed.stderr or completed.stdout).strip() or "git log failed")
    return {"path": str(bounded.path), "commits": completed.stdout.rstrip("\n").splitlines()}
