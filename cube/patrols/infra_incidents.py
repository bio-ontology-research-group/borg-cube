"""Infra-incidents patrol: hermes-infra ``infra.py`` transitions -> incident beads.

``infra.py check`` writes one JSON line per state transition to
``~/.hermes/state/infra/events.jsonl`` (``time, service, from, to, msg, group, severity,
scope, section``) and only reports DOWN after ``notify.fail_threshold`` (2) consecutive
failures, so every DOWN transition here is already confirmed. The patrol reads events after
the cursor's ``last_time`` and opens or closes ``incident:<service>`` beads accordingly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cube.beads import Beads
from cube.config import Settings
from cube.patrols.base import Finding, PatrolReport, attention_event, register
from cube.patrols.cursors import load_cursor
from cube.patrols.infra import DOWN, OK, WARN, incident_bead, needs_robert, warning_bead
from cube.sync.derivers import DesiredBead


def default_events_path(settings: Settings) -> Path:
    return settings.dirs["hermes_home"] / "state" / "infra" / "events.jsonl"


def _string_or_none(value: object) -> str | None:
    return None if not value else str(value)


def read_events(path: Path) -> list[dict[str, Any]]:
    """Accept infra.py's events.jsonl (one object per line) or events.json (a JSON array)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        return []
    out: list[dict[str, Any]] = []
    if stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return []
        out = [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    else:
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                out.append(item)
    return sorted(out, key=lambda e: str(e.get("time") or ""))


def beads_for_transition(
    ev: dict[str, Any], today: date, source: str
) -> tuple[list[DesiredBead], dict[str, Any] | None]:
    name = str(ev["service"])
    to = str(ev.get("to") or "").upper()
    frm = str(ev.get("from") or "")
    when = str(ev.get("time") or "")
    msg = str(ev.get("msg") or "")
    locator = f"{when} {name} {frm} -> {to}"
    group = _string_or_none(ev.get("group"))
    scope = _string_or_none(ev.get("scope"))
    severity = _string_or_none(ev.get("severity"))
    if to == DOWN:
        bead = incident_bead(
            name,
            today=today,
            source=source,
            locator=locator,
            msg=msg,
            since=when,
            group=group,
            scope=scope,
            severity=severity,
            extra_body=[f"Transition: {frm} -> DOWN (confirmed after repeated failures)"],
        )
        event = attention_event(
            "infra_incidents",
            f"DOWN: {name} ({ev.get('scope') or 'internal'}) since {when}: {msg[:100]}",
            body=bead.body,
            xid=bead.xid,
            data={"service": name, "scope": ev.get("scope"), "severity": ev.get("severity")},
        )
        return [
            bead,
            warning_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason="escalated to incident",
            ),
        ], event
    if to == WARN and not needs_robert(scope, severity):
        # Robert, 2026-09-07: twenty "WARN: vm-x: failed units" beads sat in the ready
        # queue. hermes-infra keeps the state and alerts the infrastructure owner; the cube records
        # the transition and closes any earlier bead for the service.
        return [
            incident_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason=f"state WARN at {when}",
            ),
            warning_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason=f"WARN is information; hermes-infra holds the state ({when})",
            ),
        ], None
    if to == WARN:
        return [
            incident_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason=f"state WARN at {when}",
            ),
            warning_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
            ),
        ], None
    if to == OK:
        return [
            incident_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason=f"recovered at {when}",
            ),
            warning_bead(
                name,
                today=today,
                source=source,
                locator=locator,
                msg=msg,
                group=group,
                scope=scope,
                severity=severity,
                closed=True,
                close_reason=f"recovered at {when}",
            ),
        ], None
    return [], None


@dataclass
class InfraIncidentsPatrol:
    name: str = "infra_incidents"
    events_path: Path | None = None
    since: str | None = None  # override the cursor (ISO time); None = cursor, "" = everything

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> PatrolReport:
        report = PatrolReport(self.name, today, dry_run)
        path = self.events_path or default_events_path(settings)
        if not path.exists():
            report.summary = f"no hermes-infra events at {path}"
            report.findings.append(
                Finding("infra-events:missing", report.summary, "info", source=str(path))
            )
            return report
        events = read_events(path)
        cursor = load_cursor(settings.state_dir(), self.name)
        last_time = self.since if self.since is not None else cursor.get("last_time")
        fresh = [e for e in events if not last_time or str(e.get("time") or "") > str(last_time)]
        downs = warns = recovered = 0
        for ev in fresh:
            if not ev.get("service"):
                continue
            made, att = beads_for_transition(ev, today, str(path))
            report.findings.extend(made)
            if att:
                report.events.append(att)
            to = str(ev.get("to") or "").upper()
            if to == DOWN:
                downs += 1
            elif to == WARN:
                warns += 1
            elif to == OK:
                recovered += 1
        newest = max((str(e.get("time") or "") for e in events), default=last_time or "")
        report.data["cursor"] = {"last_time": newest}
        report.data["events_read"] = len(events)
        report.data["events_new"] = len(fresh)
        report.summary = (
            f"{len(fresh)} new transition(s) since {last_time or 'the beginning'}: "
            f"{downs} down, {warns} warn, {recovered} recovered"
        )
        return report


register(InfraIncidentsPatrol, "infra_incidents")
