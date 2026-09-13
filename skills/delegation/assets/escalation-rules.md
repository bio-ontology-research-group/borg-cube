# Escalation rules for delegated work

A worker (agent or person) stops and hands back with a written note when any
of these holds. The note names the rule, the evidence, and what the worker
would have done next. Escalation is a normal outcome, not a failure.

## Stop immediately

1. The task requires an outbound action: a message, email, post, GitHub comment, issue, PR, form submission, signature, deletion, service restart or `scancel`. Prepare the content, open a `kind:outbound` or `needs:robert` bead, stop.
2. The material is privacy `local-only` (check-in transcript, assessment, contract, visa, health, grades) and the worker is not on the local tier. Do not read further.
3. Two sources disagree about a fact the task depends on (a date, a state, a person's role). Open a `kind:conflict` bead with both sources; never pick one silently.
4. The acceptance criterion cannot be checked as written (missing data, wrong path, tool unavailable). Report which criterion and why; do not substitute your own.
5. The work would touch files, repositories or beads owned by another bead.

## Stop and report at the next checkpoint

6. The effort budget in the brief is used up and at least one criterion is still open.
7. A test, lint or build that passed before the change now fails and the cause is outside the bead's scope.
8. A finding has people consequences (a student's progress, a staff member's conduct, authorship). It goes to Robert only, as `needs:robert`, never into a shared channel or a group briefing.
9. A high-severity security finding (committed secret, credential in history, data loss path). Report the file and line to Robert; do not rotate, delete or notify anyone.
10. The plan pattern turned out wrong (the subtasks were not independent, or the task needed judgement the brief did not allow). Report what was learned so the lead can re-plan.

## How to escalate

- Update the bead with a comment: rule number, evidence (path and locator, command output), proposed next step.
- Set the bead to blocked or hand it back to the lead; do not close it.
- Leave the working tree in a state that the next worker can pick up: committed nothing, changes listed, temporary files under `runs/<id>/`.

## Never

- Never widen the scope to get past a blocker.
- Never ask a person other than Robert for the missing information; that is contact, and contact needs a grant in `contacts.yaml`.
- Never mark a criterion as met because it is "probably fine".
