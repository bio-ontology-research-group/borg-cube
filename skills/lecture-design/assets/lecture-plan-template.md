# Lecture plan template

One file per session, written before any slide. Fill the fields in this order:
outcomes, then checks, then activities, then the exposition that the checks
turned out to need. `scripts/outcome_lint.py` and `scripts/timebox.py` read the
YAML form of it (`assets/lecture-plan.yaml.example`); this file is the guide to
what belongs in each field and the checklist to run before the session.

## Fields

| Field | What goes in it |
| --- | --- |
| `course`, `session`, `title`, `date`, `start`, `room` | identity of the session; `start` is `HH:MM` and puts clock times on the timeline |
| `length_minutes` | scheduled class length; the segments must total it |
| `audience` | how many students, their programme, what they have already done |
| `prerequisites` | the earlier sessions or skills this one stands on |
| `pre_class[]` | `id`, `kind` (reading, video, notebook, warmup), `what`, `minutes`, `check` (the id of the in-class check that makes it count) |
| `outcomes[]` | `id`, `statement`, `verb`, `level`, `knowledge` |
| `segments[]` | `id`, `kind`, `minutes`, `what`, `outcomes[]`, `verb` or `level`, and `misconception` for a question |
| `contingency` | the segment to drop when the session runs late; never a check, never the closing |
| `materials`, `after` | what students get, and what the instructor does with the closing check |

## Outcomes

An outcome is an observable verb plus a noun plus a context, at one Bloom
level and one knowledge type: "Diagnose the leak in an evaluation pipeline and
name the split it needs instead" (analyze, procedural). Run
`scripts/outcome_lint.py --verbs` for the verb table. The words understand,
know, learn about, be familiar with and appreciate are not outcome verbs,
because no activity or check can be aligned to them: state the sub-process
instead (explain, interpret, classify, compare, summarize).

Three or four outcomes fit a 90-minute session. Each one needs an activity that
practises it at or above its level and a check that evidences it inside the
same session.

## Segment kinds

| Kind | Counts as | Use for |
| --- | --- | --- |
| `lecture`, `worked-example`, `recap` | direct instruction | exposition, a worked example with labelled subgoals, a recap |
| `demo` | direct instruction | a live run; must follow a `prediction` segment |
| `prediction` | activity | recorded public prediction on cards or by hands, before any demo or plotted result |
| `peer-instruction` | activity and check | question, individual vote, small-group discussion, second vote, response |
| `poll`, `quiz`, `retrieval` | activity and check | a vote, a short quiz, retrieval of the previous session or the pre-class work |
| `exercise`, `problem`, `live-coding`, `pair-programming`, `discussion`, `think-pair-share` | activity | the work students do; live coding runs from a prepared skeleton |
| `code-check`, `exit-ticket`, `minute-paper`, `muddiest-point` | activity and check | evidence the instructor reads after the segment or after class |
| `break`, `admin`, `setup` | neither | the break, and the minutes lost to logistics |

## Shape of a session

- Open with retrieval of the last session or the pre-class work in the first 10
  minutes.
- Keep any stretch of direct instruction under 15 minutes and put a check at
  most 15 minutes after the last one.
- Put a break in a session longer than 50 minutes.
- Close with a written check (minute paper or muddiest point) in the last 10
  minutes and open the next session by answering it.

These numbers are the group defaults, changeable per course with
`--max-direct`, `--break-after`, `--check-every`, `--opening-within` and
`--closing-within`. They are choices informed by the sources, not measured
findings (`references/lecture-delivery.md`, "Not covered").

## Question design

Every multiple choice question names the misconception each wrong option
encodes, and is pitched so that roughly half the class gets it right the first
time. Record what the instructor does for each vote outcome: move on, address
one surviving wrong answer, or hand the question back to the class.

## Before the session

- [ ] `outcome_lint.py` exits 0 on the plan.
- [ ] `timebox.py --strict` exits 0, or every flag is a deliberate choice written into the plan.
- [ ] Every notebook, dataset and service in the plan was run end to end on the room's machines.
- [ ] The skeleton file, the cluster or data files and the fallback for any live service are in the course repository.
- [ ] The slides follow the presentation skill; the deck is not the plan.

## After the session

- [ ] The closing check is read and the two commonest points go into the next session's opening.
- [ ] A dated line in the teaching diary: what ran long, which check surprised you, what changes.
- [ ] The finished code and the slides are published; nothing about an individual student goes into them.
