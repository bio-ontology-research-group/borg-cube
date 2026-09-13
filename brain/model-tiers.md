# Model tiers and router policy

The router (`cube/router/policy.py`) is a pure function of (tier,
availability, budget, privacy). Configuration lives in `cube.yaml` under
`tiers:`, `slots:` and `budget:`. This page explains the policy in prose;
ADR-0005 and ADR-0006 record why.

## The four tiers

plan. Design, specification, review, verdicts, anything that judges other
work or a person's progress. Order: Claude Fable, then Claude Opus, then
refuse. Planning and review are never downgraded; when the daily cap
(`budget.plan_runs_per_day`, 20) is reached or both models are unavailable,
the bead waits. One slot.

implement. Code changes in a worktree, scripted transformations, first
drafts of structured documents. Order: Codex with the `cube-chatgpt` profile
(ChatGPT subscription), then Claude Sonnet, then an OpenRouter coder model.
Three slots, 60 runs per day.

bulk. Summaries, extraction, formatting, meeting-note drafts, prioritisation.
Order: OpenRouter cheap (price routing; `z-ai/glm-5.3-flash` today, the same
model `hermes-ws` uses), then local. Four slots.

local. vLLM on unimatrix node005 through the OpenAI-compatible API. Used by
choice for cheap work and by force for every `privacy:local-only` bead. If
`/v1/models` does not answer, the run queues; it never falls through to a
cloud model. One slot.

## How a run is routed

1. The bead's `tier:` label, or the role's `tier`, selects the list.
2. `privacy:local-only` overrides the list to `local` only.
3. The first runner in the list that is available (login present, endpoint
   answering, budget window not exhausted, slot free) is chosen.
4. `--dry-run` prints the chosen command and prompt without running.
5. Usage from `--output-format json` / `--json` is written to
   `state/budget.json`; failures back off exponentially; expired leases are
   requeued by the Marshal.

## Where each runtime may and may not go

- `claude -p` uses Claude Max on ws or the laptop only; it never calls the
  local endpoint and never runs in a bot.
- `codex exec` always carries `-p cube-chatgpt`; without it the default
  profile bills OpenRouter silently.
- Hermes profiles use OpenRouter, Codex OAuth or `providers.local`; never
  Anthropic OAuth.
- Python runners (bulk, local) call OpenRouter or vLLM directly with the key
  or URL from `.env`.

## Review tier rule

The reviewer of a bead runs at a tier at least as strong as the producer:
`implement` work is reviewed at `plan`; `plan` work is reviewed at `plan` by a
different role (senior by group leader, editor by group leader); `bulk`
drafts are reviewed by the role that owns the output (scribe by advisor).
