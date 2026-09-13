# Software release checks

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

## Contents

- Version resolution and consistency
- Changelog and CFF checks
- Distribution, dependencies, tests, and CI
- Optional JOSS checks

## Version resolution and consistency

Use an explicitly supplied `--version` when the caller names the release. Otherwise read a direct version from known packaging metadata. The checker reads `pyproject.toml`, `setup.cfg`, `setup.py`, `package.json`, and `Cargo.toml` without executing project code. This keeps the public API and release value inspectable under SemVer. [semver2, python-packaging-guide]

Treat `v1.2.3` and `1.2.3` as equivalent tag spellings, but report the exact tag as evidence. Do not treat arbitrary branch names, commit messages, or generated files as a release tag. SemVer uses the unprefixed numeric value, while a `v` prefix is a common tag convention. [semver2]

Compare every discovered packaging version. Compare the resulting expected version with the release tag, changelog heading, and CFF `version`. A missing or conflicting value is an error with the file or command that exposed it. Released contents are immutable, so a correction needs a new version. [semver2, citation-file-format]

If metadata uses a version scheme that the checker cannot map to SemVer, report it rather than translating it. Python packaging has its own specifications, and the maintainer must decide how a project-specific scheme relates to its public release policy. [semver2, python-packaging-guide]

## Changelog and CFF checks

Look first for `CHANGELOG.md`, then `CHANGELOG`, `HISTORY.md`, `NEWS.md`, or `RELEASES.md`. A release entry is a level-two heading containing the expected version, an ISO date, and at least one standard level-three category: Added, Changed, Deprecated, Removed, Fixed, or Security. Keep an `Unreleased` heading at the top when the file follows Keep a Changelog. [keep-a-changelog]

Do not derive release notes from `git log`. A changelog communicates notable changes to users and should call out deprecations, removals, security changes, and other breaking behavior. [keep-a-changelog, brack2022]

The known CFF schema is intentionally conservative. Require a YAML mapping with `cff-version`, `message`, `title`, `authors`, `version`, and `date-released`. Require non-empty author mappings with `family-names` or `name`; validate `given-names` and `orcid` when present. Validate `date-released` as an ISO date, and validate `identifiers` as a list of mappings with non-empty `type` and `value`. Preserve unknown fields and report them only as information, because the checker does not claim to implement all CFF versions. [citation-file-format]

For release readiness, require a CFF DOI identifier or a recognizable Zenodo or DOI record in repository metadata. Do not invent a DOI or date. A DOI for the JOSS paper is not evidence that the software archive itself has a version-specific identifier. [citation-file-format, smith2016-software-citation, joss-docs]

## Distribution, dependencies, tests, and CI

Inspect Python dependencies in `pyproject.toml`, `setup.cfg`, `setup.py`, and `requirements*.txt`, plus common `environment.yml` and `package.json` declarations. A direct pin such as `==1.2.3`, a compatible range such as `~=1.2`, or a range with an upper bound such as `>=1.2,<2` is bounded. A bare name, URL install, wildcard, or lower-only constraint is unbounded and gets an error with the declaration location. [python-packaging-guide, brack2022]

The checker does not claim that a bound is compatible with the project. It only reports whether the declaration limits resolver choice. License compatibility, vulnerability status, lockfile correctness, and native system dependencies remain human or ecosystem checks. [brack2022, fair4rs2022]

Recognize test files in a `tests` directory and common language test naming patterns. Recognize GitHub Actions, GitLab CI, CircleCI, Azure Pipelines, Travis, and Buildkite configurations. Missing tests or CI are errors because the release must be objectively checkable and repeatedly verified. [brack2022, joss-review-criteria, joss-review-checklist]

PyPI readiness means the repository exposes modern package metadata and installation instructions. Bioconda readiness means a separate recipe can name the release source, version, dependencies, and test command, then pass automated build and review. The checker reports repository evidence and does not submit either package. [python-packaging-guide, bioconda-guide]

## Optional JOSS checks

With `--joss`, look for `paper.md` or `paper/paper.md` and require headings for Summary, Statement of need, State of the field, Software design, Research impact statement, and AI usage disclosure. Also report the absence of a bibliography file or contribution guidance as a warning, not as proof that a paper will be accepted. [joss-review-criteria, joss-review-checklist, joss-docs]

JOSS readiness still needs human review of scope, significance, sustained development, open development, authorship, comparisons, evidence of impact, and the ability to install and verify the software. A deterministic script cannot establish those claims from filenames alone. [joss-review-criteria, joss-review-checklist]

Every finding uses one of `error`, `warning`, or `info`, includes a location or an explicit command, and includes a concrete fix. Errors make the script exit 1. Warnings and informational findings do not. JSON output keeps the same fields so a caller can build an approval packet without scraping prose. [joss-review-criteria, joss-review-checklist]
