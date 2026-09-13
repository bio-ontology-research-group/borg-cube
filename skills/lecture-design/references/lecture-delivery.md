---
topic: lecture-delivery
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Lecture delivery

Sources
- brown-wilson2018 (CC-BY-4.0; short excerpts allowed; fetched)
- carpentries-instructor-training (CC-BY-4.0; only the index page was fetched, episodes summarised from knowledge)
- wilson-teaching-tech-together (CC-BY-NC-4.0; only the landing page was fetched, book summarised from knowledge; no quotes)
- crouch-mazur2001 (journal article, proprietary; not fetched, summarised from knowledge, medium confidence)
- anderson-krathwohl2001 (book, proprietary; cite only, ideas from corpus/notes/anderson-krathwohl2001.md)
- nilson-teaching-at-its-best (book, proprietary; no notes file yet, summarised from knowledge, medium confidence)
- angelo-cross-classroom-assessment (book, proprietary; no notes file yet, summarised from knowledge, medium confidence)
- dunlosky2013 (journal article, proprietary; not fetched, summarised from knowledge, medium confidence)
- make-it-stick (book, proprietary; no notes file yet, summarised from knowledge, medium confidence)
- deslauriers2019 (journal article, proprietary; not fetched, summarised from knowledge, medium confidence)
- ambrose-how-learning-works (book, proprietary; no notes file yet, summarised from knowledge, medium confidence)
- nap2018-how-people-learn-ii (report, proprietary; not fetched, summarised from knowledge, medium confidence)
- via2011 (CC0; short excerpts allowed)

This file covers one session: the plan for a single class hour, its outcomes,
its minute budget and the checks inside it. Course-level design is in
course-design; the learning research behind the rules is in learning-science
and teaching-practice; slide style belongs to the presentation skill.

## What the evidence says

### An outcome is a verb the student can be seen to perform

- An objective is a verb plus a noun: the verb names a cognitive process
  (remember, understand, apply, analyze, evaluate, create, each with named
  sub-processes) and the noun names a knowledge type (factual, conceptual,
  procedural, metacognitive) [anderson-krathwohl2001].
- The category names are not themselves usable as objective verbs. "Understand"
  is a category with seven sub-processes (interpreting, exemplifying,
  classifying, summarizing, inferring, comparing, explaining); an objective
  states which of them the student will perform, because only the sub-process
  can be observed and assessed [anderson-krathwohl2001].
- The commonest design fault is a mismatch between the cell of the objective
  and the cell of the activity or the assessment, for example teaching
  procedures and assessing recall [anderson-krathwohl2001].
- Classifying a plan in the table exposes gaps: a unit whose cells are all
  remember-factual has no evaluate or create work in it, and that is visible
  before the class is taught [anderson-krathwohl2001].
- Retention needs remembering; transfer to new problems needs the other five
  processes, so a session meant to transfer cannot consist of recall tasks
  [anderson-krathwohl2001].
- A cell describes a task, not a person; levels are recorded against tasks and
  never used to label a student [anderson-krathwohl2001].

### Attention, segments and breaks

- Attention and retention fall after roughly ten to fifteen minutes of
  continuous exposition, so a lecture is broken into segments of that length
  separated by an activity, and each segment is paired with a question that
  students answer [nilson-teaching-at-its-best].
- The Carpentries build a session around a formative exercise every ten to
  fifteen minutes so that both learner and instructor find out what has landed
  while there is still time to act [carpentries-instructor-training].
- Carpentries training days are themselves cut into parts with a scheduled
  break between each, and the break is where minute cards are collected
  [carpentries-instructor-training].
- Via and colleagues schedule 10 to 15 minutes of review and questions at the
  end of each module and confirm that everyone reached the result before moving
  on [via2011].
- Working memory holds few items at once, which is the reason to chunk a
  session and to give a mental model before details
  [carpentries-instructor-training, nap2018-how-people-learn-ii].

