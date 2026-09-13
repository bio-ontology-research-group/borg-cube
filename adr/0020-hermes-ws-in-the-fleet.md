# ADR-0020: hermes-ws is the fleet's voice on Mattermost

Status: accepted
Date: 2026-09-07
Extends: ADR-0009 (contact policy), hermes/README.md (profiles)

## Context

The Hermes gateway `@hermes-ws` runs on ws with Mattermost access (Robert's
DM, ~infra-alerts with the infrastructure postdoc), its own cron jobs (`infra-check` every five
minutes, `infra-nightly-scan`, `infra-morning-report`) and its own server
checks. It was outside the fleet: the cube's sysadmin agent reviewed the same
servers, the literature agent wrote digests nobody read, and Robert's
instructions reached the coordinator only through the cockpit. Robert,
2026-09-07: make it part of the fleet, on beads; the sysadmin reports to it;
the literature agent's findings become a morning brief; his commands go
through it to the coordinator, so Mattermost is the main channel.

## Decision

1. `agents/hermes-ws.yaml` declares the gateway as a fleet agent with the
   concierge role on ws. The cube never plays it (zero runs a day): the Hermes
   gateway and its cron jobs drive it and call `cube` and `bd` on ws. Its
   source of truth stays `borg-infrastructure/hermes-infra` (deploy.sh).
2. Infrastructure. The sysadmin's daily server review now takes the monitor's
   night scan as context and writes `briefings/infra/<date>.md`; the morning
   report's `morning.sh` injects that file as its main input. hermes-ws no
   longer inspects the servers for the report. The five-minute DOWN monitor
   stays: it is a script, not the agent, and the cube's infra_incidents patrol
   already reads its events.
3. Literature. A no-agent Hermes cron job (`cube-literature-brief`, 07:45)
   posts the day's `briefings/literature/<date>.md` to Robert's DM when the
   digest has entries; silent otherwise.
4. Commands. hermes-ws relays Robert's own words to the coordinator with
   `cube agent tell coordinator "<text>" --from robert` and never acts on them
   itself. The coordinator answers with `cube agent tell hermes-ws ... --from
   coordinator`; a no-agent cron job (`cube-outbox`, every fifteen minutes)
   runs `cube agent inbox hermes-ws --drain` and posts the unread lines to
   Robert's DM.
5. Contact policy is unchanged: hermes-ws posts to Robert and, in
   ~infra-alerts, to the infrastructure postdoc through the existing grant path;
   nobody else.

## Consequences

- One server review a day, done by the sysadmin agent; hermes-ws writes the
  report from it. The two jobs `cube-literature-brief` and `cube-outbox` call
  no model.
- The coordinator's workday prompt tells it to answer Mattermost messages
  through hermes-ws, with bead ids.
- `cube.yaml` `hermes.profiles.hermes-ws` records the bot and Robert's DM
  channel; `cube doctor` validates the declaration like any agent.
