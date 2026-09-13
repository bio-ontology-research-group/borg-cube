# ADR-0007: Three privacy classes on every bead and source path

Status: accepted
Date: 2026-09-02

## Context

borg-cube processes material of very different sensitivity: public
repositories and published papers; internal planning (pa KG, `papers.org`,
`deadlines.md`, meeting notes); and personal data about students and staff
(check-in transcripts, progress assessments, grades, contracts, visas,
personnel and health matters). Some of it is sent to cloud models. KAUST
policy and basic decency require that the most sensitive material never leaves
the campus network and that some of it never enters the system at all.

## Decision

Three classes, attached as `privacy:` labels to beads and mapped from source
paths in `cube.yaml`:

- `public`: research knowledge graph, public repositories, published papers.
  Any tier.
- `internal`: pa KG, `papers.org`, `deadlines.md`, meeting notes, org files,
  infrastructure runbooks. Cloud tiers allowed under the subscription terms
  (ADR-0006); never posted anywhere public.
- `local-only`: check-in transcripts, progress assessments, anything about a
  person's performance, contracts, visas, personnel, health. Only the `local`
  tier (vLLM on node005) may process it; if local is down the work queues.

Further rules:

- Grades and HR records never enter beads at all. `cube doctor` greps beads
  and briefings for forbidden field patterns.
- A bead inherits the strictest class of any source it references; a role's
  `privacy_max` caps what it may be given (`cube run` refuses otherwise).
- Briefings about students are Robert-only files (`briefings/students/`),
  never posted to Mattermost.
- Secrets (tokens, password files) are a fourth thing: never seeded, never
  printed, referenced by path only (`brain/doctrine.md`).

## Consequences

- The router must know availability of the local tier before accepting a
  local-only bead; the Sentinel checks `/v1/models` every patrol.
- Some useful analyses (a strong cloud model reading a check-in transcript)
  are simply not done. This is intended.
- Class assignment is auditable: the label is on the bead, the mapping is in
  `cube.yaml`, and the audit log records which runner saw which bead.

## Alternatives considered

- Two classes (public/private): too coarse; internal planning would either be
  blocked from cloud models or personal data would be allowed there.
- Per-field redaction before sending to cloud models: fragile, and a
  redaction failure is silent. Class-based routing fails closed.
- No local tier and no local-only class: simpler, but the advisor pilot could
  not process check-ins at all.
