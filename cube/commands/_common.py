"""Helpers shared by the read commands (not a command module: leading underscore)."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from cube.beads import Beads
from cube.config import Settings
from cube.roles import RoleError, load_role
from cube.sources.rkg import load_graph
from cube.sync.context import SourceContext
from cube.sync.reconcile import bead_labels, bead_status, index_existing


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_from(args: argparse.Namespace) -> date | None:
    raw = getattr(args, "today", None)
    return date.fromisoformat(raw) if raw else None


def add_today(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--today", help="override today's date (YYYY-MM-DD) for reproducible output")


def context(
    settings: Settings, args: argparse.Namespace, *, github_details: bool = True
) -> SourceContext:
    return SourceContext(settings, today_from(args), github_details=github_details)


class Ledger:
    """One read of bd; empty when bd is unavailable so read commands still work."""

    def __init__(self, beads: Beads):
        self.by_xid, self.warning = index_existing(beads)
        self.beads = list(self.by_xid.values())

    def id_for(self, xid: str) -> str | None:
        b = self.by_xid.get(xid)
        return str(b["id"]) if b and b.get("id") else None

    def open_with_label(self, label: str) -> list[dict[str, Any]]:
        return [
            b
            for b in self.beads
            if label in bead_labels(b) and bead_status(b) not in {"closed", "done"}
        ]


def people_records(path: Path) -> dict[str, dict[str, Any]]:
    """Read the join table only.  It is not a second people model."""
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = loaded.get("people", loaded) if isinstance(loaded, dict) else {}
    if not isinstance(rows, dict):
        return {}
    return {str(slug): dict(row or {}) for slug, row in rows.items()}


def require_role(settings: Settings, role: str | None) -> str | None:
    if role is None:
        return None
    try:
        load_role(settings.root, role)
    except RoleError as exc:
        raise ValueError(str(exc)) from exc
    return role


def require_person(settings: Settings, person: str | None) -> str | None:
    if person is None:
        return None
    if person not in people_records(settings.root / "people.yaml"):
        raise ValueError(f"no such person in people.yaml: {person}")
    return person


def require_project(settings: Settings, project: str | None) -> str | None:
    """A research-KG project slug, or a checkout configured under ``projects:`` in cube.yaml.

    Robert, 2026-09-07: a software project the cube works on (FLOPO among
    them) is not always a project node in the research KG; the configured
    checkout is enough for the marshal to give it a worktree.
    """
    if project is None:
        return None
    if project in settings.projects:
        return project
    graph = load_graph(settings.dirs["rkg"] / "projects.jsonld")
    if project not in {node.slug for node in graph.projects}:
        raise ValueError(f"no such project in research KG or cube.yaml projects: {project}")
    return project
