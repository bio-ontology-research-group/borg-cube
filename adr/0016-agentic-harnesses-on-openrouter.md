# ADR-0016: Agentic harnesses on OpenRouter

Status: accepted
Date: 2026-09-05
Extends: ADR-0006 (subscriptions through their own clients), ADR-0015 (free OpenRouter defaults)

## Context

The `openrouter` runner is a single chat completion with `response_format=json_object`
and no tools. An agent routed to it can only return text. That is fine for a digest or
a review, and wrong for everything else: the coordinator's daily management review
returned twenty planned beads as `next_actions` prose and nothing executed them, and
the sysadmin's daily server review could not run the commands it was asked to run.

Robert's instruction was to set up Claude Code or Codex runners that use OpenRouter
with GLM as the model, and then to execute tasks with them. We already have two
agentic harnesses. Both can be pointed at OpenRouter, verified live on ws on
2026-09-05:

- `https://openrouter.ai/api/v1/messages` (Anthropic Messages API compatible) with
  `z-ai/glm-5.3-flash` returns `tool_use` blocks and a `usage.cost` field.
- Claude Code 2.1.261 with `ANTHROPIC_BASE_URL=https://openrouter.ai/api`,
  `ANTHROPIC_AUTH_TOKEN=$OPENROUTER_API_KEY` and `ANTHROPIC_MODEL=z-ai/glm-5.3-flash`
  ran the Bash tool under `--allowedTools` and returned the normal
  `--output-format json` envelope. It printed one harmless stderr line,
  `[claude-code:unrecognized_model] {...}`. Its `total_cost_usd` was 0.158 for a run
  that cost about 0.002 on OpenRouter, because it prices every run with Anthropic
  rates.
- Codex 0.153.3 with a provider whose `base_url` is `https://openrouter.ai/api/v1`,
  `wire_api = "responses"` (this version rejects `"chat"`), `env_key = "OPENROUTER_API_KEY"`
  and `web_search = "disabled"` (otherwise OpenRouter answers `Server tool request
  failed`) ran a shell command and returned the last message. In the read-only sandbox
  `uv run` fails because `~/.cache/uv` is not writable, so the profile adds
  `~/.cache/uv` to `sandbox_workspace_write.writable_roots`.

## Decision

A tier entry names a harness and, optionally, a provider:
`{runner: claude, provider: openrouter, model: z-ai/glm-5.3}`. The composed token
`claude@openrouter` is the runner's identity everywhere a runner is a string: routing,
tier state, backoff, the price table, the budget ledger, run reports and the cockpit.
`cube/runners/naming.py` splits it again (`harness_of`, `provider_of`, `is_agentic`).
The yaml also accepts `runner: claude@openrouter` directly; both spellings normalise to
the same object.

The Claude Code runner injects the OpenRouter settings into the child environment only,
never onto the command line and never into a file, and uses its own
`CLAUDE_CONFIG_DIR` under `state/harness/claude-openrouter` (mode 0700). ADR-0006 stays
true: `~/.claude` and the Max login belong to the native provider alone. The Codex
runner defaults to the `cube-openrouter` profile, still pins the model with
`-c model=<id>`, and repeats `-c web_search="disabled"` as belt and braces.

Routing gains `needs_tools`. When true, entries whose token is not agentic are skipped
with the reason `<target> has no tools` and the search continues through the tier
fallbacks as usual. `cube run` derives it from the role (a non-empty `allowed_tools`,
or `permission_mode` of `workspace-write` or `browser`, means tools; `permission_mode:
none` or an empty allowlist means none) and `--needs-tools` / `--no-needs-tools`
override it. The agent workday patrol passes `needs_tools=True` for the coordinator's
daily management review and the sysadmin's daily server review.

Cost: for an OpenRouter provider the runner discards the harness's own cost number and
the budget ledger estimates from the cube.yaml price table, then bills that estimate as
both `cost_usd` and `equivalent_usd`, because OpenRouter really does charge for it.
Claude Code's `total_cost_usd` is ignored for this provider; it is Anthropic pricing
applied to a GLM run and is wrong by about two orders of magnitude.

The `[claude-code:unrecognized_model]` stderr line is stripped before stderr is judged,
so it is neither an error nor a rate limit.

## Consequences

- Tool-capable work runs on GLM at roughly one fiftieth of Claude Opus rates, and the
  Claude subscription stays reserved for the group leader.
- Two new price targets exist per model and harness (`claude@openrouter:<model>`,
  `codex@openrouter:<model>`). A missing one produces the usual "no price" warning and
  counts zero, which understates real spend, so adding a harness model means adding its
  price in the same commit.
- `cube doctor` gains `check_harness_providers`: key, binary, config-dir writability and
  the Codex profile file. It is an error on ws and a warning elsewhere, because a laptop
  is a thin client.
- The Codex OpenRouter profile must be installed as `~/.codex/cube-openrouter.config.toml`
  from `deploy/codex-openrouter-profile.toml`. Without it, `codex@openrouter` fails and
  the tier falls through.
- Adding another model is a cube.yaml edit: one tier entry with `provider: openrouter`
  and one price line. No code change.
