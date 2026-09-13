# ADR-0035: Completion gates, claim release and ledger sync for the runtime scheduler

Status: accepted
Date: 2026-09-11
Source: Robert, 2026-09-11: "The cube is not doing anything, and also not
pursuing its goals." Work bead cube-in1. Evidence in doc/idle-fleet-20260911.md.

## Context

Two days after the clean slate (ADR-0032) the fleet was idle although two goals
had been decomposed and four more P1 goals had arrived:

- A run that returned a valid result with `close: false` on its own bead left
  the bead claimed (`in_progress`). `bd ready` hides claimed beads and the
  scheduler (ADR-0034) treated "not in bd ready" as blocked, so the bead was
  never dispatched again. Two design tasks sat like that for two days and every
  task behind them waited.
- The engine's implicit "result filed" close applied to goal epics. Four P1
  goals, among them "Reproduce one method paper per research agent within one
  month", were closed after one decomposition turn that created no child beads.
- Children of a Mattermost goal intake inherit the intake's `kind:request`
  label. The no-review shortcut for requests closed two of them ("result filed")
  although the laptop drop and the fleet repository they promised did not exist.
- The ws scheduler never synchronised the Dolt ledger. Only the laptop worker
  did, and it was stopped, so a liaison request filed on ws never reached the
  laptop and the two ledgers diverged.
- Hermes received the whole prompt in `-q` argv. A coordinator workday prompt
  exceeded the kernel's single-argument limit and the run failed before start.

## Decision

1. A goal (`kind:goal` or Beads type epic) is never closed by the implicit
   "result filed" rule. An explicit close is honoured only when the goal has at
   least one child and every child is closed. Otherwise the run's note records
   why the goal stays open.
2. A child of a goal intake (`intake:goal` label and a parent) is not a request
   for the no-review shortcut; it follows its role's close and review rules.
3. An explicit `close: false` on the run's own bead is a checkpoint. The
   implicit close does not override it.
4. A finished run that leaves its bead open and did not hand it to a reviewer
   releases its claim, like an errored or malformed run already did.
5. The scheduler releases stale fleet claims (`in_progress`, assignee
   `cube/...`, no live lease) at the start of every turn, reports them as
   `stale claim` in the preview, and treats `review:pending` and
   `review:revise` as waiting. A finished turn that neither closed nor handed
   off counts as an incomplete turn; four incomplete turns stop automatic
   retries until the coordinator revises the task.
6. Every non-dry scheduler tick pulls the Dolt remote first and pushes last,
   through the same `sync_ledger` the laptop worker uses. Failures are events,
   never silent.
7. The Hermes runner writes the prompt to `<run>/hermes-query.md` (mode 0600)
   and passes `--query-file`. The Claude runner pipes a prompt above 100 kB
   through stdin instead of argv.

## Second round, 2026-09-12

After the first deployment the fleet moved but stalled again within a day.
The evidence (doc/idle-fleet-20260911.md, second section) led to four more
decisions:

8. The workday filter `waiting_on_review` reads Beads' real dependency records
   (`type`, `depends_on_id`, no status). The parent link of every child bead
   had been read as an open blocker, so no twin, expert or the liaison ever
   worked a child bead from its workday. Unknown blocker status is not a block;
   `bd ready` remains the authority.
9. Local-only privacy wins over a project's harness profile when routing. The
   laptop liaison on `project:flopo` had been refused every five minutes
   because the project prefers Codex.
10. A design turn (senior or group leader) on a `stage:design` bead that keeps
    the bead open and returns a brief, spec, design or plan artifact moves the
    bead to `stage:implement` with `role:programmer` (the owning agent is kept
    as `designed-by:`). The next scheduled turn runs the programmer. Before this
    the senior re-verified its own brief turn after turn.
11. A scheduled turn on an undecomposed goal with a goal header uses the
    `cube goal decompose` prompt, and the engine creates the children from the
    returned plan. Generic turns asked a six-tool-call local model to create
    fifteen beads by hand and it never did.
12. When a task reaches the incomplete-turn limit the scheduler labels it
    `schedule:revise`, comments the reason on the bead and leaves one message in
    the coordinator's inbox. The limit is four turns.

## Consequences

Goals stay open until their work is done, so `bd ready` and the scheduler
preview show real progress. Tasks can take several bounded turns. The laptop
liaison sees ws requests within one laptop worker tick after a scheduler tick.
Fabricated completions are still possible inside a child task; the review gate
and the fleet checkpoint record remain the evidence, and a mechanical
publication gate is still follow-up work (doc/fleet-recovery-20260909.md).

13. The central local walltime floor applies to every runner on the group's own
    endpoint, not only Hermes.
14. The literature workday accepts a digest saved as a file under the checkout
    as well as inline content.
15. Ledger conflicts are resolved with the dolt CLI on ws (installed under
    `~/.local` on 2026-09-12); `bd` alone cannot resolve them. The runtime host
    (ws) is the side kept for conflicting cells unless the conflicting edit was
    made on the laptop by Robert or the liaison.
