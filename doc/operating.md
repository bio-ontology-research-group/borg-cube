# Operating

Day-to-day borg-cube work happens in the Emacs cockpit or in a shell on `ws`.
The cockpit guide is `doc/cockpit-guide.md`, the terms are in
`doc/glossary.md`, and the standing rules are in `brain/doctrine.md`.

Commands that can write normally default to a dry-run and require `--apply`.
The notable exceptions are `cube run`, `cube review`, `cube approve`, `cube
reject`, and `cube kill`; use their explicit preview or confirmation path as
described below.

## Daily routine

### Morning

- [ ] Open **Cube ▸ Dashboard ▸ Cockpit layout (`C-c b C`)** and wait for the
  dashboard sections to finish refreshing.
- [ ] Open **Cube ▸ Dashboard ▸ Loudest attention item (`C-c b !`)**, then work
  through `C-c b 1`, `C-c b 2`, and `C-c b 3` as needed.
- [ ] Generate the deterministic digest in a shell with `cube digest --apply`,
  then read `briefings/digest-YYYY-MM-DD.md`. It contains attention, last patrol
  runs, and recent events.
- [ ] Open **Cube ▸ Review ▸ Review queue (`C-c b v`)**. Read every proposal body
  with `RET` before approving with `a` or rejecting with `x` or `r` and a reason.
- [ ] Open **Cube ▸ Work ▸ Ready beads (`C-c b w`)** and claim, assign, or run
  only the work that should move today.

### Weekly

- [ ] Open **Cube ▸ Goals ▸ Goals (`C-c b O`)**. Review progress, days left,
  people owed work, ready agent work, and blockers for every active goal.
- [ ] Open **Cube ▸ Dashboard ▸ Budget (`C-c b U`)**. Check tier percentages,
  active swaps, exhausted runners, learned reset windows, and OpenRouter credit
  age.
- [ ] Open **Cube ▸ People ▸ Roster (`C-c b p`)**. Inspect conflicts with `RET`,
  preview reconciliation with `s`, and apply with `S` only after fixing the
  sources.
- [ ] Run `cube conflicts --json` and confirm that each source disagreement has
  an owner or has been resolved at the source.
- [ ] Check timer and worker state with `systemctl --user list-timers 'cube-*'`
  and `systemctl --user status 'cube-worker@3'`.

## Attention, work, and approvals

- `cube attention --json` returns the loudest approvals, `needs:robert` beads,
  conflicts, failures, and dead-session signals. In the cockpit use `C-c b !`.
- `bd ready --json` is the current ready-work command. The ready-bead cockpit
  view tries `cube ready --json` first and falls back to `bd ready --json`; the
  dashboard's Ready work section has no fallback if the `cube ready` endpoint
  is absent.
- `cube create ... --dry-run` plans a provenance-backed bead; use `--apply` to
  create it. `cube assign BEAD ... --dry-run` plans labels, deadline, priority,
  and assignment provenance; use `--apply`, optionally with `--run`.
- `cube approvals` lists pending intents. `cube approve ID` records approval and
  `cube reject ID --reason TEXT` records rejection. Ordinary approval does not
  send, submit, or write the target; preview with `cube deliver ID`, then use
  `cube deliver ID --apply` for the separately authorised delivery.
- A goal-decomposition proposal is a special approval. `cube approve ID`
  validates its saved plan and creates the goal's child beads in the same
  operation.

## Goals

Create a goal with a title, target, one or more success criteria, and
provenance:

```sh
cube goal new \
  --title "Goal title" \
  --target 2026-12-31 \
  --success "A testable result exists" \
  --provenance 'path/to/source::heading' \
  --dry-run
```

Repeat with `--apply` after checking the plan. `cube goals --json` lists goal
progress and `cube goal show ID --json` includes children, ready work, people,
and blockers. `cube goal decompose ID --dry-run` still invokes the group-leader
runner and creates a review proposal, but does not create child beads. Approve
that proposal before `cube goal spin ID --dry-run` and its checked `--apply`
run.

## Running and reviewing roles

- Preview with `cube run ROLE --bead ID --dry-run --show-prompt`. Without
  `--dry-run`, `cube run` invokes the selected runner immediately. Add
  `--attach` for a `cube/run-*` tmux session, or `--resume` to use the session
  saved for the bead.
- `cube review BEAD --dry-run` previews reviewer selection and invocation.
  Without `--dry-run`, it runs the reviewer. A direct human verdict uses
  `cube review BEAD --verdict approve|revise|reject --summary TEXT`.
