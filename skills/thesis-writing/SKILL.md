---
name: thesis-writing
description: >-
  Prepares Robert-facing thesis plans for KAUST PhD and thesis-track MS students: a
  defensible outline, chapter-to-paper map, format checklist, backward defense schedule,
  and structural chapter review. Use when asked "plan my thesis", "make a thesis outline",
  "map chapters to papers", "when should I send my thesis to the committee", "prepare for a
  defense", "check this thesis chapter", or "KAUST thesis format". Advisor role. It prepares
  material for the student's supervisor and never contacts the student.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; no network. The bundled rules are a dated local snapshot, not a substitute for the current KAUST Academic Calendar or Thesis and Dissertation Guidelines.
metadata:
  borg-role: advisor
  grounding: bourne2007-oral, dunleavy2003, evans-gruba-zobel-better-thesis, kaust-cemse-milestones, kaust-graduate-affairs-thesis-policy, kaust-registrar-program-guide, marino2014, mensh2017, naegle2021, pcbi-2025-msc-thesis, phillips-pugh-how-to-get-a-phd, zobel-writing-for-computer-science, zhang2014
  hermes:
    category: advising
    tags: thesis, dissertation, defense, outline, chapter, KAUST, local-only
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Thesis writing

This skill turns a thesis into a bounded argument with visible evidence and a
schedule that protects the committee-reading window. It is Robert-facing:
prepare an outline, map, timeline, or chapter report for the supervisor to
review. Do not email, message, submit, book a defense, or otherwise contact a
student, committee member, KAUST office, or other third party.

## Procedure

1. Establish the scope with Robert: degree programme, intended defense date,
   committee size and status, target papers, and the latest official Academic
   Calendar deadlines. Treat a missing paper, result, or committee approval as
   a risk to describe, not a fact to fill in.
2. Build the argument before the table of contents. State one thesis-level
   contribution, the question or claim each chapter makes, the evidence that
   supports it, and the reader who needs it. Put background and related work
   where they make the argument intelligible, not where the work happened in
   time (`references/thesis-writing.md`).
3. Start from `assets/chapter-map.yaml.example`. Map each chapter to a paper
   or name it as synthesis, methods, introduction, or conclusion. Record a
   status, the chapter's claim, evidence, and the next review. Do not turn a
   paper verbatim into a chapter: make its role in the thesis argument clear.
4. Produce the backward plan with the current local rule snapshot:

   ```text
   python3 scripts/thesis_timeline.py --defense YYYY-MM-DD --programme phd --committee-size 4
   ```

   Give `--registrar-deadline YYYY-MM-DD` and `--dean-deadline YYYY-MM-DD`
   when Robert has the current calendar or approval date. Use `--json` for a
   machine-readable plan. Read every source and verified-on field in the
   output. The script refuses a past or already-unachievable defense date and
   an invalid committee size.
5. Check the actual KAUST template and guidelines supplied for this student.
   Verify title-page, front-matter, citation, figure, accessibility, deposit,
   and format requirements against that version. The skill does not reproduce
   a proprietary template or infer a rule from a past thesis.
6. Run the structural pass before Robert reads a chapter:

   ```text
   python3 scripts/chapter_lint.py path/to/chapter.tex
   python3 scripts/chapter_lint.py path/to/chapter.md --json
   ```

   Correct errors, then ask Robert to judge argument quality and disciplinary
   adequacy. The linter checks only observable structural signals; a clean
   result is not a scientific or formatting approval.
7. Prepare defense practice as a separate activity. Make one audience-led
   story, rehearse questions about contribution, methods, limitations, and
   implications, and revise from observed confusion. Robert decides when the
   material is ready to share.

## KAUST rule handling

- Every KAUST date or rule used here must name its guideline source and a
  `verified_on` date. Read both fields from
  `assets/defense-timeline.yaml` and copy them into any supervisor-facing
  plan.
- Never infer a KAUST deadline. A deadline that only the Academic Calendar can
  supply is emitted as `needs-calendar`; obtain it from Robert or the current
  official record before acting on it.
- The six-week committee-delivery rule is enforced by the local rule snapshot.
  Reverify it and all template requirements against the current KAUST Thesis
  and Dissertation Guidelines before Robert relies on a plan.
- The timeline is a preparation aid, not a petition, approval, submission, or
  booking. The supervisor retains all decisions and any external action needs
  the repository approval gate.

## Hard rules

- Keep student drafts, assessments, committee discussions, and schedules
  local-only. Report to Robert only.
- Make a thesis a connected argument, not a chronological laboratory log or a
  stack of papers. Every chapter states its contribution and evidence.
- Distinguish official dates from internal writing targets. Internal targets
  may be moved by Robert; official dates may only be changed from a newly
  verified KAUST source.
- Preserve provenance: cite the source of every external claim, identify the
  rule snapshot version, and say when a calendar date or template is missing.
- Do not copy a paper's text into a thesis plan, reproduce proprietary KAUST
  material, or fabricate a citation, deadline, committee approval, or paper
  status.

## Outputs

- A Robert-facing outline with thesis contribution, chapter claims, evidence,
  chapter dependencies, and open risks.
- A chapter-to-paper map based on `assets/chapter-map.yaml.example`.
- A dated defense timeline with the source and verification date for every
  official rule, plus clearly labeled internal draft and revision targets.
- A chapter-lint report with file:line, severity, and a concrete fix.

## Grounding

- `references/thesis-writing.md`: planning, argument, chapter structure,
  defense preparation, and the local KAUST rule boundary.

## Scripts

- `scripts/thesis_timeline.py --help`: build a defense-centered schedule;
  `--json` emits the same source-bearing records.
- `scripts/chapter_lint.py --help`: check a LaTeX or Markdown chapter and
  return file:line findings; it exits 1 when errors are present.
