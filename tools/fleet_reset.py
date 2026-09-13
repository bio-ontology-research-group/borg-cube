#!/usr/bin/env python3
"""Approved clean-slate reset: explicit runtime targets, verified recoverable moves.

Stop cube/gateway writers and cross-host ledger sync before --apply. This tool
never stops processes, changes credentials, deletes GitHub history, or starts work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

RUNTIME = ("state", "runs", ".cube", ".beads")
HERMES_RUNTIME = (
    "sessions",
    "memories",
    "logs",
    "cron",
    "state",
    "state.db",
    "state.db-wal",
    "state.db-shm",
    "pending_messages",
    "gateway_state.json",
    "kanban",
    "kanban.db",
    "kanban.db-wal",
    "kanban.db-shm",
    "verification_evidence.db",
    "verification_evidence.db-wal",
    "verification_evidence.db-shm",
    "cache",
    "plans",
    "workspace",
    "sandboxes",
    "processes.json",
    "audio_cache",
    "image_cache",
)


def targets(root: Path, hermes: Path | None = None) -> list[Path]:
    result = [root / name for name in RUNTIME]
    for definition in sorted((root / "agents").glob("*.yaml")):
        directory = root / "agents" / definition.stem
        if directory.is_dir() and not directory.is_symlink():
            result.extend(
                p for p in directory.iterdir() if p.name not in {"charter.md", "charter.md.bak"}
            )
    if hermes:
        result.extend(hermes / name for name in HERMES_RUNTIME)
        # Only fleet profiles. Other personal Hermes profiles are out of scope.
        for profile in ("cube-worker", "cube-student-local", "advisor", "scribe", "concierge"):
            result.extend(hermes / "profiles" / profile / name for name in HERMES_RUNTIME)
    return sorted((p for p in result if p.exists() or p.is_symlink()), key=str)


def digest(path: Path) -> str:
    """Hash names and bytes, treating symlinks as links without reading their targets."""
    total = hashlib.sha256()
    entries = [path]
    if path.is_dir() and not path.is_symlink():
        entries += sorted(path.rglob("*"))
    for item in entries:
        total.update(str(item.relative_to(path)).encode() + b"\0")
        if item.is_symlink():
            total.update(b"link\0" + os.readlink(item).encode())
        elif item.is_file():
            total.update(b"file\0")
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total.update(chunk)
        elif item.is_dir():
            total.update(b"dir\0")
        else:
            # No live sockets/pipes should remain after quiescing writers.
            raise ValueError(f"Special file prevents safe reset: {item}")
    return total.hexdigest()


def archive(root: Path, destination: Path, hermes: Path | None, *, apply: bool) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if not (root / "cube.yaml").is_file() or not (root / "cube").is_dir():
        raise ValueError("Not a cube checkout")
    if destination == root or root in destination.parents:
        raise ValueError("Archive must be outside active checkout")
    selected = targets(root, hermes)
    for path in selected:
        if path == destination or path in destination.parents:
            raise ValueError("Archive overlaps a reset target")
    plan = {"root": str(root), "archive": str(destination), "targets": [str(p) for p in selected]}
    if not apply:
        return plan
    if destination.exists():
        raise ValueError("Archive already exists; inspect partial recovery instead of overwriting")
    destination.mkdir(parents=True, mode=0o700)
    records = []
    manifest = destination / "manifest.json"
    for index, source in enumerate(selected):
        checksum = digest(source)
        target = destination / f"{index:03d}-{source.name}"
        record = {
            "source": str(source),
            "archive": str(target),
            "sha256": checksum,
            "status": "moving",
        }
        records.append(record)
        manifest.write_text(json.dumps({**plan, "records": records}, indent=2))
        shutil.move(str(source), str(target))
        if digest(target) != checksum:
            raise ValueError(f"Archive checksum mismatch: {target}")
        record["status"] = "verified"
        manifest.write_text(json.dumps({**plan, "records": records}, indent=2))
    for name in ("state", "runs"):
        (root / name).mkdir(mode=0o700)
    return {"archive": str(destination), "verified_targets": len(records)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--hermes", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(archive(args.root, args.archive, args.hermes, apply=args.apply), indent=2))
