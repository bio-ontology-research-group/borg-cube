# ADR-0008: ws is the orchestration host, the laptop is a thin client

Status: accepted
Date: 2026-09-02

## Context

Robert works from a laptop (lc-dell, 8 GB GPU), the office, home and travel.
Orchestration must run from anywhere and survive the laptop being closed. The
office workstation `ws` (KAUST network, 56 cores, 125 GB RAM, no usable GPU)
is always on, already runs `hermes-ws` with a Mattermost gateway, has linger
enabled, and is reachable from outside through an existing ssh route that is
documented in the infrastructure repository, not here. Claude Code login on
ws is Claude Code itself, so within terms (ADR-0006). An earlier design split
state between laptop and ws with a file bridge; that is superseded here.

## Decision

- ws holds everything: the borg-cube checkout, Beads (single writer), the
  `cube` engine and Marshal, systemd user timers, Hermes profiles
  (`hermes-ws` existing; `advisor`, `scribe`, `concierge` new), Claude Code
  and Codex workers (`claude login`, `codex login` on ws), tmux for
  persistent interactive sessions, and clones of the data repos (`~/org`,
  `~/pa`, `research-knowledge-graph`, `borg-website`, papers as needed) kept
  in sync by git.
- The laptop is a cockpit: Emacs `borg-cube.el` runs `ssh ws cube ... --json`,
  attaches to `tmux` sessions on ws through `ssh -t` inside eat, edits remote
  files via TRAMP. Local mode (`cube-remote-host` nil) exists for development.
- Any machine with ssh (and optionally Emacs) is an equivalent cockpit. The
  phone uses the Concierge Hermes profile (Robert-only DM).
- Notifications flow ws to cockpit through `state/events.jsonl` and
  `state/attention.json`, tailed over ssh; Claude and Codex hooks on ws call
  `cube notify`. No file bridge between machines.
- Gnus mail stays on the laptop: email approvals produce a draft file on ws;
  the cockpit hands it to the Gnus daemon when Robert is at the laptop.
- The `local` tier is reached from ws over the KAUST network (the GPU node
  via the cluster head node); no extra route is needed for that hop.

## Consequences

- Closing the laptop kills nothing. Sessions are resumable from anywhere.
- ws becomes a single point of failure; the Sentinel and `hermes-ws` monitor
  it, and everything on it is in git or re-derivable (ADR-0001, ADR-0002).
- Two clones of the data repos (ws and laptop) must be kept in sync; the
  hourly `data-pull` patrol and push-after-approval handle ws; the laptop
  keeps its current habits.
- Credentials exist on ws (`~/.codex/auth.json`, `~/.claude`, `.env`); file
  modes are checked by `cube doctor`.

## Alternatives considered

- Laptop as host with ws as a worker: ties everything to one portable
  machine; sessions die on disconnect.
- borg-server (Hetzner) as host: outside KAUST, so no direct route to node005
  or IBEX and a worse place for internal data.
- A new dedicated VM: more to administer; ws already has capacity and the
  Hermes deployment.
