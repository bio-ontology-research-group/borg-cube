from __future__ import annotations

import json
from pathlib import Path

import pytest

from cube.model import RunResult
from cube.roles import load_role, result_schema
from cube.runners import (
    ClaudeCodeRunner,
    CodexRunner,
    HermesRunner,
    OpenAICompatRunner,
    RunContext,
    StubRunner,
    make_runner,
)
from cube.runners.base import ExecResult, extract_json_object, looks_rate_limited, parse_result
from cube.runners.claude_code import parse_envelope
from cube.runners.codex import parse_events
from tests.helpers_engine import REPO_ROOT, RecordingExec

GOOD = json.dumps({"summary": "done (source: tests)", "next_actions": ["x"]})


def ctx(tmp_path: Path, role: str, **kw: object) -> RunContext:
    r = load_role(REPO_ROOT, role)
    base = dict(
        run_id="r-test-01",
        role=r,
        prompt="do the thing",
        system_prompt="SYSTEM",
        cwd=tmp_path,
        run_dir=tmp_path / "run",
        schema=result_schema(),
        bead="cube-7",
        model="opus",
    )
    base.update(kw)
    return RunContext(**base)  # type: ignore[arg-type]


def test_claude_command_and_env(tmp_path: Path) -> None:
    ex = RecordingExec(
        {
            "claude": ExecResult(
                0,
                json.dumps(
                    {
                        "type": "result",
                        "result": GOOD,
                        "session_id": "s-1",
                        "total_cost_usd": 0.12,
                        "usage": {"input_tokens": 3},
                    }
                ),
                "",
            )
        }
    )
    out = ClaudeCodeRunner(ex).run(ctx(tmp_path, "senior", resume_id="old"))
    cmd = ex.calls[0]["cmd"]
    assert cmd[:3] == ["claude", "-p", "do the thing"]
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash(bd *)" in cmd[cmd.index("--allowedTools") + 1]
    assert cmd[cmd.index("--append-system-prompt-file") + 1].endswith("system.md")
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert "--json-schema" in cmd
    assert "--resume" not in cmd  # senior is session_policy fresh
    env = ex.calls[0]["env"]
    assert env["CUBE_RUN_ID"] == "r-test-01" and env["CUBE_BEAD"] == "cube-7"
    assert env["CUBE_SESSION"].startswith("run-") or env["CUBE_SESSION"]
    assert ex.calls[0]["stdin_devnull"] is True
    assert out.ok and out.session_id == "s-1" and out.cost_usd == 0.12
    assert out.result is not None and out.result.summary.startswith("done")


def test_claude_resume_and_workspace_write(tmp_path: Path) -> None:
    cmd = ClaudeCodeRunner(RecordingExec()).command(
        ctx(tmp_path, "lecturer", resume_id="abc", dry_run=True)
    )
    assert cmd[cmd.index("--resume") + 1] == "abc"
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "--append-system-prompt" in cmd  # dry-run: inline, no file written
    assert not (tmp_path / "run").exists()


def test_claude_envelope_variants() -> None:
    env = {
        "type": "result",
        "is_error": True,
        "subtype": "error_during_execution",
        "result": "Claude AI usage limit reached|1756800000",
        "session_id": "s",
    }
    out = parse_envelope(json.dumps(env), "", 0)
    assert out.result is None and out.rate_limited and "is_error" in (out.error or "")
    assert out.exit_code != 0
    out = parse_envelope("garbage", "429 Too Many Requests", 1)
    assert out.rate_limited and out.error and out.result is None
    env2 = {
        "type": "result",
        "structured_output": {"summary": "ok"},
        "session_id": "z",
        "usage": {},
    }
    out = parse_envelope(json.dumps(env2), "", 0)
    assert out.result is not None and out.result.summary == "ok"
    stream = "\n".join(
        [json.dumps({"type": "system"}), json.dumps({"type": "result", "result": GOOD})]
    )
    assert parse_envelope(stream, "", 0).result is not None
    assert parse_envelope(json.dumps({"type": "result", "result": "not json"}), "", 0).error


