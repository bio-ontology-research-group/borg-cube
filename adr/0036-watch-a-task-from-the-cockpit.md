# ADR-0036: Watch a task from the cockpit

Status: accepted
Date: 2026-09-13
Source: Robert, 2026-09-13, planning the BH26 demo: "I need to be able to run
this from the cockpit, and watch how the task is being solved through the
cockpit."

## Context

A run on the Claude harness prints its result once at the end
(`--output-format json`); an attached tmux session shows nothing while the
model works. The event log knew a run's start and finish, and the Claude hook
file in `emacs/` was never installed for headless runs (only the restricted
roles got a PreToolUse guard). Creating a bead, showing its prompt, starting
the run, following it and reading the result needed five terminals.

## Decision

1. Every Claude run installs PreToolUse, PostToolUse and Stop hooks that call
   the checkout's own `cube notify --hook`. The hook payload becomes a `tool`
   event with a one-line title (`Read README.md`, `Bash python3 audit_collect.py`),
   `data.tool` and `data.phase`. The restricted roles keep their fail-closed
   guard in front of the notifier. `tool` is informational: no session state
   change, no desktop notification.
2. `cube tail` filters by `--bead` and `--run`; `cube create` accepts
   repeatable `--label key:value` (for `repo:owner/name`).
3. The cockpit gets `cube-watch` (`f`): one buffer per bead with the task, its
   newest run, the live trail and the result, refreshed from the same event
   tail the rolodex uses. `cube-watch-new` (`F`) creates the bead through the
   dry-run and apply pair and opens the buffer. Prompt preview, start, resume,
   attach, run directory, artifact, review preview and approvals are keys in
   that buffer.

## Consequences

The auditor demo runs entirely from the cockpit: create, preview, start,
watch every file the auditor reads and every command it runs, open the audit
report, preview the review gate, show the empty approval queue. Hermes runs
show start, checkpoint and finish only until Hermes gets an equivalent hook.
The event log grows by one line per tool call; the 24 hour mute window does
not apply to `tool`.
