# Sentinel

Not an LLM role. This file documents the patrols for humans and agents that
read the roles directory. The Sentinel is `cube patrol <name>`: pure Python,
zero tokens, triggered by the systemd timers in `systemd/`, schedules in
`cube.yaml`. It compares sources against rules and thresholds and writes
`kind:finding` and `kind:conflict` beads, `state/events.jsonl` and
`state/attention.json`.

Rules: never poll Mattermost on a schedule; never create a second bead for an
existing xid; never contact anyone (beads and events only); stop when
`state/KILL` exists; provenance on every finding (source path, locator,
seen date).

## What to escalate

Escalation kinds: `decision` (scope, money or plan), `permission` (resources),
`integrity` (suspected fabrication), `people` (anything about a person),
`conflict` (sources), `blocked` (tooling or input; the group fixes it), `note`
(information). Robert decides only what is security-critical (a change to a
running system, spend over budget, contact) or privacy-critical (a person's
data, secrets, local-only data leaving the local tier): set `critical:
security|privacy` on that escalation. Everything else the coordinator settles;
decide what you can yourself. Never escalate "no work assigned"; idle is fine.
