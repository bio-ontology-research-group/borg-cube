---
name: course-design
description: Designs or redesigns a KAUST graduate course by backward design, from situational factors and learning outcomes with Bloom levels through assessments with specifications and weights, activities, a constructive-alignment matrix that fails on any unassessed outcome, a week plan, a KAUST-shaped syllabus in Markdown, Org and PDF, and FAIR course materials. Use when asked to "design a course", "plan the syllabus for", "write learning outcomes for CS 3xx", "check that every outcome is assessed", "alignment matrix", "build the syllabus", "set up the week plan", "grading scheme with specifications", "make the course materials FAIR", or before a new teaching semester. Lecturer role; the design record is a YAML file and nothing is published or submitted to the registrar without Robert's approval.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; pandoc with a LaTeX engine, or latexmk, for PDF output (optional, degrades to Markdown and Org); no network.
metadata:
  borg-role: lecturer
  grounding: ambrose-how-learning-works, anderson-krathwohl2001, angelo-cross-classroom-assessment, biggs-tang-teaching-for-quality-learning, biggs1996, brown-wilson2018, carpentries-instructor-training, cast-udl, crouch-mazur2001, deslauriers2019, dunlosky2013, fink2003-self-directed-guide, fink2013, freeman2014, garcia2020, kaust-registrar-program-guide, make-it-stick, mayer-moreno2003, mayer-multimedia-learning, nap2012-dber, nap2015-reaching-students, nap2018-how-people-learn-ii, nilson-specifications-grading, nilson-teaching-at-its-best, pavelin2014, theobald2020, via2011, wieman2014, wiggins-mctighe-ubd, wilson-teaching-tech-together
  hermes:
    category: teaching
    tags: course-design, syllabus, learning-outcomes, alignment, assessment, fair, kaust
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(pandoc *) Bash(latexmk *)
---

# Course design

A course is designed backward from what students should be able to do, and
the design lives in one YAML record (`references/course-yaml.md`,
`assets/course.yaml.example`). `scripts/alignment_matrix.py` renders the
constructive-alignment matrix and refuses a design in which an outcome is
never assessed, an assessment tests nothing declared, an activity practises
below the level it serves, or the weights do not sum to 100.
`scripts/syllabus_build.py` renders the same record into a KAUST-shaped
syllabus. The evidence behind the procedure is in the three synced
references; the record format is in the fourth.

## When to use

- A new course, or a course Robert will teach again next semester and wants to revise.
- A `kind:course` bead names a course code and a semester.
- Someone asks for learning outcomes, an assessment scheme, a week plan or a syllabus.
- The lecture-design skill needs a course record to build sessions from.
- Course materials are to be released or reused and must be FAIR.

## Procedure

