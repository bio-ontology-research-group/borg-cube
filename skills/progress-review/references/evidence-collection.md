---
topic: evidence-collection
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Collecting evidence of research progress

Sources
- wilson2017 (CC-BY-4.0; short excerpts allowed)
- schnell2015 (CC-BY-4.0; short excerpts allowed)
- sandve2013 (CC-BY-4.0; short excerpts allowed)
- schwab2022 (CC-BY-4.0; short excerpts allowed)
- pcbi-2023-lab-information (CC-BY-4.0; short excerpts allowed)
- maestre2019 (CC-BY-4.0; short excerpts allowed)
- google-small-cls (CC-BY-3.0; short excerpts allowed)
- crossley2025 (CC-BY-4.0; short excerpts allowed)
- marino2014 (CC-BY-4.0; short excerpts allowed)
- grove-high-output-management (book, proprietary; ideas from corpus/notes/grove-high-output-management.md)
- delamont-supervising-the-doctorate (book, proprietary; ideas from corpus/notes/delamont-supervising-the-doctorate.md)
- nap2019-mentorship (proprietary, free to read; summary only)

## What the evidence says

### What makes an artefact readable as evidence

- The notebook rules make each entry dated and titled, keep a table of
  contents so a supervisor or anyone else can find the record of a piece of
  work, and require a record of how every result was produced, in enough
  detail that the result can be reproduced [schnell2015].
- The record covers thinking, meetings and seminars, not only runs, because
  ideas held in memory are lost, and writing them out forces the argument to
  be made [schnell2015].
- The notebook is the institution's record and part of the group's legacy, not
  personal property, which is what makes it usable as evidence at all
  [schnell2015].
- Reproducible practice keeps a provenance record for every result, prefers a
  script over a manual step, and stores the raw data, so that a figure or a
  number can be regenerated rather than trusted [sandve2013].
- Good enough practice names the observable habits: raw data saved and backed
  up in more than one place, every processing step recorded, changes kept
  small and shared frequently, everything a person created backed up as soon
  as it is created, and version control in use [wilson2017].
- A project has one directory named after it, with documents, raw data and
  metadata, generated results, source code and compiled programs separated,
  and file names that say what a file is; a project laid out this way can be
  read from the outside [wilson2017].
- Collaboration artefacts are evidence too: an overview of the project, a
  shared to-do list, an explicit licence and a citation file [wilson2017].
- Records of samples, projects and decisions carry an explicit status, so that
  active work, backlog and finished work can be told apart at a glance
  [pcbi-2023-lab-information].
- Standardised workflows and identifiers make records comparable across people
  and time, and data silos are what make a group's work unreadable to itself
  [pcbi-2023-lab-information].
- Written plans with dates are themselves evidence, and the plan is reviewed
  with the supervisor rather than kept privately [marino2014].
- Delamont and colleagues ask for a written record of each supervision meeting
  saying what was agreed, what is due and by when, from the first week
  [delamont-supervising-the-doctorate].
- Crossley and Maini put expectations into a project plan at the outset and
  revisit them at regular check-ins, with each meeting reviewing progress,
  troubleshooting, and clarifying the next steps before the student leaves
  [crossley2025].
- They also scaffold writing with dated intermediate goals, for example an
  outline by week three and a methods draft by week six, which turns writing
  into an inspectable series of artefacts [crossley2025].

### Which numbers mislead

- Google's guidance is that a change spread across many files counts as larger
  than the same number of lines in one file, and that about 100 changed lines
  is usually reasonable while 1000 is usually too large. Size is a property of
  a change, not a measure of a person's output [google-small-cls].
- The same guidance treats splitting work into many small changes as good
  practice, so a high commit count can mean careful practice, a low one can
  mean batched work, and neither reads as productivity [google-small-cls,
  wilson2017].
- Grove pairs every indicator with a counter-indicator so that speed is not
  bought with rework, and monitors at the stage where the least value has been
  added [grove-high-output-management].
- Healthy-lab practice says explicitly that scientists should be evaluated by
  the outcome of their work rather than by the time they spend in the
  workplace, and that people should be able to set their own schedules
  [maestre2019].
- The same source asks group leaders not to expect work beyond normal working
  hours, which rules out presence, response time at night and weekend activity
  as progress signals [maestre2019].
- Selective reporting is a known failure mode: results that did not work are
  under-reported, so an evidence set built only from what a student chose to
  show is biased by construction [schwab2022].
- Word counts have the same problem as commit counts. Quality of writing is
  judged by whether an argument is present, and the practices behind it are
  the plan, the protocol and the reporting standard, not volume
  [schwab2022].
- The mentorship report warns that measurement inside a relationship with a
  power difference changes the behaviour it measures, which is a reason to
  keep counts as pointers and not as targets [nap2019-mentorship].

### Gaps in collection are not gaps in work

