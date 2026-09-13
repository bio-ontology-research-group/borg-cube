"""Patrol protocol, report shape, registry and the runner that reconciles findings.

A patrol is deterministic Python (sentinel role, zero tokens). It reads the sources of
record and returns a ``PatrolReport`` whose findings are either ``DesiredBead`` records
(reconciled by xid through ``cube.sync.reconcile`` so no bead is ever created twice) or
``Finding`` notes (informational, surfaced in the digest only). The runner honours
``state/KILL``, records a cursor in ``state/cursors.json`` and refreshes
``state/attention.json`` after an applied run.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from cube.beads import Beads
from cube.config import Settings
from cube.model import Provenance
from cube.notify import append_event, make_event
from cube.patrols.cursors import load_cursor, save_cursor
from cube.sync.derivers import DesiredBead
from cube.sync.reconcile import apply, index_existing, plan, summarize


@dataclass
class Finding:
    """An informational observation that does not deserve a bead (digest FYI material)."""

    key: str
    title: str
    severity: str = "info"  # info | warn | high
    detail: str = ""
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PatrolReport:
    name: str
    today: date
    dry_run: bool
    findings: list[DesiredBead | Finding] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    paused: bool = False
    failed: bool = False
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    ledger_warning: str | None = None

    def beads(self) -> list[DesiredBead]:
        return [f for f in self.findings if isinstance(f, DesiredBead)]

    def notes(self) -> list[Finding]:
        return [f for f in self.findings if isinstance(f, Finding)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "patrol": self.name,
            "today": self.today.isoformat(),
            "dry_run": self.dry_run,
            "paused": self.paused,
            "failed": self.failed,
            "summary": self.summary,
            "beads": [
                {
                    "xid": b.xid,
                    "title": b.title,
                    "kind": b.kind.value,
                    "labels": b.all_labels(),
                    "priority": b.priority,
                    "deadline": b.header.deadline.isoformat() if b.header.deadline else None,
                    "closed": b.closed,
                    "parent_xid": b.parent_xid,
                }
                for b in self.beads()
            ],
            "notes": [n.as_dict() for n in self.notes()],
            "events": self.events,
            "actions": [a for a in self.actions if a.get("op") != "noop"],
            "reconcile": self.data.get("reconcile"),
            "warnings": self.warnings + ([self.ledger_warning] if self.ledger_warning else []),
            "data": {k: v for k, v in self.data.items() if k != "reconcile"},
        }

    def text(self) -> str:
        if self.paused:
            return f"{self.name}: paused (state/KILL present)"
        head = f"{'DRY-RUN ' if self.dry_run else ''}patrol {self.name}: {self.summary}"
        lines = [head]
        for a in self.actions:
            if a.get("op") == "noop":
                continue
            lines.append(
                f"  {a.get('op', ''):13} {a.get('kind', ''):12} {a.get('xid', '')}  "
                f"{str(a.get('title', ''))[:70]}"
            )
        for n in self.notes():
            lines.append(f"  note [{n.severity}] {n.title}")
        for ev in self.events:
            lines.append(f"  event {ev.get('event')}: {ev.get('title')}")
        for w in self.warnings + ([self.ledger_warning] if self.ledger_warning else []):
            lines.append(f"  warning: {w}")
        return "\n".join(lines)


class Patrol(Protocol):
    name: str

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport: ...


PatrolFactory = Callable[..., Patrol]
REGISTRY: dict[str, PatrolFactory] = {}


def normalise(name: str) -> str:
    """systemd instances use hyphens (infra-hygiene); cube.yaml uses underscores."""
    return name.strip().replace("-", "_").lower()


def register(factory: PatrolFactory, name: str) -> None:
    REGISTRY[normalise(name)] = factory


def names() -> list[str]:
    return sorted(REGISTRY)


def make(name: str, **options: Any) -> Patrol:
    key = normalise(name)
    if key not in REGISTRY:
        raise KeyError(f"unknown patrol {name!r}; known: {', '.join(names())}")
    return REGISTRY[key](**options)


# --- helpers for patrol implementations ------------------------------------------------


def prov(source: str, locator: str | None, today: date) -> Provenance:
    return Provenance(source=source, locator=locator, seen=today)


def attention_event(
    patrol: str,
    title: str,
    *,
    body: str | None = None,
    xid: str | None = None,
    event: str = "attention",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"patrol": patrol}
    if xid:
        payload["xid"] = xid
    payload.update(data or {})
    return make_event(
        event, source="patrol", session=f"patrol-{patrol}", title=title, body=body, data=payload
    )


def event_xid(ev: dict[str, Any]) -> str | None:
    data = ev.get("data")
    if isinstance(data, dict) and data.get("xid"):
        return str(data["xid"])
    return None


# --- runner ------------------------------------------------------------------------------


def killed(settings: Settings) -> bool:
    return (settings.state_dir() / "KILL").exists()


def run_patrol(
    settings: Settings,
    patrol: Patrol,
    *,
    today: date | None = None,
    dry_run: bool = True,
    beads: Beads | None = None,
    now: datetime | None = None,
) -> PatrolReport:
    """Run one patrol: KILL check, derive, reconcile by xid, emit new events, save cursor."""
    today = today or date.today()
    now = now or datetime.now(UTC)
    state = settings.state_dir()
    if killed(settings):
        print(f"cube patrol {patrol.name}: paused (state/KILL present)", file=sys.stderr)
        return PatrolReport(patrol.name, today, dry_run, summary="paused", paused=True)

    ledger = beads or Beads(
        bin=settings.beads.bin, cwd=settings.root, dry_run=dry_run, actor=f"cube/{patrol.name}"
    )
    if dry_run:
        ledger.dry_run = True
    try:
        report = patrol.run(settings, today, dry_run, beads=ledger)
    except Exception as exc:  # noqa: BLE001 - one broken patrol must not hide the others
        report = PatrolReport(patrol.name, today, dry_run, summary=f"failed: {exc}", failed=True)
        report.warnings.append(f"{type(exc).__name__}: {exc}")
        report.events.append(
            attention_event(patrol.name, f"patrol {patrol.name} failed: {exc}", event="error")
        )

    desired = report.beads()
    if desired:
        existing, warning = index_existing(ledger)
        report.ledger_warning = warning
        actions = plan(desired, existing)
        report.actions = apply(actions, desired, ledger, existing)
        report.data["reconcile"] = summarize(actions)

    cursor = load_cursor(state, patrol.name)
    seen = set(cursor.get("xids") or [])
    fresh = [ev for ev in report.events if event_xid(ev) is None or event_xid(ev) not in seen]
    report.data["events_suppressed"] = len(report.events) - len(fresh)
    report.events = fresh

    if not dry_run and not report.paused:
        for ev in fresh:
            append_event(state, dict(ev))
        if not report.failed:
            xids = {b.xid for b in desired if not b.closed}
            xids |= {x for x in (event_xid(ev) for ev in fresh) if x}
            record: dict[str, Any] = {
                **{k: v for k, v in cursor.items() if k not in {"xids", "last_run", "today"}},
                **report.data.get("cursor", {}),
                "last_run": now.isoformat(timespec="seconds"),
                "today": today.isoformat(),
                "summary": report.summary,
                "beads": len(desired),
                "events_suppressed": report.data.get("events_suppressed", 0),
                "xids": sorted(xids),
            }
            save_cursor(state, patrol.name, record)
    return report


def run_many(
    settings: Settings,
    patrol_names: list[str],
    *,
    today: date | None = None,
    dry_run: bool = True,
    beads: Beads | None = None,
    options: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[PatrolReport]:
    """Run several patrols in order and refresh state/attention.json after an applied run."""
    reports: list[PatrolReport] = []
    for name in patrol_names:
        patrol = make(name, **(options or {}).get(normalise(name), {}))
        reports.append(
            run_patrol(settings, patrol, today=today, dry_run=dry_run, beads=beads, now=now)
        )
        if reports[-1].paused:
            break
    if not dry_run and reports and not any(r.paused for r in reports):
        from cube.engine.attention import build_attention

        build_attention(
            settings,
            beads or Beads(bin=settings.beads.bin, cwd=settings.root, dry_run=True, actor="cube"),
            now=now,
        )
    return reports
