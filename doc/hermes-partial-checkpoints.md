# Hermes partial checkpoints

2026-09-09: FLOPO runs `r-20260909-1125-a4` and `r-20260909-1141-6b`
returned a complete summary followed by a truncated inline artifact string.
The latter finished in 10m40s, within its 45-minute deadline; the Hermes session
also contained an output-length termination. Increasing walltime does not fix
this output-contract failure.

Worker prompts now request final JSON below 3000 characters and a summary below
600 characters. Larger documents should be saved through existing permitted
file tools and referenced by path. Read-only roles retain their permissions and
can return a short inline checkpoint instead. The absolute Cube executable and
ledger working directory are supplied explicitly because terminal shells can
reset PATH even when the runner inherited the correct path.

On malformed output after a clean process exit, one deterministic recovery pass
can extract a complete leading JSON summary. No model call, guessed closing
syntax, incomplete artifact, bead update, escalation or review verdict is used.
Valid JSON with an invalid schema, timeouts and incomplete summaries still fail.
The original stdout remains in the run directory, unchanged.

Recovered output becomes a non-success `checkpoint` event, not a finished task
or an error event. The engine records an explicitly unverified worker report,
skips action application and releases the task claim. After two consecutive
partial checkpoints the scheduler pauses that task with a visible waiting reason.
An operator must inspect/revise the task and reset its `checkpoints` counter in
`state/scheduler.json` while dispatch is inactive before retrying. This is not
an automatic recovery of lost artifact content or proof of research completion.

Deployment does not restart workers; changes apply to subsequent processes.
