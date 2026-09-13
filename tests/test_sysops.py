"""System changes require exact, single-use decisions; tests never run commands."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from cube.sysops import SysopsError, decide, diagnose, execute, get, propose


@pytest.fixture
def bundle(settings):
    settings.decisions.systems = [settings.host, "unimatrix01", "node005"]
    return dict(
        host="unimatrix01",
        commands=[["systemctl", "restart", "example"]],
        rationale="Service fails health check",
        impact="Brief service interruption",
        prechecks=[["test", "-f", "/tmp/ready"]],
        postchecks=[["systemctl", "is-active", "example"]],
        rollback=[["systemctl", "stop", "example"]],
        evidence=["bead:cube-l4tf"],
    )


def approved(settings, bundle):
    record = propose(settings, bundle, dry_run=False)
    decide(settings, record["id"], "approve", dry_run=False)
    return record["id"]


def test_idempotence_and_revisions(settings, bundle):
    record = propose(settings, bundle, dry_run=False)
    decide(settings, record["id"], "deny", dry_run=False)
    assert propose(settings, bundle, dry_run=False)["status"] == "denied"
    bundle["impact"] = "A different impact"
    revised = propose(settings, bundle, dry_run=False)
    assert revised["id"] != record["id"]
    assert revised["status"] == "pending"


def test_modify_never_approves(settings, bundle):
    record = propose(settings, bundle, dry_run=False)
    decide(settings, record["id"], "modify", "Use a maintenance window", dry_run=False)
    with pytest.raises(SysopsError):
        execute(settings, record["id"], dry_run=False)


def test_dry_run_and_exact_order(settings, bundle):
    proposal_id = approved(settings, bundle)
    calls = []

    def runner(argv):
        calls.append(argv)
        return 0, "password=secret", "token=secret"

    execute(settings, proposal_id, exec_fn=runner)
    assert not calls
    result = execute(settings, proposal_id, dry_run=False, exec_fn=runner)
    assert result["status"] == "applied"
    assert [argv[-1] for argv in calls] == [
        "test -f /tmp/ready",
        "systemctl restart example",
        "systemctl is-active example",
    ]
    assert "secret" not in json.dumps(result)
    with pytest.raises(SysopsError):
        execute(settings, proposal_id, dry_run=False, exec_fn=runner)


@pytest.mark.parametrize("failure", [0, 1, 2])
def test_failures_stop_and_never_run_rollback(settings, bundle, failure):
    proposal_id = approved(settings, bundle)
    calls = []

    def runner(argv):
        calls.append(argv)
        return (1 if len(calls) == failure + 1 else 0), "", ""

    result = execute(settings, proposal_id, dry_run=False, exec_fn=runner)
    assert result["status"] == "failed"
    assert len(calls) == failure + 1
    assert result["rollback_commands"] == bundle["rollback"]
    with pytest.raises(SysopsError):
        execute(settings, proposal_id, dry_run=False, exec_fn=runner)


def test_tampering_invalidates_approval(settings, bundle):
    proposal_id = approved(settings, bundle)
    path = settings.state_dir() / "sysops" / f"{proposal_id}.json"
    record = json.loads(path.read_text())
    record["payload"]["commands"] = [["true"]]
    path.write_text(json.dumps(record))
    with pytest.raises(SysopsError, match="digest"):
        execute(settings, proposal_id, dry_run=False)


@pytest.mark.parametrize(
    "argv",
    [
        ["sudo", "rootsh"],
        ["sshpass", "-p", "secret"],
        ["sudo", "-S", "true"],
        ["bash", "-c", "reboot"],
        ["ssh", "other", "true"],
    ],
)
def test_reject_interactive_or_indirect_commands(settings, bundle, argv):
    bundle["commands"] = [argv]
    with pytest.raises(SysopsError):
        propose(settings, bundle)


def test_host_and_node005_guards(settings, bundle):
    bundle["host"] = "unknown"
    with pytest.raises(SysopsError):
        propose(settings, bundle)
    bundle["host"] = "node005"
    bundle["commands"] = [["systemctl", "reboot"]]
    with pytest.raises(SysopsError):
        propose(settings, bundle)


def test_diagnostics_have_no_command_suffix(settings, bundle):
    with pytest.raises(SysopsError):
        diagnose(settings, "unimatrix01", "disk; rm -rf /tmp")
    calls = []

    def runner(argv):
        calls.append(argv)
        return 0, "password=secret", "secret"

    result = diagnose(settings, settings.host, "journal", dry_run=False, exec_fn=runner)
    assert calls == [["journalctl", "-p", "err", "-n", "40", "--no-pager"]]
    assert "secret" not in json.dumps(result)


def test_pending_cannot_execute_and_dry_decision_does_not_persist(settings, bundle):
    proposal_id = propose(settings, bundle, dry_run=False)["id"]
    decide(settings, proposal_id, "approve")
    assert get(settings, proposal_id)["status"] == "pending"
    with pytest.raises(SysopsError):
        execute(settings, proposal_id, dry_run=False)


def test_concurrent_execution_runs_bundle_only_once(settings, bundle):
    proposal_id = approved(settings, bundle)
    entered, release = Event(), Event()
    calls = []

    def runner(argv):
        calls.append(argv)
        entered.set()
        assert release.wait(5)
        return 0, "", ""

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, settings, proposal_id, dry_run=False, exec_fn=runner)
        assert entered.wait(5)
        second = pool.submit(execute, settings, proposal_id, dry_run=False, exec_fn=runner)
        release.set()
        assert first.result()["status"] == "applied"
        with pytest.raises(SysopsError):
            second.result()
    assert len(calls) == 3


def test_diagnostic_filters_before_truncating(settings, bundle):
    result = diagnose(
        settings,
        settings.host,
        "disk",
        dry_run=False,
        exec_fn=lambda argv: (0, "x" * 9000 + " password=secret", ""),
    )
    assert all(
        item["stdout"] == "[withheld: source contains credentials]" for item in result["results"]
    )