### The teaching cycle inside a session

- Peer instruction runs in phases: a brief introduction, a multiple choice
  question that probes a misconception, an individual vote, "several minutes to
  discuss those answers with one another in small groups", a second vote, and
  the instructor acting on the second result [brown-wilson2018].
- The question is calibrated: "The ideal questions are those for which 40%-60%
  of students are likely to get the right answer the first time", and every
  wrong option corresponds to a misconception some student will pick
  [brown-wilson2018].
- Acting on the result is part of the method: move on when the class is right,
  address the surviving wrong answers directly when it is not
  [brown-wilson2018].
- Peer instruction depends on the out-of-class half of the cycle: reading
  assigned before class and a short reading quiz that makes it count, so class
  time starts above recall [crouch-mazur2001].
- Ten years of peer instruction in physics report learning gains on concept
  inventories roughly double those of the lecture years [crouch-mazur2001].
- Demonstrations on their own do not improve learning and are often
  misremembered; the fix is a recorded, public prediction before the run, by
  show of hands or cue cards, and wrong predictions are used as a spur rather
  than punished [brown-wilson2018].
- Live coding replaces slides for code because the instructor can follow "what
  if" questions, works at a pace learners can follow, and shows how mistakes
  are diagnosed; boilerplate is prepared as a skeleton in advance
  [brown-wilson2018].

### Checks that produce evidence

- Classroom assessment techniques are short, ungraded and usually anonymous:
  the minute paper, the muddiest point, the background knowledge probe, the
  one-sentence summary, the application card. Their value lies in the response
  the teacher makes at the next class [angelo-cross-classroom-assessment].
- Retrieval practice and distributed practice are the two techniques rated of
  high utility; summarising, highlighting and rereading are rated low, and
  students prefer the low ones [dunlosky2013].
- Attempting an answer before being shown it (generation) and spacing the
  return to a topic are desirable difficulties: they feel worse and retain
  better, and fluency from rereading is an illusion of knowing [make-it-stick].
- Students in an active class learned more and reported feeling they learned
  less than students given a polished lecture on the same content, so the
  method is explained to them rather than assumed to feel good
  [deslauriers2019].
- Prior knowledge helps or hinders depending on what it is, so a session opens
  by surfacing it; practice needs a target, and feedback must be followed by a
  chance to act on it [ambrose-how-learning-works].
- Instructors pace by the learners' formative results rather than by the slide
  deck, and design a lesson from its exercises rather than from its material
  [wilson-teaching-tech-together].
- A session is rehearsed and reviewed like a performance, with a dated diary of
  what to change next time [wilson-teaching-tech-together,
  carpentries-instructor-training].

## Rules we adopt

1. Every outcome is written as an observable verb plus a noun plus a context,
   with its Bloom level and knowledge type stated. The category names
   understand and know, and the phrases learn about, be familiar with, be
   aware of, appreciate and gain knowledge of, are not outcome verbs; use the
   sub-process that can be observed. Checked by `outcome_lint.py`. (from
   [anderson-krathwohl2001])
2. Every outcome is practised in the session by at least one activity whose
   verb sits at or above the outcome's level, and evidenced by at least one
   formative check in the same session. An outcome with no check is an
   unassessed outcome and the plan fails. Checked by `outcome_lint.py`. (from
   [anderson-krathwohl2001], [carpentries-instructor-training])
3. A session with outcomes above remember does not consist of recall tasks; a
   plan whose activities are all at remember or understand is flagged for
   review. (from [anderson-krathwohl2001])
4. No stretch of direct instruction runs longer than the segment threshold in
   the plan (our default is 15 minutes) without an activity, and no stretch of
   class runs longer than the break threshold (our default is 50 minutes)
   without a break. Checked by `timebox.py`. (from
   [nilson-teaching-at-its-best], [carpentries-instructor-training])
