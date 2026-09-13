# borg-cube

The [autonomous fleet guide](doc/fleet.md) covers research autonomy, central
resource limits, fleet GitHub documentation and guarded Mattermost approvals.
The [private research explorer](doc/explorer.md) shows agent activity, usage,
work and memory, and can trigger bounded workdays from a browser through SSH.

Agent orchestration for a research group. borg-cube coordinates Claude Code,
Codex and Hermes agents around one work ledger (Beads), plays the roles a
group needs (advisor, lecturer, researcher hierarchy, code auditor, system
administrator, secretary), monitors real students, papers, software and
services, and is driven from Emacs. It is built for the Bio-Ontology Research
Group (BORG) at KAUST, but the architecture is generic: swap the data adapters
and the roster.

The system produces what a group produces: papers, software, services,
lectures and courses, and graduated students. It never contacts a student, a
colleague or an external service on its own; every outbound action is an
approval item for the group leader unless an explicit, recorded grant exists.

## How it is shaped

```
              laptop (thin client)                 ws (orchestration host, always on)
   Emacs cockpit  ── ssh ws cube --json ──▶  cube CLI ── Beads (bd) ledger
   C-c b …        ── ssh -t ws tmux ──────▶  tmux sessions: claude / codex / hermes
                                              patrols (systemd timers)  ─▶ findings, digests
                                              Hermes profiles (advisor, concierge) ─▶ Mattermost
                                              runners: claude -p, codex exec, hermes -z,
                                                       OpenRouter, local vLLM (unimatrix node005)
   group model (read only, never copied): ~/org, ~/pa knowledge graph, research knowledge graph
```

Three layers:

1. **Group model**, external and read-only: per-person org files and
   `staff.org`, the private project KG and deadlines in `~/pa`, the public
   research knowledge graph and roster. `cube sync` derives work from them.
