# Hermes profiles

borg-cube adds three Hermes profiles on ws next to the existing `hermes-ws`
agent, which stays untouched (its source of truth is
`~/Public/software/borg-infrastructure/hermes-infra/`, deployed by
`hermes-infra/deploy/deploy.sh`).

| Profile | Bot account | Who may talk to it | Purpose |
|---|---|---|---|
| `advisor` | `@borg-advisor` | students with a `mattermost_dm` grant in `contacts.yaml`; nobody by default | student-facing check-ins (Phase 4 pilot); per-DM sessions (ADR-0003) |
| `concierge` | `@borg-concierge` (name chosen at bot creation) | Robert only | remote control: attention list, approvals, `cube run`, briefings |
| `scribe` | none (no gateway) | invoked by `cube run scribe` | meeting-note and check-in drafts, never sends |
| `hermes-ws` | `@hermes-ws` | Robert, the infrastructure postdoc | existing infra monitor; the sysadmin role builds on it |
| `cube-worker` | none (no gateway) | invoked by cube runs (`hermes@local`) | most roles' runs on the group's own endpoint (ADR-0022); dangerous commands denied except the two script-execution classes; context bounded to the endpoint's 131072 window (ADR-0027) |

Each profile is `HERMES_HOME=~/.hermes/profiles/<name>`, started as
`hermes -p <name> ...`, with its own `config.yaml`, `.env`, `skills/`,
`transcripts/` and (advisor only) `context/`.

## Rendering

`config.yaml.tmpl` files here are rendered by `cube hermes render <profile>`
into `ws:~/.hermes/profiles/<profile>/config.yaml`. The only placeholders are
`{{PROFILE}}`, `{{CUBE_ROOT}}`, `{{VLLM_BASE_URL}}`, `{{MATTERMOST_URL}}`,
`{{MATTERMOST_ALLOWED_USERS}}` and `{{MATTERMOST_HOME_CHANNEL}}`.

- `MATTERMOST_ALLOWED_USERS` for `advisor` is generated from `contacts.yaml`
  grants with channel `mattermost_dm` only. No grants, empty list, the bot
  answers nobody. For `concierge` it is Robert's user only; the renderer
  refuses anything else.
- After rendering: `hermes -p <profile> config validate` (Hermes key names
  drift between versions; the pinned version on ws is authoritative), then
  `systemctl --user restart cube-gateway-advisor` (or the concierge unit).
- Revoking a grant re-renders and restarts; revocation is immediate.

## The gateway's own settings (hermes-ws)

`~/.hermes/config.yaml` on ws is not rendered from here. Robert, 2026-09-08
(ADR-0027): `display.tool_progress: 'off'` stops the per-tool-call messages in
his DM (applied with a dated backup); `approvals.mode: smart` would let an
auxiliary model approve low-risk flagged commands such as an `execute_code`
script that runs `ls | grep`; Robert approved it on 2026-09-08 (bead
`cube-pe17`) and it is applied, with a dated backup next to the file.

Two more DM posts wait for his decision (bead `cube-wocr`, 2026-09-08):
`display.memory_notifications: off` ends the "Self-improvement review: Memory
updated" line, `display.platforms.mattermost.long_running_notifications:
false` the "Working, N min" heartbeat. Both are a config edit on ws.

## The worker profile (cube-worker), what is verified

Checked on ws on 2026-09-08 against the pinned Hermes:

- `model.max_tokens: 8192` and `model.context_length: 131072` are honoured: a
  single query of 70k tokens through `hermes -p cube-worker` answered in 65 s
  (session `20260908_091804_0497db`). A long workday still produced one
  "requested 65536 output tokens" 400 at about 65k input tokens (session
  `20260908_080116_2d4189`, after 37 good calls) followed by context
  compression that made no progress for 600 s; where that 65536 comes from was
  not found in the Hermes source. Such a run ends at the cube's 1800 s
  deadline and is logged as `hermes timeout after 1800s; no result before the
  deadline`, not as "no JSON object in output".
- The `command_allowlist` pattern keys in the template do not unblock the
  worker's `python3 -c` and heredoc scripts: in single-query deny mode Hermes
  (`tools/approval.py`, `check_all_command_guards`) consults only command
  text and globs, never pattern keys (probe session
  `20260908_091219_264d67`, blocked with the entries installed). The way
  through, `approvals.single_query_mode: approve` plus an `approvals.deny`
  list, is a security decision and waits for Robert (bead `cube-e64t`).

## Providers

All profiles default to OpenRouter (the model `hermes-ws` uses today) with
`providers.local` pointing at vLLM on node005 (`VLLM_BASE_URL`) as fallback.
No profile ever uses Anthropic OAuth (ADR-0006). `privacy:local-only`
material does not go through a profile at all; cube routes it to the local
runner directly.

## Hooks

`hooks/pre_prompt_student_context.sh` prints
`~/.hermes/profiles/advisor/context/<mm-user>.json`, rendered by
`cube student context --mm-user <u> --json` (weekly and before check-ins).
Unknown user, missing file or stale file means no context. The hook is
covered by tests with a synthetic profile directory.

## Deployment

Mirrors `hermes-infra/deploy/deploy.sh`: from the laptop or ws,
`just deploy-skills` rsyncs `skills/<skill>/` into
`ws:~/.hermes/profiles/<p>/skills/<category>/<skill>` (category from
`metadata.hermes.category`), `cube hermes render <p>` writes the config,
`.env` is created by hand once from `profiles/advisor/env.example` (mode
0600), and the gateway runs under the user units in `systemd/`. Nothing here
touches `ws:~/.hermes/config.yaml`, `ws:~/.hermes/AGENTS.md` or
`ws:~/.hermes/scripts/infra/`.

## Bot accounts

Bot accounts are created by the Mattermost sysadmin (Robert) on
`borg.bio2vec.net`; `EnableBotAccountCreation` is already on. Tokens go into
the profile `.env`, never into the repo. The advisor bot is created in Phase 4
only.
