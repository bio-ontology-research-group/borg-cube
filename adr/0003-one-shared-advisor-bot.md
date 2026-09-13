# ADR-0003: One shared advisor bot with per-user sessions, gated by contact grants

Status: accepted
Date: 2026-09-02

## Context

The Advisor role has two audiences. By default it is Robert-facing: it drafts
evidence summaries, milestone status, 1:1 agendas and check-in questions that
Robert uses himself. In a later pilot (Phase 4), volunteers may interact with
an advisor directly on Mattermost. Options for the student-facing side were one
Hermes profile and bot account per student, or one shared profile and one bot
account with per-DM sessions. Hermes already supports per-user sessions
(`group_sessions_per_user: true` is in use on `hermes-ws`) and runs a
Mattermost gateway per profile. Bot accounts on `borg.bio2vec.net` require
sysadmin creation and each holds a token.

## Decision

- The Advisor is Robert-facing by default. Its outputs are beads, briefings and
  drafts for Robert; nothing reaches a student without a grant (ADR-0009).
- The student-facing channel is ONE Hermes profile (`advisor`) and ONE bot
  account (`@borg-advisor`). Hermes gives each DM its own session.
- `MATTERMOST_ALLOWED_USERS` for that gateway is generated from
  `contacts.yaml` grants only (`cube hermes render`). With no grants the list
  is empty and the bot answers nobody.
- Per-student context is injected by a pre-prompt hook that reads a context
  file rendered on ws by `cube student context --mm-user <u> --json`. Memory
  lives in cube, pa and org, not in Hermes.
- The bot never assesses a student. It collects self-reports, answers
  questions about the student's own milestone plan and check-in history, and
  says when it will summarise for Robert.

## Consequences

- One token, one gateway process, one unit (`cube-gateway-advisor.service`)
  to supervise and to kill.
- Revoking a grant regenerates the allowlist and restarts the gateway;
  revocation is immediate.
- Cross-student leakage is prevented by Hermes session isolation plus the
  hook, which only renders the context of the DM's own user; the hook is part
  of the test suite.
- Hermes upgrades can change session semantics; the Hermes version is pinned
  and the profile is rendered from a template.

## Alternatives considered

- One bot per student: cleanest isolation, but N tokens, N gateways, and a
  sysadmin step per student; unnecessary while the pilot is 1-2 people.
- Claude Code or Codex as the chat runtime: subscription terms forbid
  headless bot use of the Claude Max OAuth outside Claude Code, and neither
  has a Mattermost gateway (ADR-0006).
- No student-facing channel at all: keeps everything with Robert but removes
  the thing we want to pilot; the default-deny policy already gives this
  behaviour until a grant exists.
