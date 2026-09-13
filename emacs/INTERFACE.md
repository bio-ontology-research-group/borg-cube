# Cockpit to backend contract

This file is the authority for what the Emacs cockpit (`emacs/`) expects
from the `cube` command line program and from the event log. The Python
side implements it; the fixtures in `test/fixtures/` are the example
payloads and are shared with the backend tests. The cockpit is tolerant:
every key may be missing or `null`, and unknown keys are ignored.

## Transport

- Remote mode (`cube-remote-host` non-nil, default `"ws"`): every call is
  `ssh -o BatchMode=yes HOST -- cube <args> --json`. Interactive sessions
  are `ssh -t HOST -- tmux new-session -A -s cube/<name> '<cmd>'`.
- Local mode (`nil`): `cube <args> --json`, or `uv run cube ...` in
  `cube-root` when `cube` is not on `PATH`.
- Every command accepts `--json` and then prints exactly one JSON
  document on stdout and nothing else there. Diagnostics go to stderr.
  Exit code 0 on success; non-zero with a one-line message on stderr
  otherwise (the cockpit shows stderr, so keep it human readable). `cube
  tail --json` is the streaming exception and prints one JSON object per line.
- Timestamps are ISO 8601 with offset (`2026-09-02T09:15:00+03:00`).
  Durations are seconds. Paths are relative to the borg-cube checkout
  unless absolute; `~` is allowed and expanded on the host.
- Objects arrive in Emacs as alists with symbol keys, arrays as lists,
  `null` as nil and `false` as `:false`.

## Commands

| Command | Fixture | Purpose |
|---|---|---|
| `cube status --json` | `status.json` | Overview: counts, running runs, tmux sessions, bead totals, patrol health |
| `cube attention --json` | `attention.json` | The prioritised list the mode line and the `!`/`1-3` keys use |
| `cube ready --json` | `ready.json` | Ready beads (unblocked, unclaimed) |
| `cube people --json` | `people.json` | Group members with next milestone and contact grants |
| `cube student <slug> --json` | `student-alex.json` | One student's dossier |
| `cube papers --json` | `papers.json` | Papers with state, venue, deadline |
| `cube literature --json` | `literature.json` | Today's arXiv and bioRxiv digest entries with counts and the digest path |
| `cube courses --json` | none | Course offerings, schedules, materials, deadlines and derived work |
| `cube repos --json` | `repos.json` | Tracked repositories and their hygiene |
| `cube approvals --json` | `approvals.json` | The approval queue |
| `cube decisions --json` | `decisions.json` | Everything waiting for Robert's answer, all channels in one shape |
| `cube decide <id> (--choice C \| --text T) --apply --json` | inline below | Robert's answer, recorded and routed back to the asker |
| `cube question new --from X --text T [--options a,b] --apply --json` | inline below | How an agent asks Robert and stops |
| `cube approve <id> --json`, `cube reject <id> [--reason TEXT] --json` | inline below | The only outbound trigger |
| `cube run <role> [--bead ID] [--attach] --json` | `run.json` | Start a headless run; `--attach` runs it in tmux `cube/run-<run_id>` |
| `cube doctor --json` | `doctor.json` | Environment checks |
| `cube tail [-f] [--bead ID] [--run ID] --json` | `events.jsonl` | Read or follow the cockpit event log, optionally one bead's or one run's events |
| `cube notify --hook` | `hook-*.json`, `codex-notify.json` on stdin | Called by agent hooks on the host; appends to the event log |
| `cube brief --json` (proposed) | `brief.json` | Morning brief as markdown |
| `cube beads show <id> --json` (proposed) | `bead-show.json` | One bead with dependencies and comments; cockpit falls back to `bd show <id> --json` |
| `cube runs show <run_id> --json` (proposed) | `run-show.json` | One run: metadata, summary, `notes` markdown, log tail |
| `cube approvals show <id> --json` (proposed) | `approval-show.json` | One approval with its `body` text and, for email, `to` and `subject` |
| `cube approve <id> --body-file PATH --json` (proposed) | inline below | Approve with an edited body; PATH is relative to the checkout on the host |

### `status`

```json
{"ok": true, "generated": ISO, "host": "ws", "version": "0.1.0",
 "counts": {"attention": N, "ready": N, "running": N, "approvals": N},
 "runs": [{"run_id", "role", "bead", "runner", "model", "state", "started", "tmux"}],
 "sessions": [{"name", "tmux", "kind", "started", "last_event", "last_event_ts", "resume_id"}],
 "beads": {"open", "ready", "blocked", "needs_robert"},
 "patrols": {"<name>": {"last_run": ISO, "ok": bool}}}
```

`sessions` lists the `cube/*` tmux sessions on the host (from `tmux ls`)
joined with what the event log knows about them; this is the source of
truth for the rolodex after a cockpit restart.

### `attention`

```json
{"generated": ISO,
 "items": [{"id": "att-...", "kind": "approval|session|needs_robert|finding|error|deadline",
            "severity": "high|normal|low", "title": "...",
            "since": ISO, "age": SECONDS,
            "target": {"type": "approval|session|bead|file|run", "id": "...", "tmux": "cube/..."},
            "actions": ["approve", "reject", "open", "attach", "close"]}]}
```

`cube attention ack ID --reason TEXT --apply` removes an item from this list
(stored in `state/attention-acks.json`); the cockpit binds it to `d` on an
attention row. Error items otherwise stay for 24 hours.

Sorted loudest first by the backend (severity, then age). The cockpit
shows the first `cube-attention-count` items and counts all of them in
the mode line (`⚠N`). `target.type` decides what `RET` does in the
dashboard: `session` attaches, `approval` opens the review queue entry,
`bead` opens the bead, `file` opens the file (TRAMP in remote mode).

### `ready`

```json
{"beads": [{"id": "cube-142", "title", "type": "task|epic|chore", "kind": "experiment|...",
            "stage": "design|implement|review", "priority": 1-4, "labels": [...],
            "parent": "cube-100"|null, "student": "slug"|null, "deadline": "YYYY-MM-DD"|null,
            "assignee": null}]}
```

