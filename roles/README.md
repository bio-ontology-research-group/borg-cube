# Roles

One YAML file per role, one system prompt per role under `prompts/`. The
schema is in `_schema.yaml` and enforced by `cube/roles/loader.py`; `cube
doctor` validates every file and fails if any `autonomous_actions` entry is
outbound.

Roles and their runtimes (from `doc/plan.md`):

| Role | Runtime | Tier | Prompt |
|---|---|---|---|
| group-leader | claude (Fable, fallback Opus) | plan | prompts/group-leader.md |
| senior | claude (Opus) | plan | prompts/senior.md |
| programmer | codex (`cube-chatgpt` profile), fallback claude Sonnet | implement | prompts/programmer.md |
| auditor | codex read-only collection, claude Opus verdict | plan | prompts/auditor.md |
| editor | claude Opus/Fable plus codex second opinion | plan | prompts/editor.md |
| lecturer | claude Opus with presentation skills | plan | prompts/lecturer.md |
| scribe | hermes `scribe` profile or claude Sonnet | bulk | prompts/scribe.md |
| advisor | claude Opus, local vLLM for local-only; hermes `advisor` profile for granted students | plan | prompts/advisor.md |
| sysadmin | hermes `hermes-ws` (patrol), claude Opus (diagnosis), codex (config PRs) | plan | prompts/sysadmin.md |
| secretary | claude Opus with a browser session Robert logged in to | plan | prompts/secretary.md |
| sentinel | python, no LLM | none | prompts/sentinel.md |
| marshal | python, optional cheap prioritisation | bulk | prompts/marshal.md |
| concierge | hermes `concierge` profile, Robert-only DM | bulk | prompts/concierge.md |
| liaison | claude through OpenRouter on the laptop, reads bounded to `hosts.laptop.readable` (ADR-0027) | plan | prompts/liaison.md |

Conventions:

- `tier` is the tier of the role's judgment run. Roles with a cheaper
  collection pass (auditor, sysadmin) describe it under `triggers` and
  `hard_rules`; the engine runs the collection pass at `implement` or `none`
  and the verdict at `tier`.
- `privacy_max` is the strictest class the role may receive. The router still
  forces the `local` runner for any `privacy:local-only` bead regardless of the
  role's default runtime; if local is down the run queues.
- `autonomous_actions` is empty for every role. Every message, DM, email, PR,
  comment, form submission or signature becomes a `kind:outbound` bead for
  Robert. This is doctrine (`brain/doctrine.md`), not a phase setting.
- `read_roots: host` (liaison) bounds file reads to the running host's
  `readable` directories: the Claude Code runner adds `Read(//root/**)` allow
  rules and deny rules for `unreadable` directories; the role lists no Read,
  Grep or Glob and searches with `cube lookup` (ADR-0027).
- Prompts are short. They reference `brain/doctrine.md` and the playbooks by
  path instead of restating them; the engine appends the doctrine excerpt and
  skill paths at run time.
- Adding a role: copy `_schema.yaml`, fill every key, write the prompt, add
  the row above, run `cube doctor`.
