"""Patrol layer tests: registry, runner semantics (dry-run/apply, KILL, cursor dedup), CLI."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cube.beads import Beads
from cube.cli import main
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.model import BeadHeader, Privacy, Provenance, WorkKind
from cube.patrols import base
from cube.patrols.cursors import load_cursors, save_cursor
from cube.patrols.infra_hygiene import InfraHygienePatrol, Probes
from cube.patrols.infra_incidents import InfraIncidentsPatrol
from cube.patrols.mattermost_events import MattermostEventsPatrol
from cube.patrols.student_digest import StudentDigestPatrol
from cube.runners.base import ExecResult
from cube.student.context import render_context
from cube.sync.context import SourceContext
from cube.sync.derivers import DesiredBead
from tests.helpers_engine import (
    FakeBd,
    fixtures,
)

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
TODAY = date(2026, 9, 2)


def test_registry_contains_timer_patrols() -> None:
    import cube.patrols  # noqa: F401 - the package import must populate the registry

    names = set(base.names())
    expected = {
        "calendar",
        "deadlines",
        "data_pull",
        "infra_hygiene",
        "infra_incidents",
        "leases",
        "mattermost_events",
        "milestones",
        "papers",
        "repos",
        "student_digest",
    }
    assert expected <= names, f"missing patrols: {expected - names}"
    assert base.make("deadlines", **{}).name == "deadlines"  # hyphen/underscore normalise
    assert base.make("infra-hygiene").name == "infra_hygiene"


class _EchoPatrol:
    """Minimal patrol: one DesiredBead + one repeating event, for runner semantics."""

    name = "echo"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> base.PatrolReport:
        report = base.PatrolReport(self.name, today, dry_run)
        report.findings.append(
            DesiredBead(
                xid="finding:echo:one",
                title="Echo finding",
                kind=WorkKind.finding,
                labels=["src:test"],
                header=BeadHeader(xid="finding:echo:one"),
            )
        )
        report.events.append(base.attention_event("echo", "echo event", xid="finding:echo:one"))
        report.summary = "1 echo"
        return report


class _FailingPatrol:
    name = "failing"

    def run(
        self, settings: Settings, today: date, dry_run: bool, *, beads: Beads | None = None
    ) -> base.PatrolReport:
        raise PermissionError("source cannot be read")


def test_run_patrol_dry_run_writes_nothing(engine_settings: Settings, fake_bd: FakeBd) -> None:
    report = base.run_patrol(engine_settings, _EchoPatrol(), today=TODAY, dry_run=True)
    assert report.beads() and not report.paused
    writes = [c for c in fake_bd.calls() if c[0] in {"create", "close", "label", "update"}]
    assert writes == []
    assert not (engine_settings.state_dir() / "cursors.json").exists()


def test_run_patrol_apply_creates_bead_and_cursor_dedups(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    state = engine_settings.state_dir()
    base.run_patrol(engine_settings, _EchoPatrol(), today=TODAY, dry_run=False, now=NOW)
    xrefs = {b.get("external_ref") for b in fake_bd.beads().values()}
    assert "finding:echo:one" in xrefs
    cursor = base.load_cursor(state, "echo")
    assert "finding:echo:one" in cursor["xids"]
    events = (state / "events.jsonl").read_text().splitlines()
    assert len([e for e in events if "echo event" in e]) == 1
    # Second run: reconcile is a no-op and the event is suppressed by the cursor.
    base.run_patrol(engine_settings, _EchoPatrol(), today=TODAY, dry_run=False, now=NOW)
    data = json.loads((state / "cursors.json").read_text())
    assert data["echo"]["events_suppressed"] >= 1


def test_kill_switch_pauses(engine_settings: Settings, fake_bd: FakeBd) -> None:
    state = engine_settings.state_dir()
    (state / "KILL").write_text("", encoding="utf-8")
    report = base.run_patrol(engine_settings, _EchoPatrol(), today=TODAY, dry_run=False)
    assert report.paused
    assert fake_bd.calls() == []


def test_raised_patrol_fails_cli_and_does_not_advance_cursor(
    engine_repo: Path,
    engine_settings: Settings,
    fake_bd: FakeBd,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = engine_settings.state_dir()
    save_cursor(state, "failing", {"last_run": "2026-09-01T09:00:00+00:00", "summary": "clean"})
    before = load_cursors(state)
    monkeypatch.setitem(base.REGISTRY, "failing", _FailingPatrol)

    assert main(["--root", str(engine_repo), "patrol", "failing", "--apply"]) == 1
    assert load_cursors(state) == before


def test_cli_patrol_and_digest(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    root = ["--root", str(engine_repo)]
    assert main([*root, "patrol", "milestones", "--today", TODAY.isoformat()]) == 0
    assert main([*root, "patrol", "no-such-patrol"]) == 2
    digest_out = engine_repo / "briefings" / f"digest-{TODAY.isoformat()}.md"
    assert not digest_out.exists()  # dry-run is the default
    assert main([*root, "digest", "--today", TODAY.isoformat(), "--apply"]) == 0
    md = digest_out.read_text(encoding="utf-8")
    assert f"# Digest {TODAY.isoformat()}" in md and "## Attention" in md
    assert main([*root, "patrol", "leases", "--apply", "--today", TODAY.isoformat()]) == 0


def test_cli_event_mattermost_intake(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    root = ["--root", str(engine_repo)]
    payload_file = tmp_path / "mm.json"
    payload_file.write_text(
        json.dumps(
            {
                "post_id": "p1",
                "user": "alex.example",
                "user_id": "uid1",
                "text": "hello",
                "channel_type": "D",
            }
        ),
        encoding="utf-8",
    )
    assert main([*root, "event", "mattermost", "--payload-file", str(payload_file)]) == 0
    assert main([*root, "event", "mattermost", "--payload-file", str(payload_file), "--apply"]) == 0
    inbox = engine_repo / "state" / "events" / "inbox" / "p1.json"
    assert inbox.exists()
    record = json.loads(inbox.read_text(encoding="utf-8"))
    # alex has no mattermost_dm grant in contacts.yaml: routed to Robert, not mentoring
    assert record["routing"] == "robert"


def test_ungranted_dm_text_stays_only_in_local_inbox(
    engine_settings: Settings, fake_bd: FakeBd
) -> None:
    sensitive = "My GPA is 2.1 and my visa expires Friday"
    patrol = MattermostEventsPatrol(
        payloads=[
            {
                "post_id": "private-post",
                "user": "alex.example",
                "user_id": "uid1",
                "text": sensitive,
                "channel_type": "D",
            }
        ]
    )

    base.run_patrol(engine_settings, patrol, today=TODAY, dry_run=False, now=NOW)

    inbox = engine_settings.state_dir() / "events" / "inbox" / "private-post.json"
    inbox_record = json.loads(inbox.read_text(encoding="utf-8"))
    assert inbox_record["privacy"] == "local-only"
    assert inbox_record["event"]["text"] == sensitive
    stored_beads = json.dumps(fake_bd.beads())
    stored_events = (engine_settings.state_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert sensitive not in stored_beads
    assert sensitive not in stored_events
    assert "privacy:local-only" in stored_beads


def test_student_digest_is_marked_local_only(
    engine_repo: Path, engine_settings: Settings, fake_bd: FakeBd
) -> None:
    (engine_repo / "people.yaml").write_text(
        "people:\n  alex: {name: Alex Example, role: student, program: PhD-CS, source: fixture}\n",
        encoding="utf-8",
    )
    report = StudentDigestPatrol(only="alex", refresh_context=False).run(
        engine_settings, TODAY, True
    )

    preview = report.data["previews"]["alex"]
    assert "Robert-only (privacy: local-only)." in preview
    assert "Robert-only (privacy: internal)." not in preview


def test_student_context_rejects_unclassified_and_sensitive_titles(
    engine_repo: Path, engine_settings: Settings
) -> None:
    (engine_repo / "people.yaml").write_text(
        "people:\n  alex: {name: Alex Example, role: student, program: PhD-CS, source: fixture}\n",
        encoding="utf-8",
    )
    ctx = SourceContext(engine_settings, TODAY, github_details=False)
    person = ctx.people[0]
    provenanced = BeadHeader(
        xid="visible:safe",
        provenance=[Provenance(source="project-plan.md", locator="line 12", seen=TODAY)],
        privacy=Privacy.internal,
    ).render()
    sensitive = BeadHeader(
        xid="visible:sensitive",
        provenance=[Provenance(source="staff.org", locator="line 8", seen=TODAY)],
        privacy=Privacy.internal,
    ).render()
    ledger = SimpleNamespace(
        beads=[
            {
                "id": "cube-unclassified",
                "title": "Unclassified update",
                "labels": ["person:alex", "visible:student", "privacy:internal"],
            },
            {
                "id": "cube-sensitive",
                "title": "Contract renewal after surgery",
                "description": sensitive,
                "labels": ["person:alex", "visible:student", "privacy:internal"],
            },
            {
                "id": "cube-safe",
                "title": "Submit the project abstract",
                "description": provenanced,
                "labels": ["person:alex", "visible:student", "privacy:internal"],
            },
        ]
    )

    payload = render_context(
        ctx,
        person,
        ledger,  # type: ignore[arg-type]
        ContactPolicy(engine_repo / "contacts.yaml"),
    )

    assert [item["title"] for item in payload["visible_beads"]] == ["Submit the project abstract"]


def test_infra_hygiene_reports_all_required_ports_missing() -> None:
    def exec_fn(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        stdin_devnull: bool = True,
    ) -> ExecResult:
        if cmd[0] == "ss":
            return ExecResult(0, "State Recv-Q Send-Q Local Address:Port\n", "")
        return ExecResult(0, "COMMAND\n", "")

    probes = Probes(
        exec_fn=exec_fn,
        which=lambda name: name if name in {"ss", "ps"} else None,
        hostname="testhost",
    )
    patrol = InfraHygienePatrol(probes=probes)
    report = base.PatrolReport(patrol.name, TODAY, True)

    patrol.tunnel_checks(
        [{"name": "api", "type": "listen", "ssh": "local", "ports": [3000, 8000]}],
        TODAY,
        report,
    )

    assert any(bead.xid == "incident:api" and not bead.closed for bead in report.beads())
    assert any(event.get("data", {}).get("xid") == "incident:api" for event in report.events)


def test_infra_incidents_preserves_down_then_recovery(
    engine_settings: Settings, fake_bd: FakeBd, tmp_path: Path
) -> None:
    events_path = tmp_path / "infra-events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "time": "2026-09-02T10:00:00+00:00",
                "service": "api",
                "from": "OK",
                "to": "DOWN",
                "msg": "connection refused",
            }
        )
        + "\n"
        + json.dumps(
            {
                "time": "2026-09-02T10:02:00+00:00",
                "service": "api",
                "from": "DOWN",
                "to": "OK",
                "msg": "recovered",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    base.run_patrol(
        engine_settings,
        InfraIncidentsPatrol(events_path=events_path),
        today=TODAY,
        dry_run=False,
        now=NOW,
    )

    incident = next(
        bead for bead in fake_bd.beads().values() if bead.get("external_ref") == "incident:api"
    )
    assert incident["status"] == "closed"
    emitted = (engine_settings.state_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert "DOWN: api" in emitted


def test_save_cursor_preserves_concurrent_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cube.patrols import cursors as cursor_module

    original_load = cursor_module.load_cursors
    both_read = threading.Barrier(2)

    def synchronised_load(state_dir: Path) -> dict[str, dict[str, object]]:
        snapshot = original_load(state_dir)
        try:
            both_read.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        return snapshot

    monkeypatch.setattr(cursor_module, "load_cursors", synchronised_load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(save_cursor, tmp_path, "patrol_a", {"last_run": "a"}),
            pool.submit(save_cursor, tmp_path, "patrol_b", {"last_run": "b"}),
        ]
        for future in futures:
            future.result(timeout=2)

    assert load_cursors(tmp_path) == {
        "patrol_a": {"last_run": "a"},
        "patrol_b": {"last_run": "b"},
    }


def test_infra_warn_transition_is_information_not_a_bead() -> None:
    from cube.patrols.infra_incidents import beads_for_transition

    made, event = beads_for_transition(
        {
            "time": "2026-09-05T10:00:00Z",
            "service": "vm-alpha",
            "from": "OK",
            "to": "WARN",
            "message": "failed units: dailyaidecheck",
        },
        TODAY,
        "hermes-infra",
    )
    assert event is None
    assert all(b.closed for b in made)
    made, event = beads_for_transition(
        {
            "time": "2026-09-05T10:00:00Z",
            "service": "bio2vec.net",
            "from": "OK",
            "to": "WARN",
            "message": "slow",
            "scope": "external",
        },
        TODAY,
        "hermes-infra",
    )
    # an external warning keeps its open warning bead, as before
    assert any(not b.closed for b in made)
