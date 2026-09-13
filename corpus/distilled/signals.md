---
topic: signals
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Signals for monitoring a research group

Sources
- maestre2019 (CC-BY-4.0; short excerpts allowed)
- crossley2025 (CC-BY-4.0; short excerpts allowed)
- marino2014 (CC-BY-4.0; short excerpts allowed)
- pcbi-2023-lab-information (CC-BY-4.0 per manifest, paper states CC0; short excerpts allowed)
- schwab2022 (CC-BY-4.0; short excerpts allowed)
- grove-high-output-management (book, proprietary; cite only, ideas from corpus/notes/grove-high-output-management.md)
- barker-at-the-helm (book, proprietary; cite only, ideas from corpus/notes/barker-at-the-helm.md)
- hhmi-bwf-making-the-right-moves (proprietary; not fetched, summarised from knowledge)

This file grounds what the group monitor watches: papers, repositories,
students, services and teaching deadlines. The literature says what to watch
and why; it gives almost no numbers. The thresholds are Robert's settings and
are marked as such.

## What the evidence says

### Why monitor at all

- Flexibility over working hours does not remove the supervisor's duty to hold periodic meetings that check progress; the paper adds that people should be judged by the outcome of their work rather than the time spent at a desk [maestre2019].
- Regular check-ins "provide structure, help catch problems early" and signal that the work matters; consistency builds trust [crossley2025].
- A manager's output is the output of the people they supervise; delegation without a way to see output is abdication, and monitoring should sample at the stage where the least value has been added, where a correction is cheapest (from the book notes) [grove-high-output-management].
- Problems noticed early cost a conversation; problems noticed late cost a project or a person (from the book notes) [barker-at-the-helm].

### What to watch

- The final year of a PhD needs a written plan agreed with the supervisor that lists the remaining experiments, chapters and administrative tasks; postponing the writing delays the thesis without improving it [marino2014].
- Items in a laboratory information system carry a status such as to do, in progress, completed or canceled, so that active work is distinguishable from backlog and from finished work [pcbi-2023-lab-information].
- Data silos and undocumented locations are a risk; data should exist in three locations and primary data is never deleted [pcbi-2023-lab-information].
- A project has a written protocol and a data management plan before it starts, and every finding is reported, including negative ones; a project without these is a project without a checkable plan [schwab2022].
- Indicators should come in pairs (quantity with quality, throughput with rework) and leading indicators beat snapshots; a small set per process is enough (from the book notes) [grove-high-output-management].
- Short projects need a scope defined at the start and then halved, revisited at each meeting; drift from the plan is visible at the check-in, not at the end [crossley2025].
- HHMI/BWF advise project timelines with milestones and regular review of progress against them; a slipping milestone is the trigger for a conversation (from knowledge of the source, not verified against the text) [hhmi-bwf-making-the-right-moves].

### How to report

- Meetings are where supervision happens; the written trace of each meeting is the record that later reveals a stalled student or a repeated blocker (from the book notes) [barker-at-the-helm, grove-high-output-management].
- Comparing lab members against one another or by hours worked damages the lab; monitor artifacts and progress against the person's own plan [maestre2019].
- Gratitude and credit are part of a healthy lab; a monitor that reports only failures gives the PI a distorted picture [maestre2019].

## Rules we adopt

1. Monitor artifacts and states, never people: the monitor reads papers.org states, repository activity, service status files and the presence of meeting entries and milestone artifacts. It never scores a person (from [maestre2019], [grove-high-output-management]).
2. Every signal is a change or a threshold crossing with a source path and the date observed; a signal without provenance is not reported (from [pcbi-2023-lab-information], [grove-high-output-management]).
3. Report changes only. The briefing lists what moved since the last run and what crossed a threshold; unchanged items are counted, not listed (from [grove-high-output-management]).
4. Pair indicators: papers that advanced with papers that regressed to REVISING or PAUSED; beads closed with beads reopened; commits with open issues (from [grove-high-output-management]).
5. Papers: a paper in SUBMITTED for longer than 120 days, or in REVISING for longer than 30 days without a commit or note, is a signal. The numbers are Robert's settings in `assets/thresholds.yaml`; the literature gives none (from [pcbi-2023-lab-information], [schwab2022]).
6. Repositories: a repository with open issues and no commit for 90 days, a failing CI run on the default branch, or a release that is more than a year older than the last commit is a signal (from [pcbi-2023-lab-information]).
7. Students: no dated meeting entry in the person's org file for 21 days, or a milestone within 60 days without an artifact, is a signal that goes to Robert only. The 21-day figure is a group choice between the weekly cadence Crossley and Maini recommend and the every-few-weeks cadence Marino describes (from [crossley2025], [marino2014], [maestre2019]).
8. Final-year students: no final-year plan on file twelve months before the expected defense is a signal (from [marino2014]).
9. Services: a service whose status file has not been refreshed within its own reporting interval, or reports a failed check, is a signal; the monitor never restarts anything (from [pcbi-2023-lab-information]).
10. Teaching: a course deadline within 14 days without a linked artifact is a signal; the window is a group choice (from [hhmi-bwf-making-the-right-moves]).
11. Positive changes (a paper moved to PUBLISHED, a milestone passed, a release cut) are reported in their own section so credit is visible (from [maestre2019]).
12. Student signals are privacy class local-only and are written to a Robert-only file; they never enter a shared channel or a group briefing (from [maestre2019], [barker-at-the-helm]).
13. Every threshold lives in one YAML file with the rule id, the value, the unit and the source id; a change to a threshold is a commit Robert makes, not a script default (from [grove-high-output-management]).
14. Inspect early and cheaply: for new projects and new members the monitor lowers the thresholds (shorter windows) for the first semester, because that is where a correction costs least (from [grove-high-output-management], [crossley2025]).

## Where sources disagree

- Meeting cadence: Crossley and Maini recommend weekly or fortnightly check-ins for full-time projects; Marino et al. describe meetings every few weeks in the final year; Grove ties frequency to task-relevant maturity. We set the default alert at 21 days without an entry and let Robert override per person [crossley2025, marino2014, grove-high-output-management].
- What counts as progress: Maestre argues against judging by presence or hours; Grove wants measurable indicators. We reconcile by measuring artifacts (commits, drafts, entries) and never time [maestre2019, grove-high-output-management].
- Reporting failures: a changes-only briefing can read as a list of problems; Maestre's culture rules push for credit. We add a positive-changes section rather than dropping the problem list [maestre2019, grove-high-output-management].

## Not covered

- No source gives a numeric threshold for any of the signals; all numbers in `assets/thresholds.yaml` are Robert's and must be revisited after a semester of use.
- How to weigh signals against one another when many fire at once; the briefing orders them by deadline proximity and then by age, which is a house convention.
- Signals from Mattermost activity; the pa rule forbids polling, so the monitor reads only files and repositories.
- Any signal about grades, contracts or health; those never enter the monitor by the privacy rules.
