# Dependency-ready runtime scheduler

Date: 2026-09-09
Status: accepted

## Context

After the clean slate, goal intake was running but general workers remained
stopped. Intake decomposed goals without a consumer for their ready child tasks.
The local endpoint supports only two sessions and is substantially faster with
one. An LLM should not have to run continuously just to allocate a free slot.

## Decision

The coordinator owns task owners, dependencies, priorities and optional ordering
and time-allocation labels. A deterministic ws dispatcher consumes this ledger.
One synchronous scheduled research turn runs at a time under an exclusive lock;
the existing shared inference semaphore also covers intake and manual workers.
The second physical slot is available to those routes, not a second routine turn.

Priority then explicit order precede review preference and least-recently-run
agent/task rotation. This is fairness within an equal priority/order class, not
guaranteed service for low-priority work. The coordinator must revise priorities
if urgent work continuously dominates. Dependency and approval checks always win.

Dispatch uses the configured local Hermes model explicitly and the central turn
limit. Per-task walltime may only shorten the central timeout. Failures back off
exponentially up to an hour. Successful tasks remaining ready cool down 15 minutes.
The normal engine handles claims, leases, privacy, execution and review gates.
Restricted sysadmin, liaison and gateway roles retain their dedicated routes.

## Operations and rollback

See `doc/runtime-scheduler.md`. Disable only `cube-scheduler.timer` to stop future
automatic allocations; an already running turn may finish. No reset is required.
