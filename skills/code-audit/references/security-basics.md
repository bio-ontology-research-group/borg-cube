---
topic: security-basics
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Security basics for research software audits

Sources
- owasp-top-ten (CC-BY-SA-4.0; short excerpts allowed)
- cwe-top25 (proprietary; summary only, no quotes)
- openssf-scorecard (Apache-2.0; short excerpts allowed)

This file grounds the security pass of the code-audit skill over research
software: Python packages and scripts, some Java and Groovy, shell,
Dockerfiles, and notebooks, almost none of which serve HTTP. The sources were
written for web applications, all software, and open source repositories in
turn; the rules below pick what transfers.

## What the evidence says

### What the three lists are and how they relate

- The OWASP Top 10 is "a standard awareness document for developers and web
  application security" and represents broad consensus on the most critical
  risks to web applications; the current release is 2025, the previous ones
  are 2021 and 2017 [owasp-top-ten].
- OWASP presents adoption of the list as a first step toward a development
  culture that produces more secure code, not as a complete checklist
  [owasp-top-ten].
- OWASP builds its categories from CWE data. Its data call asks contributors
  for core CWEs rather than categories, ranks by incidence rate (the share of
  tested applications with at least one instance of a CWE) rather than raw
  finding counts, and adds up to two categories from a community survey
  [owasp-top-ten].
- The CWE Top 25 ranks the most common and impactful software weaknesses
  behind the CVE records in a year's dataset (about 39,000 records for the
  2025 list). MITRE describes them as often easy to find and exploit, and as
  root causes that can let an attacker take over a system, steal data, or
  stop an application from working [cwe-top25].
- MITRE says the list is meant to remove whole classes of defect, names
  memory safety and injection as examples, and singles out command injection
  as a weakness that attracts attacker attention and so deserves priority
  [cwe-top25].
- Scorecard is an automated tool that scores security heuristics ("checks")
  from 0 to 10 so that maintainers can see what to improve and consumers can
  judge dependencies [openssf-scorecard].
- Scorecard states its own limits: "The checks themselves are heuristics;
  there are false positives and false negatives", and an aggregate score
  tells you nothing about which individual behaviors a repository has
  [openssf-scorecard].
- Scorecard weights checks by risk level: Critical 10, High 7.5, Medium 5,
  Low 2.5 [openssf-scorecard].

### OWASP categories that matter for research code

The fetched project page names the releases but does not list the
categories. Every bullet in this section is from knowledge of the OWASP Top
10:2021 category list, not verified against the fetched text.

- Injection (A03): untrusted data reaches an interpreter. In research code
  this is a shell command assembled from a filename or sample id, or an SQL
  string built by formatting in a notebook [owasp-top-ten].
- Insecure design (A04): no threat model at all. A pipeline that trusts every
  file in a download directory, or runs whatever a metadata field names
  [owasp-top-ten].
- Security misconfiguration (A05): debug modes left on, world-writable
  output, containers running as root, default passwords in compose files
  [owasp-top-ten].
- Vulnerable and outdated components (A06): unpinned or years-old
  dependencies, forks of unmaintained libraries vendored into the tree
  [owasp-top-ten].
- Identification and authentication failures (A07): credentials handled
  badly. For scripts: API keys in config files or notebook cells, tokens on
  the command line where they land in shell history [owasp-top-ten].
- Software and data integrity failures (A08): code or data accepted without
  verifying its origin. Unverified downloads, unsafe deserialization (pickle,
  yaml.load, Java ObjectInputStream), and CI that pulls unpinned actions.
  This is the category that matters most for research code [owasp-top-ten].
- Security logging and monitoring failures (A09): nothing records who ran
  what with which inputs; exceptions around downloads or permission changes
  are swallowed [owasp-top-ten].
- Server-side request forgery (A10): code fetches a URL that an input file or
  a user supplied, such as a data fetcher that accepts arbitrary URLs from a
  manifest [owasp-top-ten].
- Broken access control (A01) and cryptographic failures (A02) assume a
  multi-user service and apply only to repositories that expose an HTTP API
  [owasp-top-ten].

### CWE weaknesses most relevant to scripts and tools

The fetched CWE page is the Top 25 landing page and does not list the 25
entries. Every identifier in this section is from knowledge of the CWE
catalog, not verified against the fetched text.

