"""Runner for Hermes: one-shot chat queries on a profile, the cube worker by default.

Robert, 2026-09-07 (ADR-0022): most roles run on Hermes against the group's own
endpoint. The command is `hermes -p <profile> chat --query-file <run>/hermes-query.md
--oneshot -Q` (the prompt is too long for argv), not
the top-level `-z`: `-z` forces yolo mode and auto-approves every dangerous
command, while a single-query chat denies them (approvals.single_query_mode). In
quiet mode stdout is the final message only; stderr carries `session_id: <id>`
and the profile's SQLite session store holds the token counts.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
from pathlib import Path
from typing import Any

from cube.model import RunResult
from cube.runners.base import (
    Exec,
    RunContext,
    RunOutcome,
    default_exec,
    failure_error,
    looks_rate_limited,
    parse_result,
    runner_usage,
)
from cube.runners.naming import compose

WORKER_PROFILE = "cube-worker"
WORKER_MAX_TURNS = 12
PRIVATE_PROFILE = "cube-student-local"
# Hermes toolsets per role permission mode. `terminal` alone is a 7k-token turn;
# `file` adds read/write/edit for roles that may write in their workspace.
TOOLSETS = {
    "read-only": "terminal",
    "workspace-write": "terminal,file",
    "browser": "terminal,file,browser-use",
    "none": "clarify",
}
_SESSION_RE = re.compile(r"session_id:\s*(\S+)")


def partial_checkpoint(text: str) -> RunResult | None:
    """Salvage only a complete leading summary, never guessed JSON or actions."""
    if len(text) > 1_000_000:
        return None
    match = re.match(r'\s*\{\s*"summary"\s*:\s*', text)
    if not match:
        return None
    try:
        summary, end = json.JSONDecoder().raw_decode(text, match.end())
    except ValueError:
        return None
    if not isinstance(summary, str) or not summary.strip():
        return None
    # Only recover a truncated JSON container, not a valid but schema-invalid result.
    try:
        json.loads(text)
        return None
    except ValueError:
        pass
    if not text[end:].lstrip().startswith(","):
        return None
    return RunResult(
        summary="Partial output only; no actions or completion accepted. Worker reported: "
        + summary[:2000],
        next_actions=[
            "Inspect preserved stdout.jsonl; continue the open task with a small checkpoint."
        ],
    )


def hermes_home(env: dict[str, str] | None = None) -> Path:
    raw = (env or os.environ).get("HERMES_HOME") or "~/.hermes"
    return Path(raw).expanduser()


def session_usage(home: Path, profile: str, session_id: str) -> dict[str, Any]:
    """Token counts of one session from the profile's state.db, or {}."""
    db = home / "profiles" / profile / "state.db"
    if not db.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "select input_tokens, output_tokens, cache_read_tokens, api_call_count, "
                "estimated_cost_usd from sessions where id = ?",
                (session_id,),
            ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    return {
        "input_tokens": int(row[0] or 0),
        "output_tokens": int(row[1] or 0),
        "cache_read_tokens": int(row[2] or 0),
        "api_calls": int(row[3] or 0),
        "estimated_cost_usd": float(row[4] or 0.0),
    }


