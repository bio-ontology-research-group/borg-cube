"""Fleet communications integration: mocked transport, real stores and decisions."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from cube import mailbox, sysops
from cube.config import HermesProfile
from cube.decisions import DecisionError, announce_pending, decide_from_reply, pending_decisions
from cube.fleet_delivery import deliver_outbox
from cube.resources import load_limits


@pytest.fixture
def fleet(settings, monkeypatch):
    settings.fleet_enabled = True
    settings.decisions.systems = [settings.host]
    settings.hermes.profiles["hermes-ws"] = HermesProfile(home_channel="robert-dm")
    monkeypatch.setattr(
        "cube.agents.load_agent",
        lambda root, name, **kw: SimpleNamespace(
            name=name,
            host=settings.host,
        ),
    )
    monkeypatch.setattr(
        "cube.fleet_delivery.load_agent",
        lambda root, name, **kw: SimpleNamespace(name=name, host=settings.host),
    )
    return settings


def bundle(fleet, reason="Service health check failed"):
    return sysops.propose(
        fleet,
        {
            "host": fleet.host,
            "commands": [["systemctl", "restart", "example"]],
            "rationale": reason,
            "impact": "Brief service interruption",
            "prechecks": [["test", "-f", "/tmp/ready"]],
            "postchecks": [["systemctl", "is-active", "example"]],
            "rollback": [["systemctl", "stop", "example"]],
            "evidence": ["bead:cube-l4tf"],
        },
        dry_run=False,
    )


def outbox(fleet):
    return fleet.root / "agents" / "hermes-ws" / "inbox.jsonl"


def test_failed_delivery_retains_messages(fleet):
    message = mailbox.append(outbox(fleet), "Please review one system change")
    result = deliver_outbox(
        fleet, dry_run=False, exec_fn=lambda *a, **kw: SimpleNamespace(returncode=1)
    )
    assert result["status"] == "failed"
    assert [row["id"] for row in mailbox.read(outbox(fleet), True)] == [message["id"]]


def test_batch_delivery_acknowledges_only_original_snapshot(fleet):
    mailbox.append(outbox(fleet), "First completed report")
    mailbox.append(outbox(fleet), "Second completed report")
    calls = []

    def send(argv, **kwargs):
        calls.append(argv)
        mailbox.append(outbox(fleet), "Arrived while transport was sending")
        return SimpleNamespace(returncode=0)

    result = deliver_outbox(fleet, dry_run=False, exec_fn=send)
    assert result["status"] == "sent"
    assert result["messages"] == 2
    assert len(calls) == 1
    assert calls[0][:4] == ["hermes", "send", "--to", "mattermost:robert-dm"]
    assert "First completed report\n\nSecond completed report" == calls[0][-1]
    assert [row["text"] for row in mailbox.read(outbox(fleet), True)] == [
        "Arrived while transport was sending",
    ]


def test_sysadmin_context_is_complete_and_decisions_batch_for_twelve_hours(fleet):
    first = bundle(fleet)
    second = bundle(fleet, "Second service health check failed")
    items = pending_decisions(fleet)
    assert {item["id"] for item in items} == {first["id"], second["id"]}
    for item in items:
        for text in (
            "systemctl restart example",
            "systemctl stop example",
            "systemctl is-active example",
            "test -f /tmp/ready",
            "Rationale:",
            "Expected impact: Brief service interruption",
            "bead:cube-l4tf",
        ):
            assert text in item["body"]
    now = datetime(2026, 9, 8, tzinfo=UTC)
    assert len(announce_pending(fleet, None, now=now, dry_run=False)) == 2
    assert len(mailbox.read(outbox(fleet), True)) == 1
    third = bundle(fleet, "A later service finding")
    assert announce_pending(fleet, None, now=now + timedelta(hours=11), dry_run=False) == []
    rows = announce_pending(fleet, None, now=now + timedelta(hours=12), dry_run=False)
    assert [row["id"] for row in rows] == [third["id"]]
    assert len(mailbox.read(outbox(fleet), True)) == 2


@pytest.mark.parametrize(
    ("reply", "status", "count"),
    [
        ("approve", "applied", 3),
        ("deny", "denied", 0),
        ("modify use a maintenance window", "modification_requested", 0),
    ],
)
def test_mattermost_system_decisions_execute_only_approval(
    fleet, monkeypatch, reply, status, count
):
    record = bundle(fleet)
    calls = []

    def execute(argv):
        calls.append(argv)
        return 0, "", ""

    monkeypatch.setattr(sysops, "_exec", execute)
    result = decide_from_reply(fleet, None, f"{record['id']} {reply}", dry_run=False)
    assert result["status"] == status
    assert sysops.get(fleet, record["id"])["status"] == status
    assert len(calls) == count
    if count:
        assert (
            calls
            == record["payload"]["prechecks"]
            + record["payload"]["commands"]
            + record["payload"]["postchecks"]
        )


def test_mattermost_limit_changes_are_central_and_audited(fleet):
    reply = "limits set concurrent_slurm_jobs 2"
    result = decide_from_reply(fleet, None, reply, dry_run=False)
    assert result["kind"] == "limits"
    assert load_limits(fleet).concurrent_slurm_jobs == 2
    saved = json.loads((fleet.state_dir() / "fleet-limits.json").read_text())
    assert reply in saved["audit"][-1]["evidence"]
    assert saved["audit"][-1]["previous"]["concurrent_slurm_jobs"] == 4


@pytest.mark.parametrize(
    "reply",
    [
        "limits set concurrent_slurm_jobs -1",
        "limits set unknown_limit 4",
        "limits set daily_cost_usd NaN",
        "limits set concurrent_slurm_jobs true",
        "limits set concurrent_slurm_jobs many",
    ],
)
def test_bad_limit_replies_leave_defaults_unchanged(fleet, reply):
    before = load_limits(fleet)
    with pytest.raises(DecisionError):
        decide_from_reply(fleet, None, reply, dry_run=False)
    assert load_limits(fleet) == before