5. A formative check happens at least every 15 minutes of class time, the
   session opens with retrieval of the previous session or the pre-class work,
   and it closes with a minute paper or muddiest point whose answers open the
   next session. Checked by `timebox.py`. (from
   [carpentries-instructor-training], [angelo-cross-classroom-assessment],
   [dunlosky2013], [via2011])
6. Pre-class work is named in the plan with its expected minutes and the check
   that makes it count; first exposure to definitions and notation happens
   before class so that class time starts above recall. Checked by
   `outcome_lint.py`. (from [crouch-mazur2001], [make-it-stick])
7. Every multiple choice question in a plan names the misconception each wrong
   option encodes and is pitched so that roughly half the class gets it right
   first time; the plan records what the instructor does for each vote
   outcome. (from [brown-wilson2018], [crouch-mazur2001])
8. Every demonstration, live run or plotted result is preceded by a recorded
   public prediction, and a wrong prediction is used as the next explanation,
   never corrected with scorn. (from [brown-wilson2018])
9. Code is taught by live coding from a prepared skeleton, at typing speed,
   with the finished code published after the session. (from
   [brown-wilson2018])
10. The plan carries a timing contingency: which segment is dropped when the
    session runs late. The formative checks and the closing are never the
    segments dropped. (from [wilson-teaching-tech-together], [via2011])
11. Tell students in the first session, and again when they complain, why the
    format feels harder and produces more learning. (from [deslauriers2019],
    [make-it-stick])
12. After the session, record in a dated diary what the checks revealed and
    what changes next time; the next session opens by answering the muddiest
    point. (from [wilson-teaching-tech-together],
    [angelo-cross-classroom-assessment])

## Where sources disagree

- Segment length: Nilson gives ten to fifteen minutes for a lecture segment
  [nilson-teaching-at-its-best] and the Carpentries give ten to fifteen minutes
  between formative exercises [carpentries-instructor-training], which are not
  the same interval. We treat them as two thresholds, direct instruction and
  check interval, and set both to 15 minutes so that a plan can satisfy them
  with one activity.
- What class time is for: Crouch and Mazur and Brown and Wilson move first
  exposure out of class [crouch-mazur2001, brown-wilson2018]; Via and
  colleagues assume the session itself introduces the material [via2011]. We
  assign pre-class work where the students will reliably do it and otherwise
  budget an in-class exposition segment and check it earlier.
- How students feel: Deslauriers and colleagues show active formats are rated
  lower while teaching more [deslauriers2019]; course evaluations at KAUST use
  student ratings. We keep the format and explain it, and read ratings next to
  the assessment evidence.
- Evidence base: the peer instruction and active learning results are
  undergraduate physics and undergraduate STEM [crouch-mazur2001]; the
  Carpentries and Brown and Wilson describe short workshops
  [carpentries-instructor-training, brown-wilson2018]. Our sessions are
  graduate computer science, so the thresholds are our choices informed by
  these sources, not findings transferred from them.

## Not covered

- The numeric thresholds themselves. No source gives a tested value for a
  graduate class; 15 minutes of direct instruction, 15 minutes between checks,
  50 minutes to a break and 10 minutes of closing are group choices, stated as
  defaults in the scripts so they can be changed per course and reviewed
  against what the checks show.
- Sessions that are not lectures: seminars, reading groups, project
  supervision, oral exams and lab rotations.
- Online and hybrid delivery, recording, and what the timing rules become when
  students are remote.
- Class size. The peer instruction evidence is from large classes; our courses
  are small enough that a show of hands replaces a clicker system, and no
  source tells us where that stops working.
- Language load: most students work in a second language, which the sources do
  not address beyond pre-training vocabulary.
- Nilson, Angelo and Cross, Ambrose, Make It Stick, Dunlosky, Crouch and Mazur
  and Deslauriers were not fetched and have no notes file; the claims here come
  from memory and need checking against the texts before a skill quotes them.
  Only brown-wilson2018 is quoted, and only in short excerpts.