### `people` and `student <slug>`

When `cube people` is unavailable the cockpit parses `~/org/staff.org`
(list items under the Staff and Students headings; fixture `staff.org`)
into the same shape with `slug`, `name`, `role`, `org_file`.

`people.people[]`: `slug`, `name`, `role` (`phd|msc|postdoc|staff|visitor`),
`org_file`, `program` (bead id or null), `next_milestone` (`{name, due, days}`
or null), `contact` (`{mattermost_dm, email, dossier_read}` booleans from
`contacts.yaml`), `attention` (count), `last_meeting`.

`student <slug>`: the same identity fields plus `program`, `milestones[]`
(`bead, name, due, state, days, artefact`), `evidence`
(`commits_7d, repos, drafts[], org_notes_last, checkins[]`),
`agenda_draft[]` (strings), `beads[]`, `advisor_run`
(`run_id, ts, notes_file`), `concerns[]`. Nothing in this document may
come from the student that the student did not state or that is not
derivable from artefacts Robert already has (ADR-0009).

### `courses`

```json
{"generated": ISO, "today": "YYYY-MM-DD", "courses": [{
  "xid": "course:cs249:fall-2026", "code": "CS 249", "title": "...",
  "semester": "Fall 2026", "instructor": "...",
  "lectures": [{"number": 1, "date": "YYYY-MM-DD", "topic": "...",
                "materials": ["slides/01.pdf"], "source": "path:line"}],
  "materials": ["slides/01.pdf"],
  "upcoming_deadlines": [{"date": "YYYY-MM-DD", "title": "...",
                           "source": "path:line"}],
  "work_items": [{"xid": "...", "title": "...", "type": "epic|task",
                   "kind": "course|lecture", "parent_xid": null,
                   "deadline": "YYYY-MM-DD", "closed": false}],
  "sources": ["path"]
}], "warnings": []}
```

Course files are discovered from `~/org/cs*.org` plus `course_files` in
`cube.yaml`. The command only presents the desired course and lecture work.
`cube sync --source courses` performs reconciliation.

### `literature`

```json
{"generated": "2026-09-04T06:45:00+03:00", "date": "2026-09-04",
 "counts": {"fetched": 812, "matched": 9, "summarised": 2, "pending": 0},
 "path": "briefings/literature/2026-09-04.md",
 "json_path": "briefings/literature/2026-09-04.json",
 "digest_exists": true,
 "entries": [
   {"id": "arxiv:2609.01234v1", "source": "arxiv|biorxiv",
    "url": "https://arxiv.org/abs/2609.01234v1", "title": "...",
    "one_paragraph_summary": "...",
    "relevance": [{"kind": "student|project|goal|topic|agent", "ref": "gus-student",
                   "why": "one sentence quoting the matched term or title"}],
    "priority": "high|normal|low", "doi": null, "matched": ["knowledge graph"]}]}
```

`entries` is today's digest, empty until the `literature` agent has run.
`counts.pending` is how many fetched candidates still wait for a summary. The
cockpit renders one row per entry, opens `path` on `RET` and `entries[].url` on
`o`. Every entry always carries its source `url`.

### `papers`, `repos`, `approvals`

See the fixtures; field names are flat and self-explanatory. `papers[].state`
uses the org TODO sequence of `papers.org` verbatim; `org_heading` is
`papers.org::*<heading text>` and the cockpit matches it against the
heading titles (keyword and priority cookie stripped, exact or prefix
match) when it diffs states. `approvals[].kind` is
`outbound|write|contact`; `draft_file` (or `body_file`) is the file the
cockpit opens for review (`.diff`/`.patch` or channel `git` render as a
diff, everything else as markdown; email drafts are handed to Gnus, never
sent by the cockpit). `run_id` lets the cockpit jump to the tmux session
`cube/run-<run_id>`; `bead` and `recipient` are what `o` opens.

### `approve` and `reject`

```json
{"ok": true, "id": "cube-301", "action": "approve|reject",
 "result": "queued_for_send|draft_opened|applied|rejected", "message": "human text"}
```

The cockpit never sends anything itself. For `kind: outbound, channel:
email` it first hands the body to the Gnus Emacs (`claude-email-compose`
opens a message buffer; Robert sends with `C-c C-c`) and only then calls
`cube approve`, so the backend should treat an approved email as
`draft_opened`, never as `queued_for_send`. `cube approve <id> --body-file
state/drafts/<id>.edited.md` (proposed) records an approval whose body
Robert edited in the cockpit; the cockpit writes that file on the host
(TRAMP in remote mode) before calling.

### `decisions`, `decide` and `question new`

```json
{"generated": ISO,
 "decisions": [{"id": "cube-401|apr-...", "source": "bead|approval",
                "kind": "permission|question|approval|proposal|finding|conflict|recruit",
                "from": "agent:coordinator|role:senior|patrol:milestones|cube",
                "title": "...", "question": "the text Robert must answer",
                "summary": "at most 4 short lines to decide on",
                "body": "the request text without its header, at most 4000 chars",
                "duplicates": ["cube-402"],
                "options": ["yes","no"] | ["approve","reject"] | ["free"] | [...],
                "context": {"bead": "cube-401"|null, "epic": "cube-400"|null,
                            "run_id": "r-77"|null, "evidence": ["path#locator"],
                            "host": "ws|laptop"|null, "labels": ["needs:robert"],
                            "resource_class": "gpu"|null, "member_kind": "role"|null,
                            "spend_usd": 0.0, "approval_kind": "file_change"|null,
                            "targets": ["runs/x.md"], "deletes": false},
                "since": ISO, "age": SECONDS,
                "policy_preview": {"rule": 0, "by": "policy:0", "kind": "permission",
                                   "answer": "yes", "note": "why it is safe"}|null,
                "answer_command": ["decide", "cube-401", "--choice", "yes"]}],
 "answered": [{"id": "cube-390", "choice": "yes"|null, "text": "..."|null, "ts": ISO,
               "by": "robert|policy:0"}]}
```

