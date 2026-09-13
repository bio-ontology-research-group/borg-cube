from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.engine.attention import build_attention, incident_data
from tests.helpers_engine import FakeBd, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def add_incident(
    fake_bd: FakeBd,
    bead_id: str,
    *,
    service: str,
    host: str,
    scope: str = "internal",
    created: datetime = NOW - timedelta(hours=1),
    since: datetime | None = None,
    status: str = "open",
) -> None:
    down_since = since or created
    fake_bd.add(
        bead_id,
        title=f"DOWN: {service}",
        status=status,
        labels=[
            "kind:incident",
            f"service:{service}",
            f"host:{host}",
            f"scope:{scope}",
            "severity:warning",
        ],
        created_at=created.isoformat(),
        description=(
            "---\n"
            f"xid: incident:{service}\n"
            "provenance: []\n"
            "privacy: internal\n"
            "---\n"
            f"Down since: {down_since.isoformat()}\n"
        ),
    )


def ledger(engine_repo: Path) -> Beads:
    return Beads(bin="bd", cwd=engine_repo, dry_run=True)


def test_incidents_omits_closed_beads(
    engine_settings: Settings, engine_repo: Path, fake_bd: FakeBd
) -> None:
    add_incident(fake_bd, "cube-closed", service="api", host="ws", status="closed")

    assert incident_data(engine_settings, ledger(engine_repo), now=NOW) == {
        "generated": "2026-09-02T09:00:00+00:00",
        "open": [],
        "banner": None,
    }


def test_incidents_reports_a_p1(
    engine_settings: Settings, engine_repo: Path, fake_bd: FakeBd
) -> None:
    add_incident(fake_bd, "cube-p1", service="worker", host="node005")

    data = incident_data(engine_settings, ledger(engine_repo), now=NOW)

    assert data["open"][0]["severity"] == "p1"
    assert data["banner"] == {
        "severity": "p1",
        "text": "worker on node005 since 2026-09-02T08:00:00+00:00; 0 other open incident(s)",
        "count": 0,
        "bead": "cube-p1",
    }


def test_incidents_reports_a_p0_for_external_scope(
    engine_settings: Settings, engine_repo: Path, fake_bd: FakeBd
) -> None:
    add_incident(fake_bd, "cube-p0-scope", service="gateway", host="ws", scope="external")

    assert incident_data(engine_settings, ledger(engine_repo), now=NOW) == {
        "generated": "2026-09-02T09:00:00+00:00",
        "open": [
            {
                "id": "cube-p0-scope",
                "title": "DOWN: gateway",
                "severity": "p0",
                "host": "ws",
                "service": "gateway",
                "since": "2026-09-02T08:00:00+00:00",
                "age_hours": 1.0,
            }
        ],
        "banner": {
            "severity": "p0",
            "text": "gateway on ws since 2026-09-02T08:00:00+00:00; 0 other open incident(s)",
            "count": 0,
            "bead": "cube-p0-scope",
        },
    }


def test_incidents_reports_a_p0_after_configured_age(
    engine_settings: Settings, engine_repo: Path, fake_bd: FakeBd
) -> None:
    (engine_repo / "cube.yaml").write_text(
        (engine_repo / "cube.yaml").read_text(encoding="utf-8")
        + "incidents:\n  p0_after_hours: 2\n",
        encoding="utf-8",
    )
    add_incident(
        fake_bd,
        "cube-p0-age",
        service="scheduler",
        host="ws",
        created=NOW - timedelta(hours=2, minutes=30),
    )

    data = incident_data(engine_settings, ledger(engine_repo), now=NOW)

    assert data["open"][0]["severity"] == "p0"
    assert data["open"][0]["age_hours"] == 2.5


def test_banner_orders_p0_before_p1_and_attention_puts_it_first(
    engine_settings: Settings, engine_repo: Path, fake_bd: FakeBd
) -> None:
    add_incident(
        fake_bd,
        "cube-p1-old",
        service="worker",
        host="node005",
        created=NOW - timedelta(hours=20),
    )
    add_incident(
        fake_bd,
        "cube-p0-scope",
        service="gateway",
        host="ws",
        scope="external",
        created=NOW - timedelta(minutes=30),
    )

    data = incident_data(engine_settings, ledger(engine_repo), now=NOW)
    attention = build_attention(engine_settings, ledger(engine_repo), now=NOW)

    assert [incident["id"] for incident in data["open"]] == ["cube-p0-scope", "cube-p1-old"]
    assert data["banner"]["bead"] == "cube-p0-scope"
    assert attention[0] == {
        "id": "att-incident-cube-p0-scope",
        "kind": "incident",
        "severity": "high",
        "title": "gateway on ws since 2026-09-02T08:30:00+00:00; 1 other open incident(s)",
        "since": "2026-09-02T08:30:00+00:00",
        "age": 1800,
        "target": {"type": "bead", "id": "cube-p0-scope"},
        "actions": ["open"],
    }
    assert len(attention) == 1


def test_incidents_json_shape_and_status_summary(
    engine_repo: Path, fake_bd: FakeBd, capsys: pytest.CaptureFixture[str]
) -> None:
    add_incident(fake_bd, "cube-p0-scope", service="gateway", host="ws", scope="external")

    assert main(["--root", str(engine_repo), "incidents", "--json"]) == 0
    incidents = json.loads(capsys.readouterr().out)
    assert set(incidents) == {"generated", "open", "banner"}
    assert set(incidents["open"][0]) == {
        "id",
        "title",
        "severity",
        "host",
        "service",
        "since",
        "age_hours",
    }
    assert set(incidents["banner"]) == {"severity", "text", "count", "bead"}

    assert main(["--root", str(engine_repo), "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["incidents"] == {
        "count": 1,
        "highest": "p0",
        "banner": incidents["banner"],
    }