2. **Work ledger**: [Beads](https://github.com/gastownhall/beads). Every bead
   carries a YAML header with an `xid` (idempotency key), provenance (file
   path and locator, Message-ID or permalink) and a deadline. Kinds: program,
   milestone, paper, experiment, review, audit, lecture, course, mentoring,
   meeting-note, service, finding, conflict, incident, outbound.
3. **Runtimes**: a Python engine (`cube run`) that assembles context (bd
   prime, bead, role prompt, doctrine, skills), routes to a model tier, runs a
   CLI headless, validates the JSON result, and applies it through a review
   gate; deterministic patrols on systemd timers ("crons watch, models act");
   Hermes for standing agents and the Mattermost gateway.

## Roles

| Role | Runtime | What it does |
|---|---|---|
| Group Leader | Claude Code (Fable, fallback Opus) | designs work, reviews everything before it closes |
| Senior | Claude Code (Opus) | turns designs into implementation beads |
| Programmer | Codex (ChatGPT profile) in a git worktree | implements; output goes to review |
| Auditor | Codex read-only pass + Claude verdict | audits repositories (FAIR4RS, JOSS, good-enough practices) |
| Editor | Claude + Codex second opinion | pre-submission manuscript review |
| Lecturer | Claude with presentation and course-design skills | lecture decks, courses (backward design) |
| Scribe | Hermes or Claude | meeting notes into org files, status paragraphs |
| Advisor | Claude / local vLLM; Hermes bot only for granted students | evidence summaries, milestone status, agendas for the leader |
| System Administrator | Hermes (extends the existing infra monitor) + Claude | incidents, runbooks, hygiene patrols; quotes commands before acting |
| Secretary | Claude with a browser session | KAUST forms and workflows; prepares, never submits without approval |
| Sentinel | Python patrols, no LLM | milestones, deadlines, papers, repos, calendar, infra |
| Marshal | Python | dispatches ready beads into worker slots |
| Concierge | Hermes (leader-only DM) | remote control from a phone |

Role definitions live in `roles/*.yaml` with prompts in `roles/prompts/`.
Every role has an empty `autonomous_actions` list for outbound actions;
`cube doctor` fails if one appears.

## Hard rules

- **Default deny on contact.** `contacts.yaml` holds per-person, per-channel,
  per-action grants with dates and evidence. `cube contact check` is the
  single gate used by runners and the Hermes allowlist generator.
- **Approval gate** on everything outbound or irreversible: messages, email
  drafts, PRs, form submissions, signatures, service restarts. `cube approve`
  is the only trigger; email approvals open a draft in the leader's mail
  client and are never sent by the system.
- **Provenance or nothing.** No fact enters beads, briefings or memory
  without a source. Source disagreements become `kind:conflict` beads.
- **Privacy classes** `public`, `internal`, `local-only`; local-only work runs
  only on the local vLLM tier or queues. Grades and HR details never enter.
- **Subscriptions used as intended.** Claude Max only through Claude Code
  itself; Codex through `codex exec` with the ChatGPT profile; Hermes on
  OpenRouter, Codex OAuth or local models.
- Kill switch: `cube kill on` stops patrols, workers and gateways at the next tick.

## Skills and grounding

Skills follow the [Agent Skills](https://agentskills.io) format and deploy
unchanged to Claude Code, Codex and Hermes. Each skill cites its sources: a
manifest (`corpus/sources.yaml`, 174 entries, DOIs verified against Crossref)
feeds a fetch, convert and distill pipeline that produces
`corpus/distilled/<topic>.md` files; skills copy them into `references/`.
`tools/skills_lint.py` refuses a skill without enough grounding, with
em-dashes, with Title Case headings, or with scripts lacking tests.

Twenty-three skills ship here, each with a procedure, hard rules, deterministic
scripts and tests:

| Role | Skills |
|---|---|
| Advisor | `phd-milestones`, `progress-review`, `mentoring-compact`, `mentoring-session`, `thesis-writing` |
| Researcher | `research-planning`, `literature-review`, `paper-writing`, `response-to-reviewers`, `experiment-tracking`, `reproducibility-check`, `grant-writing` |
| Lecturer | `course-design`, `lecture-design`, `talk-design` |
| Software | `code-audit`, `software-release`, `ontology-review` |
| Lead and monitoring | `delegation`, `meeting-scribe`, `group-monitor` |
| Admin | `kaust-admin`, `browser-forms` |
| Infra | `borg-skill-authoring` |

Each skill states what it does not own: `paper-writing` hands prose to the
`write-edit-scientific-paper` skill, `talk-design` and `lecture-design` hand
deck style to `presentation`, `reproducibility-check` hands cluster work to
`remote-connect`, `ontology-review` wraps `semantic-web` and ROBOT.

Grounding includes the PLOS "Ten simple rules" series, the National Academies
report on mentorship in STEMM, Vitae's Researcher Development Framework,
CIMER's Entering Mentoring, Wilson et al. on scientific computing, FAIR4RS,
the JOSS review criteria, Mensh and Kording on paper structure, Alley's
assertion-evidence approach, Mayer's multimedia principles, Wiggins and
McTighe's backward design, Biggs' constructive alignment, Freeman et al. on
active learning, and KAUST's own milestone rules.

## Emacs cockpit

```elisp
(add-to-list 'load-path "~/Public/software/borg-cube/emacs")
(require 'borg-cube)
(cube-mode 1)
```

`C-c b ?` opens the menu. The cockpit is a thin client: every backend call is
`ssh <host> cube … --json`, agent terminals are tmux sessions on the host
attached inside `eat`, files open over TRAMP, events arrive by tailing
`state/events.jsonl`. Dashboard (`C-c b d`), rolodex of agent sessions
(`C-c b n`/`p`/`j`), attention (`C-c b !`), beads, org integration (meeting
notes, papers sync), the approval queue (`C-c b v`), the tier menu to disable
or prefer a model when a subscription runs out (`C-c b T`), and the one-frame
cockpit layout, rolodex left, session center, dashboard below (`C-c b C`). The
dashboard header shows token burn per tier; an open incident renders as a P0
or P1 banner and in the mode line. See `emacs/README.org`
and `emacs/INTERFACE.md` for the JSON contract.

## Repository map

```
cube/        Python package: cli, config, beads wrapper, model, contact policy, doctor,
             sources/ (org, pa KG, research KG, GitHub, calendar, Mattermost events),
             milestones/ (KAUST rules), sync/, roles/, router/, runners/, engine/,
             approvals/, audit/, patrols/, student/, commands/ (auto-discovered)
roles/       role yamls and prompts          brain/     doctrine, playbooks, rubrics, facts
skills/      grounded skills                 corpus/    source manifest, distilled references
hermes/      profile templates and hooks     systemd/   patrol timers and services
deploy/      ws bootstrap, vLLM on node005, Gas Town spike, Codex profile
emacs/       cockpit                         adr/       architecture decision records
doc/         plan, install, operating, privacy, contact policy, student guide
tests/       pytest (cube and skills)        runs/ state/  runtime data, gitignored
```

## Install (orchestration host)

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), `just`, `tmux`,
`bd` (Beads), `claude`, `codex`, optionally `hermes`, `gh`, `pdftotext`.
See `deploy/ws-bootstrap.md` for the full sequence.

```sh
git clone git@github.com:leechuck/borg-cube.git ~/Public/software/borg-cube
cd ~/Public/software/borg-cube
uv sync --all-extras
cp .env.example .env && chmod 600 .env       # scoped tokens only, never passwords
BD_NON_INTERACTIVE=1 bd init --prefix cube
uv run cube doctor
uv run cube seed --apply                     # index existing skills, doctrine, memory
uv run cube brain push --apply               # doctrine facts into bd remember
uv run cube sync --dry-run                   # what the ledger would receive
uv run cube patrol all --dry-run
uv run cube systemd install --apply --enable # patrol timers
```

Codex workers use `~/.codex/cube-chatgpt.config.toml` (`model_provider =
"openai"`), because a default Codex config pointed at OpenRouter would bill per
token silently.

## Start here

Begin with the [cockpit guide](doc/cockpit-guide.md). It explains the three
panes, the daily workflow, goals and assignments, standing agents, projects,
budgets, session adoption, and recovery without requiring you to read code.

```sh
cube doctor --json       # check the host, policy and required tools
cube attention --json    # see the loudest decisions for Robert
bd ready --json          # list unblocked work in the Beads ledger
cube goals --json        # review goal progress, owners and blockers
cube pipeline status --json # review mail-to-gate research pipelines
cube group plan --json    # compare the declared research group with its agents
cube budget --json       # inspect tier use, runners and active swaps
```

## Status

The plan in `doc/plan.md` is implemented end to end. Phases 0 to 3 (bootstrap,
read-only monitoring, the grounded skills library, the worker fleet with its
review gate) run today. Phase 4, the student-facing advisor bot, is built and
stays inactive until a grant exists in `contacts.yaml`. Phase 5 adds course and
lecture work (`cube courses`, the course deriver, the teaching skills) and
phase 6 the remaining operational pieces (`cube tail`, the monthly
corpus-verify timer, the wave 3 and 4 skills). Gas Town is still an evaluation
for the coding fleet (`deploy/gastown-spike.md`), not a dependency.

Beyond the plan, the driver-seat layer added on 2026-09-02 and 03: goals
(`cube goal`, `cube goals`) with decomposition into person-owned and
agent-owned work, standing named agents with charters, memory and a bounded
autonomous workday (`cube agent`), assignment and creation of provenance-backed
beads (`cube assign`, `cube create`), the single org write path (`cube org`),
mail-to-gate research projects (`cube pipeline`),
adoption of running sessions and per-project runner profiles (`cube adopt`),
roster of record reconciliation (`cube roster`, ADR-0012), the project
portfolio (`cube projects`), token telemetry with proactive model swaps
(`cube budget`, `cube tier`), incident banners, and the Cube menu bar in
Emacs. Start with `doc/cockpit-guide.md`.

What is deliberately not finished: distilled references carry
`reviewed_by: null` until Robert reads them, and the sources that could not be
fetched (several books, the NAP reports, some KAUST and funder pages) are
marked in each Sources block as summarised from knowledge and pending
verification rather than presented as read.

## Student research twins

`cube twins sync --apply` derives one local-only research counterpart per current
student, with source-linked goals, literature, experiments, thesis/report drafts
and independent senior review. The explorer includes their activity and usage.
See [student twins](doc/student-twins.md) and [ADR-0030](adr/0030-student-research-twins.md).

## Grant seeker and writer

The `grants` agent searches for suitable funding, improves existing proposals
(initially CRG2026), and coordinates domain-expert input and independent review.
Private drafts stay on the local tier. Submissions and commitments remain
approval-gated. See [grant workflow](doc/grants.md).

Local worker admission, deadline handling and recovery are documented in
[local Hermes timeouts](doc/local-hermes-timeouts.md).

## Design lineage

The shape follows Steve Yegge's essays on agent orchestration (Beads as the
ledger, a rolodex of agent terminals in Emacs, "crons watch, models act", a
design-implement-review lifecycle with a stronger model reviewing), adapted to
a research group where the outputs are papers, software, courses and people.
Decisions are recorded in `adr/`.

## Licence

Code is copyright Robert Hoehndorf, all rights reserved until a licence file
says otherwise; skills and distilled references are CC-BY-4.0 where marked;
third-party sources keep their own licences as recorded in `corpus/sources.yaml`.
Site data (roster, hosts, ids) is not part of the repository.