Newest last. The sources are the pending outbound approvals and the open beads
labelled `needs:robert` whose kind is a decision: `resource:approval` and
`kind:request` become `permission` (yes/no), a recruitment request
(`pipeline-stage:recruit`) becomes `recruit` (yes/no), `kind:question` becomes
`question` with the options of its `Options:` body line or `["free"]`, and
`kind:proposal`, `kind:finding` and `kind:conflict` keep their kind with
`["accept","reject","free"]`. A `needs:robert` bead that is not a decision (a
weekly report, an incident) stays out of this list. `answered` holds the last
20 rows of `state/decisions.jsonl`. `context.host` is the host of the asking
standing agent; the cockpit delivers the answer there. `summary` is what the
cockpit prints under the row (`cube-decisions-body-lines`, default 4); `body`
is the full request, shown by `RET`. Identical asks (same kind, asker, title
and body) are folded: the newest is listed with the others in `duplicates`,
and `cube decide` on it answers them all.

`policy_preview` is the `cube.yaml` `decisions.policy` rule that would answer
this decision at the next `decisions` patrol tick, or null when it waits for
Robert. The cockpit shows it as a dim `auto: <answer> at next tick` tag after
the buttons, so Robert can pre-empt it with `n`. The extra `context` fields are
what the rules match on: the bead's labels, the `Resource class:` of a resource
request, the `Candidate:` prefix of a recruitment request, the declared
`spend_usd`, and, for an approval, its kind, the paths it would touch and
whether it deletes anything. `answered[].by` is `robert` for a hand answer and
`policy:<index>` for an automatic one.

`cube decisions apply-policy [--dry-run|--apply] --json` answers by hand what
that patrol would answer:

```json
{"dry_run": true,
 "answered": [{"id", "kind", "from", "title", "answered": true, "answer", "note",
               "policy": {...}, "guards": [], "plan": "permission"}],
 "waiting": [{"id", "kind", "from", "title", "answered": false,
              "policy": null, "guards": ["question"], "error": "..."}],
 "commands": []}
```

`guards` names the `never_automatic` reasons a decision stays human (outbound,
people, integrity, conflict, question, deletion, spend_over_budget); a decision
under any of them is never answered by a rule.

`cube decide ID (--choice CHOICE | --text TEXT) --apply --json` records the
answer in `state/decisions.jsonl`, acknowledges the matching `att-<id>`
attention item, appends an answered event, and routes by kind: an `approval`
goes through the same `ApprovalStore` path as `cube approve`/`cube reject` and
returns the same `{ok, id, action, result, message, approval}` shape under
`result`; a `permission` closes the bead with reason `robert: yes|no` and, on
yes for a `resource:approval` bead, writes a single-use grant into
`state/agents/<name>/grants.json` that the agent's next identical workday step
consumes; a `recruit` calls `cube pipeline recruit` (or `--deny`); a
`question`, `proposal`, `finding` or `conflict` comments `Robert: <answer>` on
the bead and closes it, except an accepted proposal, which stays open and gains
the label `approved:robert`. The answer then reaches the asker: a standing
agent's inbox, or, for a role, a `kind:request role:<role>` follow-up bead
titled `Robert answered: <title>` that the marshal dispatches.

When the asking agent lives on another host the command exits 3 with
`{"relay": HOST, "command": [...]}` after recording everything locally, exactly
like `cube agent inbox`; the cockpit re-runs that command with
`cube--call-json-async-on` on the named host. `--dry-run` (the default) prints
the routing plan and changes nothing.

`cube question new --from agent:NAME|role:NAME --text TEXT [--options a,b,c]
[--bead ID] [--epic ID] --apply --json` is the one command an agent uses to ask.
It creates a `kind:question needs:robert` bead with the standard header, xid
`question:<from>:<sha8 of the text>` (so asking twice is idempotent),
provenance from `CUBE_RUN_ID`, `--bead`, or the asker, a body of
`Question: TEXT` plus `Options: a | b | c`, and a `needs_robert` attention
event. It returns `{bead, xid, created, dry_run, question, options}`.

The cockpit shows the list in `*cube-decisions*` (`C-c b D`, or `D` on the
dashboard) and in the dashboard's Decisions section: `[Yes] [No]`,
`[Approve] [Reject]` or `[Answer]` text buttons (mouse-1 and RET), `y`, `n` and
`a` on the row, and `?N` next to `⚠N` in the mode line. An outbound approval
answered there still goes through the review queue, so an email draft opens in
Gnus and nothing is ever sent by the cockpit.

### `approvals show <id>` (proposed)

The approval object from `approvals` plus `body` (the draft text, so the
cockpit does not need file access) and, for email, `to` (address) and
`subject`. Fixture `approval-show.json`. Without this command the
cockpit reads `draft_file` through TRAMP.

### `beads show <id>` and `runs show <run_id>` (proposed)

`beads show` returns the `bd show --json` object (bd prints a one element
array; either is accepted) optionally extended with `dependencies[]`,
`dependents[]` (`id`, `title`, `status`) and `comments[]` (`author`,
`created_at`, `text`). Fixture `bead-show.json`; the cockpit falls back
to `bd show <id> --json` on the host, and `ready` falls back to
`bd ready --json` (fixtures `bd-show.json`, `bd-ready.json` are bd's own
shapes).

`runs show` returns `run_id`, `role`, `bead`, `runner`, `model`, `state`,
`started`, `finished`, `exit`, `log`, `notes_file`, `summary`, `notes`
(markdown text of `runs/<id>/notes.md`) and `log_tail[]` (last lines of
the log). Fixture `run-show.json`. Without it the cockpit reads
`runs/<id>/log.jsonl` and `notes_file` through TRAMP.

### `brief` (proposed)

```json
{"generated": ISO, "file": "briefings/YYYY-MM-DD.md", "markdown": "# Brief ..."}
```

Fixture `brief.json`. The cockpit shows `markdown` in `*cube-brief*`
and falls back to reading `file` from the host.

### `run`

