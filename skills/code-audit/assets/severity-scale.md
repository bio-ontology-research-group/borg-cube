# Severity scale for audit findings

Every finding carries exactly one label. The auditor assigns it, never the
author. The scale follows `references/security-basics.md` (rules section,
"Severity scale") and applies to non-security findings by analogy: how much
does the gap cost the next user, reader or maintainer of the code?

| Label | Definition | Time to fix | Examples |
| --- | --- | --- | --- |
| high | A malicious input or compromised source can run code or reach files outside the intended ones; a live credential is exposed; or the software cannot legally or practically be reused (no license, no README, cited software with no tests) | before merge, release or citation; blocks | secret in history; `eval` on user input; `shell=True` with a path from the command line; no LICENSE; dangerous workflow trigger |
| medium | Exploitation needs a second condition, or a control that Scorecard rates High or Critical is missing, or a reader cannot install or run the software from what is provided | within the current work cycle | unpinned dependencies with no lock file; GitHub Action pinned to a branch; `pickle.load` of a downloaded file; no CI; README without installation steps; Dockerfile `FROM x:latest` |
| low | Hygiene: a missing policy or metadata file, weak documentation of an existing practice, tooling gaps | record and schedule | no SECURITY.md, CONTRIBUTING or CITATION.cff; notebook outputs committed; low test ratio; no release tag; container runs as root |
| info | An observation with no fix required, or a risky pattern that is safe in context, with the reason written down | none | `subprocess` with a fixed argument list; large data files in a documented data directory |

## Rules

1. One label per finding; when in doubt between two, choose the higher and say why.
2. The label depends on context the collector cannot see (is the software cited in a paper? does it read untrusted input?). `audit_report.py --published` raises the test and documentation gaps of cited software; the auditor confirms the rest by reading the code at the file:line given.
3. A high finding about a secret or credential goes to Robert only (`needs:robert`); the auditor does not rotate, delete or notify anyone.
4. Findings about a student's repository are reported to Robert, never to the student directly and never in a group channel.
5. Every finding names file and line (or the exact command whose output is the evidence), states the problem in one sentence, and proposes one concrete fix.
