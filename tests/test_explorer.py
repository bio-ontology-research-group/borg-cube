from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cube.engine import execute
from cube.explorer import Explorer, event_lines, metrics, read_object, read_text, workday_busy
from cube.runners import StubRunner
from tests.helpers_engine import fixtures

globals().update(fixtures())


def test_large_event_log_streams_records_without_loading_whole_document(tmp_path, monkeypatch):
    monkeypatch.setattr("cube.explorer.MAX_FILE", 100)
    path = tmp_path / "events.jsonl"
    path.write_text(("x" * 150) + "\n" + '{"source":"agent"}\n' * 20)
    assert len(list(event_lines(path, tmp_path))) == 20


def test_task_header_privacy_is_authoritative_without_optional_label(explorer, monkeypatch):
    monkeypatch.setattr(
        explorer,
        "_issues",
        lambda: (
            [
                {
                    "id": "cube-private",
                    "title": "Restricted subject matter",
                    "labels": ["agent:alpha"],
                    "description": (
                        "---\nxid: private\nprovenance: []\ndeadline: null\n"
                        "privacy: local-only\n---\n"
                    ),
                }
            ],
            [],
        ),
    )
    assert explorer.snapshot(name="alpha")["tasks"][0]["title"] == "Protected task"


@pytest.fixture
def explorer(engine_settings, monkeypatch):
    agents = {}
    for name in ("alpha", "beta", "liaison"):
        agents[name] = SimpleNamespace(
            name=name,
            title=name,
            role="senior",
            host=engine_settings.host,
            runtime="claude",
            privacy_default="internal",
            charter=f"agents/{name}/charter.md",
            memory_dir=f"agents/{name}/memory",
        )
        directory = engine_settings.root / "agents" / name
        (directory / "memory").mkdir(parents=True)
        (directory / "charter.md").write_text("Research charter")
    monkeypatch.setattr("cube.explorer.load_all_agents", lambda root: (agents, {}))
    monkeypatch.setattr("cube.explorer.load_agent", lambda root, name: agents[name])
    instance = Explorer(engine_settings)
    monkeypatch.setattr(instance, "_issues", lambda: ([], []))
    return instance


def record(explorer, identifier, **overrides):
    root = explorer.settings.dirs["runs"]
    directory = root / datetime.now(UTC).date().isoformat() / identifier
    directory.mkdir(parents=True)
    data = {
        "run_id": identifier,
        "started": datetime.now(UTC).isoformat(),
        "state": "finished",
        "role": "senior",
        "usage": {},
    }
    data.update(overrides)
    (directory / "meta.json").write_text(json.dumps(data))
    (directory / "result.json").write_text(json.dumps({"summary": "Reproduced result"}))
    return directory


def test_attribution_uses_recorded_events_not_shared_role(explorer):
    record(explorer, "explicit", agent="alpha")
    record(explorer, "historical")
    record(explorer, "unknown")
    state = explorer.settings.dirs["state"]
    (state / "events.jsonl").write_text(
        json.dumps(
            {
                "source": "agent",
                "session": "agent-beta",
                "data": {"runs": [{"run_id": "historical"}]},
            }
        )
        + "\ninvalid json\n"
    )
    snapshot = explorer.snapshot()
    assert snapshot["unattributed_runs"] == 1
    assert explorer.snapshot(name="alpha")["runs"][0]["id"] == "explicit"
    assert explorer.snapshot(name="beta")["runs"][0]["id"] == "historical"


def test_current_closed_bead_labels_never_override_recorded_owner(explorer, monkeypatch):
    record(explorer, "explicit", agent="alpha", bead="cube-one")
    record(explorer, "historical", bead="cube-two")
    (explorer.settings.dirs["state"] / "events.jsonl").write_text(
        json.dumps(
            {
                "source": "agent",
                "session": "agent-alpha",
                "data": {"runs": [{"run_id": "historical"}]},
            }
        )
    )
    monkeypatch.setattr(
        explorer,
        "_issues",
        lambda: (
            [
                {"id": "cube-one", "status": "closed", "labels": ["agent:beta"]},
                {"id": "cube-two", "status": "open", "labels": ["agent:beta"]},
            ],
            [],
        ),
    )
    assert {run["id"] for run in explorer.snapshot(name="alpha")["runs"]} == {
        "explicit",
        "historical",
    }
    assert explorer.snapshot(name="beta")["runs"] == []


def test_engine_records_explicit_agent_identity(engine_settings, fake_bd):
    report = execute(
        engine_settings,
        "senior",
        agent="alpha",
        runner_name="stub",
        runner=StubRunner(),
        prompt_text="Record a source-backed research note.",
    )
    assert report.ok, report.error
    metadata = json.loads((Path(report.run_dir) / "meta.json").read_text())
    assert metadata["agent"] == "alpha"
    assert metadata["role"] == "senior"


