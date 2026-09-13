---
name: code-audit
description: Audits a software repository in two passes, deterministic fact collection (README, LICENSE, CITATION.cff, CI, tests ratio, pinned dependencies, Dockerfile, secrets, risky calls, notebook outputs, last commit, open issues) and then judgement, producing findings with file:line, severity and a concrete fix, plus a fix list as beads. Use when asked to "audit this repo", "review the code quality of", "is this software ready to publish or cite", "check the repository for secrets", "JOSS readiness", "FAIR4RS check", or when the weekly repos patrol proposes an audit candidate. Auditor role; read-only on the repository; findings about a student's repository go to Robert only.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12, PyYAML and git; gh optional for open issues; reads only the checkout given; never modifies the repository; no network unless --gh.
metadata:
  borg-role: auditor
  grounding: balaban2021, brack2022, citation-file-format, cwe-top25, fair4rs2022, google-code-review, google-small-cls, hunter-zinck2021, jimenez2017, joss-docs, joss-review-checklist, joss-review-criteria, lee2018-documenting, list2017, nust2020, openssf-scorecard, osborne2014, owasp-top-ten, romano2020, sholler2019, smith2016-software-citation, taschuk-wilson2017, turing-way, wilson2014, wilson2017
  hermes:
    category: software
    tags: audit, code-quality, security, fair4rs, joss, research-software
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git *) Bash(gh repo view *) Bash(gh issue list *)
---

# Code audit

Pass one is a script: `audit_collect.py` records facts with file paths and
line numbers and never judges. Pass two is judgement: `audit_report.py` maps
facts to findings with a severity from `assets/severity-scale.md`, a fix and
the corpus ids behind the rule, and the auditor then reads the code behind
each finding, adds what the collector cannot see (design, correctness, naming,
documentation quality) and writes the Judgement section. The evidence is in
the four references: research software practice, FAIR4RS and JOSS, security
basics, and how to write review findings.

## When to use

- A `kind:audit` bead names a repository (fresh clone under `runs/<id>/repo`).
- Software is about to be cited in a paper, released, or submitted to JOSS.
- The Monday repos patrol proposes audit candidates (at most three per week).
- Robert asks whether a repository is in a state to hand to a new student or collaborator.

## Procedure

1. Confirm the target: repository path (a clone, never the working copy someone is editing), whether a paper cites it (`--published`), and who owns it. If the owner is a student, the report is Robert-only.
2. Collect: `scripts/audit_collect.py --repo runs/<id>/repo --out runs/<id>/facts.json` (add `--gh` when GitHub may be queried). Read the JSON: every fact has a path, and secrets are redacted.
3. Derive: `scripts/audit_report.py --facts runs/<id>/facts.json --out runs/<id>/audit.md --beads runs/<id>/fixes.json [--published]` prints the report; add `--apply` to write it and the fix list. Severities follow `assets/severity-scale.md`.
4. Judge: open every high and medium finding at its file:line. Downgrade to info with the reason when the pattern is safe in context (a constant argument to `subprocess`, a test fixture). Add findings the collector cannot see, each with file:line, severity, fix and the reference it rests on (`references/research-software-practice.md` rules, `references/fair4rs-and-joss.md` checks, `references/security-basics.md` rules). Write the Judgement section: is the software reusable by a stranger, reproducible, citable, safe to run?
5. Apply the review standard from `references/code-review-practice.md`: every finding actionable and courteous, blockers separated from nits, the overall verdict stated (ready, ready after the high findings, not ready).
6. Hand the fix list to the delegation skill: `runs/<id>/fixes.json` is shaped for `beads_from_plan.py`; each bead's acceptance criterion is that the finding disappears on a rerun.
7. Secrets or credentials in history: stop, report the file and line to Robert as `needs:robert`, do not rotate, delete or notify anyone.

## Hard rules

- Read-only. The auditor never modifies, commits to, or opens issues or pull requests on the audited repository; fixes are beads for the programmer role after review.
- Every finding cites file:line or the exact command whose output is the evidence. A finding without a location is not written.
- One severity per finding, assigned by the auditor, never by the author; the scale is `assets/severity-scale.md`.
- Findings about a student's repository go to Robert only; nothing is posted to a channel or sent to the student (ADR-0009).
- Secrets are redacted in facts and reports; the value never appears in a bead, a briefing or a chat.
- No fabricated facts: if `gh` is unavailable or a check could not run, the report says so under Not checked.
- Read the fetched sources when a rule is questioned; quote a rule short with its corpus id rather than paraphrasing it as the auditor's opinion.

## Outputs

- `runs/<id>/facts.json`: deterministic facts (git, docs, tests, CI, dependencies, docker, secrets, risky calls, files, issues) with `checks_version`.
- `runs/<id>/audit.md`: report from `assets/code-audit-report.md` with findings by severity, checks passed, not checked, fix list and Judgement.
- `runs/<id>/fixes.json`: fix list as beads for the delegation skill (`review_by: senior`).
- `needs:robert` bead for any secret or high-severity data-loss finding.

## Grounding

- `references/research-software-practice.md`: auditable practices (version control, tests and CI, documentation, dependencies and containers, licensing and citation, usability, robustness, project layout) and when quick-and-dirty code is acceptable.
- `references/fair4rs-and-joss.md`: FAIR4RS principles, JOSS submission requirements and reviewer checklist, software citation and CITATION.cff.
- `references/security-basics.md`: OWASP and CWE categories relevant to research code, OpenSSF Scorecard checks, severity scale and security rules.
- `references/code-review-practice.md`: how findings are written (location, problem, severity, fix), small changes, reviewer not the author.

## Scripts

- `scripts/audit_collect.py --help`: repository to facts JSON; read-only; `--gh` optional.
- `scripts/audit_report.py --help`: facts to findings, report and fix-list beads; `--published` raises test and documentation gaps; dry run unless `--apply`.
