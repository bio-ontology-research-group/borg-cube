# ADR-0022: Most roles run on Hermes against the group's own endpoint

Status: accepted
Date: 2026-09-07
Extends: ADR-0021 (local endpoint first), hermes/README.md (profiles)

## Context

Measured on 2026-09-07 on the same task (run `uname -n`, answer the
hostname), input tokens per model call: Hermes 13.7k with all toolsets and
6.9k with the terminal toolset only, pi 29.9k, Claude Code 34.8k bare and
55.7k inside the cube, Codex 44.7k. vLLM prefix caching at the endpoint hides
most of the repeat cost, but the prompt is still what the endpoint holds in
cache per agent. Robert: switch most roles to Hermes, shorten the role
prompts.

Two facts about Hermes decided the shape. The top-level one-shot form
(`hermes -z`) forces yolo mode and auto-approves every dangerous command; a
single-query chat (`hermes chat -q ... --oneshot`) denies them
(`approvals.single_query_mode`, default deny), and with `-Q` prints only the
final message. Its usage file is written for `-z` only; the profile's SQLite
session store holds the token counts for both.

## Decision

1. `hermes@local` is a runner: Hermes on a dedicated profile `cube-worker`
   (no gateway, no skills, no memory, provider `local` on the endpoint,
   `approvals.single_query_mode: deny`), invoked as `hermes -p cube-worker
   -m <model> --provider local chat -q <prompt> --oneshot -Q -t <toolsets>`
   with `COLUMNS=4000`. Toolsets follow the role's permission mode:
   `terminal` for read-only roles, `terminal,file` for workspace-write. The
   session id comes from stderr and the usage from `state.db`.
2. Tier entries gain `not_for`: the plan tier starts with `hermes@local` for
   every role but the sysadmin, which keeps Claude Code and its per-command
   allowlist; the implement tier keeps Codex first for the programmer's
   sandbox and offers Hermes to everyone else; the bulk tier starts with
   Hermes. The rest of ADR-0021 is unchanged: local entries first, OpenRouter
   Flash as the only fallback.
3. The dangerous-command guard replaces Claude Code's allowlist for the
   roles that moved: a flagged command (delete, service restart, sudo, and
   the rest of Hermes' patterns) is blocked and reported to the model, never
   run. The role prompts keep their read-only rules.
4. `roles/*.yaml` `runtime` stays as written: it names the harness family a
   role was written for and gates agent declarations; the tiers decide where
   a run goes.
5. Role prompts were shortened by one Opus agent per prompt with the rule
   that no hard rule, path, command shape, kind or threshold may go. They
   landed at 62 to 76 percent of their length; the remainder is rules. The
   repository's `bd prime` SessionStart hook no longer fires inside a cube
   run (`CUBE_RUN_ID` set), which removes 11 KB from every Claude Code turn.
6. `cube hermes render cube-worker` renders the profile from
   `hermes/profiles/cube-worker/config.yaml.tmpl`; `cube doctor` checks the
   profile exists with the deny setting on the host that has Hermes entries.

## Consequences

- Per-turn prompt for the moved roles drops from 56k to about 7k plus the
  role prompt; the endpoint serves more agents from the same cache.
- The laptop has no Hermes binary, so its liaison runs keep Claude Code on
  the local endpoint; the router's availability check handles that.
- Hermes has no equivalent of a Bash prefix allowlist; a command that is
  neither dangerous by Hermes' patterns nor in the role's rules would run.
  The read-only roles are review and reading roles; the sysadmin, the one
  role whose commands touch hosts, stays on Claude Code.
