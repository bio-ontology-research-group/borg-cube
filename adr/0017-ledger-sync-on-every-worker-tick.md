# ADR-0017: Ledger sync on every worker tick

Status: accepted
Date: 2026-09-06
Extends: ADR-0004 (systemd user units on ws)

## Context

The laptop (`lc-dell`) and the workstation (`ws`) each hold their own Beads
ledger in an embedded Dolt database. The two share one Dolt remote, the
`refs/dolt/data` ref on the project's git remote, and no ssh route: ws cannot
reach the laptop. Nothing in the repository ran `bd dolt push` or `bd dolt
pull`. A request the coordinator filed on ws for the laptop liaison
(`cube-l7c`, `cube-eww`, `cube-3lv`) reached the laptop only when someone
synced by hand, and the liaison's answers never reached ws at all. Bead
`cube-24ip` records the gap; it held the CRG2026 support pack `cube-w47`.

## Decision

`cube worker` syncs the ledger around every tick, on every host:

1. `bd dolt pull` before the marshal tick, so the host dispatches against the
   latest shared state (a request filed elsewhere, an answer written elsewhere).
2. `bd dolt push` after the tick, so what this tick and this host's runs wrote
   (claims, comments, review beads, answers) is visible to the other host.

The worker is the right place because it already runs on both hosts on a
timer (`cube-worker-laptop.timer` every five minutes on the laptop,
`cube-worker@3.service` looping every thirty minutes on ws) and because the
agent workday patrol on ws writes beads that only the next tick needs to
publish. No dedicated sync timer, no host-to-host path.

A failed pull or push never stops the tick: the worker keeps dispatching on
the local ledger, prints the failure to stderr (journal), appends an `error`
event tagged `ledger.sync.failed` to `state/events.jsonl` for the cockpit,
and reports `ledger sync failed Nx` in its summary line. `--no-sync` skips
both steps for tests and offline work; `--dry-run` never touches the remote.

## Consequences

- A liaison answer written on the laptop reaches ws within one laptop tick
  plus one ws tick (at most thirty-five minutes).
- Both hosts must be able to reach the git remote over ssh. When one cannot,
  its ledger drifts and every tick says so in the journal and the event log.
- Dolt three-way merges resolve concurrent edits; a merge conflict surfaces as
  a failed pull and stays visible until a person resolves it.
- The first sync after a long gap can take minutes (observed on the laptop on
  2026-09-06); the laptop worker unit's four-minute start timeout may need
  raising if that recurs.
