"""`cube attention`: what Robert should look at, loudest first (emacs/INTERFACE.md shape)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cube.approvals import ApprovalStore
from cube.beads import Beads, BeadsError
from cube.config import Settings
from cube.engine import lease as leases
from cube.engine.context import bead_labels
from cube.notify import write_attention

SEVERITY_RANK = {"high": 0, "normal": 1, "low": 2}
ERROR_WINDOW = timedelta(hours=24)
INCIDENT_SEVERITY_RANK = {"p0": 0, "p1": 1, "p2": 2}
DEFAULT_INCIDENT_P0_AFTER_HOURS = 24.0
DOWN_SINCE_RE = re.compile(r"^Down since:\s*(.+?)\s*$", re.MULTILINE)


def _age(since: str | None, now: datetime) -> int:
    if not since:
        return 0
    try:
        ts = datetime.fromisoformat(since)
    except ValueError:
        return 0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return max(0, int((now - ts).total_seconds()))


def _parse_timestamp(value: object) -> tuple[str | None, datetime | None]:
    """Return a serialisable ISO timestamp and its UTC-aware form when valid."""
    if not value:
        return None, None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return text, parsed


def _label_value(labels: list[str], prefix: str) -> str | None:
    return next((label[len(prefix) :] for label in labels if label.startswith(prefix)), None)


def _incident_p0_after_hours(settings: Settings) -> float:
    """Read the incident escalation age from cube.yaml without widening Settings yet."""
    try:
        import yaml

        raw = yaml.safe_load((settings.root / "cube.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return DEFAULT_INCIDENT_P0_AFTER_HOURS
    if not isinstance(raw, dict):
        return DEFAULT_INCIDENT_P0_AFTER_HOURS
    incidents = raw.get("incidents")
    if not isinstance(incidents, dict):
        return DEFAULT_INCIDENT_P0_AFTER_HOURS
    try:
        hours = float(incidents.get("p0_after_hours", DEFAULT_INCIDENT_P0_AFTER_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_INCIDENT_P0_AFTER_HOURS
    return hours if hours >= 0 else DEFAULT_INCIDENT_P0_AFTER_HOURS


def _incident_since(bead: dict[str, Any], labels: list[str]) -> tuple[str | None, datetime | None]:
    labelled = _label_value(labels, "since:")
    if labelled:
        return _parse_timestamp(labelled)
    match = DOWN_SINCE_RE.search(str(bead.get("description") or ""))
    if match:
        return _parse_timestamp(match.group(1))
    return _parse_timestamp(bead.get("created_at") or bead.get("created"))


def _incident_record(bead: dict[str, Any], now: datetime, p0_after_hours: float) -> dict[str, Any]:
    labels = bead_labels(bead)
    since, _ = _incident_since(bead, labels)
    _, created = _parse_timestamp(bead.get("created_at") or bead.get("created"))
    age_hours = (
        round(max(0.0, (now - created).total_seconds() / 3600), 2) if created is not None else None
    )
    external = _label_value(labels, "scope:") == "external"
    severity = "p0" if external or (age_hours is not None and age_hours >= p0_after_hours) else "p1"
    return {
        "id": str(bead.get("id") or ""),
        "title": str(bead.get("title") or bead.get("id") or ""),
        "severity": severity,
        "host": _label_value(labels, "host:"),
        "service": _label_value(labels, "service:"),
        "since": since,
        "age_hours": age_hours,
    }


def incident_data(
    settings: Settings, beads: Beads | None = None, *, now: datetime | None = None
) -> dict[str, Any]:
    """Materialise the open incident ledger view and its single cockpit banner."""
    now = now or datetime.now(UTC)
    open_incidents: list[dict[str, Any]] = []
    if beads is not None and beads.available():
        try:
            p0_after_hours = _incident_p0_after_hours(settings)
            open_incidents = [
                _incident_record(bead, now, p0_after_hours)
                for bead in beads.list_issues("--label", "kind:incident", "--status", "open")
            ]
        except BeadsError:
            open_incidents = []
    open_incidents.sort(
        key=lambda incident: (
            INCIDENT_SEVERITY_RANK[str(incident["severity"])],
            -(float(incident["age_hours"]) if incident["age_hours"] is not None else -1.0),
            str(incident["id"]),
        )
    )
    if not open_incidents:
        return {"generated": now.isoformat(timespec="seconds"), "open": [], "banner": None}

    loudest = open_incidents[0]
    other_count = len(open_incidents) - 1
    service = str(loudest["service"] or "unknown service")
    host = str(loudest["host"] or "unknown host")
    since = str(loudest["since"] or "unknown time")
    banner = {
        "severity": loudest["severity"],
        "text": f"{service} on {host} since {since}; {other_count} other open incident(s)",
        "count": other_count,
        "bead": loudest["id"],
    }
    return {
        "generated": now.isoformat(timespec="seconds"),
        "open": open_incidents,
        "banner": banner,
    }


def _item(
    kind: str,
    ident: str,
    severity: str,
    title: str,
    since: str | None,
    now: datetime,
    target: dict[str, Any],
    actions: list[str],
) -> dict[str, Any]:
    return {
        "id": f"att-{ident}",
        "kind": kind,
        "severity": severity,
        "title": title,
        "since": since,
        "age": _age(since, now),
        "target": target,
        "actions": actions,
    }


ACK_FILE = "attention-acks.json"


def acknowledged(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Attention ids Robert has dismissed (`cube attention ack`), with when and why."""
    path = state_dir / ACK_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def acknowledge(
    state_dir: Path, item_id: str, *, reason: str = "", now: datetime | None = None
) -> dict[str, Any]:
    """Record that ITEM_ID needs no further attention. Errors older than the window are pruned."""
    now = now or datetime.now(UTC)
    acks = acknowledged(state_dir)
    acks[item_id] = {"ts": now.isoformat(timespec="seconds"), "reason": reason}
    keep = {
        key: value
        for key, value in acks.items()
        if _age(str(value.get("ts") or ""), now) <= 7 * 24 * 3600
    }
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / ACK_FILE).write_text(
        json.dumps(keep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return keep[item_id]


def recent_errors(state_dir: Path, now: datetime, limit: int = 20) -> list[dict[str, Any]]:
    path = state_dir / "events.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines()[-2000:]:
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict) or ev.get("event") != "error":
            continue
        if _age(str(ev.get("ts") or ""), now) > ERROR_WINDOW.total_seconds():
            continue
        out.append(ev)
    return out[-limit:]


def build_attention(
    settings: Settings, beads: Beads | None = None, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    state_dir = settings.state_dir()
    items: list[dict[str, Any]] = []
    incidents = incident_data(settings, beads, now=now)
    banner = incidents["banner"]
    if banner is not None:
        loudest = incidents["open"][0]
        age = loudest["age_hours"]
        items.append(
            {
                "id": f"att-incident-{banner['bead']}",
                "kind": "incident",
                "severity": "high",
                "title": banner["text"],
                "since": loudest["since"],
                "age": int(float(age) * 3600) if age is not None else 0,
                "target": {"type": "bead", "id": banner["bead"]},
                "actions": ["open"],
            }
        )

    for ap in ApprovalStore(state_dir).items("pending"):
        items.append(
            _item(
                "approval",
                ap.id,
                "high",
                f"Approval: {ap.summary()}",
                ap.created,
                now,
                {"type": "approval", "id": ap.id, "file": ap.body_file or ap.diff_file},
                ["approve", "reject", "open"],
            )
        )

    if beads is not None and beads.available():
        try:
            for bead in beads.list_issues("--label", "needs:robert", "--status", "open"):
                labels = bead_labels(bead)
                if "kind:incident" in labels or "approved:robert" in labels:
                    continue
                bid = str(bead.get("id") or "")
                items.append(
                    _item(
                        "needs_robert",
                        bid,
                        "normal",
                        str(bead.get("title") or bid),
                        str(bead.get("created_at") or bead.get("created") or "") or None,
                        now,
                        {"type": "bead", "id": bid},
                        ["open", "close"],
                    )
                )
        except BeadsError:
            pass
        try:
            for bead in beads.list_issues("--status", "blocked"):
                bid = str(bead.get("id") or "")
                if "needs:robert" in bead_labels(bead):
                    continue
                items.append(
                    _item(
                        "finding",
                        f"blocked-{bid}",
                        "low",
                        f"Blocked: {bead.get('title') or bid}",
                        str(bead.get("updated_at") or bead.get("created_at") or "") or None,
                        now,
                        {"type": "bead", "id": bid},
                        ["open"],
                    )
                )
        except BeadsError:
            pass

    for lease in leases.dead_leases(state_dir, now):
        items.append(
            _item(
                "session",
                f"lease-{lease.bead}",
                "normal",
                f"Expired lease on {lease.bead} ({lease.role}, run {lease.run_id})",
                lease.expires,
                now,
                {"type": "run", "id": lease.run_id, "bead": lease.bead},
                ["open", "close"],
            )
        )

    for ev in recent_errors(state_dir, now):
        ident = str(ev.get("run_id") or ev.get("seq") or "err")
        items.append(
            _item(
                "error",
                f"error-{ident}",
                "high",
                str(ev.get("title") or "error"),
                str(ev.get("ts") or "") or None,
                now,
                {
                    "type": "run" if ev.get("run_id") else "session",
                    "id": ev.get("run_id") or ev.get("session"),
                    "bead": ev.get("bead"),
                },
                ["open"],
            )
        )

    acks = acknowledged(state_dir)
    if acks:
        items = [item for item in items if item["id"] not in acks]

    items.sort(
        key=lambda item: (
            0 if item["kind"] == "incident" else 1,
            SEVERITY_RANK.get(str(item["severity"]), 9),
            -int(item["age"]),
        )
    )
    write_attention(state_dir, items)
    return items
