# Why the fleet was idle, 2026-09-11

Source: Robert, 2026-09-11 (this session): the cube does nothing, does not
pursue its goals, the literature agent does not sweep, twins do not act, nobody
reproduces baselines. Work bead cube-in1. Decisions in ADR-0035.

## Evidence

- ws `systemctl --user list-timers`: every `cube-patrol-*.timer` inactive since
  2026-09-09 (the clean slate stopped them "pending fresh goals"; nobody
  restarted them). Only `cube-scheduler.timer` and `cube-goal-coordinator.timer`
  ran. Both reported `idle` every tick. Literature watch (06:30 patrol plus the
  hourly literature workday), the twin workdays, the decisions digest and the
  research exploration steps all live behind those stopped timers.
- ws `state/schedule-plan.json`: every open bead waiting. `cube-r1n.3` and
  `cube-r1n.6` were `in_progress` with no lease since 2026-09-09 12:52; their
  runs (`r-20260909-1236-2f`, `r-20260909-1244-7d`) returned `close: false`
  with checkpoint comments. `bd ready` hides claimed beads; the scheduler read
  that as "not ready". Everything behind them (`cube-r1n.4` literature briefs,
  `cube-r1n.5` dispatch) waited.
- ws `bd list --all`: P1 goal epics `cube-ihu` (reproduce one method paper per
  research agent), `cube-7hb`, `cube-dze`, `cube-up7` closed by one
  group-leader turn each. Their `result.json` files say `close: false` and list
  "create the child beads" as the next action; none has a child bead. The
  engine's implicit "result filed" close did it.
- `cube-r1n.1` (laptop liaison push) and `cube-r1n.2` (bootstrap fleet repo)
  closed as "result filed, no review for this kind" because the children
  inherited `kind:request` from the intake. `gh repo view
  borg-cube-fleet/twin-sota-overviews` on ws: repository does not exist. No
  drop named `cube-r1n.1` under `/mnt/data1/cube-drop`. `cube-r1n.1` also
  carried `agent:coordinator` instead of `agent:liaison` and `host:laptop`, so
  ws ran it itself. Escalation `cube-de8` (needs:robert) recorded the
  repository finding; the decisions patrol that would have announced it to
  Robert was stopped.
- `cube-dwv.1` (FLOPO source push) is `host:laptop`. The laptop worker timer
  was stopped on 2026-09-09 and the laptop ledger (`bd list --all` on lc-dell:
  6 issues) had never received the ws ledger (24 issues): nothing on ws pushed
  to the Dolt remote after the reset because only `cube worker` synchronised
  and the scheduler replaced it on ws.
- laptop bead `cube-0rp`: the coordinator's general workday failed with
  `[Errno 7] Argument list too long: 'hermes'` (prompt in argv).
- `cube doctor` on both hosts: `agents:topics` failed for
  `physiomap-curator=physiomap-causal-map`, a slug the research KG does not have.

## Changes

Code (laptop checkout, mirrored to ws): `cube/engine/results.py` completion
gates, `cube/engine/run.py` claim release, `cube/scheduler.py` stale-claim
release, review wait, ledger sync and turn counting, `cube/ledger_sync.py`
(moved from the worker), `cube/runners/hermes.py` `--query-file`,
`agents/physiomap-curator.yaml` topic. Tests in `tests/test_engine.py`,
`tests/test_scheduler.py`, `tests/test_runners.py`.

Ledger repair on ws, with the evidence above quoted on each bead: reopen
`cube-ihu`, `cube-7hb`, `cube-dze`, `cube-up7`, `cube-r1n.1` (labels
`agent:liaison`, `host:laptop`, drop `agent:coordinator`) and `cube-r1n.2`;
release the claims on `cube-r1n.3` and `cube-r1n.6`; close `cube-de8` as
answered by the reopen.

Services: start the stopped patrol timers on ws and `cube-worker-laptop.timer`
on the laptop.

## Not changed

No Slurm job, vLLM server or gateway was touched. The archive of the old
ledger stays untouched. The mechanical publication gate (a bead that promises a
fleet commit cannot close without a checkpoint record) is still open work.

## Second round, 2026-09-12

The first fixes ran on ws from the evening of 2026-09-11 (about 47 scheduler
turns). Evidence from `runs/2026-09-11` and `state/schedule-plan.json` the next
morning:

- `cube-r1n.6` and `cube-dze.2.1`: the senior wrote the brief in turn one and
  then spent three turns confirming the brief was ready, because nothing ran a
  programmer on the bead. `cube-r1n.6` published the spec itself in turn four
  and still returned `close: false`.
- `cube-ihu`: four coordinator turns each verified "no children" and stopped
  at the tool-call limit; the drafts in `runs/cube-ihu/` were never turned into
  beads.
- `cube-7hb.2`: four honest literature turns, each a small increment; the
  limit of four turns stopped it with the work unfinished.
- Laptop: the liaison worker dispatched `cube-dwv.1` and `cube-r1n.1` every
  five minutes and every run was refused before start: "privacy local-only
  allows only runner 'local', not 'codex'" (the FLOPO project profile). The
  refusal went to `/dev/null`; only `state/audit.jsonl` showed the dispatches.
- Laptop and ws: `cube agent workday liaison --bead cube-dwv.1 --dry-run` was
  idle with no steps. `waiting_on_review` read the parent-child dependency
  record as an open blocker. The same filter feeds every standing agent's
  workday, so twins and experts never picked up child beads either.
- ws: the coordinator's general workday failed with `Argument list too long:
  'claude'`; the management prompt exceeds one argv string.

Changes: ADR-0035 items 8 to 12; `cube/patrols/agent_workday.py`,
`cube/agents/coordinator.py`, `cube/engine/run.py`, `cube/engine/results.py`,
`cube/scheduler.py`, `cube/runners/claude_code.py`, `cube/runners/base.py`.
Operator action on ws: the incomplete-turn counters of `cube-r1n.6`,
`cube-ihu`, `cube-7hb.2` and `cube-dze.2.1` were reset so the corrected flow
gets fresh turns.

## Afternoon, 2026-09-12

- ws ledger push failed: the laptop had pushed while ws diverged, and `bd` has no
  conflict tools. The dolt CLI (2.3.3) is now installed under `~/.local` on ws
  (Robert's explicit request). Merge commit `cl02atel` kept the remote side for the
  two conflicted rows (`cube-8js`, `cube-r1n.1`); ws pull and push work again.
  Backup of the pre-merge ws ledger: `/mnt/data1/borg-cube-reset-archives/ledger-ws-20260912`.
- Laptop `bd dolt pull` hangs indefinitely on a futex after that merge (no network
  activity, embedded Dolt). Every laptop-created bead exists on ws, so the
  laptop ledger holds nothing unique. Replacement script:
  scratchpad `laptop-ledger-replace.sh` (needs Robert; the session's permission
  classifier refused it). The laptop worker timer stays stopped until then.
- The liaison ran twice on `claude@local` and timed out at the role's 900 s;
  the central local walltime floor now applies to every local harness, not only
  Hermes (`cube/engine/run.py`, `run_timeout_seconds`).
- The literature workday wrote its digest to a file in the run directory
  instead of returning it inline, so no briefing was produced; the workday now
  reads a saved digest file under the checkout.
