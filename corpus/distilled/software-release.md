---
topic: software-release
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Software release

Sources
- semver2 (CC-BY-3.0; short excerpts allowed)
- keep-a-changelog (MIT; short excerpts allowed)
- citation-file-format (CC-BY-4.0; short excerpts allowed)
- python-packaging-guide (CC-BY-SA-3.0; short excerpts allowed)
- bioconda-guide (MIT; short excerpts allowed)
- brack2022 (CC-BY-4.0; short excerpts allowed)
- joss-review-criteria (CC-BY-4.0; short excerpts allowed)
- joss-review-checklist (CC-BY-4.0; short excerpts allowed)
- joss-docs (CC-BY-4.0; short excerpts allowed)
- smith2016-software-citation (CC-BY-4.0; not fetched, summarized from knowledge)
- fair4rs2022 (CC-BY-4.0; landing page only)

## What the evidence says

### Version and change history

- Semantic Versioning requires a declared public API and a normal version of the form `MAJOR.MINOR.PATCH` without leading zeroes. [semver2]
- A backward-compatible bug fix increments PATCH, a backward-compatible API addition or deprecation increments MINOR, and a breaking API change increments MAJOR. Minor and patch components reset when the major component changes, and patch resets when the minor component changes. [semver2]
- A released version is immutable. A correction to released contents is a new release, not an edit to the old one. [semver2]
- Pre-release and build identifiers extend the core version; build metadata does not affect precedence, and pre-releases sort below the corresponding normal version. [semver2]
- A changelog is a curated list of notable changes for people, not a raw commit log. The recommended shape has an `Unreleased` section, reverse chronological releases, ISO dates, linkable version headings, and grouped change types. [keep-a-changelog]
- The useful change headings are Added, Changed, Deprecated, Removed, Fixed, and Security. Breaking changes, removals, deprecations, and security changes need clear entries. [keep-a-changelog]

### Citation and archival metadata

- `CITATION.cff` is a human- and machine-readable repository file that tells users the software name, version label, authors, and citation information. [citation-file-format]
- The minimal CFF example uses `cff-version`, `message`, `authors`, `title`, `version`, a DOI identifier, and `date-released`; author records can carry given names, family names, and ORCIDs. [citation-file-format]
- GitHub can render CFF as citation information, and Zenodo can reuse it when archiving a release. A repository should keep one authoritative citation record rather than divergent copies. [citation-file-format]
- Software citation guidance treats software as a citable research product and emphasizes credit, persistent identification, accessibility, persistence, and citing the exact version used. This attribution is summarized from the unfetched Smith et al. source. [smith2016-software-citation]
- FAIR4RS applies FAIR ideas to software while accounting for executability, composition from other software, and continuous versioning. The fetched record is the landing page and abstract, not the full principles text. [fair4rs2022]

### Distribution and workflow readiness

- The Python Packaging User Guide covers the flow from packaging through installation and distribution, with tutorials, guides, and interoperability specifications. [python-packaging-guide]
- Bioconda contributions use a recipe, commonly `meta.yaml`, followed by repository checks, automated building and testing, review, and merge before a package is published. [bioconda-guide]
- A workflow-ready tool should be installable through a package manager, declare dependencies explicitly, and use compatible version ranges to reduce dependency conflicts. [brack2022]
- A workflow-ready tool exposes runtime options, input paths, and output paths through its interface, reports version information, documents `--help`, and keeps status and errors in conventional streams. [brack2022]
- Reproducible releases preserve source, dependency information, configuration, random seeds, and output provenance; checksums and stable serialization can make output comparisons testable. [brack2022, fair4rs2022]
- Source control, tests, automated builds, and automated test execution belong with the software, and compiling or installing from source should produce the equivalent of the official distribution. [brack2022]

### JOSS readiness

- JOSS expects a real OSI-approved license file, a repository that outsiders can access, documentation for installation and use, examples, API documentation, verification, and community contribution pathways. [joss-review-criteria, joss-review-checklist]
- JOSS reviews look for sustained development, open development, releases, and evidence of collaboration or community engagement. [joss-review-criteria, joss-review-checklist]
- A JOSS paper contains a non-specialist summary, statement of need, comparison with related tools, key references, and the required sections for state of the field, software design, research impact, and AI usage disclosure. API documentation belongs in the software documentation rather than the paper. [joss-review-criteria, joss-review-checklist]
- JOSS accepts documented manual verification as an adequate lower level, but an automated suite connected to continuous integration is the strongest test signal. [joss-review-criteria, joss-review-checklist]
- JOSS accepts software that reimplements an existing solution when the authors explain the contribution and cite related work; the decision about scope and significance belongs to the editors. [joss-review-criteria]
- JOSS acceptance gives the short paper a Crossref DOI, while Zenodo can archive the software itself. These are different records and should not be silently substituted for each other. [joss-docs, citation-file-format]

