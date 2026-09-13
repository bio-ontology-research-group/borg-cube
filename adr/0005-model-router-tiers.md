# ADR-0005: Model router with four tiers and strict fallback order

Status: accepted
Date: 2026-09-02

## Context

We have four token sources with different strengths, costs and terms: Claude
Max (Fable, Opus, Sonnet via `claude -p`), ChatGPT via Codex (`codex exec`
with the `cube-chatgpt` profile), an OpenRouter key (cheap price-routed
models; `hermes-ws` runs `z-ai/glm-5.3-flash` there today), and local vLLM
on unimatrix node005 (ADR-0011). Planning and review must never be done by a
weaker model than the work they judge; bulk summarisation should be cheap;
`privacy:local-only` material must never leave KAUST.

## Decision

Tiers, each an ordered fallback list (`cube.yaml` `tiers:`):

- `plan`: Fable, then Opus, then refuse. Never downgrade planning or review.
- `implement`: Codex with the ChatGPT profile, then Claude Sonnet, then an
  OpenRouter coder model.
- `bulk`: OpenRouter cheap (price routing), then local.
- `local`: vLLM on node005 only; if it does not answer `/v1/models`, the run
  is queued, never sent to a cloud model. Mandatory for `privacy:local-only`.

Rules:

- Every bead carries a `tier:` label chosen by the role or by `cube sync`;
  the router picks the first available runner in that tier's list.
- `state/budget.json` tracks per-tier usage windows from `--output-format
  json` / `--json` usage fields; `cube.yaml` `budget:` caps plan and implement
  runs per day; exhaustion means queue, not downgrade.
- Slots limit concurrency: `{plan: 1, implement: 3, bulk: 4, local: 1}`.
- Failures back off exponentially; expired leases are requeued by the Marshal.
- Review of a bead always runs at a tier at least as strong as the tier that
  produced the work (`plan` reviews `implement`; `plan` reviews `plan`).

## Consequences

- A Codex outage degrades implementation to Sonnet, not to silence.
- A Claude Max cap pauses planning and review for the day; the backlog waits.
- A vLLM outage pauses local-only work; nothing leaks.
- The router is testable as a pure function over (tier, availability, budget,
  privacy).

## Alternatives considered

- One model for everything: simplest, but wastes the plan budget on bulk work
  and violates privacy on local-only work.
- Dynamic model selection by the agent itself: opaque and unauditable.
- Cost-only routing (OpenRouter auto): fine for bulk, unacceptable for review.
