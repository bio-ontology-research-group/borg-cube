---
topic: briefing-format
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Briefing format for the group leader

Sources
- anthropic-context-engineering (proprietary; summary only)
- anthropic-multi-agent-research (proprietary; summary only)
- grove-high-output-management (book, proprietary; cite only, ideas from corpus/notes/grove-high-output-management.md)
- pcbi-2023-lab-information (CC-BY-4.0 per manifest, paper states CC0; short excerpts allowed)
- maestre2019 (CC-BY-4.0; short excerpts allowed)
- org-conventions-local (local file, proprietary; cited only for the shape of the existing files the briefing reads)

The group-monitor briefing follows the shape of Robert's daily briefing from
the personal assistant (`~/pa/templates/briefing.md`: a dated title, then
Top priorities, Schedule, Action items, Deadlines and important dates, Replies
owed, and Notes, each terse and action oriented). That template is a house
convention and has no manifest entry; the rules below cite the evidence for
why the shape works and mark the house choices as such.

## What the evidence says

- A reader's (or a model's) attention is a finite budget; information should be dense, at the right altitude, and loaded when it is needed rather than up front [anthropic-context-engineering].
- Long-running work benefits from a structured progress file recording completed items, open issues and decisions, and is read back at the start of the next session; the note replaces re-reading history [anthropic-context-engineering].
- Sub-agents return condensed summaries plus a pointer to the full artifact, so the coordinator reads a few thousand tokens rather than everything the worker saw [anthropic-multi-agent-research].
- Reports to a manager exist to force the writer to think; the reading matters less than the writing, and a small number of indicators with trends beats a long list (from the book notes) [grove-high-output-management].
- The one-on-one runs on the subordinate's agenda; the manager's notes from it feed the next meeting's list of open items (from the book notes) [grove-high-output-management].
- Records of samples, projects and decisions carry an explicit status so that active work, backlog and finished work are told apart at a glance [pcbi-2023-lab-information].
- Credit and recognition are part of running a healthy lab; a status report that names only problems distorts the picture [maestre2019].
- The existing org files already encode state: papers.org keywords, dated meeting headings and staff.org dates. A briefing that restates them in another form creates a second source of truth [org-conventions-local].

## Rules we adopt

1. One briefing per run, Markdown, titled `# Group briefing - <YYYY-MM-DD> (<weekday>)`, following the section order of Robert's pa briefing: Attention (at most five items), Changes since last run, Approaching deadlines, Waiting on Robert, Positive changes, Notes. The section set is a house convention modeled on `~/pa/templates/briefing.md` (from [anthropic-context-engineering], [grove-high-output-management]).
2. Attention holds the items that need a decision or an action this week, ordered by deadline proximity then by age; each is one line with the source path in parentheses (from [anthropic-context-engineering], [grove-high-output-management]).
3. Changes since last run lists only diffs against the previous state file: state transitions, new signals, cleared signals. Unchanged items are summarised as counts ("12 papers unchanged") (from [grove-high-output-management], [anthropic-multi-agent-research]).
4. Every line carries provenance: the org heading, file path, repository and commit, or status file it came from, plus the date observed. A line without provenance is dropped by the renderer (from [pcbi-2023-lab-information]).
5. Student items are written to a separate Robert-only file (`briefings/students/<date>.md`); the group briefing says only how many student signals exist and where the file is (from [maestre2019]).
6. Positive changes get their own section: papers published, milestones passed, releases cut, CI turned green (from [maestre2019]).
7. Notes states what the monitor could not read (missing files, failed fetches, stale status), so silence is never mistaken for health (from [anthropic-multi-agent-research]).
8. Keep it under roughly 60 lines; detail lives in the JSON state files the scripts write, and the briefing links to them (from [anthropic-context-engineering], [anthropic-multi-agent-research]).
9. Plain text and Markdown lists only: no tables wider than three columns, no blockquotes, no em-dashes, sentence-case headings; the renderer enforces the last two (from [anthropic-context-engineering]).
10. The briefing never restates the full state of papers.org or staff.org; it points at them (from [org-conventions-local], [grove-high-output-management]).
11. Each briefing ends with a one-line machine-readable footer naming the state files and thresholds version used, so a later run can reproduce it (from [anthropic-context-engineering]).

## Where sources disagree

- Length: Grove's reports are meant to be written more than read, which argues for completeness; the context-engineering guidance argues for density. We choose density in the briefing and completeness in the JSON state it is rendered from [grove-high-output-management, anthropic-context-engineering].
- Problems versus credit: a changes-only diff is problem heavy; Maestre's culture rules want credit visible. We keep both, in separate sections [maestre2019, grove-high-output-management].

## Not covered

- Delivery channel: the briefing is a file on ws read in the Emacs cockpit; whether the Concierge posts a digest is a Phase 1 decision, not covered here.
- How often to run: the patrol times in `cube.yaml` are Robert's; none of the sources give a cadence for a written group status.
- The pa briefing template itself has no manifest entry; if the corpus gains one, rule 1 should cite it directly.
