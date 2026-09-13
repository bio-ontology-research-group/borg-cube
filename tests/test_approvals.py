from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cube.approvals import ApprovalError, ApprovalStore, Intent, deliver, intent_from_file
from cube.cli import main
from cube.config import Settings
from cube.contact import ContactPolicy
from cube.runners.base import ExecResult
from tests.helpers_engine import RecordingExec, fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def make_intent(kind: str = "mattermost_dm", **kw: object) -> Intent:
    base: dict[str, object] = dict(
        kind=kind, to="u123", person="alex-example", action="weekly-checkin"
    )
    base.update(kw)
    return Intent(**base)  # type: ignore[arg-type]


def test_lifecycle_pending_approve_deliver(engine_repo: Path, engine_settings: Settings) -> None:
    store = ApprovalStore(engine_repo / "state")
    policy = ContactPolicy(engine_repo / "contacts.yaml")
    body = engine_repo / "msg.md"
    body.write_text("---\nto: u123\n---\nHello Alex\n")
    ap = store.create(
        make_intent(body_file=str(body)),
        policy=policy,
        created_by="advisor/r-1",
        run_id="r-1",
        bead="cube-1",
        now=NOW,
    )
    assert ap.status == "pending" and "no grants" in ap.policy["reason"]
    assert store.items("pending")[0].id == ap.id
    events = [
        json.loads(x) for x in (engine_repo / "state" / "events.jsonl").read_text().splitlines()
    ]
    assert events[-1]["event"] == "approval" and events[-1]["data"]["approval"] == ap.id
    with pytest.raises(ApprovalError, match="only approved"):
        deliver(engine_settings, store, ap.id, now=NOW)
    with pytest.raises(ApprovalError, match="needs --reason"):
        store.decide(ap.id, approve=False)
    ap = store.decide(ap.id, approve=True, by="robert")
    assert ap.status == "approved" and ap.decided_by == "robert"
    with pytest.raises(ApprovalError, match="already approved"):
        store.decide(ap.id, approve=True)
    # deliver is dry-run by default: nothing runs, the command is shown
    ex = RecordingExec({"hermes": ExecResult(0, "sent", "")})
    res = deliver(engine_settings, store, ap.id, now=NOW, exec_fn=ex)
    assert (
        res.dry_run
        and res.ok
        and res.commands[0][:4] == ["hermes", "send", "--to", "mattermost:u123"]
    )
    assert "Hello Alex" in res.commands[0][-1] and ex.calls == []
    assert store.get(ap.id).status == "approved"
    res = deliver(engine_settings, store, ap.id, now=NOW, dry_run=False, exec_fn=ex)
    assert res.ok and res.result == "sent" and ex.calls[0]["cmd"][0] == "hermes"
    assert store.get(ap.id).status == "delivered"
    audit = [
        json.loads(x)["action"]
        for x in (engine_repo / "state" / "audit.jsonl").read_text().splitlines()
    ]
    assert audit == ["approval.create", "approval.approved", "approval.delivered"]


def test_auto_approve_needs_grant_and_autonomous_action(engine_repo: Path) -> None:
    store = ApprovalStore(engine_repo / "state")
    policy = ContactPolicy(engine_repo / "contacts.yaml")
    policy.grant("alex-example", "mattermost_dm", ["weekly-checkin"], today=NOW.date())
    ap = store.create(make_intent(), policy=policy, created_by="advisor", now=NOW)
    assert ap.status == "pending" and ap.policy["allowed"] is True  # grant alone is not enough
    ap = store.create(
        make_intent(),
        policy=policy,
        created_by="advisor",
        autonomous_actions=["weekly-checkin"],
        now=NOW,
    )
    assert ap.status == "approved" and ap.policy["auto_approved"] is True
    ap = store.create(
        make_intent(action="grades"),
        policy=policy,
        created_by="advisor",
        autonomous_actions=["grades"],
        now=NOW,
    )
    assert ap.status == "pending"  # action not in the grant's scope


