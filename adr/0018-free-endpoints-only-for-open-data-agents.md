# ADR-0018: Free OpenRouter endpoints only for open-data agents

Status: accepted
Date: 2026-09-07
Extends: ADR-0016 (agentic harnesses on OpenRouter)

## Context

OpenRouter's free endpoints (`:free` model ids) are served by providers that
may log, publish or train on prompts; the account has to opt in to them, and
Robert did on 2026-09-07 to cut the compute bill. Before this decision the
router treated a free entry like any other: the bulk tier listed free models
first, and every tier falls through to bulk when its own entries are
exhausted, so a coordinator run carrying a student dossier, a manuscript or an
infrastructure detail could land on a free endpoint. The bead's privacy class
is not enough of a guard: the prompt carries the agent's charter, memory and
inbox whatever the bead says.

## Decision

OpenRouter's public API exposes no data-policy field (checked 2026-09-07:
`/api/v1/models`, `/models/{id}/endpoints` and `/providers` carry pricing,
uptime and privacy-policy URLs, nothing about training). So the cube does not
try to tell safe free endpoints from unsafe ones. It lets OpenRouter enforce
the policy per request and decides only which runs are allowed to opt in.

1. Every chat request to OpenRouter carries `provider.data_collection`:
   `deny` for a private run, which makes OpenRouter drop every endpoint that
   logs or trains on prompts whatever the account settings allow; `allow` only
   for an open-data run. A run is open-data when its agent or role is named in
   `privacy.open_endpoints_for` (`execute(..., agent=...)` from the workday
   patrol, or the bead's `agent:` label). The flag travels on the
   `RunContext` as `open_data`.
2. The free pool. The budget patrol already fetches the OpenRouter catalogue
   once a day; it now stores the `:free` models with their context length and
   whether they support tools and structured output
   (`state/cache/openrouter-models.json`, key `free`). For an open-data run the
   router puts the six best of them (structured output first, then tools, then
   context) in front of the bulk tier. A private run never sees the pool, and
   the router also skips any entry priced free for it. No free model is
   hand-listed in `cube.yaml` any more; a `:free` id is priced free by rule.
   A pool model that fails backs off on its own target for ten minutes; one
   refused for data policy is disabled for a day. A pool older than three
   days is ignored.
3. `privacy.open_endpoints_for` is `[literature]`: the literature watch agent
   reads public preprints and writes summaries. Nothing else qualifies:
   experts and the coordinator see student and project detail, the editor
   sees unpublished manuscripts, the teaching lead sees course material and
   students, the sysadmin sees infrastructure, the liaison sees the dossiers.
   Adding a name is Robert's decision, in `cube.yaml`, with a dated comment.
4. Claude Code and Codex talking to OpenRouter cannot add the request field;
   for them the account-level privacy setting applies, so the account toggle
   for providers that train on inputs must stay off and only the free-endpoint
   toggles on. They never receive a free model from the router.
5. `cube doctor` reports the allowlist (`privacy:open-endpoints`), the pool's
   size and age (`openrouter:free-pool`), and warns on a hand-listed free entry.

## Consequences

- Runs of every agent but literature never use a free entry, and their chat
  requests exclude training providers even if the account allows them. When
  the paid entries of their tier are exhausted they queue instead of leaking.
- The bulk tier is `z-ai/glm-5.3-flash` for everyone but literature, which
  tries the pool first. The budget patrol's free-first preference only helps
  literature.
- A rate limit through OpenRouter is a ten-minute per-target backoff, not a
  five-hour harness exhaustion (that is for the Claude and ChatGPT
  subscriptions). Found the same day: a finished sysadmin run whose report
  said "24G free" and "429 ms" was read as a 429 and parked the harness.
- Local-only work is unchanged: it runs on node005 or waits (ADR-0003).