```json
{"ok": true, "run_id": "r-YYYYMMDD-HHMM-xx", "role", "bead", "runner", "model",
 "needs_tools": bool,
 "pid": N, "log": "runs/<run_id>/log.jsonl", "tmux": "cube/run-<run_id>"|null, "started": ISO}
```

`runner` is a runner token: a plain harness (`claude`, `codex`, `openrouter`) or
`<harness>@<provider>` when a harness runs on a non-native provider
(`claude@openrouter`, `codex@openrouter`; ADR-0016).
`needs_tools` says whether routing required a tool-capable harness.

### `doctor`

```json
{"ok": bool, "checks": [{"name", "ok": bool, "detail", "fix": "optional one-liner"}]}
```

Doctor must include checks for: `claude`, `codex`, `codex-notify`
(`~/.codex/config.toml` has `notify = [".../emacs/bin/cube-emacs-hook", "codex"]`
in local mode, or `cube notify --hook` on the host), `tmux`, `beads`,
`events` (log readable), the installed corpus verification timer, configured
course sources, and that no role yaml lists an outbound `autonomous_actions`
entry.

## Hooks: `cube notify --hook`

Runs on the host inside the agent's hook. Reads one JSON document from
stdin and exits 0 always (never block an agent). Two payload shapes:

- Claude Code (`emacs/claude-hooks.json`, passed with `claude --settings`):
  `hook_event_name` is one of `SessionStart`, `UserPromptSubmit`,
  `Notification`, `Stop`, `SessionEnd`; other keys as Claude Code sends
  them (`session_id`, `cwd`, `message`, `notification_type`, `prompt`,
  `last_assistant_message`, `source`, `reason`). Fixtures `hook-stop.json`,
  `hook-notification.json`.
- Codex (`notify` in `~/.codex/config.toml`; Codex passes the JSON as the
  last argv element, the wrapper pipes it to stdin): `type`
  (`agent-turn-complete`), `thread-id`, `turn-id`, `cwd`,
  `input-messages`, `last-assistant-message`. Older builds used
  underscores; accept both. Fixture `codex-notify.json`.

Mapping to event names: `SessionStart` -> `start`, `UserPromptSubmit` ->
`prompt`, `Notification` -> `notification`, `Stop` -> `stop`,
`SessionEnd` -> `end`, `agent-turn-complete` -> `stop`. The session name
is `$CUBE_SESSION` (set by the cockpit via `env CUBE_SESSION=<name>` in
front of the agent command) and falls back to the agent's own session or
thread id. `resume_id` is that id, so the cockpit can `claude --resume` /
`codex resume` after a tmux session died. Long texts (`message`,
`last_assistant_message`) go to `state/bodies/<seq>.md`, referenced as
`body_file`.

`cube notify` also accepts direct use by Hermes profiles and patrols:
`cube notify --session NAME --event EVENT --title TEXT [--body-file F]
[--severity S] [--bead ID] [--run-id ID]`.

## Event log: `state/events.jsonl`

One JSON object per line, appended atomically by `cube notify`; never
rewritten (rotate by renaming at most once a day). The cockpit tails it
with `ssh HOST -- tail -n0 -F <root>/state/events.jsonl` (inotify in
local mode) and routes each line through `cube-notify` in Emacs.
Fixture: `events.jsonl`.

`cube tail` provides the same backend behavior for command-line consumers.
Without `--follow` it prints the latest 50 matching records by default. With
`--follow`, it starts at the end unless `--limit` requests an initial backlog,
waits for a missing file, and reopens it after truncation or rotation. Filters
are `--since ISO` and repeatable `--kind`; `--json` prints one object per line.

```json
{"ts": ISO, "seq": N,
 "source": "claude|codex|hermes|patrol|cube",
 "session": "alex-plan"|null,
 "event": "start|prompt|tool|stop|notification|end|attention|finished|error|approval|queued|goal",
 "severity": "info|attention|error",
 "title": "short text"|null,
 "body_file": "state/bodies/N.md"|null,
 "run_id": "r-..."|null, "bead": "cube-142"|null, "resume_id": "..."|null,
 "muted": true (only on a repeat; absent otherwise),
 "data": {}}
```

`tool` is one tool call of a Claude run, reported by the run's PreToolUse and
PostToolUse hooks (info; `title` is `<Tool> <target>`, for example `Read
README.md` or `Bash python3 audit_collect.py`; `data.tool` and `data.phase`
`pre|post`). Every Claude run installs these hooks and a Stop hook, so the
watch buffer can show the task being solved (ADR-0036). Hermes runs report
start, checkpoint, finished and error only. `tool` never changes the session
state and never notifies.