- If the record is missing, the first hypothesis is that the collection is
  wrong: an unlisted repository, a renamed branch, a draft in a different
  directory, an org file not updated. Standardised locations and identifiers
  exist precisely because ad hoc ones go missing
  [pcbi-2023-lab-information, wilson2017].
- Work that is real but unrecorded is a practice problem to raise, not a
  progress finding to score; the remedy is the notebook rule, not a lower
  score [schnell2015, sandve2013].
- Reading the artefact is the actual evidence step: the commit subject and the
  diff, the dated meeting entry, the section that changed. The counts only say
  where to look [google-small-cls, schnell2015].

## Rules we adopt

1. Collect only from the sources listed in `state/students.yaml`:
   repositories, org files and draft directories the student and Robert agreed
   on. No scanning of home directories, mail or chat. Enforced by
   `collect_evidence.py`. (from [pcbi-2023-lab-information],
   [nap2019-mentorship])
2. Give every evidence item a stable id and cite that id in every score and
   every claim. A claim without an id does not enter the report, a bead or a
   briefing. Enforced by `rubric_report.py`. (from [sandve2013],
   [schnell2015])
3. Read the `gaps` list before the evidence. A missing repository, an empty
   org file or an unreadable draft is a collection problem and is reported as
   one, never as a finding about the student. (from
   [pcbi-2023-lab-information], [wilson2017])
4. Treat counts as pointers, never as scores. Open the commit subjects and the
   largest diff, read the dated org entries, open the drafts that changed, and
   write the score from what was read. (from [google-small-cls],
   [schnell2015])
5. Pair every count reported with its counter-indicator: commits with reverted
   or reopened work, words written with sections that survived review,
   meetings held with action items closed.
   (from [grove-high-output-management])
6. Never use presence, working hours, message response time, or activity at
   night or on weekends as evidence of anything.
   (from [maestre2019])
7. Count an artefact as evidence of rigour only when its provenance is
   recorded: the script, the seed, the data version and the run that produced
   it. An undocumented result is evidence about practice, not about progress.
   (from [sandve2013], [schnell2015], [wilson2017])
8. Take dated meeting entries with their open action items as the
   communication evidence, and treat a missing entry as a supervision gap
   shared by both sides. (from [delamont-supervising-the-doctorate],
   [crossley2025])
9. Look for the plan as an artefact: a written question, an analysis plan
   fixed before the run, and dated intermediate writing goals. Their absence
   is the finding, not their content. (from [marino2014], [schwab2022],
   [crossley2025])
10. Ask what is missing from the collected set before scoring, because a
    student shows what worked; record failed runs and abandoned lines as
    evidence when they appear. (from [schwab2022])
11. Keep grades, GPA, contract, visa, human resources and health information
    out of the evidence file, the report and every bead, and keep the whole
    report `privacy:local-only`. (from [nap2019-mentorship])
12. State the collection window and the collection date in the report, since
    an evidence set is a snapshot and reads differently a month later.
    (from [grove-high-output-management])

## Where sources disagree

- Whether counts are worth collecting at all: Grove wants indicators
  [grove-high-output-management] while the healthy-lab and mentorship sources
  warn against measuring people [maestre2019, nap2019-mentorship]. We collect
  counts, keep them Robert-facing, and forbid them as scores, which is the
  narrowest use that still finds a stalled project.
- Notebook as legal record versus notebook as thinking space: Schnell treats
  it as the institution's record and part of an audit trail [schnell2015],
  while the same rules ask for ideas and meeting notes in it [schnell2015].
  In this group the org file carries meetings and thinking and the repository
  carries provenance, so the evidence is assembled from both.
- How much practice to require: Wilson and colleagues aim deliberately at good
  enough practice [wilson2017]; Sandve and colleagues ask for full provenance
  on every result [sandve2013]. We require provenance for any result that
  enters a paper or a report and accept good enough practice elsewhere.
- Who defines the record locations: the lab-information rules want group-wide
  standards [pcbi-2023-lab-information], while the healthy-lab rules want
  people to work in the way that suits them [maestre2019]. We standardise
  locations and formats and leave schedules and working style to the person.

## Not covered

- Evidence for work that leaves no digital trace: reading, thinking, debugging
  in a terminal, conversations with collaborators.
- How to weigh a long training run or a stalled data access request against
  weeks with no commits.
- Detecting fabricated or borrowed evidence. The collection assumes the record
  is honest, and nothing here checks that.
- How much of an artefact one may read without asking. The group treats
  listed repositories and org files as shared, and everything else as private,
  but no source settles this.
- Evidence from co-authors and collaborators outside the group, which is not
  collected at all.
- The thresholds used with these counts (21 days without an artefact, 90 days
  to a milestone, a 28-day digest window) are group choices and are recorded
  in `progress-rubric.md`, not derived from any source here.