- OS command injection (CWE-78): subprocess with shell=True, os.system, bash
  eval, Groovy execute() on strings that include external data [cwe-top25].
- Path traversal (CWE-22): joining a base directory with an untrusted name
  without checking the result stays inside it; archive extraction without
  member checks is the same weakness [cwe-top25].
- Deserialization of untrusted data (CWE-502): pickle, joblib, torch.load
  with full unpickling, yaml.load without SafeLoader, Java object streams on
  files the program did not itself write [cwe-top25].
- Use of hard-coded credentials (CWE-798): passwords, tokens, or keys in
  source, config, Dockerfiles, or notebook outputs [cwe-top25].
- Improper input validation (CWE-20): no type, range, or format checks on
  parameters that drive file names, sizes, or loops [cwe-top25].
- Code injection (CWE-94): eval, exec, compile, or importlib on strings from
  outside the program; Groovy Eval and GroovyShell on external text
  [cwe-top25].
- Insufficient verification of data authenticity (CWE-345, with children
  CWE-494, download of code without integrity check, and CWE-347, improper
  signature verification): curl piped to a shell, weights fetched without a
  checksum, pip installs from a URL. Not always in the current Top 25, but
  the direct match for OWASP A08 [cwe-top25].

### Scorecard checks a repository audit can reproduce

The README lists every default check with a one-line question and a risk
level [openssf-scorecard]. The checks we reproduce by hand or with a script:

- Binary-Artifacts (High): "Is the project free of checked-in binaries?"
  [openssf-scorecard].
- Branch-Protection (High): whether the default and release branches are
  protected. The detailed output looks at force pushes disabled, deletion
  disabled, required status checks, number of required reviewers, stale
  review dismissal, and whether administrators also need reviews
  [openssf-scorecard].
- Code-Review (High): "Does the project practice code review before code is
  merged?" A protected default branch with required review satisfies it
  [openssf-scorecard].
- Dangerous-Workflow (Critical): whether GitHub Actions workflows avoid
  dangerous coding patterns [openssf-scorecard]. The patterns the check
  documentation names are script injection from untrusted event context and
  checking out pull request code under pull_request_target (from knowledge of
  the checks documentation, not verified against the fetched README)
  [openssf-scorecard].
- Dependency-Update-Tool (High): whether a tool such as Dependabot or
  Renovate is configured [openssf-scorecard].
- License (Low): whether the project declares a license [openssf-scorecard].
- Maintained (High): whether the project is at least 90 days old and shows
  activity; the sample output normalizes two commits in 90 days to a score
  of 1 [openssf-scorecard].
- Pinned-Dependencies (Medium): whether dependencies are declared and pinned
  [openssf-scorecard]. The check documentation looks for actions referenced
  by full commit hash, Dockerfile images by digest, and pip, npm, and shell
  downloads with fixed versions or hashes (from knowledge of the checks
  documentation, not verified against the fetched README) [openssf-scorecard].
- SAST (Medium): whether static analysis such as CodeQL runs
  [openssf-scorecard].
- Security-Policy (Medium): whether a security policy file exists
  [openssf-scorecard].
- Signed-Releases (High): whether releases are cryptographically signed; the
  project itself ships SLSA provenance and shows how to verify it
  [openssf-scorecard].
- Token-Permissions (High): "Does the project declare GitHub workflow tokens
  as read only?" [openssf-scorecard].
- Vulnerabilities (High): whether known unfixed vulnerabilities exist, looked
  up through the OSV service [openssf-scorecard].

## Rules we adopt

Severity scale. Every finding carries exactly one of these labels; the
auditor, not the author, assigns it (from [openssf-scorecard]).

- high: a malicious input or a compromised network source can run code, read
  or write outside the intended files, or a live credential is exposed. Fix
  before merge or release; the finding blocks.
- medium: exploitation needs a second condition (a compromised upstream, a
  hostile file the user chose to fetch), or a control that Scorecard rates
  High or Critical is missing. Fix within the current work cycle.
- low: hygiene. A missing policy or license file, no update tool, no static
  analysis. Record it and schedule it.
- info: an observation with no fix required, such as a risky pattern that is
  safe in its context, with the reason written down.

1. Treat any committed secret (API key, token, password, private key,
   cloud credential) as high, always, including in git history and notebook
   outputs and even if already revoked. Fix: rotate, purge from history,
   load from an environment variable or a gitignored file (from
   [cwe-top25], [owasp-top-ten]).
