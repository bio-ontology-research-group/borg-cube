---
name: phd-milestones
description: Computes a KAUST student's milestone schedule (qualifier, proposal defense, dissertation or thesis defense, preparation steps, committee rules) from the start date and programme, flags milestones at risk, and scans staff.org for missing or late dates. Use when asked "when is X's proposal due", "milestone plan for a new PhD student", "which students have a milestone in the next 60 days", "check the roster for missing milestone dates", "what does the committee need to look like", or when preparing a 1:1 or a progress review. Advisor role; output is for Robert only.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads only the files given on the command line; no network.
metadata:
  borg-role: advisor
  grounding: gu2007, kaust-cemse-milestones, kaust-graduate-affairs-thesis-policy, kaust-proposal-format, kaust-registrar-program-guide, lovitts2001, marino2014, nap2018-graduate-stem, pcbi-2021-interdisciplinary-phd, pcbi-2025-msc-thesis, phillips-pugh-how-to-get-a-phd
  hermes:
    category: advising
    tags: phd, milestones, kaust, cemse, bese, advisor
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# PhD and MS milestones at KAUST

This skill turns a start date and a programme into a dated milestone plan
with the KAUST rules attached, and checks the group roster against it. The
rules live in `assets/programs.yaml`, each with the manifest id it came from
and the date it was verified against the fetched KAUST text. The evidence for
how the group supports students between milestones is in
`references/doctoral-process.md`.

## When to use

- A new student joins or transfers (MS to PhD): produce the plan for their org file.
- Before a 1:1, a progress review or a committee meeting: which milestone is next, what has to be filed, and when.
- The weekly milestones patrol or Robert asks which students are within 60 days of a deadline.
- staff.org needs a consistency check: missing start dates, proposals not recorded, graduation estimates later than the KAUST deadline.
- Someone asks what a proposal or defense committee must look like, or how many extensions are possible.

## Procedure

1. Establish the facts with sources: start date (people.yaml `start`, staff.org, or the admission letter), programme (`PhD-CS`, `PhD-Bioeng`, `MS-CS`, `MS-Bioeng`), track for MS students, milestones already passed. Do not infer a start date from a first commit or a first meeting; ask Robert.
2. Run `scripts/milestones.py --start YYYY-MM-DD --program <programme> [--track thesis|non-thesis] [--passed qualifier ...] [--today YYYY-MM-DD]`. The script picks the rule set from the start date (Fall 2023 boundary) and prints milestones, preparation steps, committee rules, the consequence of a miss, and flags.
3. When a defense or proposal date is scheduled, rerun with `--proposal-date` or `--defense-date` so the preparation steps (petition, document to committee, announcement, result form, archiving) are anchored to the real date.
4. Read `references/kaust-cemse-milestones.md` for the rule behind any line the student or Robert questions, and quote the KAUST rule briefly with its source id. Never paraphrase a deadline as certain: semester ends are approximations and the academic calendar governs.
5. For a roster check run `scripts/roster_scan.py --staff-org ~/org/staff.org --people people.yaml --programs assets/programs.yaml`. Report missing fields and flags; do not edit staff.org.
6. To record the plan in a person's org file, run `milestones.py ... --org-out ~/org/<person>.org --dry-run`, show the snippet to Robert, then rerun without `--dry-run` once approved. The script refuses when the file is open in Emacs (`#file#` or `.#file` lock).
7. For students at risk (overdue flag, due-soon flag without an artefact, more than four weeks without a meeting entry) apply the rules in `references/doctoral-process.md`: check structure and integration before ability, and raise a `needs:robert` bead with the evidence lines.

## Hard rules

- Robert-facing only. Never send a plan, a flag or a risk to a student; the advisor role has no outbound grant (ADR-0009).
- Every date in an output names its rule id and source; rules with `verified_on: null` print `[unverified]` and are not presented as KAUST fact.
- Programme rules change only in `assets/programs.yaml`, with source id and verified-on date, after Robert approves the diff against the re-fetched KAUST page. The script never hard-codes a deadline.
- Semesters are counted as Fall and Spring for students who started in Fall 2023 or later, and as Fall, Spring and Summer for earlier starters; the output states which counting applies.
- Milestone status is privacy class `internal`; assessments of a student's progress are `local-only` and go to `briefings/students/`, never to a shared channel.
- Do not import `cube/milestones/kaust_rules.py`; this script stands alone so that Hermes can run it in a sanitised environment.
- Never write to an org file that has an Emacs lock, and never without a dry run shown first.

## Outputs

- Text plan (default) or `--json` for the patrols: milestones with `deadline`, `days_left`, `status` (upcoming, due-soon, overdue, passed), `sources`, `verified_on`; preparation steps; committee table; flags.
- Org snippet (`--org-out`): `* Milestones (...)` heading with `- [ ]` items and active timestamps, appended newest-last under the person's file for Robert to move.
- Roster report (`roster_scan.py`): per person the dates found, fields missing for their section, and flags such as a stated graduation after the computed degree deadline.

## Grounding

- `references/kaust-cemse-milestones.md`: KAUST and CEMSE rules for qualifier, proposal, defense, committees, extensions and time limits, by rule set and programme.
- `references/doctoral-process.md`: what the literature says about finishing a doctorate and supervising it, and the group's rules for plans, meetings and flags.

## Scripts

- `scripts/milestones.py --help`: plan from start date and programme; `--org-out` writes only without `--dry-run` and only when no lock exists.
- `scripts/roster_scan.py --help`: parse staff.org, cross-check with people.yaml and programs.yaml; read-only.