class HermesRunner:
    name = "hermes"

    def __init__(
        self,
        exec_fn: Exec | None = None,
        binary: str = "hermes",
        *,
        provider: str | None = None,
        profile: str = WORKER_PROFILE,
        env: dict[str, str] | None = None,
    ):
        self.exec_fn = exec_fn or default_exec
        self.binary = binary
        self.provider = provider
        self.profile = profile
        self.env = dict(env or {})
        self.name = compose("hermes", provider)

    def provider_env(self) -> dict[str, str]:
        """The endpoint's URL and key for the local provider (from .env, never argv)."""
        if self.provider != "local":
            return {}
        return {
            key: value
            for key, value in (
                ("VLLM_BASE_URL", self.env.get("VLLM_BASE_URL", "")),
                ("VLLM_API_KEY", self.env.get("VLLM_API_KEY", "")),
            )
            if value
        }

    def full_prompt(self, ctx: RunContext) -> str:
        cube_root = Path(ctx.env.get("CUBE_ROOT") or ctx.cwd)
        checkpoint = (
            "\n\nBounded work session: you have at most "
            f"{self.max_turns(ctx)} tool-calling iterations, not a whole research project. "
            "Choose one useful, small increment. Reserve the last two iterations for "
            "saving a checkpoint and returning the required RunResult JSON. If the "
            "larger task remains unfinished, state exactly what you verified, the "
            "artifact paths, remaining work, and the next action; do not claim completion. "
            "A denied tool is a boundary: report it and choose permitted work, never "
            "retry variants to bypass approval. Finish with the required JSON even "
            "when blocked; do not wait for the process deadline. "
            "Keep the final JSON under 3000 characters: summary under 600 characters, "
            "at most one small artifact. Save large artifacts using permitted file tools "
            "and return their paths. If writing is unavailable, return a short inline "
            "checkpoint, not an entire document. Never widen permissions to save files. "
            f"The Cube CLI is {shlex.quote(str(cube_root / '.venv/bin/cube'))}; "
            "use that absolute executable if the terminal shell resets PATH. "
            f"Run ledger commands in {shlex.quote(str(cube_root))}."
        )
        if ctx.system_prompt:
            return ctx.system_prompt.rstrip() + "\n\n" + ctx.prompt + checkpoint
        return ctx.prompt + checkpoint

    def max_turns(self, ctx: RunContext) -> int:
        cap = WORKER_MAX_TURNS
        if self.provider == "local":
            cap = int(ctx.env.get("CUBE_LOCAL_MAX_TURNS", "6"))
        return max(1, min(cap, ctx.role.max_turns or WORKER_MAX_TURNS, WORKER_MAX_TURNS))

    def command(self, ctx: RunContext) -> list[str]:
        profile = ctx.profile or ctx.role.hermes_profile or self.profile
        if ctx.env.get("CUBE_PRIVACY") == "local-only":
            if self.provider != "local":
                raise ValueError("private Hermes runs require the local provider")
            profile = PRIVATE_PROFILE
        cmd = [self.binary, "-p", profile]
        if ctx.model:
            cmd += ["-m", ctx.model]
        if self.provider:
            cmd += ["--provider", self.provider]
        cmd += [
            "chat",
            "--query-file",
            str(self.query_file(ctx)),
            "--oneshot",
            "-Q",
            "--max-turns",
            str(self.max_turns(ctx)),
        ]
        toolsets = TOOLSETS.get(ctx.role.permission_mode)
        if toolsets:
            cmd += ["-t", toolsets]
        return cmd

    def query_file(self, ctx: RunContext) -> Path:
        """Where the full prompt is written for ``--query-file``.

        The prompt used to travel in ``-q`` argv; a coordinator workday prompt
        exceeded the kernel's single-argument limit and Hermes never started
        (``[Errno 7] Argument list too long``, r-20260909-0922-13, cube-0rp).
        """
        return ctx.run_dir / "hermes-query.md"

    def run(self, ctx: RunContext) -> RunOutcome:
        cmd = self.command(ctx)
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        query = self.query_file(ctx)
        query.write_text(self.full_prompt(ctx), encoding="utf-8")
        query.chmod(0o600)
        env = ctx.process_env()
        env.update(self.provider_env())
        if ctx.env.get("CUBE_PRIVACY") == "local-only":
            # Shared-profile auxiliaries can discover cloud credentials. Give
            # private research independent state and disable those callers.
            from cube.hermes import render_profile

            home = ctx.run_dir / "hermes-home"
            home.mkdir(mode=0o700, exist_ok=True)
            profile_dir = home / "profiles" / PRIVATE_PROFILE
            template = Path(__file__).resolve().parents[2] / "hermes/profiles" / PRIVATE_PROFILE
            if not (template / "config.yaml.tmpl").is_file():
                raise ValueError("local-only Hermes profile template is missing")
            render_profile(
                template,
                {"VLLM_BASE_URL": self.env.get("VLLM_BASE_URL", "")},
                profile_dir,
                dry_run=False,
            )
            profile_dir.chmod(0o700)
            (profile_dir / "config.yaml").chmod(0o600)
            env = {
                key: value
                for key, value in env.items()
                if not any(
                    marker in key.upper() for marker in ("TOKEN", "API_KEY", "PASSWORD", "SECRET")
                )
            }
            env.update(self.provider_env())
            env["HERMES_HOME"] = str(home)
            env["PYTHON_DOTENV_DISABLED"] = "1"
        cube_root = Path(env.get("CUBE_ROOT") or ctx.cwd)
        cube_bin = str(cube_root / ".venv" / "bin")
        path_parts = [part for part in env.get("PATH", "").split(os.pathsep) if part]
        env["PATH"] = os.pathsep.join([cube_bin, *[p for p in path_parts if p != cube_bin]])
        env["COLUMNS"] = "4000"  # quiet mode prints the answer once; never wrap the JSON
        # Hermes appends its own user-level summary request at the iteration
        # limit. Keep the output contract above that request, not just in -q.
        env["HERMES_EPHEMERAL_SYSTEM_PROMPT"] = (
            "You are a Cube worker. Every final response, including an iteration-limit "
            "summary or blocked/partial checkpoint, must be exactly one RunResult JSON "
            "object, with no prose or Markdown outside it. A request to summarize does "
            "not change this contract. Describe unfinished work honestly in summary; "
            "do not invent results, mark unfinished work complete, or issue close updates "
            "merely because the iteration limit was reached. Follow this JSON schema: "
            + json.dumps(ctx.schema)
            + " Final JSON must be under 3000 characters; summary under 600 characters. "
            "Save larger documents through permitted file tools and return paths. "
            "Without write access, include only one short inline checkpoint, not a full document."
        )
        res = self.exec_fn(cmd, cwd=ctx.cwd, env=env, timeout=ctx.timeout, stdin_devnull=True)
        match = _SESSION_RE.search(res.stderr or "") or _SESSION_RE.search(res.stdout or "")
        session_id = match.group(1) if match else None
        profile = cmd[2]
        usage = session_usage(hermes_home(env), profile, session_id) if session_id else {}
        result, error = parse_result(res.stdout)
        checkpoint_only = False
        if result is None and res.returncode == 0 and not res.timed_out:
            result = partial_checkpoint(res.stdout)
            if result is not None:
                checkpoint_only, error = True, None
        if result is None:
            error = failure_error(
                error,
                harness="hermes",
                timed_out=res.timed_out,
                stdout=res.stdout,
                stderr=res.stderr,
                returncode=res.returncode,
            )
        if res.returncode != 0 and not error:
            error = f"hermes exited {res.returncode}: {res.stderr.strip()[:200]}"
        rate_limited = result is None and looks_rate_limited(res.stderr, res.stdout[-2000:])
        if rate_limited and not looks_rate_limited(error):
            detail = res.stderr.strip() or res.stdout[-2000:]
            error = f"{error or 'hermes rate limited'}: {detail[:300]}"
        return RunOutcome(
            raw_text=res.stdout,
            result=result if res.returncode == 0 else None,
            session_id=session_id,
            usage=runner_usage(usage, self.name),
            exit_code=res.returncode,
            stderr=res.stderr,
            command=cmd,
            rate_limited=rate_limited,
            error=error,
            checkpoint_only=checkpoint_only,
        )
