# Local Hermes timeout correction

## Evidence on 2026-09-08

The local endpoint was producing tool calls, not uniformly returning malformed
responses. At 16:12 UTC six senior/editor workers were starting alongside local
private work. The agent-workday pool used `slots.plan`, but `execute` had no
shared physical endpoint admission gate. Logical tiers share the same GPUs.

In ws run `r-20260908-1612-f3`, the private grant session completed five API calls
and 8,389 output tokens before its 1,200-second process deadline. A postdoc twin's run
`r-20260908-1552-ec` completed seven calls and 12,285 output tokens before timeout.
Successful 12-call sessions took about 7 to 28 minutes on the same day. Increasing
deadlines without controlling concurrency would prolong competing sessions.

The two inspected non-JSON runs `r-20260908-1701-09` and
`r-20260908-1701-aa` ended after Hermes's iteration-limit summary request.
The installed Hermes `agent/chat_completion_helpers.py:handle_max_iterations`
adds a user instruction to summarize. Cube's output contract was also only in
the user query. These were prose final summaries, not evidence that vLLM had
returned a malformed HTTP response. Other failures need their own evidence.

## Correction

- All local runners through Cube `execute`, across roles and logical tiers, share
  nonblocking kernel file locks held for the whole inference session. Default:
  two local sessions. Full capacity queues; it does not trigger cloud fallback.
- `fleet_limits.local_run_timeout_minutes` defaults to 45. This is a minimum
  deadline for local Hermes sessions only; longer role deadlines are retained.
  Bead leases use the same effective deadline plus ten minutes. Cloud and other
  harness deadlines are unchanged. Local sessions now default to six tool-calling
  iterations, followed by Hermes's final summary. `local_max_turns` is centrally
  adjustable from 2 to 12; lower role-specific caps win. Smaller checkpoints leave
  substantial headroom under the 45-minute deadline instead of stretching every run.
- `fleet_limits.local_inference_concurrency` is adjustable through the existing
  Mattermost fleet-limit path. Zero pauses new local inference. Existing sessions
  drain when lowering the limit. Locks are host-local: this governs Cube on ws,
  not unrelated users of vLLM or clients on other hosts.
- Hermes receives an ephemeral system-level JSON contract, including the schema
  and explicit partial/blocked reporting. Its final-summary request cannot change
  that instruction. Invalid output is still rejected, never fabricated as success.
- A queued, unstarted research reservation is retained as cancelled audit data
  but does not spend daily allowances or autonomous intervals. Real failed
  inference attempts remain charged.
- Process timeout handling preserves stderr, including session IDs when Hermes
  emitted them, rather than replacing all diagnostics with a timeout string.
- Each worker starts in a separate process group. A deadline sends TERM, allows
  one second to exit, then KILLs that group, including tool children retaining
  output pipes. Output draining is bounded. Remote Slurm jobs are not cancelled.
- Local timeouts enter the existing per-runner/model exponential backoff, timed
  from completion rather than the old start time. Work queues during cooldown;
  local-only work still cannot fail over to cloud inference.

Approvals remain `single_query_mode: deny`; this change neither approves the
pending tool-permission proposal nor changes private routing. No GPU restart.

## Validation and rollout

Tests use stub runners and synthetic subprocess timeouts. They cover shared
admission across harnesses/threads, queueing before model calls, lease release,
matching local deadlines, unchanged cloud deadlines, cancelled queue accounting
and the system-level output contract. These prove the code paths, not a guaranteed
success rate for a nondeterministic model. Inspect subsequent production outcomes.

The hardening tests additionally spawn real synthetic processes (no models or
external sends), prove that a TERM-ignoring tool child is killed, check that stderr
and nonzero exit output survive, and verify post-timeout slot release and cooldown.
Use `just check` for the complete Python, type/lint, skills and Emacs gates.

These changes reduce preventable timeouts; they do not guarantee a response from
a stalled server. Monitor completed, reviewed artifacts as well as timeouts. If
timeouts persist with two sessions and six iterations, inspect per-call latency
and server load before raising concurrency or extending the deadline again.

Validation on 2026-09-08: `just check` passed 1,279 Python tests, 228 Emacs tests
and 7 cockpit contract tests; Ruff and mypy passed. Skills lint had zero errors
and 54 existing reference-review warnings. The ws workday service was checked:
its six-hour outer deadline and control-group cleanup do not pre-empt the
45-minute worker deadline. Production completion-rate follow-up is `cube-7urq`.

Deploy with backups; already-running Python workers retain old code/deadlines
until they exit. New workdays pick up the correction. Retain old failures for
audit rather than reclassifying them. Restore backed-up files to roll back.
