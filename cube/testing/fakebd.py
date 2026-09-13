"""A small file-backed ``bd`` replacement for tests and rehearsals."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

FAKE_BD = r'''#!/usr/bin/env python3
"""Fake bd used only for deterministic offline workflow tests."""
import json, os, sys

args = sys.argv[1:]
log = os.environ["FAKE_BD_LOG"]
data_path = os.environ["FAKE_BD_DATA"]
with open(log, "a") as handle:
    handle.write(json.dumps(args) + "\n")
data = json.load(open(data_path)) if os.path.exists(data_path) else {"beads": {}}
beads = data.setdefault("beads", {})

def save():
    with open(data_path, "w") as handle:
        json.dump(data, handle, indent=1)

def value(flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default

def dependencies(bead_id):
    return [pair[1] for pair in data.get("deps", []) if pair[0] == bead_id]

def blocking_dependencies(bead_id):
    return [
        row.get("id") for row in beads.get(bead_id, {}).get("dependencies", [])
        if row.get("dependency_type", "blocks") == "blocks"
    ]

if not args:
    sys.exit(0)
cmd = args[0]
if cmd == "--version":
    print("bd fake 0.0")
    sys.exit(0)
if cmd == "prime":
    print("FAKE PRIME CONTEXT: bd ready, bd show, bd close")
    sys.exit(0)
if cmd == "ready":
    requested = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--label"]
    out = []
    for bead in beads.values():
        if bead.get("status", "open") != "open" or bead.get("blocked"):
            continue
        if requested and not all(label in bead.get("labels", []) for label in requested):
            continue
        if any(
            beads.get(dep, {}).get("status", "open") not in ("closed", "done")
            for dep in blocking_dependencies(bead["id"])
        ):
            continue
        out.append(bead)
    print(json.dumps(out))
    sys.exit(0)
if cmd == "blocked":
    out = []
    for bead in beads.values():
        open_deps = [
            dep
            for dep in blocking_dependencies(bead["id"])
            if beads.get(dep, {}).get("status", "open") not in ("closed", "done")
        ]
        if open_deps:
            row = dict(bead)
            row["blocked_by"] = open_deps
            out.append(row)
    print(json.dumps(out))
    sys.exit(0)
if cmd == "show":
    bead = beads.get(args[1])
    if bead is None:
        print(f"no such bead {args[1]}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(bead))
    sys.exit(0)
if cmd == "list":
    out = list(beads.values())
    if "--label" in args:
        label = value("--label")
        out = [bead for bead in out if label in bead.get("labels", [])]
    if "--status" in args:
        status = value("--status")
        out = [bead for bead in out if bead.get("status", "open") == status]
    print(json.dumps(out))
    sys.exit(0)
if cmd == "create":
    number = data.get("next", 100) + 1
    data["next"] = number
    bead_id = f"cube-{number}"
    labels = value("--labels", "").split(",") if value("--labels", "") else []
    # Real bd copies the parent's labels onto a child created with --parent.
    parent_id = value("--parent")
    if parent_id and parent_id in beads:
        for inherited in beads[parent_id].get("labels", []):
            if inherited not in labels:
                labels.append(inherited)
    bead = {
        "id": bead_id,
        "title": args[1],
        "labels": labels,
        "status": "open",
        "description": value("--description", ""),
        "external_ref": value("--external-ref"),
        "priority": int(value("--priority", 2)),
        "issue_type": value("--type", "task"),
        "parent": value("--parent"),
        "acceptance_criteria": value("--acceptance"),
        "due": value("--due"),
        "created_at": f"2026-09-03T00:00:{number % 60:02d}+00:00",
    }
    beads[bead_id] = bead
    for dependency in (value("--deps", "") or "").split(","):
        if dependency:
            data.setdefault("deps", []).append([bead_id, dependency])
    save()
    print(bead_id)
    sys.exit(0)
if cmd == "comment":
    beads.setdefault(args[1], {"id": args[1], "labels": []}).setdefault("comments", []).append(
        {"text": args[2], "author": "fake"}
    )
    save()
    sys.exit(0)
if cmd == "update":
    bead = beads.setdefault(args[1], {"id": args[1], "labels": []})
    if "--description" in args:
        bead["description"] = value("--description")
    elif "--priority" in args:
        bead["priority"] = int(value("--priority"))
    elif "--status" in args:
        bead["status"] = value("--status")
        if value("--status") == "open":
            bead.pop("assignee", None)
    else:
        bead["assignee"] = "cube"
        if "--claim" in args:
            bead["status"] = "in_progress"
    save()
    sys.exit(0)
if cmd == "close":
    bead = beads.setdefault(args[1], {"id": args[1], "labels": []})
    bead["status"] = "closed"
    bead["close_reason"] = value("--reason")
    save()
    sys.exit(0)
if cmd == "label":
    bead = beads.setdefault(args[2], {"id": args[2], "labels": []})
    if args[1] == "add" and args[3] not in bead["labels"]:
        bead["labels"].append(args[3])
    if args[1] == "remove" and args[3] in bead["labels"]:
        bead["labels"].remove(args[3])
    save()
    sys.exit(0)
if cmd == "dep" and len(args) >= 4 and args[1] == "add":
    pair = [args[2], args[3]]
    if pair not in data.setdefault("deps", []):
        data["deps"].append(pair)
    bead = beads.setdefault(args[2], {"id": args[2], "labels": []})
    dep_type = value("--type", "blocks")
    record = {"id": args[3], "dependency_type": dep_type}
    if record not in bead.setdefault("dependencies", []):
        bead["dependencies"].append(record)
    save()
    sys.exit(0)
print(json.dumps([]))
sys.exit(0)
'''


class FakeBd:
    """Manage the fake executable and its file-backed ledger."""

    def __init__(self, directory: Path):
        self.dir = directory / "bin"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = directory / "bd.log"
        self.data = directory / "bd.json"
        script = self.dir / "bd"
        script.write_text(FAKE_BD, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        self.data.write_text(json.dumps({"beads": {}, "next": 100}), encoding="utf-8")

    def add(self, bead_id: str, **fields: Any) -> None:
        data = json.loads(self.data.read_text(encoding="utf-8"))
        data["beads"][bead_id] = {"id": bead_id, "labels": [], "status": "open", **fields}
        self.data.write_text(json.dumps(data), encoding="utf-8")

    def bead(self, bead_id: str) -> dict[str, Any]:
        data = json.loads(self.data.read_text(encoding="utf-8"))
        return dict(data["beads"].get(bead_id) or {})

    def beads(self) -> dict[str, dict[str, Any]]:
        data = json.loads(self.data.read_text(encoding="utf-8"))
        return dict(data["beads"])

    def dependencies(self, bead_id: str) -> list[str]:
        data = json.loads(self.data.read_text(encoding="utf-8"))
        return [pair[1] for pair in data.get("deps", []) if pair[0] == bead_id]

    def dependency_records(self, bead_id: str) -> list[dict[str, Any]]:
        return list(self.bead(bead_id).get("dependencies") or [])

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def env(self, base: MutableMapping[str, str] | None = None) -> dict[str, str]:
        source = dict(base or os.environ)
        source.update(
            {
                "PATH": f"{self.dir}{os.pathsep}{source.get('PATH', '')}",
                "FAKE_BD_LOG": str(self.log),
                "FAKE_BD_DATA": str(self.data),
            }
        )
        return source

    def install(self, monkeypatch: Any) -> None:
        for key, value in self.env().items():
            if key in {"PATH", "FAKE_BD_LOG", "FAKE_BD_DATA"}:
                monkeypatch.setenv(key, value)

    @contextmanager
    def installed(self) -> Iterator[None]:
        before = {key: os.environ.get(key) for key in ("PATH", "FAKE_BD_LOG", "FAKE_BD_DATA")}
        os.environ.update(self.env())
        try:
            yield
        finally:
            for key, value in before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
