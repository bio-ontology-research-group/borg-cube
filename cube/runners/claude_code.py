"""Runner for `claude -p`: Claude Max through Claude Code (ADR-0006), or GLM on
OpenRouter through the same harness (ADR-0016).

The Anthropic provider is the subscription and never sees an API key. The
OpenRouter provider points the same binary at the Anthropic-compatible endpoint
with an OpenRouter key, in the child environment only, and under its own
``CLAUDE_CONFIG_DIR`` so the Max login in ``~/.claude`` stays untouched.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
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
    write_system_prompt,
)
from cube.runners.naming import compose

OPENROUTER_ANTHROPIC_BASE = "https://openrouter.ai/api"
OPENROUTER_CONFIG_DIRNAME = "claude-openrouter"
LOCAL_CONFIG_DIRNAME = "claude-local"
CONFIG_DIRNAMES = {"openrouter": OPENROUTER_CONFIG_DIRNAME, "local": LOCAL_CONFIG_DIRNAME}
LOCAL_DEFAULT_ANTHROPIC_BASE = "http://localhost:8000"


def anthropic_base_from_openai(url: str) -> str:
    """The Anthropic-compatible base of an OpenAI-style base URL.

    Claude Code appends `/v1/messages` itself, so `http://host:8000/v1` (the
    VLLM_BASE_URL the chat runner uses) becomes `http://host:8000`.
    """
    base = url.strip().rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


# Claude Code prints this once per run when the model id is not an Anthropic one.
# It is informational: not an error, and never a rate limit.
UNRECOGNIZED_MODEL = re.compile(r"^\s*\[claude-code:unrecognized_model\].*$", re.MULTILINE)


def strip_harmless_stderr(stderr: str) -> str:
    """Drop the `[claude-code:unrecognized_model]` line before judging stderr."""
    return UNRECOGNIZED_MODEL.sub("", stderr).strip()


# Claude Code permission modes for the role's permission_mode. Tool allowlists do the real
# restriction; the mode only decides what happens to a tool call that is not pre-approved.
PERMISSION_MODES = {
    "read-only": "dontAsk",
    "workspace-write": "acceptEdits",
    "browser": "acceptEdits",
    "none": "dontAsk",
}
READ_ONLY_TOOLS = ["Read", "Grep", "Glob", "WebFetch"]


def deny_paths(roots: list[Path]) -> list[Path]:
    """Each closed directory by its name and, when it is a symlink, by its target."""
    out: list[Path] = []
    for root in roots:
        expanded = Path(root).expanduser()
        for candidate in (expanded, expanded.resolve() if expanded.exists() else expanded):
            if candidate not in out:
                out.append(candidate)
    return out


def read_rule(root: Path) -> str:
    """The Claude Code permission rule that allows Read under ROOT and nowhere else."""
    absolute = str(Path(root).expanduser())
    return f"Read(/{absolute}/**)" if absolute.startswith("/") else f"Read({absolute}/**)"


# Below the kernel's single-argument limit (131072 bytes) with headroom.
ARGV_PROMPT_LIMIT = 100_000


class ClaudeCodeRunner:
    name = "claude"

    def __init__(
        self,
        exec_fn: Exec | None = None,
        binary: str = "claude",
        *,
        provider: str = "anthropic",
        env: dict[str, str] | None = None,
        config_dir: Path | None = None,
    ):
        self.exec_fn = exec_fn or default_exec
        self.binary = binary
        self.provider = provider
        self.env = dict(env or {})
        self.config_dir = config_dir
        self.name = compose("claude", provider)

    def provider_env(self, ctx: RunContext) -> dict[str, str]:
        """Environment additions for a non-native provider. Secrets live here only."""
        if self.provider not in CONFIG_DIRNAMES:
            return {}
        model = ctx.model or self.env.get("ANTHROPIC_MODEL") or ""
        if self.provider == "local":
            # Robert, 2026-09-07 (ADR-0021): the group's own endpoint speaks the
            # Anthropic messages API; the key is the one in VLLM_API_KEY.
            base = anthropic_base_from_openai(
                self.env.get("VLLM_ANTHROPIC_BASE_URL")
                or self.env.get("VLLM_BASE_URL")
                or LOCAL_DEFAULT_ANTHROPIC_BASE
            )
            token = self.env.get("VLLM_API_KEY", "")
        else:
            base = self.env.get("OPENROUTER_ANTHROPIC_BASE_URL") or OPENROUTER_ANTHROPIC_BASE
            token = self.env.get("OPENROUTER_API_KEY", "")
        config_dir = self.openrouter_config_dir(ctx)
        extra = {
            "ANTHROPIC_BASE_URL": base,
            "ANTHROPIC_AUTH_TOKEN": token,
            # An inherited Anthropic key would win over the auth token; blank it.
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CONFIG_DIR": str(config_dir),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
        }
        for key in (
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
        ):
            extra[key] = model
        return extra

    def openrouter_config_dir(self, ctx: RunContext) -> Path:
        """The private config dir for this provider; `~/.claude` is never reused."""
        if self.config_dir is not None:
            return self.config_dir
        base = ctx.state_dir or ctx.run_dir
        return base / "harness" / CONFIG_DIRNAMES.get(self.provider, OPENROUTER_CONFIG_DIRNAME)

    def cube_cli(self, ctx: RunContext) -> Path:
        """The checkout's own `cube` executable; hooks run without a login PATH."""
        return Path(ctx.env.get("CUBE_ROOT") or ctx.cwd) / ".venv" / "bin" / "cube"

    def prompt_on_stdin(self, ctx: RunContext) -> bool:
        """Long prompts go through stdin: one argv string is capped at 128 KiB.

        The coordinator's management prompt exceeded it and Claude never
        started (``[Errno 7] Argument list too long: 'claude'``, r-20260912-0729-10).
        ``claude -p`` without a query reads the prompt from piped stdin.
        """
        return len(ctx.prompt.encode("utf-8")) > ARGV_PROMPT_LIMIT

    def command(self, ctx: RunContext) -> list[str]:
        cmd = [
            self.binary,
            "-p",
            *([] if self.prompt_on_stdin(ctx) else [ctx.prompt]),
            "--output-format",
            "json",
            "--permission-mode",
            PERMISSION_MODES.get(ctx.role.permission_mode, "dontAsk"),
        ]
        tools = list(ctx.role.allowed_tools) or (
            READ_ONLY_TOOLS if ctx.role.permission_mode == "read-only" else []
        )
        protected = ctx.role.name in {"liaison", "sysadmin"}
        # Every run reports its tool calls and its stop to the event log, so the
        # cockpit can watch the task being solved (cube-watch, ADR-0036). The
        # private CLAUDE_CONFIG_DIR carries no hooks of its own.
        notify = shlex.join([str(self.cube_cli(ctx)), "notify", "--hook"])
        notify_hook = {"type": "command", "command": notify, "timeout": 10}
        settings: dict[str, Any] = {
            "hooks": {
                "PreToolUse": [{"matcher": "", "hooks": [notify_hook]}],
                "Stop": [{"hooks": [notify_hook]}],
            }
        }
        if protected:
            # Only the audited dispatcher is exposed, including on resumed runs.
            tools = []  # The fail-closed hook grants only parsed, fixed dispatcher calls.
            hook = shlex.join(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve().parents[1] / "tool_guard.py"),
                    "--role",
                    ctx.role.name,
                ]
            )
            settings["hooks"]["PreToolUse"].insert(
                0,
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": hook, "timeout": 10}],
                },
            )
            cmd += [
                "--tools",
                "Bash",
                "--setting-sources",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
            ]
        cmd += ["--settings", json.dumps(settings)]
        # Robert, 2026-09-08 (ADR-0027): a role with `read_roots: host` reads files
        # only under the host's readable directories. Claude Code's path rules do
        # the bounding (`Read(//abs/path/**)`); Grep and Glob are not path-bounded,
        # so such a role must not list them, and `cube lookup` searches instead.
        for root in [] if protected else ctx.read_roots:
            tools.append(read_rule(root))
        if tools:
            cmd += ["--allowedTools", ",".join(tools)]
        denied = [read_rule(root) for root in deny_paths(ctx.deny_roots)] if ctx.read_roots else []
        if denied:
            cmd += ["--disallowedTools", ",".join(denied)]
        system_file = write_system_prompt(ctx) if not ctx.dry_run else None
        if system_file is not None:
            cmd += ["--append-system-prompt-file", str(system_file)]
        elif ctx.system_prompt:
            cmd += ["--append-system-prompt", ctx.system_prompt]
        if ctx.model:
            cmd += ["--model", ctx.model]
        if ctx.schema:
            cmd += ["--json-schema", json.dumps(ctx.schema, separators=(",", ":"))]
        if ctx.resume_id and ctx.role.session_policy == "resume":
            cmd += ["--resume", ctx.resume_id]
        if ctx.role.max_turns:
            cmd += ["--max-turns", str(ctx.role.max_turns)]
        return cmd

    def run(self, ctx: RunContext) -> RunOutcome:
        cmd = self.command(ctx)
        env = ctx.process_env()
        # The restricted dispatcher commands (`cube boundary ...`) and every
        # ledger command run through the tool shell, which inherits this PATH.
        # Under systemd it has no venv: the laptop liaison's four bounded reads
        # all failed with "cube: command not found" (r-20260912-0745-c5).
        cube_bin = str(Path(env.get("CUBE_ROOT") or ctx.cwd) / ".venv" / "bin")
        parts = [
            part for part in env.get("PATH", "").split(os.pathsep) if part and part != cube_bin
        ]
        env["PATH"] = os.pathsep.join([cube_bin, *parts])
        extra = self.provider_env(ctx)
        if extra:
            config_dir = Path(extra["CLAUDE_CONFIG_DIR"])
            config_dir.mkdir(parents=True, exist_ok=True)
            config_dir.chmod(0o700)
            env.update(extra)
        if self.prompt_on_stdin(ctx):
            res = self.exec_fn(
                cmd, cwd=ctx.cwd, env=env, timeout=ctx.timeout, stdin_text=ctx.prompt
            )
        else:
            res = self.exec_fn(cmd, cwd=ctx.cwd, env=env, timeout=ctx.timeout, stdin_devnull=True)
        outcome = parse_envelope(
            res.stdout, res.stderr, res.returncode, cmd, timed_out=res.timed_out
        )
        if self.provider in CONFIG_DIRNAMES:
            # Claude Code prices every run with Anthropic rates, which are wrong by
            # two orders of magnitude here (and by everything on the local endpoint).
            # Drop it; the budget ledger estimates from the cube.yaml price table
            # and bills that estimate (ADR-0016).
            outcome.cost_usd = None
        outcome.usage = runner_usage(outcome.usage, self.name)
        return outcome


