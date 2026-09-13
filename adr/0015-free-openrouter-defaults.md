# ADR-0015: Free OpenRouter defaults

Status: accepted
Date: 2026-09-03
Supersedes: the model ordering and cost-selection parts of ADR-0005 and ADR-0014

## Context

OpenRouter provides tool-capable free variants that are suitable for routine
bulk work and useful as implementation fallbacks. Their endpoint capacity is
less reliable than paid service, so ordinary runner-wide exhaustion would
either suppress usable models or retry too aggressively.

## Decision

Bulk tiers list explicitly priced free OpenRouter models before paid entries.
The implement tier keeps Codex first, then tries the strongest free entries
before paid fallbacks. The plan tier remains subscription-backed. Review and
design work continues to reject weaker-tier downgrades.

Every free model has an exact price entry with zero input and output rates and
`free: true`. Budget swaps rank this flag ahead of unmarked zero-cost entries
and never move from a free model to a paid model. Robert can add or remove a
free-first tier preference with `cube tier free-first`.

A capacity or rate-limit failure backs off only the affected free model for ten
minutes. Routing then tries the next entry. Selecting a paid entry after all
free entries are backing off emits a warning attention event.

The applied budget patrol refreshes `state/cache/openrouter-models.json` at
most once per UTC day. It records failed attempts to prevent repeated polling.
Doctor reads that cache without network access and warns when a configured free
id is absent.

## Consequences

Routine bulk work normally has no metered model cost. Codex remains the first
implementation choice, while free capacity absorbs subscription outages before
paid APIs. A temporary free-provider capacity failure affects one model, and a
paid fallback remains visible to Robert.

The checked-in model ids can become stale between daily patrol refreshes.
Doctor reports that drift, but does not rewrite configuration automatically.

## Alternatives considered

- Treat all zero-priced entries as free. This cannot distinguish a configured
  local or subscription estimate from an OpenRouter free endpoint.
- Back off OpenRouter as one runner. One unavailable free endpoint would hide
  every other free and paid OpenRouter model.
- Query OpenRouter from doctor. Health checks would become network-dependent
  and could exceed the daily catalogue request limit.