def test_codex_command_stdin_closed(tmp_path: Path) -> None:
    ex = RecordingExec()
    out_file = tmp_path / "run" / "codex-last-message.json"
    c = ctx(tmp_path, "programmer", model=None)

    def fake(cmd, **kw):  # type: ignore[no-untyped-def]
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(GOOD)
        return ex(cmd, **kw)

    ex.responses["codex"] = ExecResult(
        0,
        "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "t-9"}),
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}
                ),
                json.dumps(
                    {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}}
                ),
            ]
        ),
        "",
    )
    out = CodexRunner(fake).run(c)
    call = ex.calls[0]
    cmd = call["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("-p") + 1] == "cube-chatgpt"
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"
    assert "--json" in cmd and "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("--output-schema") + 1].endswith("schema-strict.json")
    assert cmd[cmd.index("-o") + 1] == str(out_file)
    assert "--ephemeral" not in cmd  # programmer resumes sessions
    assert cmd[-1].startswith("SYSTEM")  # system prompt folded into the prompt
    assert call["stdin_devnull"] is True
    assert call["cwd"] == tmp_path
    assert (tmp_path / "run" / "schema.json").exists()
    assert out.ok and out.session_id == "t-9" and out.usage["input_tokens"] == 5


def test_codex_resume_fresh_and_errors(tmp_path: Path) -> None:
    cmd = CodexRunner(RecordingExec()).command(
        ctx(tmp_path, "programmer", resume_id="t-1", dry_run=True)
    )
    assert cmd[2:4] == ["resume", "t-1"]
    cmd = CodexRunner(RecordingExec()).command(ctx(tmp_path, "auditor", dry_run=True))
    assert "--ephemeral" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    out = parse_events(json.dumps({"type": "error", "message": "rate limit exceeded"}), "", 1, "")
    assert out.rate_limited and out.result is None and "codex" in (out.error or "")


def test_hermes_command_is_a_quiet_single_query_on_the_worker_profile(tmp_path: Path) -> None:
    """ADR-0022: chat -q --oneshot (dangerous commands denied), never the yolo -z path."""
    import sqlite3

    from cube.runners.hermes import TOOLSETS, session_usage

    ex = RecordingExec({"hermes": ExecResult(0, GOOD, "session_id: 20260907_abc\n")})
    home = tmp_path / "hermes-home"
    db = home / "profiles" / "cube-worker" / "state.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "create table sessions (id text, input_tokens int, output_tokens int, "
            "cache_read_tokens int, api_call_count int, estimated_cost_usd real)"
        )
        conn.execute("insert into sessions values ('20260907_abc', 6928, 76, 0, 2, 0.0)")
    c = ctx(tmp_path, "senior", model="qwen3.8-27b", env={"HERMES_HOME": str(home)})
    out = HermesRunner(
        ex, provider="local", env={"VLLM_API_KEY": "own-key", "VLLM_BASE_URL": "http://u:8000/v1"}
    ).run(c)
    cmd = ex.calls[0]["cmd"]
    assert ex.calls[0]["env"]["VLLM_API_KEY"] == "own-key"
    assert "own-key" not in " ".join(cmd)
    assert cmd[:3] == ["hermes", "-p", "cube-worker"]
    assert cmd[cmd.index("-m") + 1] == "qwen3.8-27b"
    assert cmd[cmd.index("--provider") + 1] == "local"
    assert "chat" in cmd and "--query-file" in cmd and "--oneshot" in cmd and "-Q" in cmd
    assert "-q" not in cmd  # a workday prompt exceeded argv limits (cube-0rp)
    assert cmd[cmd.index("--max-turns") + 1] == "6"
    query_path = Path(cmd[cmd.index("--query-file") + 1])
    assert query_path == c.run_dir / "hermes-query.md"
    assert "Reserve the last two iterations" in query_path.read_text()
    assert query_path.stat().st_mode & 0o077 == 0
    assert "-z" not in cmd
    assert cmd[cmd.index("-t") + 1] == TOOLSETS["read-only"] == "terminal"
    assert ex.calls[0]["env"]["COLUMNS"] == "4000"
    contract = ex.calls[0]["env"]["HERMES_EPHEMERAL_SYSTEM_PROMPT"]
    assert "iteration-limit" in contract and "exactly one RunResult JSON" in contract
    assert json.dumps(c.schema) in contract
    assert out.ok and out.session_id == "20260907_abc"
    assert out.usage["input_tokens"] == 6928 and out.usage["api_calls"] == 2
    assert session_usage(home, "cube-worker", "missing") == {}
    assert HermesRunner(ex, provider="local").name == "hermes@local"
    assert HermesRunner(ex).name == "hermes"


def test_timeout_keeps_stderr_session_id(tmp_path):
    import sys

    from cube.runners.base import default_exec

    result = default_exec(
        [
            sys.executable,
            "-c",
            "import sys,time; print('partial',end='',flush=True); "
            "print('session_id: fixture',file=sys.stderr,flush=True); time.sleep(30)",
        ],
        cwd=tmp_path,
        env={},
        timeout=0.3,
    )
    assert result.timed_out and result.returncode == 124
    assert "session_id: fixture" in result.stderr
    assert "timeout after" in result.stderr
    assert result.stdout == "partial"


def test_hermes_iteration_budget_honours_role_and_local_limit(tmp_path):
    local = HermesRunner(provider="local")
    cloud = HermesRunner(provider="openrouter")
    c = ctx(tmp_path, "senior", env={"CUBE_LOCAL_MAX_TURNS": "4"})
    assert local.max_turns(c) == 4
    assert cloud.max_turns(c) == 12
    c.role = c.role.model_copy(update={"max_turns": 3})
    assert local.max_turns(c) == cloud.max_turns(c) == 3
    assert "3 tool-calling iterations" in local.full_prompt(c)


def test_hermes_toolsets_follow_the_permission_mode(tmp_path: Path) -> None:
    from cube.runners.hermes import TOOLSETS

    runner = HermesRunner(RecordingExec({}), provider="local")
    cmd = runner.command(ctx(tmp_path, "scribe", model=None))
    assert cmd[cmd.index("-t") + 1] == TOOLSETS["workspace-write"] == "terminal,file"
    assert "-m" not in cmd
    # the system prompt travels inside the query, the profile carries no rules of its own
    query = runner.full_prompt(ctx(tmp_path, "scribe", model=None))
    assert query.startswith(ctx(tmp_path, "scribe", model=None).system_prompt or "")


def test_hermes_worktree_keeps_cube_cli_on_child_path(tmp_path: Path) -> None:
    cube_root = tmp_path / "cube"
    cube_bin = str(cube_root / ".venv" / "bin")
    ex = RecordingExec({"hermes": ExecResult(0, GOOD, "")})
    c = ctx(tmp_path, "senior", env={"CUBE_ROOT": str(cube_root), "PATH": "/usr/bin"})
    HermesRunner(ex, provider="local").run(c)
    assert ex.calls[0]["env"]["PATH"] == f"{cube_bin}:/usr/bin"
    c.env["PATH"] = f"/usr/bin:{cube_bin}"
    HermesRunner(ex, provider="local").run(c)
    assert ex.calls[-1]["env"]["PATH"] == f"{cube_bin}:/usr/bin"


def test_hermes_checkpoint_without_system_prompt(tmp_path: Path) -> None:
    c = ctx(tmp_path, "senior", system_prompt=None)
    query = HermesRunner(RecordingExec()).full_prompt(c)
    assert query.startswith(c.prompt)
    assert "never retry variants to bypass approval" in query
    assert "do not claim completion" in query


def test_hermes_partial_checkpoint_drops_all_actions(tmp_path):
    raw = (
        '{"summary":"Not finished", "bead_updates":[{"id":"cube-a","close":true}], '
        '"artifacts":[{"content":"cut'
    )
    ex = RecordingExec({"hermes": ExecResult(0, raw, "")})
    out = HermesRunner(ex, provider="local").run(ctx(tmp_path, "senior"))
    assert out.checkpoint_only and out.error is None
    assert out.raw_text == raw
    assert out.result.artifacts == out.result.bead_updates == out.result.escalations == []
    assert out.result.verdict is None
    assert len(ex.calls) == 1  # bounded local recovery, no repeated tool/model execution


@pytest.mark.parametrize(
    "raw",
    [
        '{"summary":"cut',
        '{"summary":123,"artifacts":[',
        '{"summary":"ok","artifacts":42}',
        "ordinary prose",
    ],
)
def test_hermes_does_not_guess_incomplete_or_invalid_summary(tmp_path, raw):
    out = HermesRunner(RecordingExec({"hermes": ExecResult(0, raw, "")})).run(
        ctx(tmp_path, "senior")
    )
    assert not out.checkpoint_only and out.result is None and out.error


def test_hermes_timeout_never_recovers_as_checkpoint(tmp_path):
    raw = '{"summary":"ok","artifacts":['
    out = HermesRunner(RecordingExec({"hermes": ExecResult(124, raw, "timeout", True)})).run(
        ctx(tmp_path, "senior")
    )
    assert not out.checkpoint_only and out.result is None


def test_hermes_short_checkpoint_contract_has_absolute_cli(tmp_path):
    c = ctx(tmp_path, "senior", env={"CUBE_ROOT": str(tmp_path / "cube root")})
    prompt = HermesRunner().full_prompt(c)
    assert "under 3000 characters" in prompt
    assert str(tmp_path / "cube root/.venv/bin/cube") in prompt


def test_openai_compat(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def post(url: str, headers, body: bytes, timeout: float):  # type: ignore[no-untyped-def]
        seen.update(url=url, headers=dict(headers), body=json.loads(body))
        return 200, json.dumps(
            {
                "id": "cmpl-1",
                "choices": [{"message": {"content": GOOD}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            }
        ).encode()

    r = OpenAICompatRunner(
        "openrouter", "https://openrouter.ai/api/v1", api_key="k", http_post=post
    )
    out = r.run(ctx(tmp_path, "scribe", model="z-ai/glm-5.3-flash"))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k"  # type: ignore[index]
    body = seen["body"]
    assert body["model"] == "z-ai/glm-5.3-flash" and body["response_format"] == {
        "type": "json_object"
    }  # type: ignore[index]
    assert body["messages"][0]["role"] == "system"  # type: ignore[index]
    assert out.ok and out.usage["prompt_tokens"] == 1

    def limited(url, headers, body, timeout):  # type: ignore[no-untyped-def]
        return 429, b'{"error": "rate limited"}'

    out = OpenAICompatRunner(
        "local", "http://node005:8000", http_post=limited, default_model="m"
    ).run(ctx(tmp_path, "scribe", model=None))
    assert out.rate_limited and not out.ok
    out = OpenAICompatRunner("local", "http://x", http_post=limited).run(
        ctx(tmp_path, "scribe", model=None)
    )
    assert "no model" in (out.error or "")


def test_stub_and_registry(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from cube.config import Settings

    s = Settings(env={"OPENROUTER_API_KEY": "k", "VLLM_BASE_URL": "http://node005:8000/v1"})
    assert make_runner("openrouter", s).name == "openrouter"
    assert make_runner("local", s).name == "local"
    for name in ("claude", "codex", "hermes", "stub"):
        assert make_runner(name, s).name == name
    stub = StubRunner()
    out = stub.run(ctx(tmp_path, "senior"))
    assert out.ok and out.result is not None and "stub" in out.result.summary
    canned = tmp_path / "canned.json"
    canned.write_text(json.dumps({"summary": "from file", "verdict": "approve"}))
    monkeypatch.setenv("CUBE_STUB_RESULT", str(canned))
    out = StubRunner().run(ctx(tmp_path, "senior"))
    assert out.result is not None and out.result.verdict == "approve"
    out = StubRunner(fail="boom").run(ctx(tmp_path, "senior"))
    assert not out.ok and out.error == "boom"
    assert (
        StubRunner(result=RunResult(summary="given")).run(ctx(tmp_path, "senior")).result.summary
        == "given"
    )  # type: ignore[union-attr]


def test_parse_helpers() -> None:
    assert extract_json_object('text ```json\n{"summary": "a"}\n``` more') == {"summary": "a"}
    assert extract_json_object('prefix {"summary": "b", "x": {"y": 1}} suffix') is not None
    assert extract_json_object("nothing") is None
    res, err = parse_result('{"nope": 1}')
    assert res is None and err and "RunResult invalid" in err
    assert looks_rate_limited("HTTP 429") and not looks_rate_limited("all fine", None)


def test_codex_command_pins_the_tier_model(tmp_path: Path) -> None:
    from cube.runners.codex import CodexRunner

    c = ctx(tmp_path, "programmer", model="gpt-5.6-sol")
    cmd = CodexRunner().command(c)
    assert cmd[cmd.index("-p") + 1] == "cube-chatgpt"
    assert cmd[cmd.index("-c") + 1] == "model=gpt-5.6-sol"
    plain = CodexRunner().command(ctx(tmp_path, "programmer", model=None))
    assert "-c" not in plain


def test_codex_schema_is_strict(tmp_path: Path) -> None:
    from cube.runners.codex import strict_schema

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "artifacts": {
                "type": "array",
                "items": {"type": "object", "properties": {"kind": {"type": "string"}}},
            },
            "verdict": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["summary"],
    }
    strict = strict_schema(schema)
    assert strict["additionalProperties"] is False
    assert strict["required"] == ["summary", "artifacts", "verdict"]
    item = strict["properties"]["artifacts"]["items"]
    assert item["additionalProperties"] is False and item["required"] == ["kind"]


def test_finished_runs_are_never_rate_limited_by_their_own_text() -> None:
    """A sysadmin's disk report ("24G free", "429 ms") is not a 429 (r-20260907-0028-6f)."""
    from cube.runners.codex import parse_events

    report = "disk 92% with 24G free (df -h), upload HTTP 200 in 429 ms, free -h shows 114Gi"
    result = {"summary": report, "next_steps": [], "escalations": [], "artifacts": []}
    env = {"type": "result", "is_error": False, "structured_output": result, "session_id": "s"}
    out = parse_envelope(json.dumps(env), "", 0)
    assert out.result is not None and not out.rate_limited and out.error is None
    # the same words on stderr of a failed run still count
    out = parse_envelope("garbage", "429 Too Many Requests", 1)
    assert out.rate_limited and out.result is None

    events = "\n".join(
        json.dumps(e)
        for e in (
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(result)},
            },
            {"type": "turn.completed", "usage": {"input_tokens": 1}},
        )
    )
    out = parse_events(events, "", 0, "")
    assert out.result is not None and not out.rate_limited


def test_bare_artifact_object_becomes_a_run_result() -> None:
    """A chat model that returns the literature digest itself still yields a RunResult."""
    digest = {"kind": "literature-digest", "entries": [{"id": "arxiv:1", "title": "t"}]}
    result, error = parse_result(json.dumps(digest))
    assert error is None and result is not None
    assert result.summary == "literature-digest artifact returned bare with 1 entries"
    assert [a.kind for a in result.artifacts] == ["literature-digest"]
    assert json.loads(result.artifacts[0].content or "")["entries"][0]["id"] == "arxiv:1"
    # an object that is neither an envelope nor an artifact still fails loudly
    result, error = parse_result(json.dumps({"entries": []}))
    assert result is None and "RunResult invalid" in (error or "")


def test_private_hermes_isolates_auxiliaries_and_credentials(tmp_path: Path, monkeypatch) -> None:
    import yaml

    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-cloud-key")
    ex = RecordingExec({"hermes": ExecResult(0, GOOD, "")})
    runner = HermesRunner(
        ex,
        provider="local",
        env={"VLLM_BASE_URL": "http://local/v1", "VLLM_API_KEY": "fixture-local-key"},
    )
    outcome = runner.run(
        ctx(
            tmp_path,
            "student-researcher",
            env={"CUBE_PRIVACY": "local-only"},
            model="fixture-local",
        )
    )
    assert outcome.ok
    call = ex.calls[0]
    assert call["cmd"][2] == "cube-student-local"
    assert "OPENROUTER_API_KEY" not in call["env"]
    assert call["env"]["VLLM_API_KEY"] == "fixture-local-key"
    assert call["env"]["PYTHON_DOTENV_DISABLED"] == "1"
    profile = Path(call["env"]["HERMES_HOME"]) / "profiles/cube-student-local/config.yaml"
    config = yaml.safe_load(profile.read_text())
    assert config["compression"]["enabled"] is False
    assert config["fallback_providers"] == []
    assert config["fallback_model"] is None
    assert config["plugins"]["enabled"] == []
    assert config["memory"] == {"memory_enabled": False, "user_profile_enabled": False}
    assert all(v["enabled"] is False for v in config["auxiliary"].values())
    assert profile.stat().st_mode & 0o777 == 0o600


def test_claude_long_prompt_travels_on_stdin(tmp_path: Path) -> None:
    from cube.runners.claude_code import ARGV_PROMPT_LIMIT, ClaudeCodeRunner

    ex = RecordingExec({"claude": ExecResult(0, GOOD, "")})
    runner = ClaudeCodeRunner(ex)
    short = ctx(tmp_path, "senior", prompt="short task")
    runner.run(short)
    assert ex.calls[-1]["cmd"][1:3] == ["-p", "short task"]
    assert ex.calls[-1]["stdin_text"] is None
    long_prompt = "x" * (ARGV_PROMPT_LIMIT + 1)
    runner.run(ctx(tmp_path, "senior", prompt=long_prompt))
    cmd = ex.calls[-1]["cmd"]
    assert cmd[1] == "-p" and cmd[2] == "--output-format"
    assert long_prompt not in cmd
    assert ex.calls[-1]["stdin_text"] == long_prompt


def test_claude_tool_shell_sees_the_cube_cli(tmp_path: Path) -> None:
    import os

    from cube.runners.claude_code import ClaudeCodeRunner

    ex = RecordingExec({"claude": ExecResult(0, GOOD, "")})
    ClaudeCodeRunner(ex).run(ctx(tmp_path, "liaison", env={"CUBE_ROOT": str(tmp_path)}))
    path = ex.calls[-1]["env"]["PATH"].split(os.pathsep)
    assert path[0] == str(tmp_path / ".venv" / "bin")


def test_claude_runs_report_tool_calls_and_stop_to_the_event_log(tmp_path: Path) -> None:
    """cube-watch needs a tool trail: every Claude run installs the notify hooks."""
    import json as _json

    from cube.runners.claude_code import ClaudeCodeRunner

    runner = ClaudeCodeRunner(RecordingExec({}))
    cmd = runner.command(ctx(tmp_path, "auditor", env={"CUBE_ROOT": str(tmp_path)}))
    settings = _json.loads(cmd[cmd.index("--settings") + 1])
    notify = str(tmp_path / ".venv" / "bin" / "cube") + " notify --hook"
    pre = settings["hooks"]["PreToolUse"]
    assert pre[-1]["matcher"] == "" and pre[-1]["hooks"][0]["command"] == notify
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == notify
    # the restricted roles keep their fail-closed guard in front of the notifier
    guarded = runner.command(ctx(tmp_path, "liaison", env={"CUBE_ROOT": str(tmp_path)}))
    settings = _json.loads(guarded[guarded.index("--settings") + 1])
    pre = settings["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Bash" and "tool_guard.py" in pre[0]["hooks"][0]["command"]
    assert pre[1]["hooks"][0]["command"] == notify
    assert guarded.count("--settings") == 1
