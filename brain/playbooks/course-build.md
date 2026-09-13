# Playbook: course build

When: a `kind:course` epic exists for a coming semester (from `~/org/cs*.org`
and research knowledge graph courses), or Robert asks. Role: lecturer.

1. Outcomes: 5 to 8 course-level outcomes with Bloom verbs, each assessable.
2. Alignment matrix: outcomes x assessments; `alignment_matrix.py` fails on any
   unassessed outcome.
3. Week plan: pre-class work, in-class active segments, formative checks;
   time-boxed with `timebox.py`.
4. Syllabus in the KAUST registrar format, generated from YAML.
5. Lecture decks: each with a storyline, statement titles, assertion-evidence
   slides, verified figure captions; the `presentation` skill is the style
   authority; `slide_lint.py` runs before review.
6. Review: group leader against `rubrics/lecture-quality.md`; Robert releases.

Never: upload to any LMS or send to students; that is Robert's action.
