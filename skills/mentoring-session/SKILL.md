---
name: mentoring-session
description: Prepares a 1:1 supervision meeting for Robert and records it afterwards. Builds an agenda where every point cites evidence that already exists (commits, drafts, notebooks, the previous meeting entry), writes questions that assess whether the student understands their own work rather than testing recall, plans the feedback, and then inserts a dated meeting entry into the person's org file in the group's format. Use when asked to "prepare my 1:1 with X", "agenda for the meeting with X", "what should I ask X", "questions for the student meeting", "write up the 1:1", "record yesterday's meeting with X", or "add this meeting to X's org file". Advisor role; it never contacts the student, wellbeing signals are flagged to Robert with the evidence and never diagnosed, and the session record is privacy local-only.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; writes only inside the configured org root and only with --apply; no network.
metadata:
  borg-role: advisor
  grounding: anderson-krathwohl2001, crossley2025, delamont-supervising-the-doctorate, evans2018, jabre2021, lee2008-supervision, maestre2019, org-conventions-local, org-manual, phillips-pugh-how-to-get-a-phd, wisker-good-supervisor, woolston2019
  hermes:
    category: advising
    tags: supervision, 1:1, agenda, questions, org, advisor, local-only
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git log *)
---

# Mentoring session

A 1:1 is where supervision actually happens. This skill does the two parts a
machine can do well: it assembles an agenda from evidence that exists before
the meeting, and it turns the notes afterwards into a dated org entry in
Robert's format. The judgement in between stays with Robert.

The meeting is prepared for Robert. The skill never messages, emails or
otherwise contacts the student.

## When to use

- Before a scheduled 1:1, a check-in after a milestone, or a first meeting with a new student.
- When Robert asks what to ask a student, or how to raise a problem in a meeting.
- After a meeting, to write the record into the person's org file with action items and dates.
- When a progress review (progress-review skill) has produced a report that now needs to become a conversation.

## Procedure

1. Facts first. Confirm the student's id, programme, start date and org file from `state/students.yaml` and `~/org`, never from memory. Read the previous meeting entry in the person's org file and list the action items that are still open.
2. Collect the evidence. Reuse `skills/progress-review/scripts/collect_evidence.py` when a window is involved; otherwise read the commits, the drafts and the notebooks the student actually changed. Read the work, not the counts, and read any draft the student submitted before the meeting.
3. Build the agenda into `assets/agenda.md`. Every point names its evidence with a locator (repo and commit range, file and word count, org entry date). A point with no evidence is dropped or rewritten as a question. Student items come first in the meeting; the prepared points fill the rest.
4. Write four to six questions using `references/assessing-understanding.md`. Tag each with the cognitive process and knowledge type it targets, cover at least three processes, include one metacognitive question, and include an evaluate or create question whenever there is a result to discuss. Every question points at a piece of the student's own work.
5. Plan the feedback with `references/feedback-style.md`: argument first, then evidence, structure and prose; one specific thing that worked; one next action that fits before the next meeting; a dated turnaround promise for anything Robert has not yet read. Robert's own style file, when he writes it, sits at `references/robert-feedback-style.md` and overrides these defaults; this skill never mines `~/org` or any personal notes to reconstruct it.
6. Check the agenda against `references/supervision-and-wellbeing.md`: is the meeting more than a status check, is a stuck student being asked for output instead of being helped across a threshold, is there a skill named next to the output, is there anything to acknowledge.
7. If the evidence suggests a wellbeing or engagement problem, write a flag for Robert as observation plus evidence ("no commits and no draft change for 14 days"), with a suggested question to ask. Never a diagnosis, never a label, never a claim about a person's health.
8. After the meeting, fill `assets/session.yaml.example` (copy to `runs/<student>/<date>.yaml`) from the notes, then run `python3 scripts/org_meeting_entry.py --input runs/<student>/<date>.yaml`. Read the printed entry, fix the input, and rerun with `--apply` only when it is right.
9. Follow-ups that belong to Robert and not to the student go to `todo.org` through the meeting-scribe skill, not into the person's file. Anything needing an approval (a message to a third party, a form) becomes an approval bead.

## Hard rules

- Never contacts the student. The agenda, the questions, the flags and the record are for Robert. A message to the student is an approval bead unless `contacts.yaml` grants that person, channel and action class.
- Wellbeing signals are reported as a flag with the observed evidence and a question to ask. The skill never diagnoses, never names a condition, and never records a claim about a person. `flags` in the session input are printed for Robert and are never written to the org file.
- Grades, GPA, contracts, salary, visas, residence permits and health never enter the agenda, the session input, the org entry, a bead or a briefing. `org_meeting_entry.py` refuses when it finds them; keep them between Robert and the student.
- Every agenda point and every flag cites evidence with a locator. An impression is not evidence.
- Never compare one student with another, in the agenda, in the meeting or in the record. Compare only against the student's own plan and previous work.
- The session record is `privacy:local-only`: it lives in `runs/` and `~/org`, and any model call over it uses the local vLLM tier.
- Writing to an org file is a dry run by default. The script refuses when an Emacs lock (`#name.org#` or `.#name.org`) exists, when the target is outside the org root, when an entry for that date and topic already exists, when the file looks calendar-generated, and when an action item has no owner.
- Existing lines in an org file are never rewritten. The script only inserts, newest first, and preserves `#+` header lines, property drawers and logbooks.

## Outputs

- `runs/<student>/<date>-agenda.md`: the agenda, questions, feedback plan and flags, rendered from `assets/agenda.md`, for Robert only.
- `runs/<student>/<date>.yaml`: the session input, from `assets/session.yaml.example`.
- A dated entry in `~/org/<student>.org`: `* <D Month YYYY>, <topic>` with `- source:`, `- summary:`, `- [ ]` action items carrying an owner and a `<date>` deadline, `Decided:` and `Open:` bullets, and optional Agenda and Notes subheadings.
- Flags printed for Robert, with evidence, never written to the org file.
- Beads for anything that needs approval or that another skill owns.

## Grounding

- `references/supervision-and-wellbeing.md`: meeting rhythm, dialogic supervision, expectations, wellbeing duties and their limits, and the rules the group adopts.
- `references/assessing-understanding.md`: question forms by cognitive process and knowledge type, and how to record what an answer revealed.
- `references/feedback-style.md`: how feedback is ordered, phrased and dated in a supervision meeting, with the placeholder for Robert's own style file.
- `references/org-format.md`: the org conventions the entry follows, including the heading form, action item form and the lock file rule.

## Scripts

- `scripts/org_meeting_entry.py --help`: renders the meeting entry from a YAML or Markdown session file and inserts it newest first into the person's org file; dry run by default, `--apply` writes; refuses on locks, duplicates, paths outside the org root, missing owners and forbidden content.
