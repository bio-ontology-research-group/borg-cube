"""People are contacted only inside contact hours; agents work 24/7."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cube.approvals.deliver import deliver
from cube.approvals.store import ApprovalStore, Intent
from cube.config import ContactHours, Settings
from cube.contact import ContactPolicy
from cube.contact_hours import next_contact_window, within_contact_hours
from cube.patrols import base
from tests.helpers_engine import fixtures

globals().update(fixtures())

HOURS = ContactHours()  # 07:00-19:00 Asia/Riyadh, Sun to Thu
NIGHT = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)  # Wed 23:00 Riyadh
DAY = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)  # Wed 11:00 Riyadh
FRIDAY = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)  # Fri 11:00 Riyadh


def test_contact_window_and_next_opening() -> None:
    assert within_contact_hours(HOURS, DAY)
    assert not within_contact_hours(HOURS, NIGHT)
    assert not within_contact_hours(HOURS, FRIDAY)
    opening = next_contact_window(HOURS, NIGHT)
    assert opening.isoformat() == "2026-09-03T07:00:00+03:00"
    assert next_contact_window(HOURS, FRIDAY).isoformat() == "2026-09-06T07:00:00+03:00"
    assert next_contact_window(HOURS, DAY) == DAY


def _approved_dm(engine_repo: Path) -> tuple[ApprovalStore, str]:
    store = ApprovalStore(engine_repo / "state")
    body = engine_repo / "msg.md"
    body.write_text("---\nto: u123\n---\nHello\n")
    ap = store.create(
        Intent(
            kind="mattermost_dm",
            person="alex-example",
            to="u123",
            action="weekly-checkin",
            body_file=str(body),
        ),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor",
        now=NIGHT,
    )
    store.decide(ap.id, approve=True, by="robert", now=NIGHT)
    return store, ap.id


def test_delivery_to_a_person_waits_for_contact_hours(
    engine_repo: Path, engine_settings: Settings
) -> None:
    store, ap_id = _approved_dm(engine_repo)
    res = deliver(engine_settings, store, ap_id, dry_run=False, now=NIGHT)
    assert res.result == "deferred" and "2026-09-03T07:00" in res.message
    saved = store.get(ap_id)
    assert saved.status == "approved" and saved.delivery["result"] == "deferred"
    # --now overrides the window; the message goes out through the normal path.
    res = deliver(
        engine_settings,
        store,
        ap_id,
        dry_run=True,
        now=NIGHT,
        force=True,
        exec_fn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]
    )
    assert res.result != "deferred"


def test_deliveries_patrol_sends_deferred_messages_inside_the_window(
    engine_repo: Path, engine_settings: Settings
) -> None:
    store, ap_id = _approved_dm(engine_repo)
    deliver(engine_settings, store, ap_id, dry_run=False, now=NIGHT)
    assert "deliveries" in base.names()
    night = base.make("deliveries", now=NIGHT).run(engine_settings, NIGHT.date(), True)
    assert night.data["deferred"] == [ap_id] and night.data["delivered"] == []
    assert "outside contact hours" in night.summary
    day = base.make("deliveries", now=DAY).run(engine_settings, DAY.date(), True)
    assert day.data["deferred"] == [ap_id]
    assert "delivered" in day.summary and "outside" not in day.summary