1. Situational factors first (`references/course-design.md`, integrated design). Record in `course:` the level (200 or 300), credits, semester, meeting pattern, expected class size and prior knowledge, whether the course is core for a program (core courses run once a year), and what the department or program expects. Read the program guide rules that apply (B- minimum for credit, 300-level grades and the CS qualifier). Ask Robert for anything missing; never infer a course number or a meeting pattern.
2. Outcomes. Ask what should distinguish a student two years after the course. Write six to eight outcomes as verb plus noun plus context, each with a Bloom `level`, a `knowledge` type and a Fink `kind`. Cover more than remember and understand, and more than one kind of significant learning. Add `essential_questions` and `not_covered`.
3. Assessments before activities. For each outcome decide what evidence would show it was reached. Prefer forward-looking tasks (real data, real audience) graded pass or fail against a `specification` (copy `assets/specification-template.md`); keep points and a rubric for exams. Set `weight`s to mirror importance; they must sum to 100. Write the `grading` block: scheme, letter scale placeholder, bundle-to-grade mapping, token rule.
4. Activities. For each outcome list the activities in which students perform the outcome verb at that level or above, with `setting` and `weeks`. Every one to three week block mixes information (out of class), experience (labs, peer instruction, workshops) and reflection (minute papers, clinics). Apply `references/teaching-practice.md` for the session-level choices and `references/learning-science.md` for retrieval, spacing and load.
5. Check alignment: `python3 scripts/alignment_matrix.py --course state/courses/<code>.yaml`. Fix the design, never the script, until it exits 0. Read every warning: an outcome with no activity, an assessment below its outcome's level, a graded task due before any practice, all outcomes at low levels.
6. Week plan. Four to seven major topics across the semester, assignments growing in complexity, a background probe in week one, a low-stakes version of each assessment type before the graded one, mid-semester feedback, cumulative quizzes. Fill `weeks:` and rerun the check.
7. Debug the design: hours of out-of-class work per week, lab machines and software, dataset access, a fallback for each live service, TA load. Record fixes in the YAML comments or a `kind:course` bead.
8. Build the syllabus: `python3 scripts/syllabus_build.py --course state/courses/<code>.yaml --out runs/<code> --formats md,org,pdf`. The script refuses to build when the alignment check fails. Read the Markdown against the checklist in `references/course-design.md` (rules 11 and 14). Writing outside the repo needs `--apply`.
9. FAIR release. Fill the `fair` block (license, repository, citation, identifier, keywords, last revision). Materials are editable sources under version control; PDFs ship with sources; student work, grades and recordings never enter the shared repository.
10. Hand off. The course record feeds the lecture-design skill (sessions, pre-class work, formative checks) and the presentation skill (decks). Open a `needs:robert` bead with the syllabus path for approval before anything is sent to students, the program or the registrar.

## Hard rules

- No outbound contact: the skill never sends the syllabus to students, the program, the registrar or a channel. Robert approves and sends.
- No guessing: course number, credits, meeting pattern, room, grading scale and policy text come from Robert or the registrar's pages and are marked "confirm" until they do. `alignment_matrix.py` exits 2 rather than infer a level.
- Every outcome is assessed and practised; every assessment tests a declared outcome; weights sum to 100. Enforced by `alignment_matrix.py`; `syllabus_build.py` will not build a failing design without `--skip-alignment`, and a draft built that way is never published.
- KAUST rules are quoted short with the manifest id; the program guide is never republished. The grading policy page was not fetched, so the letter scale is a placeholder Robert confirms each semester.
- Grades, individual student data and class recordings never enter the course record, the repository or a bead. The record itself is `privacy:internal`.
- Materials are CC-BY unless Robert decides otherwise, in an editable format, with a citation and a dated revision.
- House style in every generated document: no em-dashes, sentence-case headings, plain language.

## Outputs

- `state/courses/<code>.yaml`: the course record (outcomes, assessments, activities, weeks, policies, FAIR block).
- Alignment matrix (Markdown or `--json`) with findings; exit 2 on a design error.
- `runs/<code>/<code>-syllabus.md`, `.org` and, when pandoc or latexmk is available, `.pdf`.
- Specification sheets per graded task from `assets/specification-template.md`.
- A `needs:robert` bead for approval and a `kind:course` bead per open design problem.

## Grounding

- `references/course-design.md`: backward and integrated design, constructive alignment, outcome verbs, educative assessment and specifications grading, structure and week plan, syllabus contents, FAIR and accessible materials, KAUST course rules.
- `references/teaching-practice.md`: evidence for active learning, peer instruction, prediction, live coding, formative checks, motivation and inclusion, running practicals and workshops.
- `references/learning-science.md`: memory and retrieval, spacing and interleaving, which study techniques work, the revised Bloom taxonomy, multimedia and cognitive load, motivation.
- `references/course-yaml.md`: the record format that the two scripts read.

## Scripts

- `scripts/alignment_matrix.py --help`: course YAML to alignment matrix and findings; `--json`; `--strict` turns warnings into errors; exit 2 on unassessed outcomes, orphan assessments, under-level activities, weights not 100, unknown levels.
- `scripts/syllabus_build.py --help`: course YAML to Markdown, Org and PDF syllabus from `assets/syllabus-template.md`; runs the alignment check first; stdout without `--out`; dry run outside the repository unless `--apply`; says clearly when PDF tooling is missing.