def parse_envelope(
    stdout: str,
    stderr: str,
    returncode: int,
    cmd: list[str] | None = None,
    *,
    timed_out: bool = False,
) -> RunOutcome:
    """Parse the `--output-format json` envelope: result, session_id, total_cost_usd, usage."""
    envelope: dict[str, Any] | None = None
    text = stdout.strip()
    try:
        loaded = json.loads(text) if text else None
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        envelope = loaded
    elif isinstance(loaded, list):
        for item in reversed(loaded):
            if isinstance(item, dict) and item.get("type") == "result":
                envelope = item
                break
    if envelope is None:
        # Fallback: stream-json lines; take the last "result" line.
        for line in reversed(text.splitlines()):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("type") == "result":
                envelope = item
                break

    stderr_signal = strip_harmless_stderr(stderr)
    # Robert, 2026-09-07: only error channels count. A sysadmin's own disk report
    # ("24G free", "HTTP 200 in 429 ms") in the assistant text once parked the
    # whole harness for five hours (r-20260907-0028-6f).
    rate_limited = looks_rate_limited(stderr_signal)
    if envelope is None:
        rate_limited = rate_limited or looks_rate_limited(text[-4000:])
        return RunOutcome(
            raw_text=stdout,
            result=None,
            session_id=None,
            usage={},
            exit_code=returncode or 1,
            stderr=stderr,
            command=cmd or [],
            rate_limited=rate_limited,
            error=failure_error(
                "no JSON envelope from claude"
                + (f": {stderr_signal[:200]}" if stderr_signal else ""),
                harness="claude",
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr_signal,
                returncode=returncode,
            ),
        )

    session_id = envelope.get("session_id")
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    cost = envelope.get("total_cost_usd")
    is_error = bool(envelope.get("is_error"))
    body: Any = envelope.get("structured_output")
    if body is None:
        body = envelope.get("result")
    raw = body if isinstance(body, str) else json.dumps(body) if body is not None else ""
    error: str | None = None
    result = None
    if is_error:
        error = f"claude reported is_error ({envelope.get('subtype', 'error')}): {raw[:300]}"
        rate_limited = rate_limited or looks_rate_limited(raw)
    else:
        result, error = parse_result(body if isinstance(body, dict) else raw)
    if result is not None:
        rate_limited = False
    if rate_limited and result is None and not looks_rate_limited(error):
        detail = stderr_signal or raw
        error = f"{error or 'claude rate limited'}: {detail[:300]}"
    return RunOutcome(
        raw_text=raw,
        result=result,
        session_id=str(session_id) if session_id else None,
        usage=dict(usage or {}),
        exit_code=returncode if not is_error else (returncode or 1),
        stderr=stderr,
        command=cmd or [],
        rate_limited=rate_limited,
        error=error,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
    )
