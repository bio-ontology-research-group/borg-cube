# ADR-0013: Deterministic research pipeline

Date: 2026-09-03

## Status

Accepted

## Context

A research project must be startable from one instruction and continue through
mail collection, planning, literature review, implementation, review, and a
repeatable gate. The existing Beads ledger, standing agents, marshal, run
engine, and review gate already own those concerns. Putting stage decisions in
model prompts would make transitions hard to inspect and rehearse.

## Decision

A research pipeline is an ordinary goal epic labelled `pipeline:research`.
Every stage is an ordinary child bead with a stable external reference and
explicit dependencies. `cube.pipeline` owns creation, status derivation,
artifact checks, experiment materialisation, numbered gates, iteration limits,
and kill bookkeeping. It performs no model calls.

The marshal remains the only dispatcher. The liaison workday and `cube run`
remain the only agent and model execution paths. Plan and survey artifacts are
copied under `runs/pipelines/<epic>/` and checked before their stage closes.
Programmer output keeps the existing senior review gate. A pipeline gate can
approve, reject, or create provenance-backed experiment revision beads.

The production command includes a complete offline rehearsal. It uses the
shared fake Beads executable, fake mail, and stub runner, while still passing
every executable bead through `marshal.tick`.

## Consequences

Stage changes and retry limits consume no model tokens and can be reproduced
from ledger state. Pipeline work remains visible in the existing cockpit and
worker fleet. A malformed plan, citation error, rejection, or kill condition
stops automatic progress with a `needs:robert` finding instead of guessing.
