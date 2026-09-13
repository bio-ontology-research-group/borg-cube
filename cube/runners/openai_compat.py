"""OpenAI-compatible chat completions: `openrouter` (cloud, cheap) and `local` (vLLM node005)."""

from __future__ import annotations

import json
from typing import Any

from cube.runners.base import (
    HttpPost,
    RunContext,
    RunOutcome,
    default_http_post,
    looks_rate_limited,
    parse_result,
    runner_usage,
)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
LOCAL_DEFAULT_BASE = "http://node005:8000/v1"


def chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/v1/chat/completions"


class OpenAICompatRunner:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        default_model: str | None = None,
        http_post: HttpPost | None = None,
    ):
        self.name = name
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model
        self.http_post = http_post or default_http_post

    def payload(self, ctx: RunContext) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if ctx.system_prompt:
            messages.append({"role": "system", "content": ctx.system_prompt})
        messages.append({"role": "user", "content": ctx.prompt})
        model = ctx.model or self.default_model or ""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        if self.name == "openrouter":
            # Robert, 2026-09-07: OpenRouter enforces the data policy per request.
            # "deny" excludes every endpoint that logs or trains on prompts, whatever
            # the account settings allow; only an open-data run (ADR-0018) says
            # "allow", which is what admits the free endpoints.
            body["provider"] = {"data_collection": "allow" if ctx.open_data else "deny"}
        return body

    def command(self, ctx: RunContext) -> list[str]:
        return [
            "POST",
            chat_url(self.base_url),
            f"model={ctx.model or self.default_model or '(unset)'}",
            "response_format=json_object",
        ]

    def run(self, ctx: RunContext) -> RunOutcome:
        cmd = self.command(ctx)
        body = self.payload(ctx)
        if not body["model"]:
            return RunOutcome(
                "",
                None,
                None,
                runner_usage({}, self.name),
                2,
                "",
                cmd,
                error=f"{self.name}: no model set",
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/bio-ontology-research-group/borg-cube"
            headers["X-Title"] = "borg-cube"
        try:
            status, raw = self.http_post(
                chat_url(self.base_url), headers, json.dumps(body).encode("utf-8"), ctx.timeout
            )
        except OSError as exc:
            return RunOutcome(
                "",
                None,
                None,
                runner_usage({}, self.name),
                1,
                str(exc),
                cmd,
                error=f"{self.name}: endpoint unreachable: {exc}",
            )
        text = raw.decode("utf-8", errors="replace")
        if status == 429 or (status >= 400 and looks_rate_limited(text)):
            return RunOutcome(
                text,
                None,
                None,
                runner_usage({}, self.name),
                1,
                "",
                cmd,
                rate_limited=True,
                error=f"HTTP {status}: {text[:300]}",
            )
        if status >= 400:
            return RunOutcome(
                text,
                None,
                None,
                runner_usage({}, self.name),
                1,
                "",
                cmd,
                error=f"HTTP {status}: {text[:300]}",
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return RunOutcome(
                text,
                None,
                None,
                runner_usage({}, self.name),
                1,
                "",
                cmd,
                error="non-JSON response",
            )
        content = ""
        try:
            content = str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            return RunOutcome(
                text,
                None,
                None,
                runner_usage({}, self.name),
                1,
                "",
                cmd,
                error="no choices in response",
            )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        result, error = parse_result(content)
        return RunOutcome(
            raw_text=content,
            result=result,
            session_id=str(data.get("id")) if data.get("id") else None,
            usage=runner_usage(usage, self.name),
            exit_code=0 if result else 1,
            stderr="",
            command=cmd,
            error=error,
            cost_usd=(
                float(usage["cost"])
                if self.name == "openrouter" and isinstance(usage.get("cost"), int | float)
                else None
            ),
        )
