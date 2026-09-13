from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cube.config import Settings
from cube.patrols.budget import import_interactive
from tests.helpers_engine import fixtures

globals().update(fixtures())

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_import_parses_both_formats_deduplicates_and_dry_runs(
    engine_settings: Settings,
    tmp_path: Path,
) -> None:
    codex_root = tmp_path / "codex" / "sessions"
    claude_root = tmp_path / "claude" / "projects"
    _write_jsonl(
        codex_root / "2026" / "09" / "rollout-one.jsonl",
        [
            {
                "timestamp": "2026-09-02T09:00:00Z",
                "type": "session_meta",
                "payload": {"session_id": "codex-one", "cwd": "/tmp/project"},
            },
            {
                "timestamp": "2026-09-02T09:10:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 100}},
                },
            },
            {
                "timestamp": "2026-09-02T09:20:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 150}},
                },
            },
            {
                "timestamp": "2026-09-02T09:30:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "content": "usage limit; reset at 2026-09-02T14:00:00Z",
                },
            },
        ],
    )
    _write_jsonl(
        claude_root / "encoded-cwd" / "claude-one.jsonl",
        [
            {"sessionId": "claude-one", "timestamp": "2026-09-02T09:00:00Z"},
            {
                "sessionId": "claude-one",
                "timestamp": "2026-09-02T09:10:00Z",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                },
            },
            {
                "sessionId": "claude-one",
                "timestamp": "2026-09-02T09:20:00Z",
                "message": {
                    "role": "assistant",
                    "usage": {"input_tokens": 20, "output_tokens": 3},
                },
            },
            {
                "sessionId": "claude-one",
                "timestamp": "2026-09-02T09:30:00Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "You've hit your usage limit. Reset at 14:00 UTC.",
                        }
                    ],
                },
            },
        ],
    )

    dry = import_interactive(
        engine_settings,
        apply=False,
        now=NOW,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    assert dry["dry_run"] is True
    assert dry["added"] == {"claude": 35, "codex": 150}
    assert not (engine_settings.state_dir() / "budget.json").exists()

    applied = import_interactive(
        engine_settings,
        apply=True,
        now=NOW,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    assert applied["dry_run"] is False
    assert {row["source"] for row in applied["records"]} == {"interactive"}
    assert {row["add_tokens"] for row in applied["records"]} == {35, 150}
    assert {item["runner"] for item in applied["windows"]} == {"claude", "codex"}

    repeated = import_interactive(
        engine_settings,
        apply=True,
        now=NOW,
        codex_root=codex_root,
        claude_root=claude_root,
    )
    assert repeated["added"] == {"claude": 0, "codex": 0}
    state = json.loads((engine_settings.state_dir() / "budget.json").read_text(encoding="utf-8"))
    assert state["2026-09-02"]["runners"]["codex"]["tokens"] == 150
    assert state["2026-09-02"]["runners"]["claude"]["tokens"] == 35
    assert state["windows"]["codex"]["cap"] == 150
    assert state["windows"]["claude"]["cap"] == 35
    assert all(value["source"] == "interactive" for value in state["_imports"].values())
