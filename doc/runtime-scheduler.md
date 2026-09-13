# Runtime scheduler

On ws, `cube schedule --json` is a read-only preview: selected task, ordered
queue, runtime allocations and waiting reasons. `cube schedule --apply --json`
executes one turn. `cube-scheduler.timer` checks the local ledger 30 seconds
after the previous turn completes. It never polls Mattermost or asks a model
whether work is available.

The coordinator assigns actual expert owners and prerequisite dependencies.
Beads priority (0 highest) and optional `schedule:order:N` determine order.
Within an equal priority/order, review comes first, then least-recently-run
agent and task. This does not guarantee fairness across unequal priorities.
`runtime:minutes:N` shortens the central walltime allocation; zero pauses that
task. Replace old allocation labels rather than accumulating conflicting ones.

Default: one routine local turn, central 45-minute ceiling and six tool turns.
Central overrides remain authoritative. Setting local workday concurrency or
local inference concurrency to zero pauses dispatch, as does `state/KILL`.
The scheduler deliberately remains serial even if the workday limit is two.
Existing inference admission limits protect the endpoint across other callers.
Local-only data stays on the local route. OpenRouter's shared budget is unchanged.

Blocked dependencies, approvals, another host, paused agents, pending review
and dedicated restricted roles are visible as waiting, not silently run. A bead
left `in_progress` by a run that is gone (no live lease, fleet assignee) shows as
`stale claim`; the next executed tick releases it (ADR-0035). A finished turn
that neither closes its task nor hands it to review counts as an incomplete turn;
after four the task waits for the coordinator to revise it. Original Mattermost
intakes remain owned by the intake dispatcher. Undecomposed goal epics go to the
coordinator, but goals with open children do not compete with those children.

Every executed tick runs `bd dolt pull` first and `bd dolt push` last, so
laptop liaison answers arrive and ws requests leave; sync failures are events.
State is in `state/scheduler.json`; the last dispatch preview is in
`state/schedule-plan.json`. Run artifacts and leases use the ordinary engine
locations. Failure cooldown starts at two minutes and caps at one hour.
No per-turn Mattermost progress messages are added.

To stop future allocations: `systemctl --user disable --now cube-scheduler.timer`.
This does not cancel an active turn. Laptop source requests still need their
separate push-only liaison route. The scheduler does not restart old patrols.

## Deployment verification, 2026-09-09

Enabled on ws. The preview found nine ready tasks and five waiting tasks.
The first FLOPO bootstrap attempt exposed a project-profile harness override:
it selected Codex instead of the scheduler's local Hermes runner, then failed
for a missing environment variable. Scheduled execution now explicitly opts
out of the project harness selection while preserving checkout settings and
privacy checks. Ordinary project execution retains its existing behavior.
Regression tests cover both routing choices.

The dispatcher then started `cube-ihu` as coordinator using `hermes@local`,
`qwen3.8-27b`, with a 2700-second allocation, run `r-20260909-1119-42`.
This verifies live dispatch, not completion of the research goal.
Focused and project-profile tests: 75 passed, one unrelated existing assertion
expects a removed $20 project cap; the central shared budget remains authoritative.
