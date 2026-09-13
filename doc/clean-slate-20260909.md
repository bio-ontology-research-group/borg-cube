# Clean slate and local inference scheduling, 2026-09-09

Authority: Robert's explicit Codex request to reset all fleet runtime, Beads,
goals, tasks, inboxes, memories, approvals, research, budgets, receipts and ws
work folders, then run one routed validation task. He also requested scheduling
for unimatrix01's two-session bottleneck.

## Reset boundary and recovery

All Cube timers, active workers/patrols, the old coordinator tmux session and
the ws Hermes gateway were stopped before moving state. Laptop worker/sync timers
were also stopped. GPU serving, Slurm jobs and unrelated development sessions
were not stopped.

`tools/fleet_reset.py` makes explicit runtime targets inactive by moving them
outside the checkout. Every target has a before/after SHA256 check recorded in
a permission-restricted `manifest.json`. Archives:

- ws: `/mnt/data1/borg-cube-reset-archives/20260909-clean-slate`, 130 targets.
- Laptop: `~/Public/software/borg-cube-reset-archives/20260909-laptop`,
  66 targets.

Targets include `state`, `runs`, `.cube`, `.beads`, per-agent generated state,
and ws fleet Hermes sessions, memories, logs, cron jobs, databases and caches.
Credentials, role definitions, charters, original research repositories, `~/pa`,
`~/org`, mail and pushed source files outside these runtime directories remain.
Archives are recovery-only, never inputs to new agent context. Restoring a target
requires stopping its writers first, checking its manifest checksum, and moving
aside any new active state before restoring it. Do not merge old inboxes or ledgers
into the new fleet.

The previous `refs/dolt/data` at
`015e48ff13db04157d1bfe0cce16adcc285a725e` was saved as
`refs/archive/borg-cube-pre-reset-20260909-dolt` and as a verified complete
`dolt-history.bundle` in the laptop archive. Only that exact remote runtime ref
was deleted using a force-with-lease guard. A new empty ws Dolt ledger was
initialized and published; the laptop adopted its new identity. Both issue lists
and memories were checked empty before creating validation bead `cube-2m9`.
`bd init` automatically created Beads initialization commits on each checkout;
these are not a deployment commit for the source changes.

Existing GitHub repositories, Mattermost server history and system journal history
were not deleted. No original student data was erased. During validation the
gateway and automatic patrols stay stopped to prevent old events or source scans
from reconstructing the discarded backlog.

## Bottleneck policy

Robert measured 33 tokens/s with one session and about 15 tokens/s per session
with two. One routine session therefore has better aggregate generation throughput
(33 versus 30) and roughly half the individual generation latency. The default is
one round-robin standing-agent workday, not a simultaneous workday for every agent.

- Central `local_workday_concurrency: 1`, adjustable to 0, 1 or 2.
- Shared physical session cap remains 2 across local harnesses.
- Every five minutes, the workday dispatcher offers the least-recently-offered
  due agent a bounded turn. It rotates even if the agent is idle or fails.
- Deferred agents are recorded as scheduled, without a model request or paid run.
- Existing per-agent due times still apply. Workdays do not overlap themselves.
- Coordination/sysadmin and explicit nonlocal runners bypass this workday queue;
  local calls still obey the physical cap. Manual and pipeline work can use the
  second slot. This is not a global priority/preemptive scheduler for every caller.
- Local sessions retain a 45-minute safety deadline and at most six tool turns.
  Raising deadlines alone does not solve contention. Prefer small saved checkpoints.

Fixed workday hours would leave an always-available server idle overnight. A rotating
queue fits independent research better, while allowing due-time schedules for tasks
that genuinely depend on office hours. Selection fairness is per workday offer, not
equal token allocation. Reassess using completion latency and published artifacts,
not token consumption as a goal.

## Spending

The entire fleet has one OpenRouter allowance of USD 10/day. Per-tier/project
monetary ceilings and daily research-run count limits are disabled in production.
Local inference has no monetary budget. A paid-cap failure skips paid candidates
but must still allow the local candidate in the same plan tier. Regression tests
cover this case. Physical concurrency, disk reserves, bounded sessions and Slurm
resource safeguards remain independent of API spending.

The reset removes historical administrative usage records, but today's already
incurred OpenRouter charge (USD 0.438966475) must remain as a spend-only carryover,
with zero fabricated runs or tokens. Otherwise a reset would silently grant more
than USD 10 of paid usage in one day.

## Validation scope

The sole fresh task is a synthetic directed-graph transitive-closure artifact.
It exercises a fresh Beads context, local inference, structured artifact output,
independent checks and private fleet publication. It is an integration check, not
a research finding or evidence that all research roles work end to end.

Observed results:

- Producer `r-20260909-0837-2d`: Hermes local Qwen, 68 seconds, one API call,
  14,698 input and 4,079 output tokens, valid JSON and inline code artifact.
- Independent local auditor `r-20260909-0840-94`: 64 seconds, one API call,
  15,199 input and 3,722 output tokens, verdict approve. Neither call timed out;
  neither used OpenRouter.
- The harness executed the five built-in assertions and independently compared
  every one of the 512 directed graphs on three nodes against fixed-point relation
  composition. All passed.
- Private repository created: `borg-cube-fleet/fleet-validation`; commit
  `0f6ed8d6ef5d0a2e836ff16aeb3091f8e7f3e9f5`. Remote artifact bytes verified equal
  to the generated artifact. Author: `Robert Hoehndorf (BORG Cube Fleet: senior)`,
  `leechuck@leechuck.de`. Code, README and review are published; no pending uploads.
- The live handoff exposed a dependency-order bug: approval attempted to close the
  original before its blocking review. The fix closes the review first, without
  bypassing other Beads blockers. The same ordering was corrected for student
  revision and rejection. Four regression cases failed before the patch and pass
  after it. The recorded verdict was reapplied without another model call.
- The only fresh work is `cube-2m9` plus its automatic review `cube-85c`, both closed.
  No old goals, tasks or memories were imported.
- Focused combined gate: 140 tests passed. Ruff and mypy passed for the changed
  scheduling, budget and review modules.

Explorer health on ws returned `{"status":"ok","host":"ws"}` after restart.
The main Hermes gateway was restarted with fresh session state. Its Mattermost
adapter was checked to use new WebSocket events without startup history backfill.
Automatic research/source-scanning timers remain stopped pending fresh goals.
The pre-existing `cube doctor` topic-reference error for `physiomap-curator`
(`physiomap-causal-map`) is not fixed by resetting runtime; do not describe the
entire installation as passing doctor.
