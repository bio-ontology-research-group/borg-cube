---
name: lecture-design
description: Plans one class session as a file with outcomes in observable Bloom verbs, pre-class work, active learning segments, formative checks, and a minute budget that no stretch of talking is allowed to eat. Use when asked to "plan tomorrow's lecture", "design session 8", "write the learning outcomes for this class", "make this lecture active", "flip this session", "add clicker or peer instruction questions", "my lecture runs over", "where are the checks in this class", or when a course-design week plan needs its sessions built. Lecturer role; the slide style stays with the presentation skill, and nothing here is sent to students without approval.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads and writes only the plan files given on the command line; no network.
metadata:
  borg-role: lecturer
  grounding: ambrose-how-learning-works, anderson-krathwohl2001, angelo-cross-classroom-assessment, biggs-tang-teaching-for-quality-learning, biggs1996, brown-wilson2018, carpentries-instructor-training, cast-udl, crouch-mazur2001, deslauriers2019, dunlosky2013, fink2003-self-directed-guide, fink2013, freeman2014, garcia2020, kaust-registrar-program-guide, make-it-stick, mayer-moreno2003, mayer-multimedia-learning, nap2012-dber, nap2015-reaching-students, nap2018-how-people-learn-ii, nilson-specifications-grading, nilson-teaching-at-its-best, pavelin2014, theobald2020, via2011, wieman2014, wiggins-mctighe-ubd, wilson-teaching-tech-together
  hermes:
    category: teaching
    tags: lecture, outcomes, bloom, active-learning, formative-assessment, timebox
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Lecture design

A session is designed as a plan file, not as a deck. The plan states what
students will be able to do, what evidence the session itself will produce that
they can do it, and where every minute goes.
`scripts/outcome_lint.py` refuses outcomes that name nothing observable and
refuses an outcome that no activity practises or no check evidences;
`scripts/timebox.py` lays the segments on the clock and flags the stretches of
talking, the missing break and the gaps between checks. Slides come after the
plan passes, and their style belongs to the presentation skill.

## When to use

- A session of a course has to be planned, or an existing lecture has to be turned into an active one.
- The course-design skill produced a week plan and each week needs its sessions.
- Outcomes have to be written or rewritten for a session, a module or a syllabus entry.
- A session ran over, ran dead, or the exam showed that an outcome was never practised.
- A guest lecture, tutorial or a Carpentries-style workshop session needs a plan a colleague can teach from.

## Procedure

1. Take the frame from the course. The session's outcomes are a subset of the course outcomes in `course.yaml` (course-design skill); its prerequisites are earlier sessions. Never invent a course outcome here; if the session needs one that the course does not have, that is a course-design change and a `needs:robert` note.
2. Copy `assets/lecture-plan.yaml.example` to `plans/<course>-<session>.yaml` and fill `course`, `session`, `title`, `length_minutes`, `start`, `audience`, `prerequisites`. `audience` says how many students and what they have already done, because the plan is unusable without it.
3. Write three or four outcomes: an observable verb plus a noun plus a context, with the Bloom level and the knowledge type. `scripts/outcome_lint.py --verbs` prints the verb table; the category names (understand, know) and the vague phrases (learn about, be familiar with) are rejected because no activity or check can be aligned to them.
4. Write the checks before the activities and the activities before the exposition: for every outcome, what will you see in this session that shows the outcome was reached (`references/lecture-delivery.md`, rules 2 and 5). A check is a segment: peer instruction, poll, quiz, retrieval, code check, minute paper, muddiest point, exit ticket.
5. Design the questions. Each multiple choice question names the misconception each wrong option encodes and is pitched so that about half the class gets it right the first time; the plan records what you do for each vote outcome. Every demonstration or live run is preceded by a `prediction` segment. Code is a `live-coding` segment from a prepared skeleton, never slides of code.
6. Move first exposure out of class where students will do it: list `pre_class` items with their expected minutes and the id of the check that makes them count. `outcome_lint.py` fails a pre-class item that nothing checks.
7. Lay out the minutes and run `python3 scripts/timebox.py --plan plans/<course>-<session>.yaml`. Fix the flags: break the long stretches of instruction with an activity, put the break in, close the gaps between checks, and make the total match the class length. Add the `contingency`: the segment you drop when the session runs late, which is never a check and never the closing.
8. Run `python3 scripts/outcome_lint.py --plan plans/<course>-<session>.yaml` and fix the errors in the plan, not in the script. Keep a warning only when it is a deliberate choice, and write the reason into the plan.
9. Only now build the material: slides through the presentation skill, an assertion-evidence outline through the talk-design skill, figures through their rules. This skill does not restate them.
10. Test the practicals before the session: every notebook, dataset and service run end to end on the room's machines, one machine per student or pair, and a fallback for anything live. The checklist is in `assets/lecture-plan-template.md`.
11. After the session, read the closing check, open the next session with the two commonest points, and write a dated line in the teaching diary. If a check showed an outcome was not reached, the fix is in the next session's plan, not in the grading.

