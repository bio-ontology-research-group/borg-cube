---
name: mentoring-compact
description: Drafts and maintains the written agreement between Robert and a student or postdoc (mentoring compact or expectations document), the student's individual development plan (IDP), and the annual review that compares IDP versions. Use when asked to "write a mentoring compact", "expectations document for a new student", "onboarding agreement", "set up an IDP", "prepare the annual review", "what changed in X's development plan", or when a new person joins the group. Advisor role; drafts go to Robert, who discusses and agrees them with the person himself.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12; reads only the IDP files given on the command line; no network.
metadata:
  borg-role: advisor
  grounding: barker-at-the-helm, cimer-entering-mentoring, credit, delamont-supervising-the-doctorate, gu2007, handelsman2005, hhmi-bwf-making-the-right-moves, icmje, kaust-cemse-milestones, lee2007-nature-mentors, lovitts2001, maestre2019, marino2014, masters2017, myidp, nap2018-graduate-stem, nap2019-mentorship, pcbi-2022-mentorship-programme, pcbi-2023-lab-information, pfund2006, quynn2026, vitae-rdf, wisker-good-supervisor
  hermes:
    category: advising
    tags: mentoring, compact, expectations, idp, annual-review, onboarding
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Mentoring compact and IDP

Three documents make expectations explicit: the compact (what each person
can expect of the other), the IDP (what the student wants to become and the
dated goals for the year), and the annual review (what changed). This skill
drafts them from templates, keeps them consistent with the milestone plan
and the group rules, and prepares the review from two IDP versions with
`scripts/idp_diff.py`. The evidence for why written expectations and a
revisited IDP matter is in the three references.

## When to use

- A student or postdoc joins: draft the compact and the first IDP skeleton for the onboarding meeting (`cube student onboard <id> --dry-run` calls this skill).
- A year has passed since the last compact or IDP version, or the project, funding or role changed.
- Robert wants an annual review agenda: what the student completed, dropped, rescheduled, and where self-ratings moved.
- A conflict or a mismatch of expectations appears in a 1:1: the compact is the reference point to revise, not a rulebook to cite.

## Procedure

1. Facts: name, role (PhD, MS, postdoc), programme, start date, funding end date, milestone plan (phd-milestones output). Take them from `people.yaml`, `~/org/staff.org` and the org file; ask Robert for anything missing.
2. Compact: copy `assets/compact-template.md` to `runs/<id>/compact-<person>.md`. Fill only what the sources support (meeting cadence from Robert's stated pattern, group meeting slot, storage locations, authorship rule). Leave the student's side (`<the student's own words>`) blank: it is filled in the meeting. Add `assets/postdoc-compact-addendum.md` for postdocs.
3. IDP: copy `assets/idp-template.md` to `runs/<id>/idp-<person>-<date>.md`. Pre-fill programme, milestone and the skills rows that the project needs (from `references/idp-frameworks.md`, Vitae domains). Ratings, interests and goals are the student's; never pre-fill them.
4. Check the drafts against `references/expectations-documents.md`, Rules we adopt: every commitment has a number or a date, both directions are covered, a conflict path outside the dyad is named, authorship is settled at the outline stage, and nothing contradicts KAUST policy or the compact of another student.
5. Hand both drafts to Robert with a one-paragraph note on what he must decide (cadence, presence expectation, leave pattern). He runs the onboarding meeting; the agreed versions go into the student's org file as links, and the review date into `todo.org`.
6. Annual review: `python3 scripts/idp_diff.py --old <last year> --new <this year> --today YYYY-MM-DD`. Turn the output into the agenda: completed goals first, then overdue and dropped goals as questions (what changed, what blocked it), then rating changes, then next year's goals. Add the semester progress reports (progress-review skill) as evidence.
7. After the review, the student writes the new IDP version; the compact gets a new version line only if something changed. Record the review date in the IDP review log and in the org file (meeting-scribe).

## Hard rules

- Never contacts the student; Robert-facing unless a contact grant exists (`contacts.yaml`, ADR-0009). Even with a grant, the compact and IDP are sent by Robert, not by the system.
- Every score or claim cites evidence: an IDP rating stays the student's self-assessment; anything the supervisor adds about progress comes from the progress-review report with its evidence ids, never from impression.
- No invented references: any literature cited in a compact or review (for example on authorship or mentoring) is verified by DOI (literature-review `cite_check.py`) before it appears.
- The compact never overrides KAUST policy, the programme rules or the milestone dates; where they differ, the template says which prevails.
- The IDP belongs to the student. The system never edits an IDP; `idp_diff.py` only reads two versions the student shared. Career interests, values and wellbeing entries are `privacy:local-only`.
- The compact states expectations for both people, with numbers (reply time, feedback turnaround, meeting cadence) and a conflict path outside the dyad. A draft without those is not ready.
- No assessment language in a compact or IDP draft; assessments live in progress-review reports and are never delivered to the student by borg-cube.

## Outputs

- `runs/<id>/compact-<person>.md`: filled compact, with the student's side blank, plus the postdoc addendum when applicable.
- `runs/<id>/idp-<person>-<date>.md`: IDP skeleton with programme facts and the project's skills rows pre-filled.
- `idp_diff.py` text or JSON: completed, added, dropped, reopened, rescheduled and overdue goals, rating changes, for the review agenda.
- A note to Robert listing the decisions the meeting must settle, and the review date for `todo.org`.

## Grounding

- `references/mentorship-evidence.md`: what research on STEMM mentoring says works (structured expectations, trained mentors, multiple mentors, regular feedback) and what it does not settle.
- `references/expectations-documents.md`: what a compact contains, how the conversation is run, how often it is revisited, and how it differs for postdocs.
- `references/idp-frameworks.md`: myIDP structure, Vitae RDF domains, how NAP reports frame the IDP, and how to run an annual review from it.

## Scripts

- `scripts/idp_diff.py --help`: diff two IDP Markdown files (goals with dates, rating tables); read-only; `--json` for the review agenda generator.