`queued` is a run that found no runner and waits for the marshal (info).
`goal` is emitted by the goals patrol once per completed goal (info,
`data.bead`). A loud event (`notification`, `attention`, `approval`,
`error`) that repeats the same source, session and title within 24 hours
is still logged but carries `muted: true` and `data.repeat_of` (the first
line's `seq`); the cockpit shows no desktop notification for it.

Cockpit state mapping: `start`, `prompt` -> running; `stop`, `finished`,
`queued`, `goal` -> idle; `notification`, `attention`, `approval` ->
attention; `error` -> error; `end` -> exited. Events with `session: null`
are keyed by `run_id`. Desktop notifications fire for `goal` and `error`
only (`cube-server-notify-events`), never for a muted repeat, at most once
per session and title per day, and always for a P0 incident.

`state/attention.json` is the materialised `cube attention` output,
rewritten by `cube notify` so the cockpit's 60 s poll fallback and the
Concierge read the same thing.

### `incidents`

```json
{"generated": ISO,
 "open": [{"id": "cube-142", "title": "DOWN: gateway", "severity": "p0|p1|p2",
           "host": "ws"|null, "service": "gateway"|null,
           "since": ISO|null, "age_hours": N|null}],
 "banner": null | {"severity": "p0|p1", "text": "...", "count": N, "bead": "cube-142"}}
```

`cube incidents --json` reads only open `kind:incident` beads. An incident is
`p0` when its `scope:external` label is present or its bead age reaches
`incidents.p0_after_hours` in `cube.yaml` (24 hours when absent); other open
incidents are `p1`. The banner names only the loudest incident's service,
host, since time, and the number of other open incidents. When present, the
same banner is the first `cube attention` item (`kind: incident`, `severity:
high`). `cube status --json` includes `incidents` as `{count, highest,
banner}` with that identical banner object.

### `budget`

```json
{"generated": ISO, "day": "YYYY-MM-DD", "days": N,
 "tiers": {"plan": {"runs": N, "tokens": N, "cost_usd": X,
                     "equivalent_usd": X,
                     "cap_runs": N|null, "cap_cost_usd": X|null,
                     "cap_equivalent_usd": X|null,
                     "pct": 0-100|null}},
 "runners": {"claude": {"runs": N, "tokens": N, "cost_usd": X,
                          "equivalent_usd": X,
                          "state": "ok|backoff|disabled|exhausted",
                          "until": ISO|null, "reason": "..."|null}},
 "attribution": {
   "projects": {"slug": {"today": USAGE, "week": USAGE,
                            "cap_usd_per_day": X|null}},
   "epics": {"cube-1": {"today": USAGE, "week": USAGE, "total": USAGE,
                           "cap_usd": X|null}}},
 "forecast": {"hours": 3,
               "tiers": {"plan": {"burn_usd_per_hour": X,
                                     "projected_day_end_usd": X}}},
 "controls": {"swaps": [{"tier": "implement", "from": TARGET,
                            "to": TARGET, "until": ISO, "reason": "..."}],
              "downgrades": [{"tier": "plan", "to": "implement",
                                "until": ISO, "reason": "..."}]},
 "ceilings": [{"name": "plan equivalent", "used": X, "cap": X,
                "pct": 0-100, "unit": "usd", "tier": "plan",
                "target": null}],
 "window": {"since": ISO, "until": ISO}}
```

`USAGE` is `{runs, tokens, cost_usd, equivalent_usd}`. `cube budget --json`
reports the current UTC day. `--days N` aggregates the inclusive N-day window
and `--week` selects seven days. Subscription-backed Claude and Codex runs have
zero billed `cost_usd`; `equivalent_usd` is the Claude-reported amount or a
token estimate from `prices` in `cube.yaml`. OpenRouter uses its reported cost
for both values. The text view contains the same tier, runner, attribution,
ceiling, forecast, swap, and downgrade data. `cube status --json` includes
`budget` as `{plan, implement, bulk, local, exhausted}`, where tier values are
percentages or null and `exhausted` lists runner names.

### `tier`

```json
{"generated": ISO,
 "tiers": {"plan": [{"runner": "claude", "model": "fable", "profile": null,
                       "state": "ok|backoff|disabled|exhausted|preferred",
                       "until": ISO|null, "reason": "..."|null,
                       "active": true|false}]}}
```

`cube tier --json` and `cube tier show --json` inspect runner state. The write
commands are `cube tier disable <runner>[:<model>] (--until ISO | --for 5h)
[--reason TEXT]`, `cube tier enable <runner>[:<model>]`, `cube tier prefer
<tier> <runner>[:<model>]`, `cube tier downgrade <tier> <to> (--until ISO |
--for 5h) [--reason TEXT]`, `cube tier undowngrade <tier>`, and `cube tier
reset`. `cube tier status` lists active budget swaps and downgrades. Write
commands default to dry-run and require `--apply` to write `state/tiers.json`.
Disabled and exhausted entries are checked before transient backoff;
preferences only reorder usable entries within their configured tier.

### `assign`, `create`, `org`, and `kg propose`

`cube assign <bead> [--role R] [--person SLUG] [--project SLUG]` and `cube
create --title T --kind K ...` are dry-run by default. Their JSON includes the
resulting bead shape or planned header and `commands`, the exact `bd` calls.
`assign` validates the role, person and KG project before replacing assignment
labels. `create` refuses work without provenance and at least one acceptance
criterion.

`cube org append`, `cube org todo` and `cube org property` return:

```json
{"file": "~/org/person.org", "action": "append|todo|property",
 "diff": "unified diff", "applied": false}
```

They only write with `--apply`. They refuse Emacs locks, ambiguous headings,
paths outside the configured Org root and unclassifiable private content. An
applied write appends an `org-write` event. `cube org status --person SLUG`
uses the same shape with an empty diff and adds `last_dated_heading`,
`open_items` and `milestones`.

`cube kg propose <project> --set field=value ...` writes a proposed JSON-LD
node patch under `runs/kg/` only with `--apply`; it never modifies the research
KG checkout. Its result is `{project, patch, diff, bead, applied, commands}`.
The bead is `kind:outbound`, carries the patch as evidence and waits for
Robert's approval.

### `roster` and `roster sync`

`cube roster --json` reconciles the maintained Group section of `staff.org`,
the five public website profile groups, `roster.md`, the research KG, and the
`people.yaml` join table. `cube.yaml:roster` declares the authority and field
precedence. With ADR-0012's configuration, website membership and role win;
staff.org supplies programme, start and org-file fields only where configured.

```json
{"generated": "ISO",
 "sources": {
   "staff_org": {"path": "path", "section": "Group summer 2026", "read": "ISO"},
   "website": {"url": "URL", "fetched": "ISO", "cached": false},
   "roster_md": {"path": "path"},
   "kg": {"path": "path"}},
 "authority": "website",
 "people": [{"slug": "person", "name": "Name", "role": "student",
              "program": "PhD-Bioeng", "in": {"staff_org": true,
              "website": true, "roster_md": true, "kg": true,
              "people_yaml": true}, "status": "agree", "membership": "current",
              "pending": null,
              "conflicts": []}],
 "summary": {"agree": 1, "only_in": 0, "conflict": 0,
             "alumni_still_listed": 0}}
```

Roles are `student`, `postdoc`, `research-scientist`, `staff`, `visiting`,
`intern`, `visiting-faculty`, `pi`, or `alumni`. Status is `agree`, `only-in`,
`conflict`, or `alumni` and reports source consistency independently of the
authoritative membership decision.
`agree` requires compatible current entries in both maintained roster sources,
staff.org and the website. A non-conflicting entry missing from either is
`only-in`.
`--offline` reads the website cache under `state/website/` and never performs a
request. `cube roster sync` returns `{file, diff, applied}` and defaults to a
dry run. It writes website members to `people:`, keeps a staff.org-only current
member with `pending: not on roster of record`, and writes every other retained
identity to `former:` with `left:`. It preserves `org_file`, Mattermost and a
per-entry `source:` line. Every disagreement remains in `conflicts:` for the
existing conflict deriver.

### `projects`

`cube projects --json` returns one portfolio: first-class PA project pages,
then public research-KG grant nodes. PA frontmatter controls the PA row's kind,
status and privacy. It joins papers.org, `publications.csv` as a year fallback,
the GitHub snapshot, and open beads labelled `project:<slug>`:

```json
{"generated": "ISO", "projects": [{
  "slug": "project", "name": "Project", "kind": "research", "source": "pa",
  "privacy": "internal", "abstract": "optional public summary", "start_year": 2025,
  "end_year": null, "status": "active", "status_source": "pa:status-as-of",
  "members": ["person"], "lead": "person", "grants": ["grant"],
  "topics": ["topic"], "papers": {"count": 1, "last": "ISO"},
  "software": {"count": 1, "last_commit": "ISO"},
  "beads": {"open": 1, "in_progress": 0, "blocked": 0,
             "last_activity": "ISO"},
  "directories": [], "related": [], "public_kg": [{"iri": "borg-id:project/grant",
  "slug": "grant", "name": "Grant"}], "kg_iri": "borg-id:project/project", "pa_status": "active",
  "pa_status_as_of": "ISO", "last_activity": "ISO"}],
 "warnings": []}
```

Plain text groups active PA work first and grants by end year. Private PA rows
have `privacy: local-only` and always return `abstract: null`. A PA frontmatter
status is authoritative. Grant status uses the KG end-year and recent-activity
rule. `papers.last` uses linked papers.org state dates, then `publications.csv`
year data. `status_source` names the deciding signal. `cube status --json`
includes a `projects` summary with `total`, `active`, `ending`, `ended`, and
`unknown` counts.

### `goals`, `goal`, and People-board work

`cube goal new --title T --target YYYY-MM-DD --success TEXT` creates a
`kind:goal` epic. `--success`, `--person`, and `--provenance` are repeatable;
`--project` names a research-KG project. It defaults to dry run and returns the
planned header and exact `bd` commands. A goal header records `target`,
`success`, `project`, `owner: robert`, stakeholder `people`, and its stored
status. `at-risk` is always derived and is never written into the header.

`cube goals --json` returns:

```json
{"generated": "ISO", "goals": [{
  "id": "cube-400", "title": "Goal", "target": "YYYY-MM-DD",
  "days_left": 30, "status": "active|at-risk|done|dropped|proposed",
  "project": "slug", "people": ["person-slug"],
  "progress": {"total": 4, "closed": 1, "in_progress": 1,
                 "blocked": 1, "pct": 25},
  "on_track": true, "why": "schedule explanation",
  "blockers": [{"bead": "cube-402", "title": "...", "reason": "..."}],
  "next": {
    "agents": [{"bead": "cube-403", "role": "programmer", "ready": true}],
    "people": [{"person": "person-slug", "bead": "cube-404",
                 "title": "...", "due": "YYYY-MM-DD"}]},
  "last_activity": "ISO"
}]}
```

`cube goal show <id> --json` returns the same goal object with `success` and
the raw `children` list. `cube goal decompose <id> --runner stub --json` runs
the group-leader decomposition path and places the validated proposal in the
normal approval queue. Without `--apply`, no child bead is created. Approving
that review with `cube approve <approval-id> --json`, or decomposing with
`--apply`, creates ordinary child beads with both `parent: <goal-id>` and a
`goal:<goal-id>` label. Human children have `person:<slug>` and no role label;
agent children have `role:<name>`.

`cube goal spin <id> [--bead B] [--role R]` selects ready agent work by
priority and then deadline. It defaults to dry run and shows the selected bead,
assignment operations, and engine run plan. It never selects human work.

Each `cube people --json` row additionally has `goals` (goal ids), `owed`
(`bead`, `title`, `due`), and `next_meeting_agenda` strings. Owed work is open
work with `person:<slug>` and no role label. It is only an agenda item for
Robert. Creating it does not message the person; the normal `contacts.yaml`
grant and approval rules still apply to every delivery.

### `pipeline status`

`cube pipeline status EPIC --json` returns one research pipeline. With no epic,
it returns `{"pipelines": [PIPELINE, ...]}`. The single-pipeline shape is:

```json
{
  "epic": "cube-500",
  "title": "Research project",
  "status": "active|done",
  "stage": "collect|team|plan1:draft|plan1:critique|plan1:final|survey|plan2:draft|plan2:critique|plan2:final|experiments|gate|done",
  "iteration": 2,
  "stages": [
    {"name": "collect", "bead": "cube-501", "status": "closed",
     "owner": "liaison", "blocked_by": []}
  ],
  "team": [
    {"member": "agent:ontology", "role": "senior",
     "why": "topic match (source: agents/ontology.yaml)"},
    {"member": "role:programmer",
     "why": "implements experiments (source: roles/programmer.yaml)"}
  ],
  "discussion": [
    {"round": 1,
     "draft": {"bead": "cube-503", "status": "closed",
               "artifact": "runs/pipelines/cube-500/plan-v1-draft.yaml"},
     "critiques": [
       {"member": "agent:ontology", "bead": "cube-504", "status": "closed"}
     ],
     "final": {"bead": "cube-505", "status": "closed",
               "artifact": "runs/pipelines/cube-500/plan-v1.yaml"},
     "decisions": "runs/pipelines/cube-500/discussion/plan-v1/decisions.md"}
  ],
  "experiments": [
    {"bead": "cube-505", "status": "closed",
     "review": {"bead": "cube-507", "status": "closed", "verdict": "approve"}}
  ],
  "gate": {"n": 2, "bead": "cube-512", "verdict": "approve"},
  "kill": false,
  "manager": {"lead": "agent:coordinator",
              "last_review": "2026-09-03T07:00:00+00:00", "stale": []},
  "next": "The research pipeline is complete; no actor is waiting."
}
```

Every stage row reports its current blockers. A person critique has only a
related dependency and never blocks a final plan. Experiment review is null
until the engine creates the ordinary review bead. `manager.stale` lists open
coordinator findings. `kill` becomes true when an iteration or experiment kill
condition has stopped automatic progress.

### Proactive budget extensions

`cube budget --json` retains the daily `tiers`, `runners`, and `window` objects
and adds the following keys:

```json
{"windows": {"claude": {"started": ISO|null, "resets": ISO|null,
                           "tokens": N, "cap": N|null, "pct": N|null},
              "codex": {"started": ISO|null, "resets": ISO|null,
                         "tokens": N, "cap": N|null, "pct": N|null}},
 "credits": {"openrouter": {"remaining_usd": X|null, "checked": ISO|null}},
 "swaps": [{"tier": "implement", "from": "codex", "to": "claude:sonnet",
             "until": ISO, "reason": "soft cap 90% on codex until ISO"}]}
```

`cap` for Claude and Codex is a local estimate learned from the first usage-limit
message that includes a reset time. `cube budget import [--since DATE]` reads
local Codex rollouts and Claude Code transcripts, tags imported records as
`interactive`, and is dry-run by default. `--apply` updates the ledger.

`cube status --json` exposes active budget swaps under `budget.swaps`; the key
may be omitted when the list is empty for compatibility with older cockpit
payloads. The budget patrol never disables runners and never sends requests
outside OpenRouter's credits endpoint.

### Adopted sessions and project runner profiles

`cube adopt <tmux-session> --project SLUG [--bead ID] [--role programmer]`
adopts an existing tmux agent session. It is dry-run by default and requires
`--apply` to rename or record anything. JSON returns:

```json
{"ok": true, "session": "cube/project-codex", "runner": "codex",
 "resume_id": "uuid"|null, "cwd": "/absolute/checkout", "project": "project",
 "bead": "cube-44"|null, "role": "programmer", "adopted": true,
 "dry_run": true, "renamed_from": "old-name"|null,
 "rollout": "/path/to/verified-rollout.jsonl"|null,
 "alternatives": [{"resume_id": "uuid", "path": "/path", "source": "tui|exec",
                    "modified": "ISO"}],
 "commands": [["tmux", "rename-session", "-t", "old-name",
                "cube/project-codex"]], "message": "human explanation"}
```

Codex matching reads only the first `session_meta` record in each rollout and
requires its `payload.cwd` to equal the tmux pane path. A matching `source:
tui` is preferred for an interactive session, with newest modification time
breaking ties. Other matching rollouts are returned in `alternatives`. No
match is not an error: the session is adopted with `resume_id: null` and the
message says why. Claude matching uses the encoded cwd directory under
`~/.claude/projects`; Hermes adoption has no resume id.

Applied records live in `state/sessions.json` as `{"sessions": [...]}` and
produce an `adopted` event. With `--bead`, a verified resume id is also stored
under `state/sessions/<bead>.json`. A later `cube run programmer --bead ID
--resume` uses that id.

Every `cube fleet --json` session has `project`, `cwd`, `resume_id`, and
`adopted`, with null values and `false` for an ordinary session. `cube status
--json` includes `counts.running` and `counts.adopted`.

A configured `projects.<slug>` runner profile is applied when the bead has a
`project:<slug>` label. The run JSON adds `project`, `cwd`, `runner_profile`,
and `pre_steps`. `runner_profile.effective_cwd` is the resolved checkout or
project worktree, and environment values containing `$PWD` are expanded
against it. Pre-steps run in listed order before the runner. A non-zero result
stops the run and writes an `error` event naming the failed step. Codex
`danger-full-access` is accepted only when the current hostname equals the
configured orchestration host. Dry-run output includes the effective profile,
the planned pre-steps, and the exact runner command without executing them.

### Standing agents

`cube agent list --json` returns named standing agents with identity, live
state, inbox count, proposal count, and today's resource use:

```json
[{"name": "coordinator", "kind": "coordinator", "title": "Group coordinator",
  "topics": ["topic"], "runtime": "claude", "tier": "plan",
  "state": "idle|working|talking|paused", "session": "cube/agent-name|null",
  "last_journal": "ISO|null", "pending_proposals": 0, "inbox_unread": 0,
  "resources_used_today": {"gpu_hours": 0, "runs": 0, "spend_usd": 0}}]
```

`cube agent talk [name]` defaults to `coordinator`, and returns its tmux name,
the assembled context-file path, and the command in dry-run mode. `cube agent
tell <name> TEXT` appends a durable inbox record and sends it to a live tmux
session when one exists. `cube agent workday <name> --now` runs only declared,
resource-checked steps. It writes approval beads for restricted resources and
never bypasses `cube contact check` for outbound actions.

The `agents` key in `cube status --json` is a compact cockpit summary:

```json
{"agents": [{"name": "coordinator", "kind": "coordinator", "state": "idle",
             "pending_proposals": 0, "inbox_unread": 0}]}
```

### `fleet drill status`

`cube fleet drill status [BEAD] [--date YYYY-MM-DD] [--json]` is a read-only
report on the hello-world fleet drill. It reads the drill bead and every
`agents/*/inbox.jsonl` and runs no model. `cube fleet drill start
[--agents a,b] [--json] [--dry-run|--apply]` creates the bead and `cube fleet
drill run [--json] [--apply]` also runs the coordinator's workday.

```json
{"bead": "cube-101", "date": "2026-09-05",
 "agents": {"ontology": {"told": true, "told_ts": "2026-09-05T09:00:00+00:00",
                         "replied": true, "replied_ts": "2026-09-05T09:20:00+00:00"}},
 "routes": {"coordinator_to_agent": {"n": 2, "of": 3},
            "agent_to_coordinator": {"n": 1, "of": 3},
            "agent_to_agent": {"asked": true, "answered": true, "relayed": false},
            "agent_to_robert": {"summary_comment": false, "closed": false}},
 "complete": false,
 "missing": ["genomics has not replied to the coordinator"]}
```

`told_ts` and `replied_ts` are null when the message has not arrived. `bead` is
null when no drill bead exists for the date, and `missing` then names that.

### `work`

`cube work --json` is the one call behind the cockpit work section: what the
cube is working on, joined from `agents/*.yaml`, the live leases, the run
metadata, the Beads ledger and the pipeline view. It writes nothing.

```json
{"generated": "ISO",
 "agents": [{"name": "coordinator", "kind": "coordinator", "host": "ws", "cron": "hourly",
             "state": "running|idle|paused|killed|not-due",
             "current": {"bead": "cube-pjr.4", "title": "...", "run_id": "r-...",
                         "since": "ISO", "runner": "openrouter", "model": "..."},
             "assigned": [{"bead": "cube-pjr.4", "title": "...", "status": "in_progress",
                           "stage": "plan1:final", "epic": "cube-pjr"}],
             "inbox_unread": 2, "last_workday": "ISO|null", "next_tick": "hourly",
             "today": {"runs": 1, "spend_usd": 0.0}}],
 "tasks": [{"bead": "cube-pjr.4", "title": "...", "status": "in_progress",
            "owner": "agent:coordinator|role:programmer|null", "epic": "cube-pjr",
            "stage": "plan1:final", "kind": "goal|design|experiment|review|request",
            "deadline": "ISO|null", "running": true}],
 "epics": [{"bead": "cube-pjr", "title": "...", "stage": "plan1:final",
            "next": "waiting for ...", "open": 7, "done": 3}]}
```

`current` is the live lease whose bead carries the agent's `agent:<name>`
label, or, when no bead names the agent, a lease whose role belongs to that
agent alone. `state` is `killed` under `state/KILL`, `paused` under the agent's
`PAUSED` marker, `running` while a lease matches, `idle` when the workday timer
is due, and `not-due` otherwise. `tasks` are the open and in-progress beads
carrying an `agent:`, `role:` or `pipeline-stage:` label, plus every
`kind:goal`, sorted running first, then in-progress, then by deadline. `epics`
come from the research pipelines with their stage and next actor. The text view
prints one table per block.

### `agent inbox`

`cube agent inbox NAME [--now] [--json] [--dry-run|--apply]` lists an agent's
inbox, read and unread. With `--now --apply` it runs an inbox-only workday:
only the unread messages and the assigned beads those messages name, at most
`workday.runs_per_tick` steps, and never the default reading step. Dry run
prints the plan without running a model.

The pass runs on the agent's own `host:`. Issued anywhere else the command
answers with the command to run there and exits 3:

```json
{"agent": "coordinator", "relay": "ws",
 "command": ["cube", "agent", "inbox", "coordinator", "--now", "--apply", "--json"]}
```

The cockpit uses that host with `cube--call-json-async-on`, so `i` on an agent
row always reaches the machine the agent lives on.

### Laptop liaison and multi-host dispatch

Host names are execution labels, not shared filesystem mounts. `cube status
--json` includes the active `host` and a peer probe payload:

```json
{"host": "laptop", "peers": [
  {"name": "ws", "reachable": true, "sha": "abc123", "lag_commits": 0}
]}
```

Every row from `cube agent list --json` includes `host`. `cube request AGENT
TEXT [--due YYYY-MM-DD] [--host HOST]` is dry-run by default and creates a
`kind:request` bead labelled `agent:AGENT` and `host:HOST`. The coordinator
uses it for mail, files, memories, and calendar context that exists only on
the laptop.

`cube worker --once --host laptop` considers host-less beads and
`host:laptop` beads. It reports another host's bead in `last.skipped` with
reason `host`. The `cube-worker-laptop.timer` runs this pass every five
minutes on `lc-dell`.

`cube relay HOST CUBE-ARGS... --json` attempts a non-interactive SSH delivery
with a 10 second connect timeout. Its JSON includes `reachable`, `queued`,
the bounded command, the remote `result` when available, and an `error` when
not. An unreachable peer is not a command failure: `queued` is true because
the request or answer remains in Beads for the next Dolt sync.

A non-sensitive liaison mail answer is stored in the closed request bead as
an `answer` mapping with numbered ideas, Message-ID, and paragraph numbers.
A personal-category answer stores its text only in
`state/agents/liaison/answers/<bead>.md` on the laptop. The bead is labelled
`privacy:local-only` and its `answer` mapping contains only the pointer, item
counts, and Message-ID paragraph provenance. Neither form stores the full mail
body, address list, or attachments in Beads.

## Watching one task (`cube-watch`)

`cube-watch BEAD` (global key `f`) opens `*cube:watch:BEAD*`: the bead from
`cube bead-show` (falls back to `bd show`), the newest run for the bead from
`cube status` `runs[]` and `cube run-show`, the event backlog from `cube tail
--bead BEAD --limit N --json`, and then every live line from the event tail
that carries the bead id, the run id or the session `run-<run_id>`. A
state-changing event (start, stop, finished, checkpoint, error, attention,
approval, queued, end) refetches the bead and the run two seconds later.

Keys: `p` runs `cube run ROLE --bead BEAD --dry-run --show-prompt --json` and
shows runner, model, command and prompt; `s` is `cube-run-bead` (dry-run,
confirm, `cube run ... --attach` in tmux `cube/run-ROLE-BEAD`); `S` adds
`--resume`; `a` jumps to that rolodex session; `o` opens the run directory
(TRAMP) and `O` its `audit.md`, `notes.md` or `result.json`; `r` shows `cube
review BEAD --dry-run --json`; `A` opens the approval queue. ROLE is the
bead's `role:` label, else asked.

`cube-watch-new` (global key `F`) asks title, kind, role, project, privacy,
acceptance, provenance and extra `key:value` labels, runs `cube create ...
--label repo:owner/name --dry-run`, shows the plan, applies after
confirmation and opens the watch buffer. `cube create --label` is repeatable
and validated as `key:value`.
