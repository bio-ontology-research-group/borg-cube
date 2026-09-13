---
topic: org-format
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Org file conventions for meeting notes and action items

Sources
- org-conventions-local (local file ~/org/CLAUDE.md, proprietary; read on 2026-09-02; rules summarised, file never copied)
- org-manual (GFDL-1.3; fetched 2026-09-02, table of contents only; the syntax claims below are from knowledge of the manual sections named)

## What the evidence says

### The workspace

- The org directory is a flat set of files, not a software project: nothing builds or runs, and an edit is the work product [org-conventions-local].
- main.org is the hub; other files are reached from it through `[[file:NAME.org][Label]]` links. A new person or project file also gets a link from main.org [org-conventions-local].
- One file per student or staff member (for example alex.org), one per project, plus hubs: staff.org is the roster with contract end dates and graduation estimates, papers.org is the paper pipeline, todo.org is the global TODO list, inbox.org captures unsorted notes, groupmeeting.org holds group meeting notes [org-conventions-local].
- papers.org declares a custom TODO sequence in its first line: READY_TO_SUBMIT, SUBMITTED, REVISING, PAUSED, TODO, then PUBLISHED and CANCELED as done states. These keywords must be preserved, never normalized to TODO and DONE [org-conventions-local].
- Calendar-derived files (work.org and any file with BEGIN:VEVENT blocks under COMMENT headings) and the .cal and .ics files are generated and are never hand-edited [org-conventions-local].

### Files to leave alone

- `NAME.org~` are Emacs backups and `#NAME.org#` are Emacs auto-save lock files; a lock file means the user has that file open in Emacs and writing to NAME.org at the same time risks an edit conflict [org-conventions-local].
- The Emacs lock is a symlink `.#NAME.org` pointing at `user@host.pid:time`; a stale one survives a crash, so a writer should check for both forms and prefer to wait [org-conventions-local].
- LaTeX intermediates next to bioe-meeting.org are generated artifacts [org-conventions-local].

### Syntax in use

- Headings nest with `*`, `**`, `***`; property drawers (`:PROPERTIES:` to `:END:`) and logbooks (`:LOGBOOK:` to `:END:`) appear under headings and are preserved verbatim [org-conventions-local, org-manual].
- Tags sit at the end of a heading line as `:WORK:` or `:PERSONAL:` with the surrounding colons [org-conventions-local, org-manual].
- Active timestamps `<2026-05-11 Mon>` appear in the agenda; inactive ones `[2026-05-11 Mon]` do not. Repeaters look like `<2025-01-27 Mon 11:30-12:00 +1w>` [org-conventions-local, org-manual].
- todo.org uses plain TODO and DONE with `SCHEDULED:`, `DEADLINE:` and `CLOSED:` timestamps on the line after the heading [org-conventions-local, org-manual].
- Checkbox lists `- [ ]` and `- [X]` track subtasks inside an entry; the manual treats them as lightweight tasks below the heading level [org-manual].
- `#+STARTUP:` and `#+TODO:` lines at the top of a file control how Emacs opens it and which keywords it accepts; they are left intact [org-conventions-local, org-manual].

### Dated meeting entries as they appear in the files

- Meeting notes live in the person's file under dated headings. Observed forms include `* 21 April, practice talk`, `** Meeting 16 November 2023`, `** Group meeting 15 Feb 2024`, `** 27 January 2025` and `*** Meeting with Paul <2023-10-26 Thu>`; the date is human-readable in the heading text, not an org timestamp, in most entries [org-conventions-local].
- Newer entries sit above older ones within a Notes or top-level section, so the most recent meeting is read first [org-conventions-local].
- Action items inside an entry are plain `- ` bullets or `- [ ]` checkboxes; deadlines, where present, are `<date>` timestamps [org-conventions-local].

## Rules we adopt

1. A meeting entry is a heading `* <D Month YYYY>, <topic>` (for example `* 3 September 2026, weekly 1:1`) at the top of the person's file, or under the file's Notes heading when one exists, so that the newest entry is read first. The scribe script takes the heading level from the neighbouring entries (from [org-conventions-local]).
2. The entry body holds a short summary paragraph, then `- [ ]` action items, each with an owner in the form `(owner)` and, when a date was agreed, an active timestamp `<YYYY-MM-DD Day>` (from [org-conventions-local], [org-manual]).
3. Decisions are recorded as plain `- ` bullets starting with "Decided:"; open questions start with "Open:"; anything the scribe could not hear or read is marked `[unclear]` and never guessed (from [org-conventions-local]).
4. Never write to NAME.org while `#NAME.org#` or `.#NAME.org` exists; the script reports the lock and exits non-zero, and a dry run is the default (from [org-conventions-local]).
5. Never touch generated files (work.org, *.cal, *.ics, LaTeX intermediates) and never edit VEVENT or CLOCK blocks (from [org-conventions-local]).
6. Preserve every `#+` header line, property drawer, logbook and tag exactly; the script only inserts, never rewrites, existing lines (from [org-conventions-local], [org-manual]).
7. Keep the papers.org TODO sequence as declared in its `#+TODO:` line; a state read from papers.org is compared against that line, not against a hard-coded list (from [org-conventions-local]).
8. Global follow-ups go to todo.org as `* TODO <text>` with `DEADLINE: <date>` on the next line when a date exists; person-specific ones stay in the person's file (from [org-conventions-local], [org-manual]).
9. Cross-references use `[[file:other.org][Label]]`; when a new file is created the script prints the main.org link line for Robert to add (from [org-conventions-local]).
10. Commit messages in the org repository are terse (the history shows `update staff`, `reorg`); the scribe never commits (from [org-conventions-local]).

## Where sources disagree

- Heading date form: the files mix `21 April, practice talk`, `Meeting 16 November 2023` and `Group meeting 15 Feb 2024`. The org manual would put an org timestamp in the heading so the agenda picks it up. We follow the files (readable date in the heading text, day first, full month name, year) because Robert's existing entries and grep habits depend on it; the action-item timestamps still use org syntax for agenda visibility [org-conventions-local, org-manual].
- Checkboxes versus TODO headings for action items: the manual supports both. We use `- [ ]` inside the meeting entry, since that is what the person files already do, and reserve TODO headings for todo.org [org-conventions-local, org-manual].

## Not covered

- The Org manual text was not fetched beyond its table of contents; the syntax claims are from knowledge of the manual and should be checked against the fetched sections when the manual is fetched in full.
- Where an entry goes when a person file has no Notes heading and starts with a Todo or Projects section; the script defaults to inserting after the `#+` header block.
- How Robert wants group-meeting entries split between groupmeeting.org and the person files; the scribe writes to groupmeeting.org only when told to.
- Anything about tags on meeting entries; none of the observed meeting headings carry tags.
