# ADR-0002: The group model stays external and read-only

Status: accepted
Date: 2026-09-02

## Context

Facts about people, projects, papers, deadlines and meetings already live in
three maintained places: the personal-assistant repo `~/pa` (KG project nodes
with "Status as of" sections, contacts, `deadlines.md`), the public research
knowledge graph (`research-knowledge-graph`, 435 nodes, `borg-id:` IRIs) with
the roster of record in `borg-website/people/roster.md`, and `~/org` (one org
file per person, `staff.org` with milestone estimates, `papers.org` with the
custom TODO sequence). These sources disagree today (one PhD student is an "MSc
former member" in `projects.jsonld` but a current PhD student in `staff.org`;
two alumni are listed as alumni in `staff.org` but current in the roster). Any
copy borg-cube made would drift into a fourth opinion.

## Decision

- borg-cube holds no group model. It reads `~/pa`, `~/org`, the research
  knowledge graph and the roster through `cube/sources/*` (read-only adapters)
  and stores only work items and provenance in Beads (ADR-0001).
- `people.yaml` is a join table only: cube id to pa contact slug, `borg-id`
  IRI, org file, Mattermost user, programme and start date, each with its
  source.
- `cube sync` derives beads from the sources and surfaces disagreements as
  `kind:conflict` beads for Robert. It never resolves a conflict silently and
  never writes back to a source without an approval gate.
- Writes to `~/org` (meeting entries, milestone plans) and `~/pa` overlays go
  through the existing scripts in those repos, are lock-aware, default to
  `--dry-run`, and are tagged (`:cube:`) with provenance.
- Clones of the data repos live on ws and are kept fresh by the hourly
  `data-pull` patrol; git conflicts become `needs:robert` beads.

## Consequences

- No duplicate source of truth; when a fact is wrong, it is fixed where it
  lives and every consumer sees the fix.
- borg-cube can be rebuilt from scratch by re-running `cube sync`.
- Latency: a fact is only as current as the last pull and sync; acceptable for
  a weekly advising cadence.
- Some queries are slower than a local database would be; we accept this.

## Alternatives considered

- A cube-owned people/projects database: fast queries, but a fourth diverging
  copy and a privacy liability.
- Making Beads the group model: beads are work items, not entities; the
  provenance model would blur.
- Making the public KG the single source: it is public by design and cannot
  hold internal facts (milestone risk, meeting notes).
