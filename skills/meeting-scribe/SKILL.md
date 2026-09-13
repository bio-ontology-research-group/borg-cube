---
name: meeting-scribe
description: Turns meeting notes, a transcript or a Mattermost thread into a dated org entry in Robert's format (heading "<D Month YYYY>, <topic>", "- [ ]" action items with owner and date, decisions, open questions, [unclear] markers), inserted newest-first into the person's org file after a dry-run diff, plus optional todo.org items and a summary draft that is never posted. Use when asked to "write up the meeting", "add meeting notes to X's org file", "extract action items", "scribe this", "what did we agree", or after a check-in reply. Drafts only; respects Emacs lock files.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads only the files given; writes an org file only with --apply; no network.
metadata:
  borg-role: advisor
  grounding: anthropic-multi-agent-research, barker-at-the-helm, crossley2025, google-small-cls, grove-high-output-management, hhmi-bwf-making-the-right-moves, invest-wake2003, maestre2019, org-conventions-local, org-manual, pcbi-2023-lab-information, schwab2022, scrum-guide2020, sholler2019
  hermes:
    category: advising
    tags: meetings, org-mode, action-items, scribe
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Meeting scribe

Two scripts and three templates turn what was said into what Robert's org
files expect: `actions_extract.py` finds action items, decisions and open
questions and renders the entry skeleton; `org_append.py` inserts the finished
entry newest-first, with a diff first and a write only on `--apply`. The
conventions come from `references/org-format.md`; the rules for a good action
item (owner, date, done condition) from `references/task-decomposition.md`.

## When to use

- After a 1:1, group meeting or committee meeting for which notes or a transcript exist under `runs/<id>/` or in a bead.
- After a granted student's check-in reply arrives through the Hermes gateway (Phase 4).
- When Robert dictates notes and wants them in the person's file.
- When a Mattermost thread needs a written trace in org.

## Procedure

1. Establish the source: transcript path, Mattermost permalink or Message-ID. It goes on the `- source:` line of the entry. Without a source, stop and ask.
2. Run `scripts/actions_extract.py --notes <file> --date YYYY-MM-DD --topic "<topic>" --attendees "<names>" --source <ref> --format org > runs/<id>/entry.org`. Check the JSON view (`--format json`) for `flags`: items with `owner unclear` or `no date` stay marked `[unclear]`; do not fill them from guesswork.
3. Write the `- summary:` line yourself in two or three plain sentences: what was discussed and where things stand. No assessment of the person, no praise or blame; those belong in Robert's own notes.
4. Read the target file's existing entries to match the heading form and level (`references/org-format.md`, rule 1). Then run `scripts/org_append.py --file ~/org/<person>.org --entry runs/<id>/entry.org` and read the diff. The script refuses when `#file#` or `.#file` exists or when the file is calendar-generated.
5. Show the diff to Robert (or attach it to the bead). Only after `cube approve` rerun with `--apply`.
6. Follow-ups that belong to Robert rather than to the student go to `todo.org` with `assets/todo-entry-template.org` and `org_append.py --file ~/org/todo.org --anchor top`.
7. If a summary for the group or the student is wanted, fill `assets/mattermost-summary-template.md` into `runs/<id>/summary.md` and open a `kind:outbound` approval bead. Never post it yourself.
8. If the notes contain a blocker, a complaint or a wellbeing concern, open a `needs:robert` bead quoting the line and its source; do not paraphrase it into the org entry.

## Hard rules

- Drafts only. The scribe never sends, posts or emails anything; the only write is the org file after Robert's approval and `--apply`.
- Never invent what was said. Gaps are `[unclear]`; relative dates ("next week") stay `[unclear]` unless the notes give the date.
- Every action item has an owner and, when agreed, a date; an item missing either is flagged, not silently recorded (`references/task-decomposition.md`, rule 12).
- Respect locks: `#name#` and `.#name` mean Emacs has the file open. Wait; never delete a lock.
- Never edit generated files (`work.org`, `*.cal`, `*.ics`) or existing lines; insert only.
- Check-in transcripts are privacy `local-only`: the scribe run must use the local tier, and the entry contains no grades, contract, visa or health details.
- Heading: `* <D Month YYYY>, <topic>` with the day first, full month name and year, newest entry first; action items as `- [ ] text (owner) <YYYY-MM-DD Day>`.
- No em-dashes; plain language; the person's file is the record, not a place for commentary.

## Outputs

- `runs/<id>/entry.org`: the entry (heading, source, summary, `- [ ]` items, `- Decided:`, `- Open:`, `[unclear]`).
- Unified diff from `org_append.py` for the approval bead; the applied change after approval.
- Optional `runs/<id>/todo.org` snippet and `runs/<id>/summary.md` draft.
- `needs:robert` bead when the notes contain a blocker or concern.

## Grounding

- `references/org-format.md`: Robert's org conventions (files, heading forms, timestamps, locks, generated files) and the entry format we adopt.
- `references/task-decomposition.md`: what makes an action item complete (owner, date, done condition) and how decisions are recorded.
- `references/lab-management.md`: why every meeting leaves a written trace and why concerns go to the PI alone.

## Scripts

- `scripts/actions_extract.py --help`: notes to org entry skeleton or JSON; read-only.
- `scripts/org_append.py --help`: insert an entry newest-first; dry-run diff by default, `--apply` to write; refuses on locks.
