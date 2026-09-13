# Playbook: code audit

When: the Monday repos patrol proposes candidates (idle repositories with
open issues, missing licence or citation, no CI), or Robert names a repo.
At most three audits dispatched per week. Roles: auditor, senior (review),
programmer (fixes).

1. Collect: `scripts/audit_collect.py` on a fresh clone under `runs/<id>/repo`
   gathers facts: README, LICENSE, CITATION.cff, CI config, tests-to-code
   ratio, pinned dependencies, Dockerfile, secrets regex hits, notebook
   outputs committed, last commit date, open issues via `gh`. Deterministic,
   no LLM.
2. Judge: `cube run auditor --bead <id>` applies `rubrics/code-audit.md`.
   Every finding is file:line or a command output, with severity and a
   concrete fix.
3. Escalate: high severity (committed secret, data-loss path, licence
   violation) becomes `needs:robert` immediately.
4. Propose: fixes grouped into `stage:design` beads with acceptance
   criteria; the senior specifies; the programmer implements in a worktree;
   the senior reviews.
5. Deliver: PR text is a `kind:outbound` bead; Robert approves before any
   push or PR. Student repositories: the report goes to Robert only.

Never: modify the audited repository during the audit; open an issue or PR
without approval; report a finding you cannot point to.
