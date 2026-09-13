# borg-cube: research-group agent orchestration suite

## Context

Robert wants a Yegge-style ("The Shape of Things to Come" / Wheelhouse) agent
orchestration system, but for the BORG research group at KAUST rather than a
software company. It coordinates Hermes agents, Claude Code and Codex; uses the
Claude Max subscription, ChatGPT subscription (via Codex), OpenRouter and local
GPU models for different purposes; monitors research projects, papers and
software; audits code; plays roles (student advisors, lecturers, a research
hierarchy with delegation). Real students, postdocs and scientists are members:
their progress is monitored, they are mentored, the system moves their projects
forward. Controlled from Emacs. Every skill grounded in methodology literature.
Group outputs: papers, software, services, lectures/courses, graduated MS/PhD
students.

Repo: `~/Public/software/borg-cube` (currently empty, not git).

### Decisions already taken (with Robert, 2026-09-02)

- Work ledger: **Beads** (`bd`), wrapped behind one Python module. Not Gas Town.
- Standing role agents + Mattermost gateway: **Hermes Agent**. Heavy workers:
  Claude Code (`claude -p`) and Codex (`codex exec`).
- Token sources: Claude Max, ChatGPT Plus/Pro via Codex, OpenRouter key, local
  GPU (unimatrix node005, 2x RTX 4090; laptop GPU is 8 GB only).
- Contact policy (Robert, revised): **by default borg-cube never contacts
  students or anyone else; everything goes to Robert.** A student (or any
  person) is contacted only with explicit, recorded permission, granted per
  person and per channel/action class (see Contact policy below). Students
  may later be given read access to their own dossier/milestones, also only
  by explicit grant.
- Additional role: **System Administrator** for group infrastructure
  (borg-server, ws, unimatrix, KAUST DMZ VMs, services), building on the
  existing `hermes-infra` monitor.
- Evaluate **Gas Town** on top of Beads for the coding fleet (spike, not a
  commitment).
- Seed skills and memory from existing local material
  (`~/Public/software/borg-infrastructure`, `~/pa`, `~/org`, skills library,
  Claude memory) rather than starting empty.
- Local LLMs may be installed on unimatrix node005 (2x RTX 4090) as the
  `local` tier.

### Survey findings that shape the design

- Installed: claude 2.1.258, codex-cli 0.146.1, opencode, aider, uv 0.9.5, go
  1.24, node 22, python 3.13, sqlite3, pdftotext. Missing: `bd`, `dolt`,
  `hermes`, `just`, `tmux`, `ollama` runtime (22 GB of ollama models on disk).
- `~/.codex/config.toml` defaults to OpenRouter (kimi-k3). Codex workers must
  run with an explicit ChatGPT profile or they silently bill OpenRouter.
- Anthropic bans subscription OAuth outside Claude Code; Hermes' Anthropic OAuth
  only burns Max extra-usage credits. So: Claude Max only via `claude -p` /
  interactive; Hermes uses Codex OAuth (ChatGPT), OpenRouter, local vLLM.
- Existing assets to reuse, never duplicate:
  - `~/pa` (Python stdlib+PyYAML, `just`, `scripts/x.py <subcmd> --dry-run`,
    unittest): `kg/projects/<slug>.md` project nodes with "Status as of"
    sections (de facto student progress reports), `contacts/*.md`,
    `deadlines.md` (`- YYYY-MM-DD - text [status: open] [pa:id]`),
    `scripts/kg.py`, `scripts/mattermost_inbox.py` (rule: never poll
    Mattermost on a schedule), `scripts/todo_sync.py`, `triggers/rules.yaml` +
    `email_triggers.py`, `protocols/<student>-*.md` (supervision briefs),
    `journal/reviews/*.md` (dual-agent Claude+Codex manuscript reviews).
    Pattern: source-of-truth markdown/yaml -> generated JSON -> hand overlay
    keyed by stable id. ADR-0002 there: never infer facts without a source.
  - `~/Public/software/website/research-knowledge-graph` (public KG,
    `projects.jsonld` 435 nodes, ShEx schema, `borg-id:` IRIs, `refresh.sh`)
    and roster of record `~/Public/software/website/borg-website/people/roster.md`.
  - `~/org/` (git): one org file per person with dated meeting headings,
    `staff.org` (milestone/graduation estimates), `papers.org` (TODO sequence
    `READY_TO_SUBMIT SUBMITTED REVISING PAUSED TODO | PUBLISHED CANCELED`),
    `groupmeeting.org`, teaching files `cs249.org`, `cs321.org`.
  - Skills library `~/Public/software/skills/{claw,local}/<skill>/` deployed to
    `~/.claude/skills` and `~/.codex/skills`: presentation,
    write-edit-scientific-paper, write-paper-review, new-paper,
    personal-assistant, email-contacts (Gnus emacs server pattern:
    `emacsclient -s gnus --eval`, 835-line helpers.el), remote-connect, gog,
    social-media-agent, showboat.
  - Mattermost MCP server configured for Claude and Codex.
- Sources disagree today (e.g. one student is an "MSc former member" in
  projects.jsonld vs a current PhD in staff.org; two alumni in staff.org are
  current in the roster). `cube sync` must surface conflicts, never resolve silently.
- KAUST CEMSE milestones (cohorts from Fall 2023): PhD qualifying exam by end of
  semester 3, proposal defense by end of semester 5, PhD in 4 years (+1
  extension), missed milestone = dismissal; MS thesis 4 semesters + summer,
  thesis application by first week of semester 3; committees 3 (proposal) / 4
  incl. external (dissertation); dissertation to committee 6 weeks before.
- Hermes ALREADY runs in the group: `hermes-ws` on office workstation `ws`
  (KAUST network, 56 cores, 125 GB RAM, no usable GPU), Hermes
  v0.20.6, provider OpenRouter `z-ai/glm-5.3-flash`, Mattermost gateway
  running as `@hermes-ws`, crons `infra-check` (5 min), `infra-nightly-scan`,
  `infra-morning-report` -> ~infra-alerts; skills infra-monitor, semantic-web,
  kaust-compute; source of truth
  `~/Public/software/borg-infrastructure/hermes-infra/` (deploy.sh rsyncs to
  `ws:~/.hermes/`). A second agent `@hermes-home` (mail/calendar) exists; the
  ~agents Mattermost channel is used for agent-to-agent handoff. Hermes cron
  scripts run with a sanitised env (no `.env` secrets).
- Paperclip (github.com/GXL-ai/paperclip): hosted biomedical literature search
  CLI + MCP (BM25+vector over bioRxiv/medRxiv/arXiv/PMC/FDA/trials, virtual
  filesystem, `map`/`reduce`, `paperclip install` skill for Claude Code/Codex).
  Use as a tool for literature-review/research-planning skills. Requires
  account (OAuth); check terms before pointing student agents at it.

## Architecture (recommended)

Three layers: (1) group model, external and read-only for us: pa KG + public KG
+ `~/org`; (2) work ledger: Beads, holding work items and provenance only;
(3) runtimes: Python `cube` engine dispatching `claude -p` / `codex exec` /
Hermes profiles, systemd timers for deterministic patrols, Hermes gateway for
Mattermost. Emacs cockpit shells to `cube ... --json`.

Hosting topology (server-centric; laptop is a thin client, Robert's
requirement: orchestration must be runnable from anywhere):
- **ws = the orchestration host** (always-on, KAUST network, 56 cores, 125 GB
  RAM, reachable from outside through the existing ssh route documented in
  the infrastructure repository). Holds: the borg-cube checkout, Beads
  (single writer), the `cube` engine + Marshal, systemd user timers (patrols),
  Hermes profiles (`hermes-ws` existing, new `advisor`, `scribe`,
  `concierge`), Claude Code and Codex workers (Claude Code login via
  `claude login` device flow on ws is Claude Code itself, so within terms;
  Codex via `codex login` device flow or copied `~/.codex/auth.json`),
  **tmux** for persistent interactive sessions (also a Gas Town prerequisite),
  clones of the data repos (`~/org`, `~/pa`, `research-knowledge-graph`,
  `borg-website`, papers as needed) kept in sync by git (`cube data pull`
  timer + push after approved writes; laptop keeps its own clones as today).
  Skills, brain/, corpus, roles: all on ws in the repo; nothing lives only on
  the laptop.
