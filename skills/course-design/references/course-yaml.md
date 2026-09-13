# The course YAML record

Sources
- fink2003-self-directed-guide (proprietary guide, fetched; summary only)
- biggs-tang-teaching-for-quality-learning (book, proprietary; ideas from corpus/notes)
- anderson-krathwohl2001 (book, proprietary; ideas from corpus/notes)
- nilson-specifications-grading (book, proprietary; ideas from corpus/notes)
- garcia2020 (CC-BY-4.0; short excerpts allowed)
- kaust-registrar-program-guide (KAUST page; quote rules short, never republish)

## Why one file

The record mirrors Fink's integration worksheet: every goal with the
assessment that would show it was reached and the activity that leads to it
[fink2003-self-directed-guide]. Putting outcomes, assessments, activities and
the week plan in one file lets `alignment_matrix.py` check the connections
Biggs calls constructive alignment [biggs-tang-teaching-for-quality-learning]
and lets `syllabus_build.py` render the syllabus from the same facts, so the
syllabus can never drift from the design. The file lives in
`state/courses/<code>.yaml` (gitignored) or in the course's own repository;
`assets/course.yaml.example` is a complete example.

## Top-level keys

- `course`: identity, situation and policies (below).
- `outcomes`: list of intended learning outcomes.
- `assessments`: graded tasks with weights.
- `activities`: teaching and learning activities.
- `weeks`: the week plan.

Ids are unique across outcomes, assessments and activities (`O1`, `E2`, `T3`
by convention). Bloom levels are `remember`, `understand`, `apply`,
`analyze`, `evaluate`, `create`; common synonyms are accepted, anything else
is an error because the script does not guess [anderson-krathwohl2001].

## course

Required for a KAUST syllabus: `code`, `title`, `credits`, `level` (200 or
300), `semester`, `weeks`, `meetings`, `instructor` (name, email, office,
office_hours), `prerequisites`, `target_audience`, `description`. Recommended:
`not_covered` (what the course will not teach), `essential_questions`,
`materials`, `policies` (attendance, integrity, late_work, accommodation,
ai_use, communication), `grading` (scheme, minimum_for_credit, scale,
bundles), `evaluation_plan`, `fair` (license, repository, citation,
identifier, keywords, last_revision) [garcia2020]. The program guide's rules
that matter here: a B- is the minimum for course credit, courses carry 3
credits, and 300-level grades can count toward the CS qualifier
[kaust-registrar-program-guide].

## outcomes

Each outcome has `id`, `text` (verb plus noun plus context), `level` (Bloom),
optional `knowledge` (factual, conceptual, procedural, metacognitive) and
optional `kind` (Fink's kinds: foundational, application, integration, human,
caring, learning-how-to-learn) [anderson-krathwohl2001,
fink2003-self-directed-guide].

## assessments

Each has `id`, `title`, `kind`, `level`, `tests` (outcome ids), `weight`
(percent; all weights sum to 100), `week` (due), `grading` (`points` or
`specifications`) and, for specification-graded work, `specification` (the
pass checklist) [nilson-specifications-grading].

## activities

Each has `id`, `title`, `kind` (lecture, peer-instruction, lab, reading,
discussion, workshop, clinic), `level` (the verb students perform), `serves`
(outcome ids), `weeks` and `setting` (in-class, out-of-class, lab).

## weeks

Each has `week`, `topic`, `activities` (ids), optional `reading` and `due`
(assessment ids). The plan is where the check that practice precedes
assessment runs.

## Rules we adopt

1. The record is written before any slide or lab, and the alignment check
   passes before the syllabus is built (from [fink2003-self-directed-guide],
   [biggs-tang-teaching-for-quality-learning]).
2. Levels are never inferred from the outcome text by the script; the
   designer states them and the reviewer checks them (from
   [anderson-krathwohl2001]).
3. Specification checklists live in the record so the syllabus, the task
   sheet and the grader see the same items (from
   [nilson-specifications-grading]).
4. The `fair` block is filled before release, with the source files under
   version control and a dated revision (from [garcia2020]).
