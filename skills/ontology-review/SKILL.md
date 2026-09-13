---
name: ontology-review
description: Review an ontology repository and an OWL or OBO release against the OBO Foundry principles, MIRO reporting evidence, ROBOT checks, and repository maintenance evidence. Use when asked to "review an ontology", "check OBO compliance", "run ROBOT report", "audit OWL", "audit an OBO file", "check ontology release readiness", "review PATO terms", "review FLOPO terms", or "assess ontology governance". It reports file- and term-level findings with severity and fixes; it never modifies, files, or submits anything.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; the offline checker supports OBO and RDF/XML OWL; ROBOT is optional for report and reasoning checks; no network.
metadata:
  borg-role: auditor
  grounding: fair4rs2022, malone2016, miro2018, obo-foundry-principles, robot-report, wilson2014
  hermes:
    category: software
    tags: ontology, obo, owl, robot, miro, governance, audit
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(robot *)
---

# Ontology review

Review ontology quality as both a release artifact and a maintained community
resource. `scripts/obo_check.py` performs only deterministic local checks.
The separate `semantic-web` skill remains the authority for RDF deployment,
SPARQL endpoints, linked-data behavior, and semantic-web integrations.

## Procedure

1. Establish the review target: repository revision, release file, stated
   scope, intended users, and review purpose. Record the path and revision in
   the report. A release file alone cannot establish governance claims.
2. Create repository metadata from `assets/ontology-metadata.yaml.example`.
   Link each governance field to evidence in the repository: license, scope,
   release policy, user evidence, collaboration channel, authority contact,
   naming policy, and maintenance process. Do not supply a missing URL or
   claim from memory.
3. Run the offline review:

   `python3 scripts/obo_check.py --ontology <release.owl-or-obo> --metadata <metadata.yaml> --json`

   It checks parseable common format, declared license and version evidence,
   identifier pattern, labels, definitions, obsolete-term handling, and
   imports. It returns file- and term-level findings with severity and a fix.
   It cannot prove that a license is legally open or that an IRI resolves.
4. If ROBOT is installed, preserve separate review artifacts under `runs/` and
   run both checks on a copy or release artifact, never an edit file in place:

   `robot reason --input <release.owl> --output runs/<id>/reasoned.owl`

   `robot report --input runs/<id>/reasoned.owl --output runs/<id>/robot-report.tsv`

   Add `--robot` to `obo_check.py` for an ephemeral local report and reasoning
   probe. If ROBOT is missing, record that report and reasoning were not run.
   Do not say the ontology passed ROBOT in that case.
5. Review each OBO principle with the exact names used by OBO: Open, Common
   Format, URI/Identifier Space, Versioning, Scope, Textual Definitions,
   Documented Plurality of Users, Commitment To Collaboration, Locus of
   Authority, Naming Conventions, and Maintenance. Treat Relations,
   Documentation, Notification of Changes, Term Stability, and Responsiveness
   as applicable additional review areas. Link each judgment to repository
   evidence or mark it not verified.
6. Add MIRO evidence only after checking the complete guideline. The local
   corpus copy does not include its full text, so a missing MIRO claim is not
   a pass and an invented MIRO requirement is not a finding.
7. Report findings as: severity, file or term identifier, evidence location,
   failed principle or check, impact, and smallest safe fix. Separate
   deterministic failures, ROBOT output, and human governance review.
8. For PATO work derived from FLOPO, also apply the repository's PATO/FLOPO
   checklist: keep PATO atomic and reusable, avoid disjunctive parents, audit
   existing terminology and definitions, use defensible parentage and synonym
   scope, trace sources, and preserve Robert's contributor metadata. Draft
   changes for review; do not submit or comment externally without approval.
9. Give Robert the report, input revision, metadata evidence, ROBOT status,
   and unresolved items. Changes, issue filing, pull requests, and review
   replies remain approval-gated.

## Hard rules

- Do not modify the ontology, repository metadata, release files, or imported
  ontologies while reviewing. Findings describe the smallest safe fix.
- Do not claim an OBO, MIRO, or ROBOT pass without the associated evidence.
  Tool absence, an unsupported syntax, missing metadata, or unavailable
  guidance is reported as not checked or unverified.
- Keep the OBO principle names exact. Do not substitute a remembered rule for
  a named principle or treat a metadata field as proof of real-world practice.
- Treat duplicate labels, an identifier-pattern violation, a missing required
  definition, or a malformed ontology as release-blocking until the target's
  own policy says otherwise. Treat absent governance evidence as a finding,
  not a failure of ontology syntax.
- Preserve obsolete identifiers. A retired term needs an explicit obsolete
  record and, when appropriate, a replacement or consideration; do not delete
  it merely to silence a check.
- Never contact maintainers, open an issue, update an ontology registry, push
  a branch, make a pull request, or submit a release from this skill without
  Robert's explicit approval.

## Grounding

- `references/ontology-engineering.md`: OBO principles, selection evidence,
  ROBOT report behavior, source limits for MIRO, and software maintenance
  evidence.

## Scripts and assets

- `scripts/obo_check.py --help`: offline OBO and RDF/XML OWL checks plus an
  explicit ROBOT availability result; emits `--json` findings and does not
  write the target.
- `assets/ontology-metadata.yaml.example`: repository evidence schema for
  OBO-principle review; replace every placeholder with a traceable path or URL.