def test_token_cache_and_cost_accounting(explorer):
    record(
        explorer,
        "claude",
        agent="alpha",
        billed_cost_usd=0,
        equivalent_usd=2,
        cost_usd=99,
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 3,
            "api_calls": 0,
        },
    )
    record(
        explorer,
        "codex",
        agent="alpha",
        billed_cost_usd=1,
        equivalent_usd=3,
        usage={"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 50},
    )
    detail = explorer.snapshot(name="alpha")
    totals = detail["agent"]
    assert totals["total_tokens"] == 148
    assert totals["cache_read_tokens"] == 70
    assert totals["cost_usd"] == 1
    assert totals["equivalent_usd"] == 5
    assert totals["api_calls"] == 0
    assert totals["api_calls_missing"] == 1
    assert sum(row["equivalent_usd"] for row in detail["runs"]) == 5
    assert metrics([{"api_calls": None}])["api_calls"] is None


@pytest.mark.parametrize("agent,privacy", [("liaison", "internal"), ("alpha", "local-only")])
def test_private_run_summaries_are_withheld(explorer, agent, privacy):
    path = record(explorer, "private", agent=agent, privacy=privacy)
    (path / "result.json").write_text('{"summary":"confidential content"}')
    assert "confidential" not in json.dumps(explorer.snapshot(name=agent))


def test_liaison_memory_withheld(explorer):
    path = explorer.settings.root / "agents/liaison/memory/journal.md"
    path.write_text("private mail body")
    assert explorer.snapshot(name="liaison")["memories"] == []


def test_reported_total_tokens_is_not_double_counted(explorer):
    record(
        explorer,
        "total",
        agent="alpha",
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 20,
            "total_tokens": 35,
        },
    )
    assert explorer.snapshot(name="alpha")["agent"]["total_tokens"] == 35


def test_bounded_reads_reject_escape_symlink_and_malformed_json(tmp_path):
    root = tmp_path / "owned"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("not for explorer")
    (root / "link").symlink_to(outside)
    assert read_text(root / "link", root) == ""
    assert read_text(root / ".." / "secret", root) == ""
    assert read_text(outside, tmp_path, limit=1) == ""
    assert read_object(outside, tmp_path) == {}


def test_malformed_run_sources_are_ignored(explorer):
    directory = record(explorer, "bad")
    (directory / "meta.json").write_text("broken")
    assert explorer.snapshot()["totals"]["run_count"] == 0


def test_malformed_event_run_collection_is_ignored(explorer):
    state = explorer.settings.dirs["state"]
    (state / "events.jsonl").write_text(
        json.dumps(
            {
                "source": "agent",
                "session": "agent-alpha",
                "data": {"runs": None},
            }
        )
    )
    assert explorer.snapshot()["totals"]["run_count"] == 0


def test_flock_busy_is_not_file_presence(tmp_path):
    path = tmp_path / "workday.lock"
    assert not workday_busy(path)
    with path.open("w") as handle:
        assert not workday_busy(path)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert workday_busy(path)
    assert not workday_busy(path)


def test_controls_obey_pause_kill_and_remote(explorer, monkeypatch):
    state = explorer.settings.dirs["state"]
    pause = state / "agents/alpha/PAUSED"
    pause.parent.mkdir(parents=True)
    pause.touch()
    assert explorer.status("alpha")[0] == "paused"
    with pytest.raises(ValueError, match="paused"):
        explorer.trigger("alpha")
    (state / "KILL").touch()
    assert explorer.status("alpha")[0] == "stopped"
    (state / "KILL").unlink()
    monkeypatch.setattr(
        "cube.explorer.load_agent", lambda root, name: SimpleNamespace(host="laptop")
    )
    assert explorer.status("alpha")[0] == "remote"


def test_trigger_queues_only_fixed_workday_command(explorer, monkeypatch):
    thread = Mock()
    inbox = Mock()
    monkeypatch.setattr("cube.explorer.threading.Thread", thread)
    monkeypatch.setattr("cube.explorer.append_inbox", inbox)
    result = explorer.trigger("alpha", "Reproduce the ontology benchmark")
    assert result["status"] == "queued"
    assert result["command"][-5:] == ["agent", "workday", "alpha", "--apply", "--json"]
    inbox.assert_called_once()
    thread.return_value.start.assert_called_once()
    with pytest.raises(ValueError, match="already active"):
        explorer.trigger("alpha")
    with pytest.raises(ValueError, match="protected"):
        explorer.trigger("beta", "password=not-a-real-secret")


def test_launch_never_uses_shell(explorer, monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr("cube.explorer.subprocess.run", run)
    explorer.jobs["alpha"] = {"status": "queued"}
    explorer._launch("alpha", ["fixed", "command"])
    assert run.call_args.args == (["fixed", "command"],)
    assert "shell" not in run.call_args.kwargs
    assert explorer.jobs["alpha"]["status"] == "finished"
