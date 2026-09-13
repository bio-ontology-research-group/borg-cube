# ADR-0006: Subscription usage boundaries

Status: accepted
Date: 2026-09-02

## Context

Anthropic prohibits using the Claude Max subscription OAuth outside Claude
Code itself; Hermes' Anthropic OAuth path only consumes Max extra-usage
credits. OpenAI's ChatGPT subscription is usable through Codex with ChatGPT
authentication. On this laptop `~/.codex/config.toml` defaults to OpenRouter
(kimi-k3), so a Codex run without an explicit profile silently bills the
OpenRouter key. Terms may change; usage must stay attributable to Robert and
capped.

## Decision

- Claude Max is used only through Claude Code: interactive sessions and
  `claude -p` runs started by `cube run` on ws, where Robert has logged in with
  `claude login`. No Agent SDK with OAuth, no proxying of the OAuth token to
  other tools.
- Hermes never uses Anthropic OAuth. Hermes profiles run on OpenRouter, Codex
  OAuth (ChatGPT) where supported, or local vLLM.
- Codex is used only through `codex exec` with the `cube-chatgpt` profile
  (ChatGPT auth). `cube doctor` fails if the profile is missing; the runner
  always passes `-p cube-chatgpt`.
- A daily cap on plan-tier runs (`budget.plan_runs_per_day`) and on implement
  runs keeps usage bounded; the router queues rather than exceeds.
- API keys with a spending limit are the fallback if terms change; this ADR is
  revisited then.

## Consequences

- Claude Max is reachable only from a machine where Claude Code is logged in
  (ws and the laptop); that is the reason ws is the orchestration host
  (ADR-0008).
- Concierge and advisor bots cannot use Claude models; they use Codex,
  OpenRouter or local models (ADR-0005).
- Usage is Robert-attributable: every run records the runner, profile, model
  and session id in `runs/<date>/<run-id>/meta.json` and `state/audit.jsonl`.

## Alternatives considered

- Anthropic API keys for everything: allowed, but metered per token and much
  more expensive than the subscription for our volume.
- Hermes with Anthropic OAuth: forbidden by terms outside Claude Code.
- Sharing `~/.codex/auth.json` widely: works mechanically but multiplies the
  places a credential lives; kept to ws and the laptop only.
