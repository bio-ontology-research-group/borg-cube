---
name: software-release
description: Prepare and inspect a versioned research-software release across packaging metadata, SemVer tags, Keep a Changelog, CITATION.cff, DOI archival, PyPI or Bioconda readiness, and an optional JOSS paper skeleton. Use when asked to "prepare a release", "check release readiness", "publish this package", "make a CITATION.cff", "mint a software DOI", "prepare for PyPI or Bioconda", or "check JOSS readiness". The skill prepares evidence and files; external publication and other irreversible actions remain approval-gated.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; no network; release checks are read-only and CFF writes require --apply.
metadata:
  borg-role: researcher
  grounding: balaban2021, bioconda-guide, brack2022, citation-file-format, fair4rs2022, google-code-review, hunter-zinck2021, jimenez2017, joss-docs, joss-review-checklist, joss-review-criteria, keep-a-changelog, lee2018-documenting, list2017, nust2020, openssf-scorecard, osborne2014, python-packaging-guide, romano2020, semver2, sholler2019, smith2016-software-citation, taschuk-wilson2017, turing-way, wilson2014, wilson2017
  hermes:
    category: software
    tags: release, semver, citation, pypi, bioconda, joss
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Software release

Prepare a citable, installable research-software release and show the evidence
needed for review. The release check is deterministic and read-only. The CFF
generator prints a proposed file by default and writes only with explicit
approval through `--apply`.

## When to use

- A repository is moving from development to a tagged release.
- A paper, archive, PyPI package, or Bioconda recipe needs release metadata.
- Robert asks whether software is ready for JOSS or asks for a CFF file.

## Procedure

1. Confirm the target repository, intended release version, package ecosystem,
   and whether JOSS is in scope. Do not infer a missing version or author.
2. Run `python3 scripts/release_check.py --repo <path> --version <version>`.
   Add `--joss` for the JOSS gate and `--json` when another tool will consume
   the findings. Read every finding, its location, severity, and fix.
3. Resolve version conflicts across `pyproject.toml` or other packaging
   metadata, the `v<version>` or `<version>` tag, the Keep a Changelog entry,
   and `CITATION.cff`. Use a new immutable version for corrections.
4. Prepare citation metadata with
   `python3 scripts/cff_gen.py --repo <path> --authors <authors.yaml> --version <version>`.
   Inspect stdout. Re-run with `--apply` only when the exact output is approved.
5. Verify the release archive or DOI record, package build metadata, bounded
   dependencies, tests, CI, installation instructions, and examples. Prepare
   PyPI or Bioconda submission artifacts locally; do not upload or open an
   external request from this skill.
6. If `--joss` is in scope, fill `paper.md` with evidence for every required
   section and keep API details in the repository documentation. Run the check
   again and hand the report to Robert for approval.

## Hard rules

- Treat the version as one value. Stop on missing or conflicting metadata.
- Keep released tags and archives immutable. Never rewrite a released version.
- Require a root license, bounded or pinned dependencies, tests, CI, and a
  versioned changelog before calling a release ready.
- Keep `CITATION.cff` authors sourced from an explicit authors file. Never
  invent an author, ORCID, DOI, release date, or package version.
- `release_check.py` never writes the target repository. `cff_gen.py` writes
  only with `--apply` and refuses to write an output outside the target root.
- Publishing to PyPI, submitting a Bioconda recipe, minting or enabling a DOI,
  opening a JOSS submission, and posting external comments require Robert's
  approval and evidence first.
- Report unknown or unsupported metadata as a warning or not checked. Do not
  convert uncertainty into a passing claim.

## Grounding

- `references/software-release.md`: release checks, CFF fields, dependency
  policy, and JOSS routing.
- `references/research-software-practice.md`: synced research software
  practices for tests, documentation, dependencies, licenses, and releases.
- `references/fair4rs-and-joss.md`: synced FAIR4RS, citation, and JOSS
  expectations.

## Scripts

- `scripts/release_check.py --help`: inspect a repository without writing;
  reports severity and one concrete fix per finding, with `--json` output.
- `scripts/cff_gen.py --help`: render a CFF from repository metadata and an
  authors file; it writes only with `--apply` and otherwise prints the file.
