# ADR-0032: Local workday admission and an approved clean slate

Status: accepted
Date: 2026-09-09
Source: Robert's Codex requests for bottleneck-aware scheduling, a full runtime
reset, no local API budget, and USD 10/day shared OpenRouter spending.

## Decision

Use durable round-robin admission before standing-agent model dispatch. Default to
one routine local workday per wave; preserve the two-session physical semaphore
across all local harnesses. The timer checks every five minutes and respects agent
due times. Record offers, including idle/failing offers, so alphabetical order and
repeated failures cannot monopolize subsequent waves. Deferred work creates no
model call. Centrally adjustable wave size is 0, 1 or 2.

Robert's measured rates are 33 tokens/s alone versus 15 tokens/s for each of two
sessions. One session improves both aggregate generation and individual latency.
Fixed office-hour windows unnecessarily idle an always-available research service.
Bounded checkpoints and fair admission address contention; merely extending all
timeouts does not. Coordination and manual/pipeline calls can use the second
physical slot, so this is not a globally preemptive or token-fair scheduler.

Local inference is not gated by paid-provider budgets. Production disables daily
research-run count ceilings and per-tier/project monetary ceilings, retaining one
shared USD 10/day paid allowance. Concurrency, deadlines, disk and Slurm safeguards
are separate. Retain incurred spend for the current day across a reset so resets
cannot grant additional paid allowances.

The explicitly approved reset replaces, rather than merges, runtime state and the
shared Dolt ledger. Stop writers first and archive exact targets with verified
checksums outside active runtime. Do not erase credentials, original research,
mail or notes. No old inbox/task/memory imports. Restore communication/UI services
after one synthetic routed test; leave autonomous source scans paused for fresh
goals. This reset authority is specific to this request, not a standing permission
for agents to erase their own history.

Execution evidence, recovery locations, test results and limitations are recorded
in [the reset report](../doc/clean-slate-20260909.md).