def test_email_never_sent_and_diff_applied(engine_repo: Path, engine_settings: Settings) -> None:
    store = ApprovalStore(engine_repo / "state")
    policy = ContactPolicy(engine_repo / "contacts.yaml")
    body = engine_repo / "mail.md"
    body.write_text(
        "---\nto: k@example.org\nperson: alex-example\nchannel: email\n"
        "subject: Hi\n---\nBody text\n"
    )
    intent = intent_from_file(body)
    assert intent is not None and intent.kind == "email" and intent.subject == "Hi"
    ap = store.create(intent, policy=policy, created_by="advisor", now=NOW)
    store.decide(ap.id, approve=True)
    res = deliver(engine_settings, store, ap.id, now=NOW, dry_run=False)
    assert res.result == "draft_opened" and res.commands[0][:3] == ["emacsclient", "-s", "gnus"]
    draft = Path(res.files[0])
    assert draft.exists() and "Body text" in draft.read_text() and "never sent" in res.message
    # org_edit: patch dry-run then apply through the injected exec
    diff = engine_repo / "note.diff"
    diff.write_text("--- a/x.org\n+++ b/x.org\n@@ -1 +1 @@\n-a\n+b\n")
    intent = intent_from_file(diff, default_kind="org_edit")
    assert intent is not None and intent.diff_file == str(diff) and intent.action == "edit"
    ap = store.create(intent, policy=policy, created_by="scribe", now=NOW)
    assert ap.status == "pending" and "local write" in ap.policy["reason"]
    store.decide(ap.id, approve=True)
    ex = RecordingExec({"patch": ExecResult(0, "patching file x.org", "")})
    res = deliver(engine_settings, store, ap.id, now=NOW, exec_fn=ex)
    assert res.dry_run and "--dry-run" in ex.calls[0]["cmd"] and ex.calls[0]["cmd"][0] == "patch"
    assert ex.calls[0]["cmd"][ex.calls[0]["cmd"].index("-d") + 1] == str(
        engine_settings.dirs["org"]
    )
    res = deliver(engine_settings, store, ap.id, now=NOW, dry_run=False, exec_fn=ex)
    assert res.result == "applied" and "--dry-run" not in ex.calls[1]["cmd"]


def test_mattermost_channel_rest(engine_repo: Path, engine_settings: Settings) -> None:
    engine_settings.env.update(MATTERMOST_TOKEN="t", MATTERMOST_URL="https://mm.example")
    store = ApprovalStore(engine_repo / "state")
    body = engine_repo / "post.md"
    body.write_text("post body")
    ap = store.create(
        make_intent("mattermost_channel", to="chan1", person=None, body_file=str(body)),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="sysadmin",
        now=NOW,
    )
    assert "no person" in ap.policy["reason"]
    store.decide(ap.id, approve=True)
    seen: list[object] = []

    def post(url, headers, body, timeout):  # type: ignore[no-untyped-def]
        seen.append((url, dict(headers), json.loads(body)))
        return 201, b"{}"

    res = deliver(engine_settings, store, ap.id, now=NOW, http_post=post)
    assert res.dry_run and seen == []
    res = deliver(engine_settings, store, ap.id, now=NOW, dry_run=False, http_post=post)
    assert res.ok and seen[0][0] == "https://mm.example/api/v4/posts"  # type: ignore[index]
    assert seen[0][2] == {"channel_id": "chan1", "message": "post body"}  # type: ignore[index]


def test_cli_approvals_flow(engine_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = ApprovalStore(engine_repo / "state")
    body = engine_repo / "b.md"
    body.write_text("x")
    ap = store.create(
        make_intent(body_file=str(body)),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor",
        now=NOW,
    )
    assert main(["--root", str(engine_repo), "approvals", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["approvals"][0]["id"] == ap.id and out["approvals"][0]["kind"] == "outbound"
    assert out["approvals"][0]["actions"] == ["approve", "reject", "edit"]
    assert main(["--root", str(engine_repo), "reject", ap.id, "--reason", "not now", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["result"] == "rejected" and out["action"] == "reject"
    assert main(["--root", str(engine_repo), "approve", ap.id, "--json"]) == 3
    capsys.readouterr()
    ap2 = store.create(
        make_intent(body_file=str(body)),
        policy=ContactPolicy(engine_repo / "contacts.yaml"),
        created_by="advisor",
        now=NOW,
    )
    assert main(["--root", str(engine_repo), "approve", ap2.id, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "queued_for_send" and "cube deliver" in out["message"]
    assert main(["--root", str(engine_repo), "deliver", ap2.id, "--now", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["result"] == "dry_run"
    assert main(["--root", str(engine_repo), "approvals", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["approvals"] == []


def test_a_header_that_is_not_yaml_is_still_read(tmp_path: Path) -> None:
    # 2026-09-07: "subject: FLOPO status: audit filed" failed the whole
    # agent_workday patrol twice with "mapping values are not allowed here"
    body = tmp_path / "dm.md"
    body.write_text(
        "---\nkind: mattermost_dm\nto: robert-hoehndorf\n"
        "subject: FLOPO status: audit filed, answer waits on the laptop\n---\nBody\n"
    )
    intent = intent_from_file(body)
    assert intent is not None and intent.kind == "mattermost_dm"
    assert intent.subject == "FLOPO status: audit filed, answer waits on the laptop"
    assert intent.to == "robert-hoehndorf"
    # and a header with no kind at all is still no intent
    (tmp_path / "plain.md").write_text("---\nnote: a: b\n---\nText\n")
    assert intent_from_file(tmp_path / "plain.md") is None