- `cube worker --slots N` performs one Marshal pass and dispatches up to `N`
  ready items within the per-tier limits in `cube.yaml`. The checked-in worker
  unit currently invokes this one-pass form.
- Interactive sessions are `cube/*` tmux sessions on `ws`. The cockpit attaches
  with SSH. Closing a laptop buffer leaves remote tmux running.
- Adopt a pre-existing Claude, Codex, or Hermes tmux session with `cube adopt
  SESSION --project SLUG --dry-run`, then repeat with `--apply` after checking
  runner, checkout, resume ID, and proposed name.

Role definitions are in `roles/*.yaml`; `review_required_by` names the reviewer.
No role closes work around that gate, and no role has autonomous outbound
actions.

### Agentic harnesses on OpenRouter

The plain `openrouter` runner is one chat completion with no tools: it can
return text and nothing else. Work that has to run `cube`, `bd`, `git` or any
shell command needs an agentic harness. Claude Code and Codex both run against
OpenRouter GLM models, so that work is cheap without losing tools (ADR-0016).

A tier entry names the harness and the provider:

```yaml
- {runner: claude, provider: openrouter, model: z-ai/glm-5.3}
- {runner: codex, provider: openrouter, model: z-ai/glm-5.3-flash}
```

The runner is then identified everywhere by the token `claude@openrouter` or
`codex@openrouter`: in `cube run --json`, `cube tier`, `cube budget`, backoff
state and the price table. `runner: claude@openrouter` is an accepted spelling
of the same entry.

Routing skips chat-only entries when the work needs tools. `cube run` derives
that from the role (a non-empty `allowed_tools`, or a `permission_mode` of
`workspace-write` or `browser`); `--needs-tools` and `--no-needs-tools` override
it, and the report carries `needs_tools`. A skipped entry says
`<target> has no tools` in the route reason.

