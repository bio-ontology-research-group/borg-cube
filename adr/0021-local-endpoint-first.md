# ADR-0021: The group's own endpoint first, OpenRouter Flash as the fallback

Status: accepted
Date: 2026-09-07
Extends: ADR-0016 (agentic harnesses on OpenRouter), ADR-0018 (free endpoints)

## Context

Robert, 2026-09-07, in the group channel: the Claude subscriptions do not
scale, and a Qwen3.8-27B (FP8) now serves at the group's own vLLM endpoint
with the OpenAI API behind per-person keys. Probed from ws the same day: it
answers `/v1/chat/completions` with tool calls, `/v1/messages` (the Anthropic
API) and `/v1/responses`, 131k context. Robert's instruction: "switch the
models in the cube all to run on this local endpoint, and only fall back to
OpenRouter GLM 5.3 Flash when it fails", with his own key from
`~/.config/borg-llm/api-key`, never the test key posted in the channel.

## Decision

1. `local` is a runner provider like `openrouter`: `claude@local` is Claude
   Code with `ANTHROPIC_BASE_URL` at the endpoint's Anthropic side,
   `codex@local` is Codex with the `cube-local` profile
   (`deploy/codex-local-profile.toml`, provider `local`, `wire_api`
   responses), and `local` stays the tool-free chat runner. All three read
   `VLLM_BASE_URL` and `VLLM_API_KEY` from `.env`; the key file is copied, not
   printed, and the channel's test key is never used.
2. Every tier starts with the local entries (harness first where tools are
   needed, then the chat runner). OpenRouter GLM 5.3 Flash follows as the only
   fallback; the Claude subscription, the ChatGPT profile, the cheaper
   OpenRouter chat models and the hand-listed free models are gone from the
   tiers. The free pool (ADR-0018) sits behind the local entry for open-data
   runs.
3. Fallback is the router's existing behaviour: a failed local run backs its
   target off (one minute, doubling) and the next dispatch takes the next
   entry; an unreachable endpoint (no URL in `.env`) makes the local entries
   unavailable. Nothing falls back on a successful run.
4. Prices: `local`, `claude@local` and `codex@local` cost 0; the budget ledger
   bills nothing for them, so the daily ceilings bind only on the fallback.
5. `cube doctor` checks the `cube-local` profile when a `codex@local` entry
   exists and that the endpoint URL and key are in `.env`
   (`local:endpoint`).

## Consequences

- OpenRouter spend drops to the failure fallback. Watch `cube budget` for a
  day: a steady Flash share means the endpoint is failing, not slow.
- Local-only work still requires runner `local`
  (`privacy.local_only_requires`), which is now the same endpoint; ADR-0003's
  intent holds because the endpoint is the group's own machine inside KAUST.
- hermes-ws keeps its own Hermes config (OpenRouter Flash, data collection
  denied); switching it to the endpoint is a one-line change in
  `~/.hermes/config.yaml` on ws, outside this repository.
- The endpoint is a single node: when it is down every tier runs on Flash
  until it answers again, at Flash prices.
