# ADR-0010: Gas Town for the coding fleet, decided after a Phase 3 spike

Status: proposed
Date: 2026-09-02

## Context

Gas Town (Yegge) adds to Beads what a coding fleet needs: a Mayor
(coordinator), Polecats (workers with persistent identity and ephemeral
sessions, each on a git worktree "hook"), a Witness (stuck-agent detection per
rig), a Deacon (cross-rig patrol), a Refinery (merge queue), Dogs (infra
maintenance workers), convoys (bundled beads with tracked status), formulas
and molecules (TOML multi-step workflows with checkpoint recovery), `gt
sling`, `gt escalate`, `gt feed --problems`, a scheduler with dispatch
capacity, OpenTelemetry, and runtime presets for Claude Code, Codex, Gemini,
OpenCode, Copilot and Cursor. Requirements: Go 1.26.2+ (we have 1.24;
`GOTOOLCHAIN=auto` downloads it), tmux 3.0+ (needed anyway on ws), `bd`
0.57+, sqlite3. Yegge's own warning: Gas Town "fell apart" for him under Opus
4.7's over-eager loop, and he moved to a bespoke harness. Gas Town has no
notion of people, milestones, privacy classes or approval queues.

## Decision (proposed)

- Use Gas Town, if at all, only for the coding fleet: one rig per software
  repository (bio-ontology-research-group repos, borg-infrastructure,
  borg-cube itself). Programmer, Auditor and merge queue would then come from
  Gas Town, and `cube` gains a `gastown` runner that turns a `stage:implement`
  bead into a convoy and reads completion back from beads.
- Research, advising, teaching, sysadmin and monitoring stay in `cube`.
- Phase 3 opens with a one-week spike on ws: install `gt`, one rig
  (borg-cube), one convoy through Mayor, Polecat and Refinery with Claude and
  Codex runtimes; measure stuck detection and merge behaviour.
- Kill criteria: cannot be driven headless from `cube`, or Witness and
  Refinery churn exceeds the benefit. On kill, `cube` keeps its own worktree
  runner and review gate (already designed), and Gas Town's TOML formulas
  remain a template for cube's `work-standard` and `paper-submit` molecules.
- This ADR moves to accepted or rejected at the end of the spike with the
  measurements attached.

## Consequences

- Nothing in Phases 0 to 2 depends on Gas Town.
- If adopted: less bespoke code for the coding fleet, another daemon set to
  operate, Go toolchain on ws.
- If rejected: the `cube` engine carries worktrees, leases and review itself,
  which is the current design anyway.

## Alternatives considered

- Adopt Gas Town for everything: it does not model people or approvals, and
  the contact policy (ADR-0009) could not be enforced inside it.
- Never evaluate it: we would rebuild stuck detection and a merge queue by
  hand without knowing whether the existing tool is good enough.
