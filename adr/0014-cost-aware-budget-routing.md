# ADR-0014: Cost-aware budget routing

Status: accepted
Date: 2026-09-03

## Context

Run counts and provider availability do not reveal the economic cost of model
work. Subscription runners report no billed charge even when their equivalent
API value is high, while OpenRouter reports an actual charge. A fixed fallback
order can therefore keep selecting an expensive model after a cheaper usable
model is available.

## Decision

The budget ledger stores billed `cost_usd` and comparable `equivalent_usd`
separately. Reported runner cost supplies the equivalent value. When no cost is
reported, input and output tokens use the validated price table in `cube.yaml`.
A missing price produces a run warning and a zero, explicitly unestimated
equivalent value.

Tier, daily, weekly, project, and pipeline epic ceilings are binding. An
exhausted tier falls through the privacy-safe tier order. Project and epic
ceilings refuse the run and request Robert's attention. Project and epic labels
on the bead are the sole attribution source.

At a soft cap, the patrol selects the cheapest active entry only when it is not
more expensive than the current entry. If no cheaper entry exists, it installs
a temporary tier downgrade. Plan reviews and design work ignore that downgrade
and stay on plan or queue. Local-only work never leaves local. Controls clear
after reset, after OpenRouter credit recovery, or below a 15 percentage point
hysteresis margin.

## Consequences

Subscription use remains billed at zero while still participating in economic
limits and forecasts. Pipeline spend is visible without changing pipeline
code. Routing can recover automatically after short cost spikes without
oscillating at the soft cap.

Estimates are only as current as the configured price table. Missing prices do
not block work by themselves, but their warning makes the blind spot visible.

## Alternatives considered

- Count only billed dollars. This makes subscription tiers appear free and
  cannot compare them with metered providers.
- Queue immediately at a tier cap. This leaves cheaper, privacy-safe capacity
  unused.
- Always choose the next configured model. Ordering is not a stable statement
  of price and can select a more expensive model.
