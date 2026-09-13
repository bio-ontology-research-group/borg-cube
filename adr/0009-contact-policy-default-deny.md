# ADR-0009: Contact policy is default-deny with per-person, per-channel grants

Status: accepted
Date: 2026-09-02

## Context

Robert's revised decision (2026-09-02): by default borg-cube never contacts
students or anyone else; everything goes to Robert. Automated messages to
students carry real risk: a wrong or badly timed message damages trust, and a
system that assesses people must not speak to them without a human in the
loop. At the same time a Phase 4 pilot wants volunteers to talk to an advisor
bot, and infrastructure alerts already reach the infrastructure postdoc through
`hermes-ws`.

## Decision

- Default: no outbound contact to anyone but Robert. Every message, email,
  DM, GitHub comment, PR or post that would reach another person is a
  `kind:outbound` bead in the approval queue. Robert sends it himself or
  approves it.
- Grants live in `contacts.yaml`, source-controlled, empty by default. A grant
  is per person, per channel (`mattermost_dm`, `email`, `github`, ...) and per
  action class (`weekly-checkin`, `milestone-reminder`, `infra-alerts`, ...)
  with date, granted-by, scope, optional expiry and an evidence permalink.
- `cube contact check <person> <channel> <action-class>` is the single gate
  used by every runner and by the Hermes allowlist generator. No grant means
  the action is queued for Robert, never sent.
- Granting and revoking are Robert-only actions (`cube contact grant`,
  `cube contact revoke`), logged to `state/audit.jsonl`. Revocation is
  immediate: the advisor allowlist is regenerated and the gateway restarted.
- Students' read access to their own dossier is a separate grant
  (`dossier_read`).
- `autonomous_actions` in every `roles/*.yaml` must be free of outbound
  actions; `cube doctor` fails otherwise. This stays true through Phase 4;
  whether any action class becomes autonomous for granted students is decided
  at the pilot review.

## Consequences

- Phases 1 to 3 need no grants at all; the system is Robert-facing.
- The advisor bot literally cannot answer anyone not in `contacts.yaml`.
- Robert is the bottleneck for outbound volume, by design; the approval queue
  in the cockpit and the Concierge make approving cheap.
- Auditing "who did the system ever talk to" is a grep of `contacts.yaml`
  history and the audit log.

## Alternatives considered

- Opt-out (contact everyone unless they object): rejected by Robert; the
  power asymmetry between supervisor and student makes opt-out meaningless.
- Role-level allowlists (the advisor may DM any student): too coarse; grants
  are about a person's consent, not a role's capability.
- Rate limits instead of gates: limits volume, not harm.
