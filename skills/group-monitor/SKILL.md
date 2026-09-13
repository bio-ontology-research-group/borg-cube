---
name: group-monitor
description: Produces the changes-only group briefing for Robert from papers.org states, repository activity, student meeting and milestone signals, service status files and teaching deadlines, using Robert's thresholds. Use when asked "what changed in the group this week", "group briefing", "which papers are stuck", "which repos are idle", "who have I not met in three weeks", "run the monitor", or when a patrol needs the state snapshots and signals. Lead role; runs on ws by cron (collect and diff) with an optional Claude Code deep dive.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12, PyYAML and git; gh optional for open-issue counts; reads only the paths given; no network unless --gh.
metadata:
  borg-role: lead
  grounding: anthropic-context-engineering, anthropic-multi-agent-research, barker-at-the-helm, crossley2025, grove-high-output-management, hhmi-bwf-making-the-right-moves, maestre2019, marino2014, org-conventions-local, pcbi-2023-lab-information, schwab2022, sholler2019
  hermes:
    category: lead
    tags: monitoring, briefing, papers, repos, students, thresholds
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git *)
---

# Group monitor

Five scripts turn the group's own files into a short briefing: snapshot the
state of papers, repositories and students; diff against the previous
snapshot with Robert's thresholds; render the briefing in the shape of the pa
daily briefing. The literature behind the signals is in
`references/signals.md`; the numbers are Robert's and live only in
`assets/thresholds.yaml`.

## When to use

- The daily or weekly patrol on ws (deterministic, zero tokens): snapshot, diff, render.
- Robert asks what changed, what is stuck, or who needs a meeting.
- A deep dive: a paper or repository flagged in the briefing needs a reading of the org entry or the repository history before Robert decides.
- After a threshold change: rerun the diff on the same snapshots to see what would fire.

## Procedure

1. Snapshot papers: `scripts/papers_state.py --papers ~/org/papers.org --out state/monitor/papers.json`. Keywords come from the file's `#+TODO:` line; `last_touched` is the newest org timestamp in the entry.
2. Snapshot repositories: `scripts/repos_state.py --repos-file state/monitor/repos.txt --out state/monitor/repos.json` (add `--gh` only when the patrol may reach GitHub).
3. Snapshot students (local-only): `scripts/students_state.py --org-dir ~/org --people people.yaml --milestones-dir state/monitor/milestones --out state/monitor/students.json`. The milestones directory holds `<slug>.json` files from the phd-milestones skill.
4. Optional inputs: a services file `{"kind": "services", "generated": ISO, "interval_minutes": N, "checks": [{"name", "status", "detail"}]}` from hermes-infra, and a teaching file `{"kind": "teaching", "deadlines": [{"course", "item", "due", "artifact"}]}`.
5. Diff: `scripts/diff_state.py --current state/monitor/papers.json --current state/monitor/repos.json --current state/monitor/students.json --previous state/monitor/prev/papers.json ... --thresholds assets/thresholds.yaml --out state/monitor/signals.json`. Rotate the current snapshots into `prev/` after a successful run.
6. Render: `scripts/briefing_render.py --signals state/monitor/signals.json --out briefings/group/<date>.md --students-out briefings/students/<date>.md` prints a dry run; add `--apply` to write. The renderer refuses output with an em-dash, a Title Case heading or more than 60 lines.
7. Deep dive (Claude Code): read the org entry or `git log` behind an attention item, then write the finding as a bead with the source line; never edit papers.org or the repository from here.
8. Threshold changes go into `assets/thresholds.yaml` with the rule id from `references/signals.md`, as a commit Robert makes.

## Hard rules

- Monitor artifacts, never people: no ranking, no scores, no hours. Student signals are privacy `local-only`, go only to `briefings/students/`, and the group briefing carries only their count.
- Every line in the briefing has a source path and a date; the renderer drops nothing silently, so a signal without a source is a bug to fix in the collector.
- Changes only: unchanged items are counted, not listed. The full state stays in the JSON snapshots.
- The scripts never write to org files, repositories or Mattermost and never poll Mattermost; the only writes are the JSON snapshots and the briefing files, and file writes need `--apply` or `--out`.
- Thresholds are Robert's numbers; a script default is never a threshold. Report the thresholds version in every briefing footer.
- No service restarts, `scancel` or deletions from a monitor finding; those need a sysadmin ask with the commands quoted back.

## Outputs

- `papers.json`, `repos.json`, `students.json`: snapshots with `kind`, `generated`, per-item `source`.
- `signals.json`: signals with `id`, `category`, `severity` (attention, change, positive, cleared, waiting, note), `message`, `source`, `observed`, `deadline`, `privacy`; counts and unchanged totals.
- `briefings/group/<date>.md`: Attention (at most five), Changes since last run, Approaching deadlines, Waiting on Robert, Positive changes, Notes, footer with state and thresholds version.
- `briefings/students/<date>.md`: Robert-only student signals.

## Grounding

- `references/signals.md`: what the evidence says to watch and why, and the group's signal rules with the thresholds marked as Robert's.
- `references/briefing-format.md`: the shape of the briefing, provenance per line, changes-only, Robert-only student file.
- `references/lab-management.md`: running the group (one-to-ones, roster of record, paper states, onboarding, hand-over) that the monitor supports.

## Scripts

- `scripts/papers_state.py --help`: papers.org to JSON.
- `scripts/repos_state.py --help`: git repositories to JSON; `--gh` optional.
- `scripts/students_state.py --help`: per-student meeting and milestone facts (local-only).
- `scripts/diff_state.py --help`: snapshots plus thresholds to signals.
- `scripts/briefing_render.py --help`: signals to Markdown; dry run unless `--apply`.
