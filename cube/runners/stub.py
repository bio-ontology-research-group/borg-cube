"""Stub runner: returns a canned RunResult. Used by tests and `cube run --runner stub`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cube.model import RunResult
from cube.runners.base import RunContext, RunOutcome, parse_result, runner_usage

STUB_RESULT_ENV = "CUBE_STUB_RESULT"


class StubRunner:
    name = "stub"

    def __init__(self, result: RunResult | None = None, fail: str | None = None):
        self.result = result
        self.fail = fail
        self.calls: list[RunContext] = []

    def command(self, ctx: RunContext) -> list[str]:
        return ["stub", "--role", ctx.role.name, "--bead", ctx.bead or "-"]

    def run(self, ctx: RunContext) -> RunOutcome:
        self.calls.append(ctx)
        cmd = self.command(ctx)
        if self.fail:
            return RunOutcome(
                "", None, None, runner_usage({}, self.name), 1, self.fail, cmd, error=self.fail
            )
        result = self.result
        if result is None:
            override = os.environ.get(STUB_RESULT_ENV)
            if override:
                path = Path(override)
                text = path.read_text(encoding="utf-8") if path.exists() else override
                result, err = parse_result(text)
                if result is None:
                    return RunOutcome(
                        text,
                        None,
                        None,
                        runner_usage({}, self.name),
                        1,
                        err or "",
                        cmd,
                        error=err,
                    )
        if result is None:
            result = RunResult(
                summary=f"stub run of role {ctx.role.name}"
                + (f" on bead {ctx.bead}" if ctx.bead else "")
                + " (no model was called; source: cube/runners/stub.py)",
                next_actions=["nothing; this was a stub"],
            )
        text = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        return RunOutcome(
            raw_text=text,
            result=result,
            session_id=f"stub-{ctx.run_id}",
            usage=runner_usage({"input_tokens": 0, "output_tokens": 0}, self.name),
            exit_code=0,
            stderr="",
            command=cmd,
        )
