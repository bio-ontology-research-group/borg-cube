# ADR-0023: The cube runs itself; Robert decides security and privacy

Status: accepted
Date: 2026-09-07
Extends: ADR-0019 (Robert sees decisions, not a queue), ADR-0021 and ADR-0022
(the group's own endpoint first), brain/doctrine.md 2 and 7a

## Context

Measured on ws on 2026-09-07 at 13:40 local: 116 open beads, 39 in progress,
75 ready. A dry worker tick dispatched 2 and skipped 81 with "no free plan
slot": `slots.plan` was 1 and the worker ticked every 30 minutes, so at most
two plan runs an hour served every design, review and escalation bead. Of the
26 runs that day, 20 were reviews of escalations, escalations about
escalations, or reviews of those. Fourteen ready beads carried
`needs:robert`; three were about one disk on ws and three about one disk on
unimatrix01. Every hourly agent stayed idle unless a bead named it, and the
coordinator's management review ran once a day. Robert: the cube does
nothing, it feels deadlocked; it must be busy on the group's own endpoint,
which is free; fewer escalations, only security-critical or privacy-critical
matters are his; the coordinator must distribute the work and make sure it is
done; FLOPO is one project among many and reaches the cube through the normal
channels.

## Decision

1. Throughput. `slots.plan` is 6 (`local` 2); the worker unit ticks every 5
   minutes. The agent-workday patrol plays the due agents side by side, as
   many at once as the plan tier has slots; each agent still takes its own
   workday lock. The local endpoint is priced at zero, so the dollar ceilings
   do not bind.
2. What Robert decides (doctrine 7a). Security-critical: a change to a
   running system, spend above the budget, contact with a person.
   Privacy-critical: a person's data, secrets, `local-only` material leaving
   the local tier. An escalation reaches `needs:robert` only when it is of
   kind `people` or `integrity` or sets the new `critical: security|privacy`
   field. Every other `decision`, `permission` or `conflict` is labelled
   `agent:coordinator` and the coordinator settles it. Three triage rules
   move the existing ones the same way. The group-leader's closes no longer
   route to Robert (`closes_need_robert` is always false).
3. One bead per subject. An escalation's xid is `esc:<role>:<title key>`;
   when an open bead with that prefix exists the run comments on it and files
   nothing.
4. Findings close on result. A bead of kind finding, incident, request,
   question, note, conflict, proposal, approval, reading-list or meeting-note
   is done when its answer is on the ledger; no review bead is created for
   it. The review gate stays for designs and implementations (doctrine 2).
5. The coordinator distributes and chases. Its management review runs every
   `coordination.review_every_hours` (4) and sees, per agent, every assigned
   bead with its last run and whether it is stale (`coordination.stale_hours`,
   24); per project, days since a bead named it moved and whether it is quiet
   (`coordination.project_gap_days`, 14); and the review queue. The prompt
   says: distribute to quiet projects (literature scan, plan refinement,
   bounded improvement, one batch bead at a time for a table or corpus),
   chase stale work, fill idle agents and people, settle routed escalations.
   Pipeline recruitment of agents and roles is the coordinator's
   (`pipeline.autonomy.recruit: coordinator`).
6. The sysadmin prepares, Robert approves. The daily review reads the logs,
   pending upgrades, failed units, containers and backups on every reachable
   host, and bundles every change for one host into one `kind:approval` bead
   per host and day with the commands, evidence, gain, rollback and kill
   criterion. `cube create --kind approval|proposal` labels the bead
   `needs:robert` and gives it no stage; `cube decisions` shows a
   `kind:approval` bead as a proposal (accept keeps it open as approved,
   reject closes). The role's allowlist gains read-only log, upgrade and
   container commands.
7. FLOPO. A project entry names the checkout on ws so implement runs get a
   worktree; the work itself is a goal bead for the coordinator, filed the
   way any goal is. No FLOPO-specific code.

## Consequences

- Up to six plan runs at once on the endpoint; a review or design waits
  minutes, not hours. The endpoint's prefix cache holds one prompt per agent.
- Robert's decision list shrinks to approvals with commands ready, people
  and integrity matters, and questions; disk percentages, PATH gaps and
  "is this diagnosis right" never reach it.
- The coordinator's own escalations to itself are possible; the dedup and
  the prompt ("decide what you can yourself") bound them.
- Executing an approved change is still Robert's hand; a delivery path for
  approved sysadmin bundles is a follow-up.
- Existing state: `management.json` written before this ADR holds a bare
  date and reads as that day's midnight, so the first review after deploy is
  due at once.
