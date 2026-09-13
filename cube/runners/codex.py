"""Runner for `codex exec`.

The ChatGPT provider uses the `cube-chatgpt` profile (never the OpenRouter default
in `~/.codex/config.toml`). The OpenRouter provider uses `cube-openrouter`, which
points Codex at the OpenRouter responses API with the key from the environment
(ADR-0016).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cube.runners.base import (
    Exec,
    RunContext,
    RunOutcome,
    default_exec,
    failure_error,
    looks_rate_limited,
    parse_result,
    runner_usage,
    write_schema,
)
from cube.runners.naming import compose

DEFAULT_PROFILE = "cube-chatgpt"
OPENROUTER_PROFILE = "cube-openrouter"
LOCAL_PROFILE = "cube-local"
PROFILES = {"chatgpt": DEFAULT_PROFILE, "openrouter": OPENROUTER_PROFILE, "local": LOCAL_PROFILE}
SANDBOX = {
    "read-only": "read-only",
    "workspace-write": "workspace-write",
    "browser": "workspace-write",
    "none": "read-only",
}


def strict_schema(schema: Any) -> Any:
    """OpenAI structured output demands strict object schemas.

    Every object needs ``additionalProperties: false`` and must list all of its
    properties as required; optional fields stay optional through their
    ``anyOf [..., null]`` that pydantic already emits.
    """
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {key: strict_schema(value) for key, value in schema.items()}
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties") or {}
        out["additionalProperties"] = False
        out["required"] = list(props)
    return out


class CodexRunner:
    name = "codex"

    def __init__(
        self,
        exec_fn: Exec | None = None,
        binary: str = "codex",
        *,
        provider: str = "chatgpt",
    ):
        self.exec_fn = exec_fn or default_exec
        self.binary = binary
        self.provider = provider
        self.name = compose("codex", provider)

    @property
    def default_profile(self) -> str:
        return PROFILES.get(self.provider, DEFAULT_PROFILE)

    def output_file(self, ctx: RunContext) -> Path:
        return ctx.run_dir / "codex-last-message.json"

    def full_prompt(self, ctx: RunContext) -> str:
        if ctx.system_prompt:
            return ctx.system_prompt.rstrip() + "\n\n" + ctx.prompt
        return ctx.prompt

    def command(self, ctx: RunContext) -> list[str]:
        cmd = [self.binary, "exec"]
        if ctx.resume_id and ctx.role.session_policy == "resume":
            cmd += ["resume", ctx.resume_id]
        cmd += ["-p", ctx.profile or self.default_profile]
        if ctx.model:
            # The tier entry names the model; never inherit config.toml's default,
            # which on a laptop may be an OpenRouter id the ChatGPT account rejects.
            cmd += ["-c", f"model={ctx.model}"]
        if self.provider in ("openrouter", "local"):
            # OpenRouter answers `Server tool request failed` to Codex's server-side
            # web search and the local endpoint has no such tool. The profiles
            # disable it; repeat it here as belt and braces.
            cmd += ["-c", 'web_search="disabled"']
        cmd += [
            "--sandbox",
            ctx.sandbox or SANDBOX.get(ctx.role.permission_mode, "read-only"),
            "--json",
        ]
        if ctx.schema:
            schema_path = ctx.run_dir / "schema-strict.json"
            if not ctx.dry_run:
                write_schema(ctx)  # the plain schema stays in the run dir for provenance
                if not schema_path.exists():
                    schema_path.write_text(
                        json.dumps(strict_schema(ctx.schema), indent=1), encoding="utf-8"
                    )
            cmd += ["--output-schema", str(schema_path)]
        cmd += ["-o", str(self.output_file(ctx)), "--skip-git-repo-check"]
        if ctx.role.session_policy == "fresh":
            cmd.append("--ephemeral")
        cmd.append(self.full_prompt(ctx))
        return cmd

    def run(self, ctx: RunContext) -> RunOutcome:
        cmd = self.command(ctx)
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        # stdin must be closed: over ssh an open stdin makes codex wait for input forever.
        res = self.exec_fn(
            cmd, cwd=ctx.cwd, env=ctx.process_env(), timeout=ctx.timeout, stdin_devnull=True
        )
        out_file = self.output_file(ctx)
        final = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
        outcome = parse_events(
            res.stdout, res.stderr, res.returncode, final, cmd, timed_out=res.timed_out
        )
        outcome.usage = runner_usage(outcome.usage, self.name)
        return outcome


def parse_events(
    stdout: str,
    stderr: str,
    returncode: int,
    final_message: str,
    cmd: list[str] | None = None,
    *,
    timed_out: bool = False,
) -> RunOutcome:
    """Parse `codex exec --json` JSONL: thread id, usage, agent messages, errors."""
    thread_id: str | None = None
    usage: dict[str, Any] = {}
    messages: list[str] = []
    errors: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("type") or "")
        if kind in ("thread.started", "session.created", "session_configured"):
            tid = ev.get("thread_id") or ev.get("session_id") or ev.get("id")
            if tid:
                thread_id = str(tid)
        elif kind in ("turn.completed", "turn_completed"):
            u = ev.get("usage")
            if isinstance(u, dict):
                usage = dict(u)
        elif kind in ("item.completed", "item_completed"):
            item = ev.get("item")
            if isinstance(item, dict) and item.get("type") in ("agent_message", "message"):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    messages.append(text)
        elif kind in ("error", "turn.failed", "turn_failed"):
            msg = ev.get("message") or ev.get("error") or json.dumps(ev)
            errors.append(str(msg))
        if "thread_id" in ev and not thread_id:
            thread_id = str(ev["thread_id"])
    text = final_message.strip() or (messages[-1] if messages else "")
    result, error = parse_result(text) if text else (None, "codex produced no final message")
    if result is None:
        error = failure_error(
            error,
            harness="codex",
            timed_out=timed_out,
            stdout=text or stdout,
            stderr=stderr,
            returncode=returncode,
        )
    # Error channels only (stderr, error events, and the raw stream when no message
    # came back); a run that produced a result is never rate limited.
    rate_limited = result is None and looks_rate_limited(
        stderr, " ".join(errors), stdout[-4000:] if not text else None
    )
    if errors and result is None:
        error = f"codex error: {errors[-1][:300]}"
    if returncode != 0 and not error:
        error = f"codex exited {returncode}: {stderr.strip()[:200]}"
    if rate_limited and result is None and not looks_rate_limited(error):
        detail = errors[-1] if errors else (stderr.strip() or stdout[-4000:])
        error = f"{error or 'codex rate limited'}: {detail[:300]}"
    return RunOutcome(
        raw_text=text,
        result=result,
        session_id=thread_id,
        usage=usage,
        exit_code=returncode,
        stderr=stderr,
        command=cmd or [],
        rate_limited=rate_limited,
        error=error,
    )
