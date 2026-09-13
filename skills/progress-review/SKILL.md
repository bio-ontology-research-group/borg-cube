---
name: progress-review
description: Builds a Robert-only progress review for a PhD or MS student from evidence (commits per repository, dated org meeting entries, draft word counts) against the group rubric and the student's milestones, with every score tied to an evidence id. Use when asked "how is X doing", "progress review for X", "prepare the semester evaluation", "evidence since the last 1:1", "what has X produced since August", "weekly student digest", or before a committee or progress form. Advisor role; never contacts the student; the report is privacy local-only.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12, PyYAML and git on PATH; reads only the repositories, org files and drafts listed in students.yaml; no network.
metadata:
  borg-role: advisor
  grounding: anderson-krathwohl2001, crossley2025, delamont-supervising-the-doctorate, google-small-cls, grove-high-output-management, gu2007, kaust-cemse-milestones, kaust-registrar-program-guide, lovitts2001, maestre2019, marino2014, nap2018-graduate-stem, nap2019-mentorship, pcbi-2023-lab-information, sandve2013, schnell2015, schwab2022, sutherland2013, vitae-rdf, wilson2017, wisker-good-supervisor
  hermes:
    category: advising
    tags: progress, evidence, rubric, students, advisor, local-only
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git log *)
---

# Progress review

A progress review is an evidence table plus a rubric plus a conversation
plan. `scripts/collect_evidence.py` gathers the evidence and gives each item an
id; the agent (or Robert) scores the seven rubric dimensions in a small YAML
file, citing those ids; `scripts/rubric_report.py` renders the report and
refuses any score without evidence. The rubric is
`brain/rubrics/progress-assessment.md`; the evidence for how to read the
evidence is in the three references below.

## When to use

- The weekly student digest (Robert-facing patrol) or a "how is X doing" question.
- Before a 1:1 that is meant to review progress rather than solve a problem.
- Before a semester evaluation, a committee meeting, a progress form or a contract decision.
- When a milestone flag from phd-milestones needs the artefact evidence behind it.

## Procedure

1. Facts first. Confirm the student's id, programme and start date in `state/students.yaml` (copy `assets/students.yaml.example`; the file is gitignored). Never infer a start date from a first commit. Ask Robert for anything missing.
2. Choose the window: since the last review or the last dated meeting entry; default 28 days for a digest, one semester for an evaluation.
3. Collect: `python3 scripts/collect_evidence.py --students state/students.yaml --student <id> --since YYYY-MM-DD --out runs/<id>/evidence.json`. Read the `gaps` list before anything else: a missing repository or org file is a collection problem, not a student problem.
4. Read the evidence, not the counts. Open the commit subjects and the diff of the largest change; read the dated org entries; open the drafts that changed. Commit counts, lines and word counts are pointers to what to read, never scores (`references/evidence-collection.md`).
5. Score with `python3 scripts/rubric_report.py --example > runs/<id>/scores.yaml` as the starting point. For every dimension write a score of 1 to 5 with the evidence ids that justify it, or `no evidence`. Descriptors per level are in `brain/rubrics/progress-assessment.md` and `references/progress-rubric.md`. Milestone standing takes its dates from `skills/phd-milestones/scripts/milestones.py`, never from memory.
6. Before finalising, run the bias checks in `references/avoiding-bias.md`: is a low score explained by structure (meeting frequency, plan clarity, blocked resources) before ability; is a score driven by the most recent week; would the same evidence get the same score for another student; does any note state a reason the student did not state.
7. Render: `python3 scripts/rubric_report.py --evidence runs/<id>/evidence.json --scores runs/<id>/scores.yaml --student <id>` and read the flags. Then `--out briefings/students/<date>-<id>.md`. The script exits 2 if a score lacks an evidence id or cites an unknown id; fix the scores, not the script.
8. Turn the review into a conversation: two or three agenda points and questions that test understanding (mentoring-session skill), not a verdict. For a semester evaluation, fill `assets/semester-evaluation.org` from the report; Robert transfers the text to the KAUST form himself.
9. If the evidence shows a blocker, a wellbeing signal, or a milestone under 90 days without an artefact, open a `needs:robert` bead quoting the evidence line and id.

## Hard rules

- Never contacts the student. Robert-facing unless a `contacts.yaml` grant exists for the person, channel and action class; even then, scores and assessments are never delivered to a student (ADR-0009).
- Every score or claim cites evidence: an evidence id from `collect_evidence.py` or a path with a locator. `rubric_report.py` enforces this; a dimension without evidence is `no evidence`, never a low score.
- No invented references: any literature cited in a report is verified by DOI (literature-review `cite_check.py`) before it appears.
- Never rank students against each other, never compare two students in one report, never infer a reason (health, motivation, family) the student did not state.
- Grades, GPA, contracts, visas, HR and health never enter the evidence file, the report or a bead. Reports are `privacy:local-only`, written to `briefings/students/`, and any model call over them uses the local tier.
- Reads only what `students.yaml` lists. No scanning of home directories, mail or chat for extra evidence.
- Thresholds (21 days stale, 90 days milestone) are group choices (`references/progress-rubric.md`, Not covered); state them in the report rather than presenting them as findings.

## Outputs

- `runs/<id>/evidence.json`: evidence with stable ids, per-repository stats, dated org headings with open items, draft word counts, gaps.
- `runs/<id>/scores.yaml`: the scored rubric with evidence ids and notes.
- `briefings/students/<date>-<id>.md`: the rendered report (evidence table, scores, flags, agenda, reviewer notes) from `assets/progress-report.md`.
- `assets/semester-evaluation.org` filled per student per semester, for Robert's records and the KAUST form.
- `needs:robert` beads for blockers and milestone flags, each quoting an evidence id.

## Grounding

- `references/progress-rubric.md`: the seven dimensions, level descriptors, Bloom verbs for judging reasoning, institutional criteria, and the thresholds we chose.
- `references/evidence-collection.md`: what counts as evidence of progress, which numbers mislead, lab notebook and reproducibility rules that make evidence readable.
- `references/avoiding-bias.md`: how supervisors misjudge students (deficit model, recency, similarity, base rates) and the checks we run before a score stands.

## Scripts

- `scripts/collect_evidence.py --help`: evidence JSON or Markdown from git, org and drafts for the students in a YAML mapping; read-only.
- `scripts/rubric_report.py --help`: renders `assets/progress-report.md`; exits 2 on any score without an evidence id; prints to stdout unless `--out`.
