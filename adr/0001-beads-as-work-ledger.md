# ADR-0001: Beads is the work ledger, wrapped behind one Python module

Status: accepted
Date: 2026-09-02

## Context

borg-cube needs a durable, queryable ledger of work items (student programs,
milestones, papers, experiments, reviews, audits, incidents, patrol findings,
source conflicts) with dependencies, labels, comments and a ready queue that
several runtimes (Claude Code, Codex, Hermes, plain Python) can share. Steve
Yegge's Beads (`bd`) provides exactly this: a git-friendly issue graph with
`bd ready`, `bd prime`, `bd remember`, labels, dependencies, JSON output and
first-class support for agent workflows. Gas Town builds on Beads but adds a
coordination layer we have not evaluated (see ADR-0010). Beads is young and
its CLI changes; we have seen a Dolt backend and a Linux install path that
need pinning.

## Decision

- Beads (`bd`) is the only work ledger. Every work item is a bead with a
  native type (`epic`, `task`, `chore`) and a `kind:` label carrying the
  research semantics (program, milestone, paper, experiment, review, audit,
  lecture, course, mentoring, meeting-note, service, finding, conflict,
  incident, outbound).
- All access goes through one Python module, `cube/beads.py`. No other code
  and no role prompt calls `bd` directly for writes. Reads through `bd ... --json`
  are allowed for agents (`bd prime`, `bd show`, `bd ready`).
- Every bead description begins with a fenced YAML header holding `xid`
  (idempotency key), `provenance[]` and `deadline`. `cube sync` never creates a
  second bead for an existing `xid`.
- `bd remember` holds doctrine facts, pushed by `cube brain push` from
  `brain/facts/`.
- The Beads version is pinned; `bd export` runs nightly to a JSONL backup;
  xid headers allow full re-derivation of synced beads from the sources.

## Consequences

- One place to change when the `bd` CLI changes; tests exercise the wrapper
  against recorded `bd` JSON fixtures.
- Beads hold work and provenance only. Facts about people, projects and
  papers stay in their sources of truth (ADR-0002).
- Agents get a consistent view (`bd prime`) at session start at zero cost.
- We accept the risk of a young tool because the data is small, exportable and
  re-derivable.

## Alternatives considered

- Gas Town as the ledger and coordinator: heavier, Go 1.26 and tmux required,
  Yegge himself reports it fell apart under an over-eager model loop. Kept as a
  Phase 3 spike for the coding fleet only (ADR-0010).
- GitHub issues: not private enough for student data, no dependency graph, no
  local ready queue.
- Org-mode files as the ledger: they are already the group model for meetings
  (`~/org`), but they are hand-edited and lock-prone; making them the machine
  ledger would mix human notes and agent state.
- Own SQLite schema: full control but we would rebuild what `bd` already has.
