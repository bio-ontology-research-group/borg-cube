# CLAUDE.md - borg-cube operating guide

This file is authoritative for any agent working in this repo (Claude Code,
Codex via the AGENTS.md mirror, Hermes profiles via their skills). Read it
before acting. The approved design is `doc/plan.md`; decisions are `adr/`;
standing rules are `brain/doctrine.md`.

## What this repo is

The orchestration layer for the BORG research group: a Beads work ledger,
roles (group leader, senior, programmer, auditor, editor, lecturer, scribe,
advisor, sysadmin, secretary, sentinel, marshal, concierge), runners for
Claude Code, Codex, Hermes and local vLLM, deterministic patrols, a skills
library with a grounding corpus, and an Emacs cockpit. It runs on the office
workstation `ws`; laptops are thin clients over ssh.

It is NOT the group model. People, projects, papers, software and courses
live in `~/pa` (private KG, contacts, deadlines), `~/org` (per-person notes,
staff.org, papers.org) and the research knowledge graph
(`~/Public/software/website/research-knowledge-graph`). Read them; never copy
them here. Beads holds work items and provenance only.

## Hard rules

- **Research autonomy.** Researchers can access research resources, choose
  experiments within their charter and active high-level goals, and reproduce
  and document relevant results supplied by the literature agent. Central
  fleet limits bound compute, concurrency, storage headroom, and expenditure.
  Submit Slurm jobs to IBEX (`ssh dragon`) or `unimatrix01` through
  `cube fleet submit`. Robert can raise or lower central limits through the
  Mattermost agent (`hermes-ws`); researchers cannot raise their own limits.
- **Fleet GitHub authorization.** Document research code, methods, environment
  commands, evidence, and all outcomes, including negative results, in private
  `borg-cube-fleet` repositories. Commits, evidenced bug issues, and improvement
  PRs there are authorized without individual approval. This does not authorize
  merging, deployment, or publication of protected information. Local-only work
  contributes safe metadata only; mail, org contents, and credentials stay local.
- **Other outbound contact is denied by default.** Beyond fleet GitHub and
  communication with Robert himself, a person, channel, and action class need
  a grant in `contacts.yaml`. Without a grant, prepare an approval bead.
  Email, forms, signatures, service changes, and deletion retain their approval
  gates. Show the concrete evidence before execution.
- **Save Robert's time.** Routine decisions are batched twice daily in
  Mattermost. Progress belongs in GitHub and Beads; a completed goal produces
  one report to Robert. Interrupt immediately only for an urgent consequential
  decision. Changes to running systems and laptop access beyond standing
  grants need his decision. Research choices within goals and central limits,
  local checkout edits, and ordinary coordination do not.
- **Provenance or nothing.** Every bead starts with the YAML header (`xid`,
  `provenance[]`, `deadline`). No fact enters beads, briefings or `bd
  remember` without a source (path + locator, Message-ID, Mattermost
  permalink). The pa repo's ADR-0002 records a fabricated grant node; do not
  repeat it. Conflicts between sources become `kind:conflict` beads, never a
  silent choice.
- **Privacy classes.** `public`, `internal`, `local-only`. `local-only` (student
  check-in transcripts, assessments, anything about grades, contracts, visas,
  personnel, health) runs only on the local vLLM tier or queues. Grades and
  HR details never enter beads at all.
- **Secrets.** Scoped, revocable tokens in the gitignored `.env`; never
  passwords; never print `.env`, `password*.md`, `auth.json`. Reference by
  path.
- **Never poll Mattermost on a schedule** (pa rule). Events come from the
  Hermes gateway or webhooks.
- **Sysadmin boundary.** Use fixed `cube boundary` inspection and proposal
  tools, never a general shell or unrestricted SSH/Python. Monitor free space,
  quota, inodes, and capacity for planned jobs. Propose each change as an
  immutable bundle with exact commands, rationale, expected impact,
  preconditions, postchecks, and rollback. Robert approves, denies, or modifies
  the bundle through Mattermost before deterministic execution. A modification
  is a new bundle requiring approval; approval never grants an unrestricted shell.
- **Forms** (secretary) are never delivered partially filled and never
  submitted or signed without approval.
- **Subscriptions.** Claude Max only through Claude Code itself (`claude`,
  `claude -p`) on this host; no Agent SDK with OAuth; Hermes uses
  OpenRouter, Codex OAuth or local. Codex workers use the `cube-chatgpt`
  profile; the default Codex config bills OpenRouter.
- **Writing.** No em-dashes anywhere. Sentence-case headings. Plain language.
  No markdown blockquotes for copy-paste text.
- **Git.** In fleet repositories, use the role identity, for example
  `Robert Hoehndorf (BORG Cube Fleet: ontologist)`, with
  `leechuck@leechuck.de`. This is Robert's fleet role attribution, never an
  LLM author or co-author. For this borg-cube checkout and other repositories,
  author as Robert Hoehndorf and commit or push only when explicitly asked.
  Fleet authorization does not change the conservative session-close policy here.
- **Smoke tests** use `--dry-run` or the stub runner; never a real send.
- **Hosts.** ws never reaches into the laptop (no ssh, no ping, no pull).
  What lives only on the laptop comes through the laptop liaison: a
  `kind:request` bead (`cube request liaison "..." --apply`), answered on the
  bead on the laptop and carried back by the ledger sync (ADR-0025). Name the
  absolute path. Standing grants cover existing `hosts.laptop.readable`
  roots, read-only `~/org/` including the synced Google Calendar, and
  bounded email reads through the dedicated Emacs/Gnus server. The liaison
  uses bounded tools only, with no general Bash, `bd`, `cube`, or arbitrary
  Emacs evaluation. Credentials remain inaccessible even inside readable roots.
  Other directory or tool requests go through Mattermost for a scoped grant;
  approval never switches the liaison to an unrestricted researcher role.
  Files and checkouts travel by an authorized, path-bounded push into
  `/mnt/data1/cube-drop/<bead>/` on ws with sha256 on the bead. Read access
  does not imply export permission; beads carry text, never file content
  (ADR-0026). Protected mail and org data remain local.

## Layout

- `cube/` Python package (`uv run cube ...`; every read command has `--json`,
  every write command has `--dry-run`). `cube doctor` first when in doubt.
- `roles/*.yaml` + `roles/prompts/*.md` role definitions.
- `brain/` doctrine, playbooks, rubrics, facts for `bd remember`.
- `skills/` agentskills.io skills; `corpus/` grounding manifest and distilled
  references; `tools/` corpus and skills tooling; `skills/seeded/` index of
  existing skills elsewhere.
- `hermes/`, `systemd/`, `deploy/` deployment templates for ws and node005.
- `emacs/` cockpit; `emacs/INTERFACE.md` is the JSON contract.
- `runs/`, `state/` gitignored runtime data; `state/KILL` stops everything.

## Working here

- `just` is the entry point (`just check`, `just test`, `just doctor`).
- Add or update a test for every script you touch (`tests/`, `tests/skills/`).
- Non-obvious decisions get an ADR (`adr/NNNN-title.md`).
- Beads: `bd prime` for context, `bd ready`, `bd update <id> --claim`, `bd
  close <id>`, `bd remember` for durable facts (through `cube brain push`).
- Existing skills to invoke rather than reimplement: presentation,
  write-edit-scientific-paper, write-paper-review, new-paper,
  personal-assistant, email-contacts (all mail via the Gnus emacs server),
  remote-connect, gog, social-media-agent, showboat, infra-monitor,
  semantic-web, kaust-compute, datawaha-backup. See `skills/seeded/index.yaml`.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

## Beads

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.