## Hard rules

- Every outcome is an observable verb plus a noun plus a context with a stated Bloom level and knowledge type. Understand, know, learn about, be familiar with and appreciate are not outcome verbs (`references/lecture-delivery.md`, rule 1).
- Every outcome is practised by at least one activity at or above its level and evidenced by at least one formative check in the same session. An unassessed outcome fails the plan (`outcome_lint.py` exits 2).
- No stretch of direct instruction longer than the segment threshold, no session over the break threshold without a break, no gap over the check threshold between checks, an opening retrieval and a written closing check. Flagged by `timebox.py`.
- The thresholds are group choices, not findings: 15 minutes of direct instruction, 15 minutes between checks, 50 minutes to a break, 10 minutes for the opening and the closing. Their sources and the reason they are choices are in `references/lecture-delivery.md`, "Where sources disagree" and "Not covered". State the threshold whenever a flag is reported, and change it per course with the script flags rather than silently.
- Every demonstration is preceded by a recorded public prediction, and a wrong prediction is used as the next explanation, never corrected with scorn.
- Never say a task is easy, never let one student set the pace, never label a student's ability; a level describes a task (`references/learning-science.md`, rule 10).
- The plan and the material are Robert-facing until he approves them. Nothing is posted to a course channel, a mailing list or the LMS, and no student is contacted, without an approval bead. Anything about an individual student (a name in a check response, a grade, an accommodation) never enters a plan, a bead or a briefing; it is `privacy:local-only`.
- Slide and figure style is the presentation skill's; the assertion-evidence outline and the practice-talk review are the talk-design skill's; syllabus, week plan, grading and the course alignment matrix are the course-design skill's. Point at them, do not restate them.
- No invented citation in a lecture: anything cited on a slide or in a reading list is verified by DOI (literature-review `cite_check.py`) first.
- Materials are published under CC-BY with their sources in the course repository, and a PDF ships with the file it was built from (`references/course-design.md`, rule 12).

## Outputs

- `plans/<course>-<session>.yaml`: the session plan, from `assets/lecture-plan.yaml.example`.
- The timeline from `timebox.py`, pasted into the plan's commit message or the course repository, so the taught version can be compared with the planned one.
- Pre-class assignment text for the course page, held for approval before it reaches students.
- A dated teaching diary line and, when a check showed an outcome was missed, a bead against the next session.
- A `needs:robert` bead when the session needs a course outcome that `course.yaml` does not have.

## Grounding

- `references/lecture-delivery.md`: one session end to end, the observable-verb rule, the segment and check thresholds we chose, question and demonstration design, and what the sources do not cover.
- `references/learning-science.md`: retrieval practice, spacing, cognitive load, the revised Bloom taxonomy, and the multimedia principles behind the material.
- `references/teaching-practice.md`: the active learning evidence, peer instruction, live coding, worked examples, pairs, classroom assessment techniques, and how practicals are run.
- `references/course-design.md`: backward design and constructive alignment, which fix the outcomes a session inherits, and the KAUST syllabus and materials rules.

## Scripts

- `scripts/outcome_lint.py --help`: checks a plan's outcomes, alignment, pre-class work and questions; `--verbs` prints the verb table; `--json`; exits 2 on any error.
- `scripts/timebox.py --help`: minute-by-minute timeline with clock times, minutes by kind, and flags for instruction stretches, breaks, check gaps, opening and closing, total and contingency; `--json`, `--strict`.
