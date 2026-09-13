import json
from pathlib import Path

from cube.beads import Beads
from cube.brain import fact_key, load_facts, push
from cube.notify import append_event, event_from_claude_hook, make_event, write_attention


def test_append_and_attention(tmp_path: Path) -> None:
    ev = append_event(tmp_path, make_event("stop", session="s", body="x" * 500))
    assert "ts" in ev and ev["seq"] == 1 and ev["body_file"] == "state/bodies/1.md"
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["event"] == "stop"
    assert append_event(tmp_path, make_event("finished"))["seq"] == 2
    write_attention(tmp_path, [{"id": "a"}])
    assert json.loads((tmp_path / "attention.json").read_text())["items"] == [{"id": "a"}]


def test_claude_hook_mapping() -> None:
    ev = event_from_claude_hook(
        {
            "hook_event_name": "Notification",
            "message": "Permission needed",
            "session_id": "abc",
            "cwd": "/x/y",
        },
        session="advisor/alex",
    )
    assert ev["event"] == "notification" and ev["severity"] == "attention"
    assert ev["session"] == "advisor/alex" and ev["title"] == "permission needed"
    assert ev["resume_id"] == "abc" and ev["source"] == "claude"
    assert event_from_claude_hook({"hook_event_name": "Stop", "cwd": "/x/y"})["session"] == "y"


def test_brain_push_dry_run(tmp_path: Path) -> None:
    facts = tmp_path / "brain" / "facts"
    facts.mkdir(parents=True)
    (facts / "a.yaml").write_text(
        "facts:\n  - text: node005 has two RTX 4090\n    source: memory\n  - just a string fact\n",
        encoding="utf-8",
    )
    loaded = load_facts(tmp_path / "brain")
    assert len(loaded) == 2 and loaded[1]["source"] == "facts/a.yaml"
    assert fact_key("Hello World") == fact_key("Hello World") and fact_key("a") != fact_key("b")
    b = Beads(dry_run=True)
    pushed = push(b, tmp_path / "brain")
    assert len(pushed) == 2 and b.log[0][:2] == ["bd", "remember"] and "--key" in b.log[0]


def test_repeated_loud_events_are_muted_once_per_day(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from cube.notify import mark_repeat

    first = append_event(tmp_path, make_event("error", source="worker", title="sync failed"))
    assert "muted" not in first
    again = append_event(tmp_path, make_event("error", source="worker", title="sync failed"))
    assert again["muted"] is True and again["data"]["repeat_of"] == first["seq"]
    other = append_event(tmp_path, make_event("error", source="worker", title="other"))
    assert "muted" not in other
    # quiet events never mute, whatever the title
    quiet = append_event(tmp_path, make_event("finished", source="agent", title="workday finished"))
    assert "muted" not in append_event(
        tmp_path, make_event("finished", source="agent", title="workday finished")
    )
    assert "muted" not in quiet
    # after the window the same title tells Robert again
    later = datetime.now(UTC) + timedelta(days=1, seconds=1)
    fresh = mark_repeat(
        tmp_path, make_event("error", source="worker", title="sync failed"), now=later
    )
    assert "muted" not in fresh
    lines = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [line.get("muted", False) for line in lines] == [False, True, False, False, False]


def test_tool_hooks_become_readable_tool_events() -> None:
    from cube.notify import tool_title

    pre = event_from_claude_hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/home/x/repo/README.md"},
            "session_id": "abc",
            "cwd": "/x/y",
        },
        session="run-r-1",
    )
    assert pre["event"] == "tool" and pre["title"] == "Read /home/x/repo/README.md"
    assert pre["data"] == {"hook": "PreToolUse", "tool": "Read", "phase": "pre"}
    post = event_from_claude_hook(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls  -la\n"},
        }
    )
    assert post["title"] == "Bash ls -la" and post["data"]["phase"] == "post"
    assert (
        tool_title({"tool_name": "Grep", "tool_input": {"pattern": "secret", "path": "."}})
        == "Grep secret"
    )
    assert tool_title({"tool_name": "Task", "tool_input": {"description": "x" * 200}}).endswith(
        "..."
    )
    assert tool_title({}) == "tool"
