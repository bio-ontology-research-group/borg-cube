# ADR-0019: Robert sees decisions, not a queue

Status: accepted
Date: 2026-09-07
Extends: ADR-0009 (contact policy default deny), decisions policy in cube.yaml

## Context

On 2026-09-07 the ready list on ws held 139 beads. Robert: "140 beads needing
my attention is not appropriate". Sorted by origin: 32 escalations (16 with
`needs:robert`, mostly disk percentages, sandbox permissions and tool
allowlists), 21 review beads for other agents, 20 hermes-infra "WARN: <DMZ VM>:
failed units" findings, 16 "Robert answered" request beads nobody played, 15
deadline findings overdue by 26 to 60 days, 4 copies of the coordinator's daily
goal-review proposal already accepted by policy, and 22 real tasks. Two or three
were decisions.

## Decision

1. A new triage patrol runs every fifteen minutes over the open beads and
   applies `triage.rules` from `cube.yaml` in order, first match wins:
   `route` (becomes an agent's work, loses `needs:robert`, duplicates by asker
   and subject close), `close` (information), `deliver` (a "Robert answered"
   bead goes to the inbox of the agent that plays the role and closes),
   `defer` (keeps the bead, drops `needs:robert`). Built in: an accepted
   advisory proposal closes; only the newest daily coordinator review stays.
2. What stays Robert's: questions, conflicts, approvals, external or critical
   incidents, deadlines inside two weeks, milestones inside thirty days, and an
   escalation no rule names. The `never_automatic` guards of the decisions
   policy are untouched.
3. Source patrols stop producing the noise: deadlines overdue for more than
   fourteen days fold into one weekly digest bead (prune or reschedule in
   deadlines.md); a hermes-infra WARN transition that needs no human is
   recorded and closed, never an open bead; an escalation bead carries the
   agent behind the run so Robert's answer reaches that agent's inbox instead
   of a role bead.
4. The attention list ignores proposals already carrying `approved:robert`.

## Consequences

- Escalations about infrastructure become the sysadmin's beads; about the
  harness, the research software lead's. Both file approval beads for
  changes; Robert sees the approval, not the finding.
- The triage patrol comments every action on the bead
  (`[triage] <action> (<rule>): <note>`), so a routed or closed bead explains
  itself.
- Adding a rule is a `cube.yaml` edit with a dated comment; the patrol never
  answers a question or a conflict.