What the Claude Code runner injects, into the child environment only and never
onto the command line or into a file: `ANTHROPIC_BASE_URL`
(`https://openrouter.ai/api`, overridable with `OPENROUTER_ANTHROPIC_BASE_URL`
in `.env`), `ANTHROPIC_AUTH_TOKEN` from `OPENROUTER_API_KEY`, an empty
`ANTHROPIC_API_KEY`, the entry model in `ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
`ANTHROPIC_DEFAULT_OPUS_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL`, plus
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `DISABLE_TELEMETRY` and
`DISABLE_ERROR_REPORTING`. It runs under its own
`CLAUDE_CONFIG_DIR=state/harness/claude-openrouter` (created mode 0700), so
`~/.claude` and the Max login are untouched. The harmless
`[claude-code:unrecognized_model]` line it prints on stderr is ignored.

Codex uses the profile `cube-openrouter`, installed on ws as
`~/.codex/cube-openrouter.config.toml` from `deploy/codex-openrouter-profile.toml`.
It must set `model_provider = "openrouter"`, `wire_api = "responses"` and
`web_search = "disabled"`; `cube doctor` checks all three when a tier entry uses
`codex@openrouter`, along with the key, the binary and the config dir
(`check_harness_providers`, an error on ws and a warning on a laptop).

Cost accounting: Claude Code prices its runs with Anthropic rates, which are
wrong by about fifty times for a GLM run, so that number is discarded. The
budget ledger estimates from the `prices:` table in `cube.yaml` and bills the
estimate as both billed and equivalent cost, because OpenRouter does charge for
these runs.

To add another model: add the tier entry with `provider: openrouter` and add the
matching `claude@openrouter:<model>` or `codex@openrouter:<model>` price line in
the same edit. A missing price counts zero and understates spend. No code
change is needed.

## Standing agents

`cube agent list` shows the named coordinator and experts. `cube agent talk
[NAME] --apply` starts or reuses a persistent `cube/agent-NAME` conversation,
while `cube agent tell NAME TEXT --apply` puts a durable message in its inbox
and also delivers it to a live session. Both are dry-run by default.

`cube agent workday NAME --now --dry-run` previews a bounded workday; repeat
with `--apply` only after checking its assigned beads and resources. Pause or
resume future workdays with `cube agent pause NAME --apply` and `cube agent
resume NAME --apply`. Restricted resources create approval beads, all outbound
use remains denied, and the global kill switch wins.

## People and Org files

`cube people --json` is the operational people view and `cube student SLUG
--json` is one Robert-facing student dossier. There is no `cube student
context` subcommand. Assignment to `person:SLUG` affects Robert's ledger and
meeting views only; it does not contact that person.

Use the lock-aware writer for authoritative Org changes:

- `cube org append PERSON --heading TEXT --dry-run`
- `cube org todo FILE --heading-match TEXT --item TEXT --dry-run`
- `cube org property FILE --heading-match TEXT --set KEY=VALUE --dry-run`
- `cube org status --person SLUG --json`

The write commands show a diff. Repeat the same command with `--apply` only
after reading it. The Emacs Org transient under `C-c b o` performs this preview
and confirmation for you. Agent notes enter Org as draft material and are not
authoritative until Robert edits them.

## Sync and source conflicts

`cube sync --dry-run` compares the external group sources with Beads. Use
`cube sync --apply` only after reviewing create, label-update, close, and
conflict operations. Source disagreements become `kind:conflict` work. Resolve
the disagreement in the source of record, then run sync again.

`cube roster --json` compares `staff.org`, the public website and website
repository roster, the research KG, and `people.yaml`. Membership and role come
from the public website by policy. `cube roster sync --dry-run` shows the local
join-table change; `--apply` rewrites `people.yaml` from the agreed facts.

## Budget patrol and model controls

`cube budget --json` reports daily usage, subscription windows, runner state,
OpenRouter credits, and active swaps. `cube budget import --dry-run` reads local
Claude and Codex transcripts and calculates new interactive usage records;
`--apply` updates the budget ledger and learned reset windows.

Bulk work uses free OpenRouter models by default. This includes digests,
meeting-note drafts, summaries, and first-pass literature screening. Implement
work starts on Codex and falls back to free OpenRouter models before paid
models. Plan and review work stays on the Claude and Codex subscription tiers.

The budget patrol's soft cap is 85 percent. When run as `cube patrol budget
--apply`, it can install a reversible preference from the current runner to the
next usable runner until the learned reset or next midnight. It can also react
to OpenRouter credits at or below the configured USD 5 floor. It does not
disable runners globally. In addition to checking OpenRouter credits, it
refreshes `state/cache/openrouter-models.json` from OpenRouter's public model
catalogue at most once per day. Doctor reads this cache and never contacts
OpenRouter.

Manual controls are dry-run first:

```sh
cube tier show --json
cube tier disable codex --for 5h --reason "usage limit" --dry-run
cube tier disable codex --for 5h --reason "usage limit" --apply
cube tier enable codex --dry-run
cube tier prefer implement openrouter:tencent/hy3 --dry-run
cube tier free-first implement --dry-run
cube tier free-first implement --off --dry-run
cube tier reset --dry-run
```

Tier entries may carry `only: [role, ...]`. Such an entry is skipped for every
other role, with the reason `reserved for <role>` in the route. Since 2026-09-04
the Claude subscription appears once, in `plan`, as `{runner: claude, model:
opus, only: [group-leader]}`: every model call runs on OpenRouter, and only the
coordinator (group leader) may fall back to Claude Opus when the OpenRouter
entries are unavailable or backing off.

The cockpit's `C-c b T` menu previews and confirms the corresponding apply
operation. Controls affect new routing and do not stop a process already in
flight.

## Installed timers

The checked-in systemd timer files use the `ws` clock, which is Asia/Riyadh:

| Unit | Schedule | Intended check |
|---|---:|---|
| `cube-patrol-infra-hygiene.timer` | daily 04:00 | disks, certificates, backups, tunnels, upgrades, SLURM, local model |
| `cube-patrol-milestones.timer` | daily 07:00 | 180, 90, and 30 day milestone warnings |
| `cube-patrol-deliveries.timer` | hourly | send approved messages to people once contact hours (07:00 to 19:00 Asia/Riyadh, Sun to Thu) open |
| `cube-patrol-agent-workday.timer` | hourly | standing-agent workdays: `cron: hourly` agents (coordinator) every tick, `HH:MM` agents once a day |
| `cube-patrol-literature-watch.timer` | daily 06:30 | new arXiv, bioRxiv and medRxiv submissions matched against keywords, topics, projects and goals |
| `cube-patrol-papers.timer` | daily 07:10 | `papers.org` against paper directories |
| `cube-patrol-deadlines.timer` | daily 07:20 | 7 and 30 day deadline horizon |
| `cube-patrol-calendar.timer` | daily 17:00 | preparation work for tomorrow's meetings |
| `cube-patrol-student-digest.timer` | Thursday 12:00 | Robert-only student digests |
| `cube-patrol-repos.timer` | Monday 06:00 | GitHub scan, at most three audit candidates |
| `cube-patrol-data-pull.timer` | hourly | update the external data repositories |
| `cube-patrol-leases.timer` | every 15 minutes | expire dead leases and make work dispatchable |
| `cube-patrol-budget.timer` | every 15 minutes | evaluate tier usage and credit thresholds |
| `cube-patrol-decisions.timer` | every 15 minutes | answer the decisions `cube.yaml` `decisions.policy` covers; the rest wait for Robert |
| `cube-corpus-verify.timer` | monthly | verify corpus DOI metadata |

There are three important facts about the units as currently checked in:

1. `cube-patrol@.service` runs `cube patrol NAME` without `--apply`. Since the
   command defaults to dry-run, these scheduled patrols report plans but do not
   persist beads, events, cursors, data pulls, digests, lease expiry, or budget
   swaps. A manually checked applied run is `cube patrol NAME --apply`.
2. `cube-patrol-agent-workday.timer` names
   `cube-patrol-agent-workday.service`, but that service file is not currently
   present. The timer cannot run a standing-agent workday until the service is
   supplied.
3. `cube-worker@.service` runs `cube worker --slots %i`, which is a single pass,
   and restarts only after failure. It is not a continuously polling worker.

`cube systemd install --dry-run` lists every unit it would copy. `cube systemd
install --apply --enable` copies the checked-in files, reloads the user manager,
and enables every timer. It does not render schedules from `cube.yaml`, enable
`cube-worker@3.service`, enable a gateway, or install a Beads backup unit.

Inspect operations with:

```sh
systemctl --user list-timers 'cube-*'
systemctl --user status 'cube-patrol@papers'
journalctl --user -u 'cube-patrol@papers' --since today
```

## Deploying a laptop change to ws

The cockpit does not execute the laptop checkout. It calls exactly `ssh ws --
cube ...`, so the `cube` found on the host's non-interactive SSH `PATH` and the
checkout on `ws` must be current.

After every laptop commit:

1. On `ws`, change to `~/Public/software/borg-cube` and run `git pull`. Prefer a
   fast-forward-only pull when the deployment branch permits it.
2. Run `uv sync --all-extras` when Python dependencies or entry points may have
   changed.
3. Run `.venv/bin/cube doctor --json`, then verify the actual cockpit command
   with `ssh ws -- cube --version` from the laptop. An absolute `.venv/bin/cube`
   test does not prove that the cockpit's `cube` on `PATH` is current.
4. If units changed, run `cube systemd install --apply --enable`, then inspect
   the copied unit and its journal. The installer does not enable the worker or
   gateways.
5. Refresh the cockpit dashboard with `g` inside `*cube*`. A missing command or
   unexpected JSON shape in only one section often means version skew.

Do not deploy by copying runtime state, Beads data, secrets, `runs/`, or the
external group model from the laptop.

## Kill switch and recovery

`cube kill on` writes `state/KILL` immediately; `cube kill off` removes it, and
`cube kill` or `cube kill status` reports it. The Emacs `C-c b K` command asks
before calling the backend, but its current JSON wrapper is not accepted by the
`cube kill` parser. Use the CLI on `ws` until that interface mismatch is fixed.

The checked-in timer and gateway units have a `ConditionPathExists=!state/KILL`
condition, and patrols, workers, and standing-agent workdays also check the
marker. The switch prevents new starts or stops work at the next checked
boundary. It does not prove that every arbitrary process already running was
terminated. Inspect tmux, leases, and service state after turning it on. There
is no top-level `cube resume` command; clearing the global switch is `cube kill
off`.

## Diagnosis and logs

- `cube doctor --json` checks environment, paths, tools, authentication shape,
  tmux, role policy, and the Beads installation.
- `cube status --json` reports version, host, root, Beads availability, sessions,
  running and adopted counts, kill state, budget summary, incident banner,
  project summary, and standing-agent summary. It does not currently report
  timer or gateway service status.
- `cube fleet --json` reports host tmux sessions and live leases.
- `cube incidents --json` reports open infrastructure incidents and the P0 or
  P1 banner.
- `runs/YYYY-MM-DD/RUN-ID/` contains run metadata, output, transcripts,
  artifacts, and review files.
- `state/events.jsonl` is the cockpit event stream, `state/audit.jsonl` is the
  append-only action trail, and `state/cursors.json` stores applied patrol
  cursors.
- `journalctl --user -u UNIT --since today` is the systemd log. The cockpit's
  own command and reconnect log is the Emacs buffer `*cube-log*`.

For contact policy questions, run `cube contact check PERSON CHANNEL ACTION
--json` and read `doc/contact-policy.md`. For a sysadmin incident, run `cube run
sysadmin --bead ID --dry-run`; it diagnoses and quotes commands but does not
restart, cancel, edit configuration, or delete anything without Robert's
explicit request.
