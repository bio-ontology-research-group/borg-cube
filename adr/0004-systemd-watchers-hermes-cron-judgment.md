# ADR-0004: systemd timers for watchers, Hermes cron only for judgment and delivery

Status: accepted
Date: 2026-09-02

## Context

Yegge's lesson: crons watch, models act. Most scheduled work in borg-cube is
deterministic (compare dates, scan repos, expire leases, pull git) and should
run even when no LLM or gateway is up, cost zero tokens, and leave an audit
trail. Hermes has its own cron (`hermes cron`) which `hermes-ws` already uses
for `infra-check` (5 min), `infra-nightly-scan` and `infra-morning-report`.
Hermes cron scripts run with a sanitised environment (no `.env` secrets),
which is good for safety but limits what they can reach.

## Decision

- Deterministic patrols run as systemd user timers on ws:
  `cube-patrol@<name>.service` triggered by `cube-patrol-<name>.timer`
  (milestones, papers, deadlines, calendar, student-digest, repos,
  infra-hygiene, data-pull, leases). They are pure Python, write beads and
  `state/events.jsonl`, and stop when `state/KILL` exists
  (`ConditionPathExists=!.../state/KILL`).
- Hermes cron is used only where the scheduled action is a judgment delivered
  through a bot identity: the advisor weekly nudge (granted students only),
  the concierge morning brief, and the existing `hermes-ws` infra jobs.
- Event-driven inputs (Mattermost, `infra-check` results, email triggers)
  arrive through gateway events, webhooks or `cube event`, never through REST
  polling on a schedule.
- Schedules live in `cube.yaml` (`patrols:`); `cube systemd install` renders
  and enables the units from it.

## Consequences

- Patrols are visible in `systemctl --user list-timers` and `journalctl
  --user -u cube-patrol@milestones`; a broken gateway does not stop them.
- Two schedulers exist, but with a clear rule: no tokens in systemd, no
  deterministic work in Hermes cron.
- ws must have `loginctl enable-linger <user>` (already the case for the
  hermes gateway).

## Alternatives considered

- Everything in Hermes cron: single scheduler, but patrols would depend on the
  Hermes process, could not read `.env`, and would be logged only in Hermes.
- Everything in systemd, including LLM judgments: possible via `cube run`, but
  bot-delivered messages then need a second path into Mattermost; Hermes
  already has one.
- A Python scheduler daemon (APScheduler or similar): another long-running
  process to keep alive; systemd already does this well.
