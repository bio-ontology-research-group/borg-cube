---
topic: ontology-engineering
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Ontology engineering

Sources
- obo-foundry-principles (CC-BY-4.0; short excerpts allowed)
- miro2018 (CC-BY-4.0; stored source text is unavailable)
- malone2016 (CC-BY-4.0; short excerpts allowed)
- robot-report (BSD-3-Clause; short excerpts allowed)
- fair4rs2022 (CC-BY-4.0; short excerpts allowed)
- wilson2014 (CC-BY-4.0; short excerpts allowed)

## What the evidence says

- The OBO Foundry names the relevant principles exactly as Open, Common Format, URI/Identifier Space, Versioning, Scope, Textual Definitions, Documented Plurality of Users, Commitment To Collaboration, Locus of Authority, Naming Conventions, and Maintenance [obo-foundry-principles].
- Under the OBO summary, an ontology must be openly available, use an accepted common formal syntax, have a unique identifier space, document and mark releases, and stay within a clearly specified scope [obo-foundry-principles].
- The OBO summary requires textual definitions for most classes and top-level terms, asks developers to document multiple independent users and collaborative work, assigns a responsible contact, requires unique primary labels within an ontology, and expects maintenance responsive to scientific consensus and community requests [obo-foundry-principles].
- Malone and colleagues advise selecting an ontology with domain coverage appropriate to the task, current scientific understanding, persistent class identifiers, textual definitions, and community evidence rather than choosing on a label match alone [malone2016].
- Malone and colleagues describe obsolescence as preferable to deletion when a class must be removed, because preserving identifiers maintains the audit trail for annotated data [malone2016].
- ROBOT report evaluates quality-control queries and classifies findings as ERROR, WARN, or INFO; its report can be restricted to an input ontology or applied to a merged import closure [robot-report].
- FAIR4RS treats research software as an evolving, versioned digital research object whose sharing and reuse need explicit supporting practice [fair4rs2022].
- Scientific software guidance recommends version control, documentation of design and purpose, automated checks, and collaboration practices that make a repository's ontology maintenance evidence inspectable [wilson2014].
- The stored MIRO source text contains only an unavailable-page message, so the detailed MIRO reporting items must be verified against the complete guideline before being asserted as review requirements [miro2018].

## Rules we adopt

1. Review the exact OBO principle names in scope and distinguish what the offline checker can demonstrate from repository claims that need human evidence. (from [obo-foundry-principles], [robot-report])
2. Require a declared license, parseable OBO or RDF/XML input, a stable identifier pattern, a version marker, a documented scope, textual definitions, unique labels, declared imports, and explicit handling for obsolete terms before calling the deterministic review complete. (from [obo-foundry-principles], [malone2016])
3. Preserve identifiers for retired classes and report missing replacements or considerations as a review item instead of deleting or silently renaming a term. (from [malone2016], [obo-foundry-principles])
4. Record every finding at file or term level with a severity, evidence location, and concrete fix; do not turn an unrun ROBOT check into a pass. (from [robot-report])
5. Run ROBOT report and a reasoner when ROBOT is installed and the review scope permits it, preserving their output as separate evidence from the offline checks. (from [robot-report])
6. Review scope, documented plurality of users, collaboration, locus of authority, naming conventions, and maintenance from repository evidence, not from ontology syntax alone. (from [obo-foundry-principles], [wilson2014])
7. Treat ontology source, release process, tests, and maintenance records as versioned research-software evidence. (from [fair4rs2022], [wilson2014])
8. Verify every MIRO-specific assertion against the complete guideline before reporting it as a requirement. (from [miro2018])

## Where sources disagree

- The OBO principles prescribe development and governance expectations, while Malone and colleagues frame criteria for choosing an ontology for a use case; review both the repository's engineering evidence and its suitability for the stated application [obo-foundry-principles, malone2016].
- ROBOT can identify defined quality-control patterns but cannot prove governance, scope fitness, or community adoption; use its output as evidence, not as a complete OBO review [robot-report, obo-foundry-principles].
- The stored MIRO text cannot support a detailed checklist, while OBO and ROBOT source texts can support the checks stated here; leave MIRO details unverified until the complete source is available [miro2018, obo-foundry-principles, robot-report].

## Not covered

- Semantic-web endpoint design, SPARQL service behavior, linked-data deployment, and ontology authoring workflows; the separate semantic-web skill is the authority for those topics [robot-report].
- Logical soundness beyond the parser's deterministic checks when ROBOT or a compatible reasoner is absent or cannot process the ontology [robot-report].
- A complete MIRO field checklist, because the stored source does not contain the guideline text [miro2018].
- Whether a license is legally suitable or an identifier is permanently resolvable; the offline checker can inspect declared evidence but cannot provide legal or network verification [obo-foundry-principles, fair4rs2022].