## Rules we adopt

1. Declare the public API before choosing the release increment, then apply SemVer to every public change. [semver2]
2. Treat the release version as one value that must agree across packaging metadata, the release tag, the changelog heading, and `CITATION.cff`. Refuse to guess when a source is missing or conflicting. [semver2, citation-file-format]
3. Do not modify a released version. Correct a release by publishing a new version and describing the correction in the changelog. [semver2, keep-a-changelog]
4. Keep `CHANGELOG.md` with `Unreleased` at the top, put the newest dated release first, use ISO dates, and group notable changes under the standard headings. [keep-a-changelog]
5. Keep a valid root `CITATION.cff` with the known required fields, the exact release version, authors from an explicit authors file, and a version-specific DOI when one exists. [citation-file-format, smith2016-software-citation]
6. Archive each immutable release in Zenodo or another DOI service, preserve the archive record, and link the software record from the README. Do not treat a JOSS paper DOI as the software archive DOI. [smith2016-software-citation, fair4rs2022, joss-docs]
7. Build Python distributions from declared project metadata, keep dependencies pinned or bounded, publish to PyPI only after a local or TestPyPI verification, and prepare a reviewed Bioconda recipe when the audience uses Conda. [python-packaging-guide, bioconda-guide, brack2022]
8. Require tests in the repository and a CI configuration that runs them. A release check reports a missing test suite or CI as an error rather than inferring quality from a README claim. [brack2022, joss-review-criteria, joss-review-checklist]
9. Add a JOSS paper skeleton only when JOSS is in scope, and fill every required section with evidence about need, alternatives, design, impact, references, and AI use. [joss-review-criteria, joss-review-checklist, joss-docs]
10. Keep installation, examples, interface help, version output, and release documentation synchronized with the release. [brack2022, python-packaging-guide]
11. Run checks read-only against the target repository. A generator may print a proposed CFF, but it writes only after the caller passes `--apply`; publication, archival, and external comments remain approval-gated actions. [citation-file-format, joss-docs]
12. Report the file or command that supports every finding, give one concrete fix, and separate errors that block release from warnings that require human judgment. [joss-review-criteria, joss-review-checklist]

## Where sources disagree

- SemVer defines the meaning and precedence of version strings, while Python packaging has its own packaging and version-specification ecosystem. We require SemVer for the project release value and report any packaging-specific normalization as a human review item rather than silently translating it. [semver2, python-packaging-guide]
- JOSS allows documented manual verification as an acceptable lower grade, while the group's release gate requires tests and configured CI. We follow the stricter gate because a release should be repeatably checked before publication. [joss-review-criteria, joss-review-checklist, brack2022]
- CFF's simple example shows a DOI and release date, while a repository can exist before its archive record is minted. We allow a generated CFF without inventing either value, but the release checker blocks a final release until the version-specific record is supplied. [citation-file-format, smith2016-software-citation]
- JOSS acceptance provides a DOI for the paper, whereas software citation principles require identification of the exact software product and version. We check for a separate Zenodo or software DOI record. [joss-docs, smith2016-software-citation]

## Not covered

- The fetched CFF page gives a practical minimal example, not a complete validator for every CFF version or field. The checker validates the fields it knows and leaves unfamiliar valid fields for a schema-aware tool or human review. [citation-file-format]
- The fetched Python Packaging page is an overview, not a complete policy for every build backend, index, or version-normalization case. Backend-specific behavior remains the maintainer's responsibility. [python-packaging-guide]
- The Bioconda source describes the contributor workflow but does not establish a universal recipe for every dependency, platform, or migration. Recipe review and build results remain external checks. [bioconda-guide]
- None of these sources specifies a universal upper bound for every dependency or a complete policy for vendored code. The checker flags unbounded declarations and leaves compatibility and license review to the maintainer. [brack2022, fair4rs2022]
- JOSS criteria do not guarantee acceptance from a paper skeleton. Scope, significance, authorship, sustained development, and reviewer judgment remain outside deterministic release checks. [joss-review-criteria, joss-review-checklist]
- The Smith 2016 text was not fetched in this corpus. Claims attributed to it are explicitly summarized from the manifest citation and existing group notes, not presented as verified quotations. [smith2016-software-citation]