- **Laptop (lc-dell) = cockpit client.** Emacs `borg-cube.el` runs all `cube`
  commands as `ssh ws cube ... --json` (defcustom `cube-remote-host`; local
  mode when `nil`), opens agent terminals as `ssh -t ws tmux new -A -s
  cube/<name> <cmd>` inside eat, edits remote files via TRAMP
  (`/ssh:ws:~/org/<student>.org`). Disconnecting the laptop never kills a
  session. Any other machine with ssh + Emacs (or plain `ssh ws` + `tmux
  attach`) is an equivalent cockpit. Gnus mail stays on the laptop: email
  approvals produce a draft file on ws; the cockpit hands it to the Gnus
  daemon when Robert is at the laptop, otherwise it waits in the queue.
- **Phone / anywhere without Emacs**: Hermes `concierge` profile on ws
  (Robert-only Mattermost DM, Yegge's Seneschal): read attention list,
  approve/reject, dispatch `cube run`, ask for briefings.
- `local` tier: vLLM on unimatrix node005 (below), reached from ws over the
  KAUST network (no extra route needed); when down, queue.
- Notifications ws -> cockpit: `state/events.jsonl` + `state/attention.json`
  on ws; the cockpit tails them over ssh (`ssh ws tail -F`) or polls every
  60 s; Claude/Codex hooks on ws call `cube notify` (appends to events) instead
  of emacsclient. Hermes advisor writes events the same way; no file bridge
  between machines is needed any more (supersedes the earlier two-machine
  split; ADR-0008 records this).

Yegge lessons kept: crons watch, models act; brain/ doctrine + `bd remember`
facts + skills as boot context; every work bead goes design -> implement ->
review by a stronger tier; keep a designed-but-unimplemented backlog; harness
is bespoke; budget 20-25% effort for the harness itself.

### Repository layout

```
borg-cube/
  pyproject.toml  uv project, package `cube`; deps pydantic>=2, pyyaml (no LLM SDKs)
  justfile        test lint doctor sync patrol install-* deploy-skills corpus-*
  CLAUDE.md       operating guide, mirrored to AGENTS.md (`just mirror-agents`)
  cube.yaml       non-secret config (paths to pa/org/rkg/skills, slots, tiers)
  people.yaml     JOIN TABLE only: cube id -> pa contact slug, borg-id IRI,
                  org file, Mattermost user, program+start (sourced)
  contacts.yaml   outbound-contact grants per person/channel/action class (empty by default)
  .env.example    MATTERMOST_URL/TOKEN GH_TOKEN OPENROUTER_API_KEY VLLM_BASE_URL
  cube/           typed Python (mypy --strict)
    cli.py config.py beads.py ids.py doctor.py emacs_api.py
    model/        WorkKind Labels Provenance PersonRef Escalation RunResult
    sources/      pa_kg.py org.py rkg.py github.py calendar.py mattermost.py (read-only)
    milestones/   kaust_rules.py (pure) plan.py
    sync/         derivers.py reconcile.py (xid-keyed create/update/close/conflict)
    roles/loader.py   router/policy.py
    runners/      base.py claude_code.py codex.py hermes.py stub.py
    engine/       run.py context.py lease.py worktree.py review_gate.py results.py
    patrols/      milestones deadlines papers repos calendar digest mattermost_events leases
    student/      onboarding.py checkin.py dossier.py escalation.py
    audit/        log.py gates.py killswitch.py
  brain/          doctrine.md decisions.md playbooks/ rubrics/ model-tiers.md
  doc/            install.md operating.md student-guide.md privacy.md
  skills/         agentskills.io layout (see Skills section)
  corpus/         grounding sources manifest + distilled references (see Skills)
  roles/          <role>.yaml
  hermes/         profiles/{advisor,concierge,scribe}/config.yaml.tmpl, hooks/, env.example
  systemd/        cube-patrol@.service, *.timer, cube-gateway-advisor.service, cube-worker@.service
  emacs/          INTERFACE.md + elisp (see Emacs section)
  adr/            0001.. (below)
  tests/          pytest + fixtures (staff.org sample, deadlines.md, jsonld slice, bd JSON)
  runs/ state/    gitignored: transcripts; leases/, cursors.json, budget.json, KILL
```

ADRs to write in Phase 0: 0001 beads as work ledger (wrapped); 0002 group
model stays external; 0003 one shared advisor bot with per-user sessions
(gated by contact grants); 0004 systemd for watchers, Hermes cron only for
judgment+delivery; 0005 model router tiers; 0006 subscription usage
boundaries; 0007 privacy classes; 0008 ws as orchestration host, laptop as
thin client; 0009 contact policy default-deny with per-person grants; 0010
Gas Town for coding rigs (after spike); 0011 local inference on node005.

### Data model (Beads)

Native bd types (`epic`, `task`, `chore`) + `kind:` label as the stable
research semantics key:

| Object | type | kind | parent | deps |
|---|---|---|---|---|
| Student program | epic | program | none | children milestones |
| KAUST milestone | task | milestone | program | blocks next |
| Paper | epic | paper | none | |
| Experiment | task | experiment | paper/program | blocks submission |
| Review (pre-submission, dual-agent) | task | review | paper | blocks submit |
| Code audit | task | audit | software | related repo |
| Lecture / course | task / epic | lecture / course | course | |
| Mentoring session | task | mentoring | program | replies-to previous |
| Meeting note | chore | meeting-note | program/project | |
| Service | task | service | none | |
| Patrol finding | task | finding | none | related target |
| Source conflict | task | conflict | none | |

Labels: `person:<roster-slug>`, `project:<pa-slug>`, `paper:<dir>`,
`repo:<owner/name>`, `venue:`, `course:`, `src:staff.org|deadlines.md|...`,
`privacy:public|internal|local-only`, `tier:plan|implement|bulk|local`,
`role:<role>`, `needs:robert`, `visible:student`, `stage:design|implement|review`.

Every bead description starts with a fenced YAML header: `xid` (idempotency
key for sync, e.g. `milestone:alex-example:phd-defense`), `provenance[]`
(source path + locator, Mattermost permalink, Message-ID, seen date),
`deadline`. `cube sync` never creates a second bead for an xid. `bd remember`
holds doctrine facts (`cube brain push`). Formulas: `work-standard`,
`paper-submit`, `student-checkin`, `code-audit`.

`cube sync` derivations: staff.org+roster+people.yaml -> program epics +
milestone tasks via `kaust_rules.py` (rule vs estimate mismatch -> conflict
bead); deadlines.md `[pa:id]` -> tasks (read-only toward pa in Phase 1);
papers.org -> paper epics with `paper-state:` label; pa kg "Status as of"
freshness > 21 days -> finding; GitHub org scan -> audit candidates;
Mattermost -> beads only from gateway events/webhooks; calendar ICS -> prep
beads for tomorrow's group-member meetings. `--dry-run` prints the plan.

### Roles, runtimes, router

| Role | Runtime | Tier | Trigger | Escalation |
|---|---|---|---|---|
| Group Leader | `claude -p` Fable (fallback Opus) | plan | manual / weekly backlog design | findings -> needs:robert |
| Senior/Postdoc | `claude -p` Opus | plan | `stage:design` beads | Leader |
| Programmer | `codex exec -p cube-chatgpt --sandbox workspace-write --json` in worktree; fallback claude sonnet | implement | `stage:implement` ready beads | Senior after 2 failures |
| Auditor | codex read-only pass + claude Opus verdict | implement+plan | weekly patrol / manual | high severity -> Robert |
| Editor | claude Opus/Fable + codex second opinion (pa dual-review pattern) | plan | `kind:review` | verdict to Robert before any student sees it |
| Lecturer | claude Opus + presentation + lecture-design skills | plan | course bead | Robert releases |
| Scribe | Hermes `scribe` profile (OpenRouter) or claude sonnet | bulk | after meetings / check-ins | never sends |
| Advisor (per student, Robert-facing by default) | `claude -p` Opus / local vLLM for progress notes; Hermes `advisor` profile + bot `@borg-advisor` only for students with a recorded contact grant | plan + local | weekly patrol, before 1:1s, on request | drafts everything for Robert; contact requires grant; concerns -> needs:robert |
| System Administrator | Hermes `hermes-ws` (existing, extended) for patrol + Mattermost ~infra-alerts; `claude -p` Opus for diagnosis/runbooks; `codex exec` for config PRs | implement + plan | hermes-infra crons (5 min check, nightly scan, morning report), events from `infra.py check --notify`, manual | any state-changing action (restart, delete, config edit, scancel) only on explicit ask, quoted back first (hermes-infra hard rule); outages -> needs:robert |
| Secretary | `claude -p` Opus with browser (claude-in-chrome MCP on the laptop Chrome, or Playwright/CDP against a dedicated Chrome profile on ws where Robert has logged in to KAUST SSO); pa scripts for Concur/travel/admissions | plan | inbound requests (email triggers, Mattermost, Robert), deadline patrol, manual | prepares and pre-fills; every submit/approve/sign is an approval-gated outbound action with screenshot + field table; never stores passwords |
| Sentinel | Python patrols, no LLM | none | systemd timers | thresholds -> needs:robert |
| Marshal | Python (+ optional haiku/sonnet prioritisation) | bulk | 30-min timer | backlog starvation > 48h |
| Concierge | Hermes `concierge` profile, Robert-only DM | Codex/OpenRouter | Robert's DMs | n/a |

Advisor topology (ADR-0003): the Advisor role is Robert-facing by default
(drafts agendas, progress reviews, check-in questions for Robert to use).
The student-facing channel is ONE Hermes profile + ONE bot account
`@borg-advisor`; `MATTERMOST_ALLOWED_USERS` is generated from
`contacts.yaml` grants only (empty until Robert grants); Hermes gives each DM
its own session; per-student context via a pre-prompt hook calling
`cube student context --mm-user <u> --json` on ws, so memory lives in
cube/pa/org, not in Hermes.

System Administrator role (new): owns borg-server, ws, unimatrix01 + nodes,
KAUST DMZ VMs, and the services in `hermes-infra/scripts/services.yaml`
(AberOWL, PAVS, Rub al-Khali KB, Mattermost, dashboards, tunnels). Built on
the existing `hermes-ws` monitor rather than replacing it: `infra-check`
findings become `kind:incident` beads (label `host:<name>`, `service:<id>`),
the nightly digest becomes a `kind:finding` bead, and `cube run sysadmin
--bead ID` runs diagnosis with the `infra-monitor`, `kaust-compute`,
`semantic-web`, `remote-connect` skills plus the runbooks in
`borg-infrastructure/*.md` (PAVS_MAINTENANCE, RUBALKHALI_MAINTENANCE,
migration notes, unimatrix KNOWN_ISSUES). Outputs: incident report, proposed
commands quoted back, config PRs into `borg-infrastructure` (review gate),
inventory updates (`deployment/ip_addresses.md`, `unimatrix/CLUSTER_CONFIG`).
Patrols added: certificate/domain expiry, disk and backup freshness
(DataWaha/dm archives via `datawaha-backup`), SLURM node health and GPU
driver caps (node006 dead card, node003 Kepler cap), tunnel liveness, unattended
upgrades pending. Hard rules inherited from hermes-infra AGENTS.md: no
`scancel`, delete, restart, or config edit without an explicit ask; never
print secrets (credential files live outside the repository); root shells only
interactively.
Also owns the borg-cube deployment itself (Hermes updates, `bd` backups,
vLLM service on node005).

Router (ADR-0005): `plan` = Fable -> Opus -> refuse (never downgrade
planning/review); `implement` = codex (ChatGPT profile) -> claude sonnet ->
OpenRouter coder; `bulk` = OpenRouter cheap (price routing) -> local; `local`
= vLLM on node005 via SSH tunnel -> else QUEUE (never cloud); mandatory for
`privacy:local-only`. `state/budget.json` tracks per-tier windows from
`--output-format json` / `--json` usage; exponential backoff; lease expiry lets
Marshal requeue. Slots `{plan:1, implement:3, bulk:4, local:1}`.
Subscription boundary (ADR-0006): Claude Max only via `claude -p` on this
machine with a daily plan-tier cap; no Agent SDK with OAuth; Hermes never uses
Anthropic OAuth; Codex only through `codex exec` with ChatGPT auth.

### Execution engine

`cube run <role> [--bead ID] [--runner stub|claude|codex|hermes] [--resume] [--dry-run] [--json]`:
1. load `roles/<role>.yaml` (tier, runtime, model, allowed_tools,
   permission_mode, skills[], system_prompt_file, can_close,
   review_required_by, escalation, privacy_max, session_policy, autonomous_actions);
2. `bd update ID --claim` + `state/leases/ID.json` (pid, expiry); refuse if live lease;
3. context = `bd prime` + `bd show --json` + `cube resolve` of labelled refs
   (privacy-filtered) + role prompt + doctrine excerpt + skill paths
   (`--append-system-prompt` / prompt preamble / `--skill`) + output schema
   (`--json-schema` claude, `--output-schema` codex);
4. router picks runner+model; `--dry-run` prints command + prompt;
5. execute headless, stream to `runs/<date>/<run-id>/stdout.jsonl`, store
   session/thread id in `meta.json` and as bead comment for `--resume`;
6. parse `RunResult{summary, artifacts[], bead_updates[], escalations[], verdict?, next_actions[]}`;
   invalid -> comment, no state change;
7. apply: comments; close only if `can_close` and review approved, else create
   `kind:review` bead (blocks original, plan tier); escalations -> `needs:robert`;
   code beads use `git worktree add .cube/wt/<ID> -b cube/<ID>`;
8. release lease, append `state/audit.jsonl`.

`cube review <bead>` runs stronger-tier reviewer with transcript + diff ->
`approve|revise|reject` (revise spawns follow-up implement bead).
`cube worker --slots N` = Marshal loop over `bd ready --json`. All idempotent.

### Event/cron layer (ADR-0004)

systemd user timers run deterministic Python patrols (zero tokens, journalctl
audit trail, run even when no LLM/gateway is up). Hermes cron only where the
scheduled action is a judgment delivered through the bot identity (advisor
weekly nudge, concierge morning brief).

| Patrol | Schedule | Output |
|---|---|---|
| milestones | daily 07:00 | 180/90/30-day warnings -> finding beads; risk -> needs:robert |
| student-digest | Thu 12:00 (before 18:00 reports) | `briefings/students/<date>-<id>.md`, Robert-only |
| papers | daily 07:10 | papers.org vs paper dirs (last commit, TODO markers) |
| repos | Mon 06:00 | GitHub org scan -> audit candidates (max 3 dispatched/week) |
| deadlines | daily 07:20 | 7/30-day horizon |
| calendar | daily 17:00 | tomorrow's group meetings -> prep-brief beads (Scribe drafts) |
| mattermost-events | event only | gateway/webhook -> `cube event mattermost`; never REST polling |
| infra-incidents | event (hermes-infra `infra-check`, 5 min) | DOWN after 2 failures -> `kind:incident` bead + sysadmin dispatch |
| infra-hygiene | daily 04:00 | cert/domain expiry, disk, backup freshness, tunnel liveness, pending upgrades, SLURM node/GPU health, vLLM endpoint |
| data-pull | hourly | `git pull` of ~/org, ~/pa, KGs on ws; conflicts -> needs:robert |
| leases | 15 min | expire dead leases, requeue |

Secretary role (new): knows KAUST policies and administrative workflows and
operates the web systems for them. Scope: travel requests and BTR web forms,
travel justification and exception-request forms, Concur expense reports and
reimbursement tracking, purchase requests, visitor/guest invitations, student
forms Robert must approve (travel, leave, thesis application, committee
forms, TA assignments), hiring and contract paperwork checklists, CS
admissions chair workflow (`~/pa/lists/admissions.md`), JBMS editor duties
(desk-reject/decision letters from `~/Public/software/jbms`), website CMS
edits (Drupal via the existing `publish_*.mjs` CDP scripts). Knowledge
sources seeded into `skills/kaust-admin/references/`: `~/pa/protocols/`
(travel-requests, travel-justification-form, exception-request-form,
btr-web-form-fields), `~/pa/scripts/{reimburse_track,concur_ledger,travel_bundle}.py`,
`~/pa/concur_portal.txt`, `~/pa/reimbursements.yaml`, KAUST policy pages
(Graduate Affairs, Research Administration, HR, Travel, Procurement,
Academic Integrity; fetched with date into the corpus, institutional
licence), CEMSE milestone rules, `feedback_complete_forms` memory (never
deliver a partially filled form; every Yes/No and checkbox answered; ask when
unknown). Browser: on the laptop, the `claude-in-chrome` MCP (already
installed) drives Robert's logged-in Chrome; on ws, a dedicated Chrome
profile under Playwright/CDP (pattern from research-knowledge-graph
`publish_*.mjs` and social-agent `browser-profile/`) where Robert performs
KAUST SSO + MFA himself; the secretary reuses the session, never the
credentials (tokens-over-passwords rule; KAUST password is never in any
agent-readable file). Form work flow: `cube run secretary --bead ID` reads
the request, fills the form from KG/pa data, saves a field-by-field table +
screenshot to `runs/<id>/form.md`, creates a `kind:outbound` approval bead;
Robert approves in the cockpit or via Concierge (with a one-time
authorisation phrase for signatures); only then the secretary clicks
submit/approve/sign and records the confirmation number and receipt PDF as
provenance (`pa` overlay files such as `reimbursements.yaml` are updated
through the existing scripts). Signing: PDF signature image or e-signature
portals only per-request; the signature asset lives outside the repo, path in
`.env`. Skills: `kaust-admin` (policies, workflows, form field maps, approval
etiquette), `browser-forms` (deterministic Playwright helpers: open, fill
from YAML, screenshot, diff before submit, `--dry-run` stops before submit),
plus reuse of `personal-assistant`, `email-contacts`, `gog`. Patrols:
reimbursement and travel deadlines (from `deadlines.md`), pending approvals
in KAUST portals (only if a read-only check is possible from the session;
otherwise Robert forwards the notification email, which the email trigger
turns into a bead).

### Contact policy and advising flow (ADR-0009)

Default: **no outbound contact to anyone.** Every message, email, DM,
GitHub comment, or post that would reach a person other than Robert is a
`kind:outbound` bead in the approval queue; Robert sends it himself or
approves it. Grants live in `contacts.yaml` (source-controlled, each with
date, granted-by, scope, expiry, evidence permalink):

```yaml
alex-example:
  mattermost_dm: {granted: 2026-10-01, scope: [weekly-checkin, milestone-reminder], expires: 2027-01-31}
  email: null
fin-fellow:
  mattermost_dm: {granted: 2026-09-15, scope: [infra-alerts]}
```

`cube contact check <person> <channel> <action-class>` is the single gate
used by every runner and by the Hermes gateway allowlist generator; no grant
means the action is queued for Robert, never sent. Granting is a Robert-only
CLI/cockpit action (`cube contact grant ...`, logged to audit). Revocation is
immediate (regenerates `MATTERMOST_ALLOWED_USERS`, restarts the gateway).
Students' read access to their own dossier is a separate grant
(`dossier_read`). `cube doctor` fails if any role yaml lists an
`autonomous_actions` entry that is outbound.

Advising flow, Robert-facing (Phase 1-3, no grants needed): weekly per
student, the Advisor drafts for Robert: evidence summary (commits, drafts,
org notes), milestone status from `kaust_rules.py`, suggested 1:1 agenda and
questions, and, if Robert asks, a draft message to the student. Robert reads
these in the cockpit or via Concierge and acts himself. Meeting notes Robert
types or dictates go through meeting-scribe into `~/org/<person>.org`.

Advising flow, student-facing (only per grant, Phase 4 pilot): onboarding
`cube student onboard <id> --dry-run` produces the transparency note +
mentoring compact for Robert to send; grant recorded; milestone plan
written as beads + `* Milestone plan (cube, DATE)` heading in the org file.
Weekly check-in (Hermes cron, Wed 10:00, only for granted students): three
questions plus one milestone-aware prompt. Reply -> Scribe drafts org entry
(tag `:cube:`), "Status as of" paragraph, mentoring bead; written only after
`cube approve` during the pilot.

Escalation doctrine (both modes): the system never delivers assessments to
students; concern triggers (2 missed check-ins, milestone < 90 days without
artefact, self-reported blocker) create `needs:robert` beads + briefing
paragraph. Granted students see: milestone plan, own check-in history,
`visible:student` beads, transparency note. Never: Robert's notes, other
students, risk scores. No fact about a student reaches Robert that the
student did not state or that is not derivable from artefacts Robert already
has access to; the bot says when it will summarise for Robert.

### Safety and privacy (ADR-0007)

Privacy classes on every bead and source path: `public` (rkg, public repos,
published papers), `internal` (pa kg, papers.org, deadlines.md, meeting
notes), `local-only` (check-in transcripts, progress assessments, grades,
contracts, visas, personnel, health: vLLM only or queue; grades/HR never enter
beads; `cube doctor` greps forbidden fields). Scoped tokens in `.env`, bot
tokens per bot account, GitHub fine-grained read token; doctor checks file
modes. Append-only `state/audit.jsonl`. Kill switch `state/KILL`
(`cube kill` / `cube resume`; units `ConditionPathExists=!.../state/KILL`).
Approval gate on every outward action (Mattermost post, email draft, PR/comment)
unless listed in the role's `autonomous_actions` (empty in Phase 4).
`--dry-run` for all send paths; never a real send as smoke test.

### Gas Town on top of Beads (ADR-0010, decided after a spike)

What Gas Town adds that Beads lacks: Mayor (coordinator), Polecats (workers
with persistent identity, ephemeral sessions, each on a git worktree
"hook"), Witness (per-rig stuck-agent detection and lifecycle), Deacon
(cross-rig patrol), Refinery (merge queue), Dog (infra maintenance workers),
convoys (bundled beads with tracked status), formulas/molecules (TOML
multi-step workflows with checkpoint recovery), `gt sling`, `gt escalate`,
`gt feed --problems`, scheduler with dispatch capacity, OpenTelemetry, and
runtime presets for Claude Code, Codex, Gemini, OpenCode, Copilot, Cursor.
Requirements: Go 1.26.2+ (we have 1.24; `GOTOOLCHAIN=auto` downloads it),
tmux 3.0+ (needed anyway on ws), `bd` 0.57+, sqlite3. Yegge's own warning:
Gas Town "fell apart" for him under Opus 4.7's over-eager loop; he moved to a
bespoke harness.

Plan: use Gas Town where its model fits, the **coding fleet**: one rig per
software repo (bio-ontology-research-group repos, borg-infrastructure,
borg-cube itself). Programmer, Auditor and Refinery then come from Gas Town
(`gt rig add`, `gt convoy create`, `gt sling`), and `cube` gains a `gastown`
runner that converts a `stage:implement` bead into a convoy and reads
completion back from beads. Research, advising, teaching, sysadmin and
monitoring stay in `cube` (Gas Town has no notion of people, milestones or
approval queues). Its formulas are also the template for cube's own
`work-standard`/`paper-submit` molecules if we adopt the TOML format.
Phase 3 opens with a one-week spike on ws: install `gt`, one rig
(borg-cube), one convoy through Mayor -> Polecat -> Refinery with Claude and
Codex runtimes; measure stuck-detection and merge behaviour; decide adopt vs
cube-only. Kill criteria: cannot run headless from cube, or Witness/Refinery
churn exceeds the benefit.

### Seeding skills and memory from local material (Phase 0)

`cube seed` imports, with provenance pointers back to the originals (no
duplication of sources of truth; symlink or rsync with `seed_from:` in the
frontmatter/manifest):
- Skills: `hermes-infra/skills/{infra-monitor,semantic-web,kaust-compute}`
  and `borg-infrastructure/skills/datawaha-backup` (sysadmin role);
  `~/Public/software/skills/local/*` (presentation, new-talk, remote-connect,
  email-contacts, new-paper, bcl-email-backup, datawaha-backup) and
  `claw/showboat`; `~/.codex/skills/write-edit-scientific-paper`,
  `~/.claude/skills/write-paper-review`, `~/pa/skill` (personal-assistant),
  social-media-agent. borg-cube's `skills/` gains a `seeded/` index that
  references them; lint checks the originals still exist.
- Doctrine and runbooks into `brain/` (as summaries + links): hermes-infra
  `AGENTS.md` (hard rules, skill routing), borg-infrastructure `AGENTS.md`
  (admin account, root shell procedure, IBEX ownership table), `README.md`,
  `PAVS*.md`, `RUBALKHALI*.md`, `borg-server2-migration.md`,
  `deployment/*.md` (ip_addresses, DOMAIN_HOSTING, unimatrix_cluster),
  `unimatrix/{CLUSTER_CONFIG_JAN2026,KNOWN_ISSUES,SLURM_INSTALL,INSTRUCTIONS}.md`,
  `office-ws/README.md`, `~/pa/CLAUDE.md` (autonomy policy, hard rules, tool
  patterns), `~/org/CLAUDE.md` (org conventions), `~/.codex/AGENTS.md`
  (PATO/FLOPO ontology contribution checklist -> `ontology-review`),
  `~/Public/software/skills/CLAUDE.md`.
- Facts into `bd remember` via `cube brain push`: the 30 memories in
  `~/.claude/projects/<home>/memory/` (filtered: project/feedback/
  reference types; user-type memories only where relevant to the group; the
  spam-filter and personal-training ones excluded), hermes-infra
  `services.yaml` registry entries, unimatrix GPU/driver caps, roster and
  milestone estimates from `staff.org` (as provenance-tagged facts).
- Secrets are never seeded; `password*.md` and `.env` paths are listed in
  `brain/doctrine.md` as "reference by path only".
- The seed is idempotent and re-runnable (`cube seed --diff` shows drift
  between originals and seeded copies).

### Local inference on unimatrix node005 (ADR-0011)

Hardware: node005 = 2x RTX 4090 (24 GB each, 48 GB total), driver
580.159.03, Slurm 23.11 partition `debug`, reachable from ws over the KAUST
network via unimatrix01 (`ProxyJump` already in Robert's ssh config).
Deployment: vLLM in a uv venv (or the vLLM Docker image if Docker is on the
node) started by a Slurm job script `deploy/vllm-node005.sbatch`
(`--nodelist=node005 --gres=gpu:2`, long wall time, requeue on preemption)
or, if the node can be dedicated, a systemd unit; `--tensor-parallel-size 2
--enable-auto-tool-choice --tool-call-parser hermes --max-model-len 32768`
(Hermes docs). A `cube local status|start|stop` wrapper and a Sentinel
patrol check the endpoint; the router marks `local` tier available only when
`/v1/models` answers. Model candidates (pick by eval in Phase 1; VRAM fit in
brackets): Qwen3-32B FP8/AWQ (~20 GB) as default general model for
`privacy:local-only` work; Qwen2.5-Coder-32B or Qwen3-Coder-30B-A3B for code
tasks; gpt-oss-20b (~14 GB) as the fast/cheap bulk model; Llama 3.3 70B AWQ
(~40 GB) only if quality demands and KV headroom allows. Serve one model at a
time per GPU pair, or two smaller models with `--tensor-parallel-size 1`
each. Hermes profiles on ws get a `providers.local` entry
(`base_url: http://node005:8000/v1`); `claude`/`codex` do not use it (they
stay on subscriptions); cube's `bulk` and `local` runners call it via the
OpenAI-compatible API. The laptop's 22 GB of ollama models are irrelevant to
the server design (optional offline fallback only).

## Skills library and methodological grounding

### Where skills live, how they deploy

New skills live in `borg-cube/skills/<skill>/` (versioned with the corpus,
lint and tests). Existing skills (presentation, write-edit-scientific-paper,
write-paper-review, new-paper, personal-assistant, email-contacts,
remote-connect, gog, social-media-agent, showboat) are referenced by name only.
`just deploy`: symlink into `~/.claude/skills/<skill>`, rsync copy into
`~/.codex/skills/<skill>`, rsync into `ws:~/.hermes/profiles/<p>/skills/<category>/<skill>`
(category from `metadata.hermes.category`). Same directory to all three; only
`metadata.hermes.*` keys are runtime-specific.

Frontmatter template (agentskills.io compliant):

```yaml
---
name: phd-milestones
description: <what + when, quoted trigger phrases, <=1024 chars>
license: CC-BY-4.0
compatibility: Requires python3 >= 3.11; no network unless noted.
metadata:
  borg-role: advisor            # advisor|researcher|lecturer|auditor|lead|infra
  grounding: kaust-cemse-milestones, nap2019-mentorship, marino2014
  hermes:
    category: advising
    tags: phd, milestones, kaust
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---
```

Rules: SKILL.md < 500 lines, holds procedure + hard rules + a "Grounding"
section listing `references/*.md` one line each; references one level deep,
each starting with a Sources block (manifest ids + licences). Shared
references are copies of `corpus/distilled/<topic>.md` made by
`tools/skills_sync.py` (edit the original only; lint fails on drift). House
style enforced by lint: no em-dashes, sentence-case headings, no meta-labels.

### Corpus pipeline

`corpus/sources.yaml` manifest entry: id, type, citation, doi/url, license,
oa flag, excerpt_ok, topics[], fetched date, sha256, verified_by, optional
`notes:` path for copyrighted books (Robert's own summaries, never copies).
Recipes: `just corpus-fetch` (OA PDFs/HTML -> `corpus/raw/`, gitignored, one
req/s; PLOS via printable PDF or XML API, NAP needs a manual download click),
`just corpus-convert` (`pdftotext -layout` / pandoc -> `corpus/text/`),
`just corpus-distill <topic>` (Claude/Codex headless writes
`corpus/distilled/<topic>.md`: Sources block; "What the evidence says" with
`[id]` per claim; "Rules we adopt" numbered; "Where sources disagree"; "Not
covered". Constraints: no quote > 25 words from CC-BY, zero quotes from
copyrighted, no claim without id; a second agent run `--check` verifies ids;
Robert reviews before commit, recorded as `reviewed_by/on`), `just skills-sync`,
`just corpus-verify` (Crossref title match for every DOI, re-fetch and diff
institutional pages; monthly timer).

Copyright: CC-BY (PLOS, F1000, PeerJ, Turing Way, Carpentries) short excerpts
with attribution; CC-BY-NC summarise only; NAP free-to-read PDFs summarise
only; KAUST pages stored locally, rules quoted short, never republished;
books via `corpus/notes/`. Distilled files are the group's own words.

### Skill catalog (runtime: CC = Claude Code, CX = Codex, H = Hermes)

Advisor / mentor role:
- `phd-milestones` (CC/CX/H): schedule from start date + programme; risk flags;
  committee rules. `scripts/milestones.py --start --program [--org-out]`,
  `roster_scan.py` over staff.org. `assets/programs.yaml` with source URL +
  verified-on per rule. Grounding: KAUST CEMSE milestones page, registrar
  program guide (CS PhD/MS), Graduate Affairs thesis policy [KAUST]; Marino et
  al 2014 finishing your PhD (pcbi.1003954), Gu & Bourne 2007 (pcbi.0030229),
  2025 computational MSc thesis rules (pcbi.1012756), 2021 interdisciplinary
  PhD (pcbi.1008554), NAP 2018 Graduate STEM Education [OA]; Phillips & Pugh
  "How to Get a PhD", Lovitts 2001 [cite].
- `mentoring-compact` (CC/CX): expectations document + IDP + annual review.
  `assets/compact-template.md`, `idp-template.md`, `scripts/idp_diff.py`.
  Grounding: NAP 2019 Science of Effective Mentorship in STEMM (10.17226/25568),
  Masters & Kreeger 2017 (pcbi.1005709), Quynn et al 2026 writing partnership
  (pcbi.1014250), 2022 mentorship programme (pcbi.1010015), HHMI/BWF "Making
  the Right Moves" [OA]; myIDP, Vitae RDF domains A-D, CIMER Entering
  Mentoring themes, Handelsman 2005, Lee/Dennis/Campbell 2007 Nature, Pfund
  2006 Science [cite/paraphrase].
- `mentoring-session` (CC/CX; H agenda-only): agenda from evidence, questions
  that assess understanding, post-meeting org entry in Robert's format.
  `scripts/org_meeting_entry.py` (respects `#file#` locks). Grounding:
  Crossley & Maini 2025 (pcbi.1013690), Jabre et al 2021 (pcbi.1009330),
  Maestre 2019 (pcbi.1006914), Evans 2018 / Woolston 2019 wellbeing [OA]; Lee
  2008 supervision models, Delamont et al, Wisker [cite];
  `robert-feedback-style.md` mined from ~/org with approval, names removed.
- `progress-review` (CC/CX; H collector only): evidence table (commits,
  notebooks, drafts, org notes) vs milestones + rubric; Robert-only report.
  `scripts/collect_evidence.py --student --since`, `rubric_report.py` (every
  score cites evidence id). Grounding: Vitae RDF domain A, NAP 2019, KAUST
  criteria, Bloom revised [cite], Schwab et al 2022 good research practice
  (pcbi.1010139), Wilson 2017 good enough practices (pcbi.1005510), Schnell
  2015 lab notebook (pcbi.1004385), Sutherland 2013 twenty tips.
- `thesis-writing` (CC/CX): outline, chapter-to-paper map, KAUST format,
  defense timeline (6-week rule). `scripts/thesis_timeline.py --defense`,
  `chapter_lint.py`. Grounding: KAUST thesis guidelines + LaTeX template
  [KAUST]; Marino 2014, Zhang 2014 (pcbi.1003453), Mensh & Kording 2017,
  Bourne 2007 oral (pcbi.0030077), Naegle 2021 slides (pcbi.1009554) [OA];
  Phillips & Pugh, Dunleavy 2003, Evans/Gruba/Zobel, Zobel [cite].

Researcher role:
- `research-planning` (CC/CX): question, hypotheses, strong inference,
  experiment matrix with baselines/success thresholds, risks, kill criteria,
  beads. `scripts/plan_to_beads.py`. Grounding: Alon 2009 Mol Cell, Hamming
  1986, Heilmeier catechism, Schwab 2022, Kass 2016 statistical practice
  (pcbi.1004961), Osborne 2014 (pcbi.1003506), Ioannidis 2005, Kapoor &
  Narayanan 2023 leakage, REFORMS 2024, DOME 2021, Chicco 2017 [OA]; Platt
  1964, Booth et al Craft of Research [cite]; KAUST 10-page proposal format.
- `literature-review` (CC/CX, web): search log, screening, synthesis matrix,
  BibTeX via doi2bib; Paperclip CLI/MCP as a search tool for biomedical
  literature. `scripts/cite_check.py` (Crossref/PubMed), `search_log.py`.
  Grounding: Pautasso 2013 (pcbi.1003149), Carey 2020 reading (pcbi.1008032),
  Keshav 2007, PRISMA 2020, Grant & Booth 2009, Kitchenham & Charters 2007
  [OA]; Booth/Sutton/Papaioannou, Webster & Watson 2002 [cite].
- `paper-writing` (CC/CX; structure layer over write-edit-scientific-paper):
  one message, outline, figure storyboard, CRediT, venue, submission
  checklist. `scripts/paper_lint.py`, `cite_check.py`. Grounding: Mensh &
  Kording 2017 (pcbi.1005619), Zhang 2014, Bourne 2005 (pcbi.0010057), Frassl
  2018 (pcbi.1006508), Romano & Nolte 2020 (pcbi.1008390), Gopen & Swan 1990,
  Plaxco 2010, Rougier 2014 figures (pcbi.1003833), Weissgerber 2015, ICMJE,
  CRediT, MIRO 2018, DOME, NeurIPS checklist [OA]; Whitesides 2004, Schimel,
  Heard, Tufte [cite]. `venues.md` hand-maintained.
- `response-to-reviewers` (CC/CX): point-by-point table, change log.
  `scripts/split_reviews.py`, `response_check.py`. Grounding: Noble 2017
  (pcbi.1005730), Bourne & Korngreen 2006 (pcbi.0020110).
- `experiment-tracking` (CC/CX; H nightly audit): run manifest, seeds, data
  versions, figure-to-run provenance. `scripts/runs_manifest.py`,
  `figure_provenance.py`; model card / datasheet templates. Grounding: Sandve
  2013 (pcbi.1003285), Rule 2019 notebooks (pcbi.1007007), Hart 2016, Michener
  2015, Goodman 2014, Dodge 2019, Pineau 2021 JMLR, Mitchell 2019 model cards,
  Gebru 2021 datasheets, Heil 2021 Nature Methods.
- `reproducibility-check` (CC/CX, often on IBEX via remote-connect): clean
  re-execution, ACM badging grade. `scripts/repro_env.sh`,
  `compare_results.py --tolerance`. Grounding: Peng 2011, Stodden 2016, NAP
  2019 Reproducibility and Replicability (10.17226/25303), ACM badging v1.1,
  Turing Way, Grüning 2018, Nüst 2020 Dockerfiles (pcbi.1008316).
- `grant-writing` (later): Bourne & Chalupa 2006 (pcbi.0020012), HHMI/BWF,
  NIH application pages, Heilmeier, ERC criteria; KAUST internal calls.

Lecturer role:
- `talk-design` (CC/CX; style authority stays `presentation`): assertion-
  evidence outline, slide plan, practice-talk review in Robert's slide-numbered
  style. `scripts/slide_lint.py`, `frames_to_png.sh`. Grounding: Alley
  assertion-evidence materials, Naegle 2021, Bourne 2007, Erren & Bourne 2007
  poster (pcbi.0030102) [OA]; Alley Craft of Scientific Presentations, Garner &
  Alley 2013, Doumont Trees Maps Theorems, Tufte Cognitive Style of PowerPoint,
  Mayer Multimedia Learning (12 principles), Mayer & Moreno 2003 [cite].
- `lecture-design` (CC/CX): outcomes (Bloom verbs), pre-class work, active
  learning segments, formative checks. `scripts/outcome_lint.py`, `timebox.py`.
  Grounding: NAP 2018 How People Learn II, Dunlosky 2013, Freeman 2014 PNAS,
  Deslauriers 2019 PNAS, Theobald 2020 PNAS, Wieman 2014, Carpentries
  Instructor Training (CC-BY), Wilson Teaching Tech Together (CC-BY-NC), Brown
  & Wilson 2018 (pcbi.1006023) [OA]; Ambrose How Learning Works, Make It Stick,
  Nilson, Crouch & Mazur 2001, Anderson & Krathwohl 2001 [cite].
- `course-design` (CC/CX): backward design, constructive-alignment matrix,
  KAUST syllabus, week plan, FAIR materials. `scripts/alignment_matrix.py`
  (fails on unassessed outcomes), `syllabus_build.py` (YAML -> md/org/PDF).
  Grounding: Fink 2003 self-directed guide [OA], NAP 2012 DBER, NAP 2015
  Reaching Students, Garcia 2020 FAIR training (pcbi.1007854), Via 2011
  (pcbi.1002245), Pavelin 2014 (pcbi.1003485), CAST UDL [OA]; Wiggins &
  McTighe UbD, Fink 2013, Biggs 1996, Biggs & Tang, Nilson Specifications
  Grading, Angelo & Cross [cite]; KAUST registrar course rules [KAUST].

Auditor / software role:
- `code-audit` (CC/CX; H collector nightly): deterministic facts
  (`scripts/audit_collect.py`: README/LICENSE/CITATION.cff/CI/tests ratio/
  pinned deps/Dockerfile/secrets regex/notebook outputs/last commit/open
  issues via gh) + agent judgement, every finding file:line with severity and
  fix; fix list as beads. Grounding: Wilson 2014 best practices
  (pbio.1001745), Wilson 2017, Taschuk & Wilson 2017 (pcbi.1005412),
  Hunter-Zinck 2021 (pcbi.1009481), List 2017 (pcbi.1005265), Balaban 2021
  (pcbi.1008549), FAIR4RS 2022 (10.15497/RDA00068), JOSS review checklist +
  criteria, Jiménez 2017 F1000, Lee 2018 documenting (pcbi.1006561), Smith
  2016 software citation, Google code review guide, Sholler 2019
  (pcbi.1007296), OWASP Top Ten, CWE Top 25, OpenSSF Scorecard, OBO Foundry
  principles + MIRO + ROBOT report for ontology repos.
- `software-release` (CC/CX): SemVer, Keep a Changelog, CITATION.cff, Zenodo
  DOI, PyPI/Bioconda, JOSS paper skeleton. `scripts/release_check.py`,
  `cff_gen.py`. Grounding: SemVer 2.0, Keep a Changelog 1.1, CFF spec,
  Python Packaging Guide, Bioconda guide, Brack 2022 (pcbi.1009823), JOSS.
- `ontology-review` (later, BORG-specific): OBO principles, MIRO, Malone 2016
  selecting a bio-ontology (pcbi.1004743); wraps ROBOT + semantic-web skill.

Lead / orchestration / monitoring:
- `delegation` (CC lead; CX; H): goal -> beads with testable acceptance
  criteria, deps, owner role, worker briefs with scoped context, review gate.
  `scripts/beads_from_plan.py` (fails on bead without criterion),
  `dependency_check.py`, `worker_brief.py`. Grounding: Anthropic Building
  effective agents 2024, multi-agent research system 2025, writing effective
  tools 2025, context engineering 2025, agentskills.io spec, Scrum Guide 2020,
  INVEST, Google small CLs, HHMI/BWF project management, Crossley & Maini 2025
  [OA]; Grove High Output Management [cite].
- `meeting-scribe` (CC/CX/H): transcript/notes/Mattermost thread -> org entry
  `* <date>, <topic>` with `- [ ]` action items + `<date>` deadlines, optional
  todo.org, Mattermost summary. `scripts/org_append.py` (lock-aware, dry-run
  default), `actions_extract.py`. Grounding: ~/org/CLAUDE.md conventions, Org
  manual, HHMI/BWF lab meetings, 2021 productive lab meetings (verify DOI).
- `group-monitor` (H cron on ws + CC deep dive): papers pipeline
  (papers.org states), software (repo activity/CI/releases), services
  (hermes-infra status.json), students (milestones, last meeting, evidence
  velocity), teaching deadlines; changes-only briefing in pa briefing style.
  `scripts/papers_state.py`, `repos_state.py`, `students_state.py`,
  `diff_state.py`, `briefing_render.py`; `assets/thresholds.yaml` (paper
  SUBMITTED > 120 d, REVISING > 30 d without commits, repo idle 90 d with open
  issues, student no meeting entry 21 d, milestone < 60 d without artefact).
  Grounding: HHMI/BWF, Maestre 2019, 2023 lab information (pcbi.1011652),
  Schwab 2022 [OA]; Barker At the Helm [cite].
- `borg-skill-authoring` (infra): how to write, ground, lint, test, deploy a
  skill here; SKILL.md + references templates.

Flows: advisor = phd-milestones -> progress-review -> mentoring-session ->
meeting -> meeting-scribe -> delegation; paper = research-planning ->
experiment-tracking -> paper-writing -> write-edit-scientific-paper ->
reproducibility-check -> response-to-reviewers -> new-paper; teaching =
course-design -> lecture-design -> talk-design -> presentation/new-talk;
software = code-audit -> software-release -> new-paper.

### Skill quality gates

`just skills-lint` (`tools/skills_lint.py`): `agentskills validate` (pip
`skills-ref`); SKILL.md <= 500 lines / ~5k tokens; `metadata.grounding` >= 3
ids (>= 5 for advising, teaching, writing skills), each in manifest and cited
by a references Sources block; references match `corpus/distilled/` byte for
byte; style checks (U+2014, Title Case headings, banned phrases); hermes
category in allowed set; every `scripts/*.py` has `--help` and a test, stdlib +
pyyaml only (Hermes sanitised env). `just skills-test` pytest with synthetic
~/org tree (incl. lock file), synthetic repo, dated milestone cases (Fall vs
Spring start, an MS-to-PhD transfer). Pre-commit + CI; `just deploy`
refuses on lint failure; new distilled files need Robert's review line.

### Skill waves

- Wave 0: skeleton, manifest seeded with every source above, fetch/convert/
  lint/sync/deploy tools, borg-skill-authoring, CI.
- Wave 1 (Phase 1/2): phd-milestones, group-monitor, meeting-scribe,
  delegation, code-audit. Topics: kaust-cemse-milestones, doctoral-process,
  lab-management, org-format, agent-orchestration, task-decomposition,
  research-software-practice, fair4rs-and-joss, security-basics.
- Wave 2 (Phase 3/4 prep): progress-review, mentoring-compact,
  mentoring-session, research-planning, literature-review, paper-writing,
  response-to-reviewers, kaust-admin + browser-forms (secretary; grounded in
  pa protocols, KAUST policy pages, `feedback_complete_forms`; browser
  helpers tested against a local mock form, real portals only `--dry-run`
  until Robert approves the first submission).
- Wave 3: talk-design, thesis-writing, reproducibility-check,
  experiment-tracking, software-release.
- Wave 4: lecture-design, course-design (before next teaching semester),
  grant-writing, ontology-review.

## Emacs cockpit (`emacs/`)

Verified environment: Emacs 30.1 (native-comp, inotify), no eat/vterm
installed (eat available from NonGNU ELPA, vterm buildable), elpa
`transient-20231103` shadows the built-in 0.7.2 and the 2023 magit depends on
it, only server socket is `gnus`, `C-c b` free, `notify-send` + `jq` present,
`~/.claude/settings.json` has `"tui": "fullscreen"` and no hooks.

Decisions:
- **Thin client.** `cube-remote-host` (default `"ws"`): every backend call is
  `ssh ws cube ... --json` (async, `make-process`), remote files via TRAMP,
  event tail via `ssh ws tail -F state/events.jsonl`. Local mode (`nil`) kept
  for development. All knowledge (skills, brain, beads, runs) stays on ws.
- Own generic session manager over **eat** (vterm switchable), not
  claude-code.el: fleet is multi-CLI (claude, codex, `hermes -p X chat`,
  `cube run --attach`, shells to IBEX), and claude-code.el needs transient
  >= 0.7.5 which risks the old magit. Borrow its eat tuning (TERM, S-TAB/ESC,
  scroll fix). Can adopt `*aider*`/`*claude:*` buffers into the ring.
- Interactive sessions are **tmux sessions on ws** (`tmux new -A -s
  cube/<name> <cmd>`) attached through `ssh -t` inside an eat buffer, so they
  survive laptop disconnects and are reachable from any machine; headless
  runs are `cube run` processes on ws. Ring state comes from `tmux ls` on ws
  plus `cube status`, not from Emacs memory. Resume via `claude --resume` /
  `codex exec resume` when a tmux session died.
- Main Emacs runs `(server-start)` as `cube`; Gnus daemon stays separate;
  email approvals bridged with `(server-eval-at "gnus" '(claude-email-compose ...))`.
- Prefix `C-c b` with `repeat-map` so `C-c b n n n` flips the rolodex.
- Dashboard and review queue on `magit-section` (installed); flat lists on
  `tabulated-list-mode`. transient usage limited to the 0.4-compatible subset.
- Notifications: on ws, Claude/Codex hooks (`claude --settings
  emacs/claude-hooks.json`, Codex `notify`) call `cube notify`, which appends
  to `state/events.jsonl` and rewrites `state/attention.json`; Hermes and
  patrols do the same. The cockpit tails events over ssh (reconnecting
  process; 60 s poll fallback) and routes them through `cube-notify` in
  Emacs. When running locally, inotify replaces the tail. No HTTP server, no
  D-Bus. Desktop `notify-send` only for attention/permission/error/finished
  when the session buffer is not selected. `cube-server.el` still starts the
  `cube` Emacs server so local agents (and the Gnus bridge) can call in.

Files: `borg-cube.el` (defcustoms `cube-root`, `cube-program` with `uv run`
fallback, `cube-terminal-backend`, `cube-prefix-key`, `cube-attention-count`
3, `cube-claude-tui`; global `cube-mode`; keymap; transient `cube-menu`;
async JSON helper `cube--call-json-async`; mode line `⚠3 ●5`),
`cube-term.el` (eat/vterm abstraction + activity hook), `cube-rolodex.el`
(`cl-defstruct cube-session`, buffers `*cube:<kind>:<name>*`, attention-first
ordering, next/prev/jump/toggle, kill/restart/resume, header line,
`cube-run-headless`), `cube-dashboard.el` (`*cube*`: Attention (3 loudest),
Fleet, Ready work, Students, Papers, Repos; parallel async refresh; RET
dispatch by item type), `cube-beads.el` (list/show/create/claim/close, org
link type `bead:`, org-capture key `b` creating a bead), `cube-org.el`
(person files, `cube-org-meeting-note` inserts dated heading newest-first,
pull agent notes as `** Agent notes :draft:` with `:RUN:`, papers.org state
sync preserving the custom TODO sequence), `cube-review.el` (approval queue;
`a` approve = the ONLY outbound trigger, calls `cube approve`; email kind
opens a Gnus draft instead of sending), `cube-server.el` (agent-callable
API: `cube-notify`, `cube-session-register`, `cube-open-file`,
`cube-show-markdown/org/diff`, `cube-ask-user` writing an answer file,
`cube-add-attention`; inotify watcher), `claude-hooks.json` (passed via
`claude --settings`, leaves `~/.claude/settings.json` untouched),
`bin/cube-emacs-hook`, `test/` (ert + fixtures + fake `cube` binary),
`Makefile` (compile with warnings as errors, ert batch).

Keymap `C-c b`: `d` dashboard, `!`/`1-3` attention, `n`/`p` flip, `j` jump,
`l` fleet, `b` toggle back, `c`/`x`/`h`/`$` new claude/codex/hermes/shell,
`r` run role, `s` student session, `S` dossier, `m` meeting note, `M` pull
notes, `P` papers, `w`/`W` beads ready/create, `v` review queue, `k` kill,
`R` restart/resume, `y` send region or `@file:line`, `g` refresh, `B` brief,
`D` doctor, `?` menu. In session buffers: `<escape>` interrupt, `<backtab>`
mode cycle, `C-c C-o` open context.

JSON contract (`emacs/INTERFACE.md`, fixtures shared with backend tests):
`cube status`, `cube attention` (items with kind, severity, age, target,
actions), `cube ready`, `cube people`, `cube student <slug>`, `cube papers`,
`cube repos`, `cube approvals`, `cube approve/reject`, `cube run --json`,
`cube doctor --json`; all `--json`, cockpit tolerant to missing keys.

Deployment: three lines in `~/.emacs` (`add-to-list 'load-path`, `(require
'borg-cube)`, `(cube-mode 1)`); `package-install eat`; Codex `notify =
[".../bin/cube-emacs-hook", "codex"]` in `~/.codex/config.toml` (doctor
checks). Optional separate housekeeping: delete stale transient-20231103 and
upgrade magit together.

Cockpit steps: spike (eat vs vterm vs `tui inline` with claude/codex, pin
fixtures) -> v0 rolodex -> v1 dashboard (fake `cube` suffices) -> v2 beads +
org + review -> v3 server/hooks/notifications/polish. Each with ert on pure
functions and a manual checklist.

## Phased roadmap (stop points for Robert in bold)

Phase 0, bootstrap (developed on the laptop, deployed to ws from day one).
`git init` + `gh repo create leechuck/borg-cube --private` (everything,
including corpus manifest, brain, roles, elisp, lives in this one private
repo; `runs/`, `state/`, `.env`, fetched corpus and any signature assets are
gitignored), `uv init`, package skeleton, justfile, CLAUDE.md/AGENTS.md,
`.env.example`, `.gitignore`; on ws: install `just`, `tmux`, `bd` (curl
script), `skills-ref`, clone data repos (`~/org`, `~/pa`,
research-knowledge-graph, borg-website), `claude login` + `codex login`,
`bd init`, `bd setup claude`, `bd setup codex`; add `[profiles.cube-chatgpt]`
to `~/.codex/config.toml` on ws and laptop (default untouched); `cube seed`
(skills, brain, `bd remember` from borg-infrastructure, pa, org, skills
library, Claude memory); `cube doctor`; `people.yaml` for 15 students + staff
with sources and the known conflicts listed; `contacts.yaml` empty (no
grants); ADRs 0001-0011; skills Wave 0 tooling + manifest seeded; Emacs
thin-client spike (`ssh ws cube`, eat + `ssh -t ws tmux`). **Stop: Robert
reviews ADRs, doctor output, people.yaml, seeded brain.**

Phase 1, read-only monitoring, Robert-only. `sources/*`, `kaust_rules.py`,
`sync/` (dry-run first), patrols milestones/deadlines/papers/calendar plus
the sysadmin patrols wired to hermes-infra (`infra-check` -> incident beads),
`cube digest`, systemd timers on ws (`just install-timers`), skills Wave 1
(phd-milestones, group-monitor, meeting-scribe, delegation, code-audit,
sysadmin runbooks) with distilled topics; vLLM on node005 deployed and
evaluated (model choice), `local` tier live; Concierge Hermes profile
(Robert-only DM) for remote access; Emacs v0 + v1. No LLM calls except bulk
summarisation and Concierge. **Stop: two weeks of daily digests judged useful.**

Phase 2, grounding library. Skills Wave 2 + brain/ doctrine, rubrics,
playbooks; `cube brain push` -> `bd remember`; `just deploy-skills`.
**Stop: Robert reads each SKILL.md and distilled reference.**

Phase 3, worker fleet with review gate. Opens with the one-week Gas Town
spike on ws (one rig, one convoy, Claude + Codex runtimes) and the adopt/
cube-only decision (ADR-0010). Then `runners/` (incl. `gastown` runner if
adopted), `router/`, `engine/`, `cube run/review/worker`, worktrees or Gas
Town hooks, sessions, budget tracking; first real uses: Editor dual-agent
review on one paper bead, Auditor on one bio-ontology-research-group repo,
Programmer on a cube-internal bead, Sysadmin on one real incident from
hermes-infra, Secretary on one real travel or reimbursement form end to end
(pre-fill -> approval bead -> Robert approves -> submit -> receipt recorded);
Emacs v2. **Stop: one demo bead design -> implement -> review
shown in the cockpit.**

Phase 4, advisor pilot with 1-2 volunteers (first outbound contact). Robert
picks students and records grants in `contacts.yaml`; Hermes `advisor`
profile + `@borg-advisor` bot on ws with allowlist generated from grants;
transparency note sent by Robert; weekly check-in; Scribe drafts; `cube
approve` from Emacs or Concierge; escalation beads; Emacs v3. **Stop: 4-week
pilot review with the students; decide whether any action class becomes
autonomous for granted students.**

Phase 5, lecturer/course. Course epics from `~/org/cs*.org` + rkg courses;
skills Wave 3/4 (talk-design, lecture-design, course-design); decks via
presentation skill. **Stop: one lecture deck for cs249/cs321 accepted.**

Phase 6, polish. Emacs cockpit polish, `cube tail`, Beads server mode
decision, grant-writing/ontology-review skills, corpus-verify monthly timer.

## Verification

- pytest on fixtures: `kaust_rules.py` table-driven (Fall 2023 PhD ->
  qualifier end of semester 3, proposal end of semester 5, 4y+1; Spring
  start; an MS-to-PhD transfer), org/papers/deadlines parsers,
  reconciler decisions, router fallback + privacy refusal, RunResult
  validation, lease expiry; skill scripts each with a test; `skills_lint`.
- `runners/stub.py` canned RunResult so `cube run --runner stub` exercises the
  full engine; `cube run --dry-run` prints commands for claude/codex/hermes.
- `cube doctor` green at each phase; `cube sync --dry-run` diff reviewed
  before first apply; patrols `--dry-run` a week before creating beads.
- Emacs: `make check` (byte-compile warnings as errors + ert), fake `cube`
  binary for manual dashboard checks; manual checklists per version.
- Phase 3 acceptance: demo bead by Leader (Fable), implemented by Codex in a
  worktree, reviewed by Opus/Fable, closed only after approval; transcripts
  in `runs/`, audit lines present.
- Phase 4 acceptance: consent recorded; one full check-in with approval; org
  entry appended with `:cube:` tag + permalink provenance; escalation
  round-trip; kill switch stops the gateway.

## Risks

- Subscription terms (Claude Max headless, ChatGPT via Codex): keep usage
  Robert-attributable and capped; no SDK with OAuth; Hermes on
  OpenRouter/Codex/local; ADR-0006 revisited if terms change; API keys with
  budget as fallback.
- Beads/Dolt on Linux: pin version, nightly `bd export` JSONL backup, xid
  headers allow re-derivation; group model never lives in beads.
- Hermes churn (ws is 195 commits behind already): templates rendered by
  `cube hermes render`, pinned version, advisor memory outside Hermes.
- Student consent/trust: opt-in, written transparency note, `cube student
  export` shows everything stored, pilot review, bot never assesses.
- Source conflicts: conflict beads, never silent resolution.
- Citation rot / fabricated references: `corpus-verify` Crossref check; no
  Sources block without a verified id.
- vLLM on node005 via SLURM: `local` tier queues rather than degrades.
- eat fidelity with fullscreen TUIs: spike first; vterm and `tui inline`
  fallbacks.
- Secretary acting in KAUST portals: SSO sessions expire (MFA), portals change
  layout, a wrong submission is hard to undo. Mitigations: session reuse only,
  `--dry-run` default, screenshot + field table before every submit, approval
  gate with one-time authorisation for signatures, confirmation numbers
  recorded as provenance, no autonomous submissions in any phase.