2. Treat eval, exec, compile, os.system, subprocess with shell=True, bash
   eval, or Groovy Eval on data from a user, file, network, or environment
   as high. Fix: argument lists, shlex.quote, or a lookup table (from
   [cwe-top25], [owasp-top-ten]).
3. Treat a path built from untrusted input without normalization and a
   prefix check as high when the code can write or delete, medium when it
   only reads; archive extraction without member path checks is high (from
   [cwe-top25]).
4. Treat pickle, joblib, full torch.load, yaml.load without SafeLoader, or
   Java object deserialization of a downloaded or user-supplied file as
   medium; raise to high when the file arrives over an unauthenticated
   connection at run time. Fix: safe loaders, checksums, or a schema-based
   format (from [cwe-top25], [owasp-top-ten]).
5. Treat downloads used as code or data without checksum or signature
   verification (curl piped to sh, wget of weights, pip install from a URL
   or git+https without a hash) as medium (from [owasp-top-ten],
   [openssf-scorecard]).
6. Treat GitHub Actions referenced by tag or branch, Dockerfile FROM without
   a digest, and unpinned requirements as medium. Fix: full commit SHA,
   image digest, lock file with hashes (from [openssf-scorecard]).
7. Treat a workflow that interpolates untrusted event fields into a run step
   or checks out pull request code under pull_request_target as high (from
   [openssf-scorecard]).
8. Treat workflow tokens without a top-level read-only permissions block as
   medium (from [openssf-scorecard]).
9. Run a vulnerability scan (pip-audit, osv-scanner, or equivalent) and
   report a known vulnerability as high when the vulnerable call is
   reachable from the tool's entry points, medium otherwise (from
   [openssf-scorecard], [owasp-top-ten]).
10. Report an unprotected default branch, or one that accepts pushes without
    review, as medium (from [openssf-scorecard]).
11. Report a missing SECURITY.md, a missing LICENSE, no dependency update
    tool, and no static analysis in CI each as low (from
    [openssf-scorecard]).
12. Report checked-in binaries (jars, shared objects, wheels, compiled
    Python) that have no source and build recipe in the repository as medium
    (from [openssf-scorecard]).
13. Report a Dockerfile that runs as root or uses a floating tag as low, and
    a secret in ENV, ARG, or a COPY of a credentials file as high under rule
    1 (from [owasp-top-ten]).
14. Report swallowed exceptions around downloads, verification, credential
    loading, or permission changes as low (from [owasp-top-ten]).
15. Write every finding with the file and line, the weakness class (a CWE
    id, an OWASP category, or a Scorecard check name), the severity, the
    command or observation that reproduces it, and a concrete fix. Never
    report an aggregate score (from [openssf-scorecard], [cwe-top25]).

## Where sources disagree

- Scorecard rates Dangerous-Workflow as Critical and Token-Permissions as
  High but Pinned-Dependencies only as Medium, while OWASP groups all
  pipeline and dependency integrity into one category (A08). We follow the
  Scorecard split: an unpinned action is medium and a dangerous workflow
  pattern is high, because the first needs an upstream compromise and the
  second needs only a pull request [openssf-scorecard, owasp-top-ten].
- OWASP is scoped to web applications; CWE covers all software. Most of our
  repositories are not web applications. We name findings by CWE weakness
  and use OWASP categories only for grouping, and we skip A01 and A02 unless
  the repository serves HTTP [owasp-top-ten, cwe-top25].
- Scorecard produces a weighted aggregate and then warns that the aggregate
  hides which behaviors are present. We report per-check results only
  [openssf-scorecard].

## Not covered

- Notebooks: none of the sources address executed cells committed with
  outputs, secrets printed in outputs, or notebooks as the unit of review.
- Cluster job scripts, shared filesystem permissions, and data under
  human-subject or export restrictions.
- Model weights and other pickled machine learning artifacts as a supply
  chain; the sources treat deserialization generically.
- Java and Groovy specifics: Gradle plugin resolution, Groovy script engines
  embedded in pipelines.
- The single-user threat model, where the author runs their own script on
  their own data and the "attacker" is a corrupted input file.
- Secret scanning: Scorecard has no committed-secret check; tool choice is
  left to the skill.
- License compliance beyond the presence of a license file.
- Repositories hosted outside GitHub; Scorecard's GitLab support is partial.
