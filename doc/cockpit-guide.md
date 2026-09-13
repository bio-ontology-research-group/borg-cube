# Cockpit guide

This guide is for using the borg-cube Emacs cockpit without reading its Emacs
Lisp or Python. The menu path is given before the keyboard shortcut throughout.
`C-c b ?` opens the same command set as the Cube menu.

## What you are looking at

Load the Emacs feature with `(require 'borg-cube)` and enable it with
`(cube-mode 1)`. There is no interactive command named `borg-cube`; that is the
feature name. **Cube ▸ Dashboard ▸ Cockpit layout (`C-c b C`)** opens the
three-pane working layout:

- The narrow left pane is the fleet. It lists cockpit session buffers and
  sessions known on the host.
- The upper-right pane is the selected Claude, Codex, Hermes, shell, or role-run
  session. It shows a short help page until a session exists.
- The lower-right pane is the dashboard. It is the overview of attention,
  active work, people, projects, and services.

The dashboard header starts with `borg-cube on ws`. When the backend supplies
them, `attention`, `ready`, `running`, and `approvals` are item counts. The
`plan`, `impl`, `bulk`, and `local` values are percentage use of the configured
daily run or cost cap for each model tier. A percentage of 90 or more is shown
as a warning. An exhausted runner may also show the time at which it is expected
to become available again.

The current `cube status` payload supplies `running` and `adopted`, but not the
header's `attention`, `ready`, or `approvals` count fields. Blank values for
those three labels mean "not supplied", not zero. The sections themselves still
show their own data or error.

The default dashboard sections each answer one question:

- **Goals** shows active objectives with progress, time left, blockers, and
  stakeholders.
- **Pipelines** shows each research epic's title, current stage and iteration.
  Press `RET` on a row to open its focused pipeline status.
- **Attention** shows the loudest items that need Robert, including approvals,
  conflicts, failures, and sessions waiting for input.
- **Fleet** shows tmux sessions and headless runs known on `ws`, plus session
  buffers that only the current Emacs knows about.
- **Projects** joins the project records to their latest paper, software, and
  bead activity.
- **Ready work** shows unblocked Beads work that can be claimed or dispatched.
  The current backend has no `cube ready` endpoint, so this dashboard section
  shows an error; **Cube ▸ Work ▸ Ready beads (`C-c b w`)** remains usable
  because that view falls back to `bd ready`.
- **Students** shows each person's role, next milestone, last meeting, and an
  attention marker.
- **Papers** shows the tracked paper state, venue, deadline, and lead.
- **Literature** shows today's relevant arXiv and bioRxiv preprints with the
  student, project, goal or topic each one concerns.
- **Repos** shows repository branch, dirty state, ahead or behind counts, pull
  requests, CI state, and any audit bead.
- **Budget**, when enabled in `cube-dashboard-sections`, expands the tier bars
  and the state, reset time, and reason for every runner.

An incident appears as a P0 or P1 banner below the header rather than as a
normal section. Press **Dashboard ▸ Open item or toggle section (`RET`)** on the
banner to open its bead.

The mode line is a compact alert, not a general status display:

- `P0` or `P1` means an incident of that severity is open.
- `⚠N` is the number of cached backend attention items plus local sessions in
  attention or error state. An item that needs nothing more (an error already
  handled) is dismissed with `d` on its dashboard row, which runs `cube
  attention ack ID --reason TEXT --apply`; error items otherwise stay 24 hours.
- `●M` is the number of running local session buffers.

The fleet and session header use a separate set of state glyphs: `⚠` needs
attention, `✖` is an error, `○` is idle, `●` is running, `†` has exited, and `?`
is unknown. A session header such as `[2/5] codex:paper ●running 3m` gives its
position in the rolodex, kind and name, state, and age.

`(loading)` means that section has never returned data. `(refreshing)` means a
request is in flight. A Cube menu entry ending in `refreshing...` means that its
local cache is empty; opening a menu never starts a network call. A dashboard
marker such as `[projects failed (255): ...]` is the failed command and exit
code. If that section returned successfully before, it also says `showing stale
data` and keeps the old rows visible.

The default backend is the checkout on the always-on workstation `ws`. A normal
cockpit query is executed as `ssh ws -- cube COMMAND --json`; interactive
sessions use `ssh -t ws -- tmux ...`. The laptop holds only the interface and
terminal attachments. If `ws` or SSH is unreachable, each affected section
gets its own error marker and any cached data stays visible. There is no
automatic local fallback. Sessions already running in tmux on `ws` keep
running, but the laptop cannot see or control them until SSH returns. The event
tail reconnects with increasing delays, while ordinary dashboard calls wait for
the next refresh.

## Ten-minute tour

Before the tour, load `borg-cube` and enable `cube-mode` as shown above.

1. **Cube ▸ Dashboard ▸ Cockpit layout (`C-c b C`).** Start here. The command
   saves the current window arrangement, builds the three panes, starts all
   dashboard requests in parallel, and leaves point in the session pane.

2. **Cube ▸ Dashboard ▸ Loudest attention item (`C-c b !`).** Open the first
   item that needs a decision. Use **Cube ▸ Dashboard ▸ Attention item 1, 2, or
   3 (`C-c b 1`, `C-c b 2`, `C-c b 3`)** when you want a specific item from the
   short list.

3. **Cube ▸ Work ▸ Ready beads (`C-c b w`).** Move to a row and use **Ready
   beads ▸ Open bead (`RET`)**. The bead buffer shows its provenance, labels,
   acceptance conditions, parent, and dependencies. Use **Ready beads ▸ Claim
   bead (`c`)** only when you intend to own the item.

4. **Cube ▸ Sessions ▸ Attach tmux session (`C-c b L`).** Choose a `cube/*`
   session on `ws`. The displayed completion name omits the `cube/` prefix.
   **Session ▸ Send ESC (`<escape>`)** interrupts the terminal agent, and **Session ▸
   Open session context (`C-c C-o`)** opens its bead, run log, or working
   directory.

5. **Dashboard ▸ Refresh dashboard (`g`).** Put point in the dashboard pane
   first. This refreshes all nine backend calls. By contrast, **Cube ▸ Control
   ▸ Refresh (`C-c b g`)** refreshes only the cached attention list.

6. **Dashboard ▸ Restore layout (`q`).** Put point in the dashboard and restore
   the window arrangement that was active before the cockpit opened.

## Decisions: how agents ask you

An agent that needs a decision only you can make stops and asks. Every way it
can ask now ends up in one place.

The channels behind the list:

- an outbound approval in the approval store (an email, a Mattermost message, a
  file change), the same items the review queue shows;
- a `resource:approval` bead a standing agent files when a workday step needs
  IBEX, more GPU hours, or more spend than its charter grants;
- a pipeline recruitment request, when the coordinator wants another agent or
  role on a project team;
- a proposal, finding or conflict bead labelled `needs:robert`;
- a free-text question: `cube question new --from agent:ontology --text
  'Which release should the benchmark use?' --options 2025,2026 --apply`,
  which is the one command every role prompt and every agent context names.

Under each row the cockpit prints a short summary of the request (at most
`cube-decisions-body-lines` lines, default 4: the Question, Finding, Rationale
or Resources lines the agent wrote, else the first lines), so you decide on the
content, not the title. `RET` opens the full bead or approval. Identical asks
show once with a note "same request N more times"; one answer closes them all.

`cube decisions --json` normalises all of them into one shape, and the cockpit
shows them in two places: the **Decisions** section of the dashboard, right
under Goals, with the first `cube-decisions-count` rows (default 5) and the
total in the heading, and the full buffer, **Cube ▸ Review ▸ Decisions
(`C-c b D`, or `D` on the dashboard)**, grouped into Permissions, Questions,
Approvals, Other and Answered.

Each row shows who is waiting, how long, and what they ask, with clickable
buttons: `[Yes] [No]` for a permission or a recruitment request,
`[Approve] [Reject]` for an outbound approval, `[Answer]` for a free-text
question. Click one with mouse-1, or press RET on the button. From anywhere on
the row:

- `y` answers yes, approve or accept;
- `n` answers no or reject;
- `a` offers the options with completion, or opens a small compose buffer where
  you type the answer and send it with `C-c C-c` (`C-c C-k` cancels);
- `RET` opens the bead or the approval, `o` opens the first piece of evidence,
  `g` refreshes, `q` quits, `?` lists every key.

There is no extra confirmation: clicking `[Yes]` is the approval. The mode line
carries `?N` next to `⚠N`, so a waiting decision is visible from any buffer,
and the section refreshes with the attention poll.

What happens after each answer:

- **Permission, yes.** The bead closes with reason `robert: yes` and a
  single-use grant lands in `state/agents/<name>/grants.json`. The agent's next
  workday step with exactly those declared needs runs; the one after that asks
  again.
- **Permission, no.** The bead closes with reason `robert: no` and no grant is
  written.
- **Approval.** The answer goes through the review queue, so an email draft
  still opens in Gnus for you to read and send with `C-c C-c`, and nothing is
  ever sent by the cockpit. Delivery of anything else still needs
  `cube deliver <id> --apply`.
- **Recruitment, yes or no.** `cube pipeline recruit` adds the member to the
  team artifact and opens their critique bead, or `--deny` closes the request.
- **Question, finding or conflict.** The answer is commented on the bead as
  `Robert: <answer>`, the bead closes, and the answer reaches the asker: a
  standing agent's inbox, or, for a role, a `kind:request` follow-up bead
  titled `Robert answered: <title>` that the marshal dispatches.
- **Proposal, accepted.** The bead stays open and gains the label
  `approved:robert`, so the work can start.

If the asking agent lives on the laptop, the answer is recorded on `ws` and
delivered to that agent's inbox on its own host; the cockpit does that second
step for you.

Every answer is appended to `state/decisions.jsonl` and the last twenty show in
the Answered section, so you can see what you already decided.

## What answers itself

Most pending decisions are not choices you would ever refuse: a resource step
inside an agent's declared allowance, a role or agent joining a project team,
an advisory goal review, a reversible write under `runs/`. The `decisions`
block in `cube.yaml` lists those, and the `decisions` patrol answers them every
15 minutes. The shipped rules are:

- a `permission` whose resource class is `ws_cpu` or `gpu` and whose spend
  stays inside the budget: yes;
- a `recruit` whose candidate is an agent or a role (never a person): yes;
- the coordinator's "Review coordinator goal decomposition" proposal: accept;
- a `file_change` approval whose paths all sit under `runs/`, `briefings/` or
  `state/`: approve;
- a finding labelled `blocked`: reject, because it belongs to the group and not
  to you.

Everything else waits for you. On top of that, `never_automatic` lists the
classes no rule can ever touch: outbound approvals, anything labelled `people`
or `integrity`, conflicts, free-text questions, changes that delete a file, and
spend above the budget ceilings. `cube doctor` fails when a rule names a
guarded kind or answers with a word outside that decision's options.

A row the policy would answer carries a dim `auto: yes at next tick` tag after
its buttons. Press `n` (or `y`) on it and your answer wins; the rule never sees
it again. `P` in the decisions buffer runs the policy now: the plan appears in
`*cube-decisions-policy*` and nothing is answered until you confirm, exactly
like every other write. On the command line that is
`cube decisions apply-policy --dry-run`, then `--apply`.

Automatic answers raise no notification and no attention item. They appear as
one line in the daily brief: "Policy answered 3 decisions: ..." with the ids
and the rule note behind each. Set `decisions.digest: never` in `cube.yaml` to
drop that line. To change what answers itself, edit `decisions.policy` in
`cube.yaml`; the rules are tried in order and the first match wins.

## What the cube is working on

The `work` section of the dashboard is the answer to "what is the cube doing
right now". It sits directly under Goals and comes from one backend call,
`cube work --json`, so its two groups always agree with each other.

The **Agents** group has one row per standing agent:

```
◎ coordinator   ws      hourly  ●running cube-pjr.4 plan1:final (3m, glm-5.3-flash)  inbox 2  today 1 run
● literature    ws      07:00   ○not-due next 07:00                                  inbox 0  today 0 runs
● liaison       laptop  */5 * * * * ○idle                                            inbox 1  today 0 runs
```

Read it left to right: the agent glyph and name, the host it runs on, when its
next workday tick is due, its state, the bead it is running now with its
pipeline stage, how long it has been running and on which model, unread inbox
messages, and today's runs. A paused agent shows `‖paused`; a stopped cube
shows `✗killed`.

The **Tasks** group has one row per open work item, running first, then
in-progress, then by deadline:

```
● cube-pjr.4    plan1:final  agent:coordinator    Final plan v1                       due 2026-09-10
○ cube-171      open         agent:literature     Read the new benchmark              due 2026-09-06
○ cube-180      survey       role:senior          Survey the literature
```

A task is any open bead carrying an `agent:`, `role:` or `pipeline-stage:`
label, plus every goal. The owner column says which agent or which role owns
it.

Keys on an agent row: `RET` opens the agent, `t` tells it something, `i` makes
it read its inbox now, `w` runs its workday, `T` opens its terminal session.
Keys on a task row: `RET` shows the bead, `c` claims it, `k` closes it.

`i` is the direct way to make an agent act on what you told it without waiting
for the next hourly tick. It runs `cube agent inbox NAME --now` on the agent's
own host and is restricted to the unread messages and the assigned beads those
messages name; it never starts the agent's general reading step. Like every
other write it goes through the dry-run gate first: the plan appears in
`*cube-agent-plan*` and nothing runs until you confirm.

## The keys are in the buffer

Every cube buffer prints its own keys under its heading, so nothing has to be
memorised:

```
RET open  t tell  i inbox  w workday  T talk  o url  c claim  k close  d dismiss  g refresh  y yes
n no  a answer  D decisions  x reject  s session  S dossier  m note  v review  b beads  ? all keys
```

The beads and fleet lists carry the same legend on their header line. Press `?`
in any cube buffer for the full list as a transient, grouped into Open, Act,
Agents and Navigate. Set `cube-show-key-legend` to nil to hide the in-buffer
legend; `?` keeps working.

## Literature watch

Every morning at 06:30 the `literature_watch` patrol reads yesterday's and
today's new submissions from arXiv (one Atom query over all configured
categories, paged 200 at a time, newest first, until it is past yesterday),
bioRxiv and medRxiv (the details API, paged 100 at a time by cursor), keeps the
entries whose title or abstract contains a configured keyword, a group topic
slug, an active project name or an open goal title, tags each with the
`per_topic_keywords` directions it hits, and writes them to
`state/literature/<date>.jsonl`. A request that fails is retried once after a
pause; a source that still fails is a warning on the patrol, never a crash. The
patrol calls no model and files no bead.

The `literature` standing agent then summarises those candidates on the bulk
tier. It only has work when candidates are pending, so an ordinary tick costs
nothing. Its output is validated against the candidate list (a paper that was
not fetched cannot appear, and every relevance record must say why) and written
to `briefings/literature/<date>.md` and `.json`.

What reaches you is deliberately small:

- `cube brief` grows a **Literature** block with at most five high-priority
  entries and the path to the full digest.
- One `kind:reading-list` bead per day carries the digest as provenance. It is
  labelled `needs:robert` only when a high-priority paper concerns a goal whose
  deadline is within 30 days.
- Each high-priority paper is appended to the `reading.md` of the expert agents
  that own the matched topic, with the arXiv or bioRxiv URL as its source.

In the dashboard the **Literature** section shows one row per entry. `RET`
opens the digest markdown, `o` opens the paper itself in a browser. From a
terminal, `cube literature` prints the same rows and `cube literature --json`
is the cockpit payload.

Configuration lives in the `literature_watch` block of `cube.yaml`: the arXiv,
bioRxiv and medRxiv categories, the keyword list, optional `per_topic_keywords`,
the daily summary ceiling and the digest directory. `cube doctor` checks it as
`literature_watch:config`.

## Set a goal and get work done

A goal is a provenance-backed Beads epic with a target date and testable
success criteria. Its children remain ordinary beads, so the same assignment,
runner, and review rules apply.

1. **Cube ▸ Goals ▸ New goal (`C-c b G`).** In the transient, use `t` for the
   title, `d` for the target date, `s` for each success criterion, `p` for an
   optional project, `P` for each person, and `v` for at least one
   `PATH::LOCATOR` source. `RET` previews the exact `cube goal new` dry-run,
   then asks before applying it.

2. **Cube ▸ Goals ▸ Goals (`C-c b O`).** This refreshes the goal cache. Open the
   Cube menu again and choose the named goal at the top of **Cube ▸ Goals**.
   The focused view separates ready agent work, work owed by people, and
   blockers.

3. **Goal ▸ Decompose for review (`d`).** In a focused goal, the group-leader
   role proposes child beads and opens the ordinary review queue. This command
   invokes the planning runner and records a proposal even in its preview mode,
   but it creates no child beads until the proposal is approved.

4. **Cube ▸ Review ▸ Review queue (`C-c b v`).** Select the decomposition and
   use **Review ▸ Load body (`RET`)** to inspect the proposed plan. Check the
   owners, dependencies, deadlines, acceptance conditions, provenance, and
   reasons for assigning human work.

5. **Review ▸ Approval (`a`).** For a goal-decomposition proposal, approval is
   the explicit apply step: the backend validates the saved plan again and
   creates its child beads. **Review ▸ Reject (`x` or `r`)** records a reason
   and creates nothing.

6. **Goal ▸ Spin ready agent (`s`).** On a ready agent row in the focused goal,
   the cockpit previews `cube goal spin`, asks for confirmation, then
   runs the selected role on that child. This action only accepts a ready child
   owned by a role. It does not turn a person's task into agent work silently.

7. **Cube ▸ Dashboard ▸ Fleet (`C-c b l`).** Watch the session or run state.
   Use **Cube ▸ Sessions ▸ Next session (`C-c b n`)** to move through the
   rolodex, and return to **Dashboard ▸ Refresh dashboard (`g`)** to see goal
   and work state after the run finishes.

The review queue exists for decisions that must remain human: proposed goal
decompositions, outbound contact, file or Org changes, and other irreversible
actions. For an ordinary approval, `a` records Robert's decision but does not
send or submit anything. Delivery is a separate, dry-run-first CLI operation,
`cube deliver APPROVAL --apply`. Goal decomposition is the documented special
case in which approval itself applies the reviewed plan. Email review opens a
Gnus draft for Robert to read and send.

## Research pipeline

A research pipeline is a goal epic that starts from mail Robert already sent.
It moves through liaison collection, team formation, two discussion-based
planning rounds separated by a literature survey, programmer experiments with
senior review, and a group-leader gate. Python creates the beads, dependencies,
stage transitions, and gate bookkeeping. Model work runs only through the
existing agent workday and `cube run` engine paths.

Start one with:

```sh
cube pipeline new --title "Project title" --target 2026-12-31 \
  --success "the final gate passes its stated threshold" \
  --from-mail "subject words or recipient" --apply
```

The collect request asks the laptop liaison to find the newest matching sent
mail and record its ideas, publication identifiers, links, and matching local
repositories.

### Team and discussion

After collection, the coordinator recruits the smallest team that covers
planning, literature, implementation, and review. A team can contain standing
agents, functional roles, and current people from `people.yaml`. Every member
has a source-backed reason. The validated team lives at
`runs/pipelines/<epic>/team.yaml`; `pipeline.max_team` limits its size.

Each planning round has a group-leader draft, one critique per team member, and
a group-leader final step. Agent and role critiques block the final step. A
person critique is related-only, stays on Robert's board, and never blocks the
pipeline. Collaborators are external people listed on the PA project page;
their critiques are related-only and any contact with them becomes an approval
item for Robert. Draft and final plans are stored as `plan-vN-draft.yaml` and
`plan-vN.yaml`. Critiques and the final acceptance or rejection decision log
live under `discussion/plan-vN/`.

Team members ask for help only through:

```sh
cube pipeline ask EPIC --from agent:ontology --to role:programmer \
  "Can you estimate this experiment?" --apply
```

Questions to a standing agent use its inbox. Questions to a role create a help
bead. A request for anyone outside the team becomes a coordinator recruitment
request and reaches nobody until approved. Any request to contact a person
becomes an outbound approval bead for Robert. The coordinator records a
decision with `cube pipeline recruit`; people and collaborators can be
recruited with a free-text project role after their roster or project-page
membership is validated. `pipeline.autonomy.recruit` defaults to
`robert` and can be set to `coordinator` explicitly.

After the second final plan, the pipeline patrol creates one programmer bead per
experiment and maps the plan dependencies into Beads dependencies. Programmer
results pass through the ordinary senior review gate. Once every experiment is
closed, the group leader reviews the combined evidence. An approve verdict
closes the epic. A revise verdict creates programmer follow-ups and then a new
numbered gate after those follow-ups close. A reject verdict, a recorded kill
criterion, or exhaustion of `pipeline.max_iterations` stops automatic progress
and labels the epic `needs:robert`.

Use `cube pipeline status EPIC --json` for one pipeline or omit the epic for
all pipelines. `cube pipeline advance EPIC --apply` runs one deterministic
transition. The ten-minute pipeline patrol normally performs that transition.
The coordinator workday reviews every open pipeline. It adds one briefing line
per epic and files an idempotent `needs:robert` finding for stale ready work or
an optional person critique that is still open when finalization begins.
Run `just pipeline-rehearsal` at any time to exercise the complete offline
fixture workflow, including discussion, expert recruitment, one revision loop,
and approval at gate 2.

The cockpit puts these commands in **Cube ▸ Pipelines**: **New pipeline
(`C-c b P n`)**, **List pipelines (`C-c b P l`)**, **Show pipeline (`C-c b P s`)**,
**Advance pipeline (`C-c b P a`)**, and **Rehearsal (`C-c b P r`)**.
The new-pipeline transient collects title, target date, repeatable success
criteria, sent-mail words or recipient, person, project and privacy. `RET`
renders the dry-run result, and `a` in that preview applies it and opens the
new epic.

**List pipelines** renders each epic's stage, iteration, gate verdict, kill
state and next-action sentence in `*cube-pipelines*`. `RET` opens
`*cube-pipeline: EPIC*`; its Stages, Experiments, Gate and Next sections expose
the underlying beads. There, `g` refreshes, `RET` opens a bead, `d` previews
an advance, `A` confirms and applies it, `T` talks to the coordinator, `t`
tells the coordinator, and `o` opens `plan-v2.yaml` over TRAMP with a
`plan-v1.yaml` fallback. Rehearsal opens a named rolodex shell session so its
transcript remains visible.

## Assign work to a person or an agent

Use a person assignment for something that person owes. Use a role assignment
for work the runner can perform. An assignment may also carry a project,
deadline, priority, and note.

1. **Cube ▸ Work ▸ Create bead (`C-c b W`).** Enter the title, then use `k` for
   kind, `r` for a role, `p` for a person, `P` for a project, `d` for a
   deadline, `i` for priority, and `y` for privacy. At least one acceptance
   condition (`a`) and provenance source (`v`) are required. `x` shows the
   dry-run and asks before creation.

2. **Cube ▸ Work ▸ Assign bead (`C-c b a`).** Choose the bead, then use `r` for
   role, `p` for person, `P` for project, `d` for deadline, and `n` for the
   assignment note. `RET` assigns after a dry-run and confirmation. `x` assigns
   and immediately runs the selected role after the same gate.

3. **Cube ▸ Work ▸ Run role (`C-c b r`).** Use this when the bead already has
   the right assignment and you want an interactive role run. The command asks
   for a role and optional bead before opening its host session.

A person's open assignments are beads with `person:<slug>`. For goal work they
also appear in the focused goal's **People** group, in `cube people` as `owed`,
and in the generated next-meeting agenda. On a person row in a focused goal,
`m` adds the item to that person's next-meeting agenda through a guarded Org
write.

**Cube ▸ People ▸ People board (`C-c b u`)** gives the direct operational view:
one row per current member with active-goal count, owed-item count, meeting age,
and next milestone. In that buffer, **People ▸ Open extended dossier (`RET`)**
shows the owed items and agenda, and **People ▸ Open notes (`o`)** opens the Org
file.

Assigning work to a person does not contact them. It changes the local ledger
and Robert's views only. Contact requires a matching person, channel, and action
grant in `contacts.yaml`, then a separate approval and delivery step. Without
that grant, the system creates work for Robert instead of sending.

## Spending limits

The global limits live in `cube.yaml` under `budget:`: `daily_total_usd`,
`weekly_total_usd`, per-tier `*_cost_usd_per_day`, `soft_cap_pct` and the
OpenRouter credits floor. The router enforces them on every run, the budget
patrol swaps or downgrades models near a cap, and `cube budget` (Cube ▸ Budget
in the cockpit) shows spend against each ceiling. A per-agent
`resources.spend_usd_per_day` of 0 means no per-agent gate: the global budget
governs, and the agent does not ask you for permission to spend.

## Contact hours

Agents work 24/7. People do not: `contact.hours` in `cube.yaml` (07:00 to
19:00 Asia/Riyadh, Sunday to Thursday) is the only window in which an approved
message to a person is sent. Approving outside the window keeps the approval
and marks it deferred; the hourly `deliveries` patrol sends it when the window
opens. `cube deliver ID --now` sends immediately when Robert wants that.

Desktop notifications are limited to a completed goal (`goal` event from the
goals patrol), an error, and a P0 incident (Robert, 2026-09-07). The same
session and title notifies at most once a day, and the backend marks a
repeated loud event `muted` so it never notifies twice even across cockpit
restarts. Attention, approval and permission events stay in the header line,
the `!` key and `cube attention`. Add `"approval"` to
`cube-server-notify-events` to hear about waiting approvals again
(`cube-server-notify-repeat-seconds` sets the window).

## The group as agents

Ontology and machine learning are deliberately separate experts (Robert,
2026-09-04); when one needs the other inside a project it asks through
`cube pipeline ask`, and outside a project the coordinator brokers the contact.

The `group` section of `cube.yaml` is the declaration of Robert's research group.
It maps each research knowledge graph topic to an expert allowance and adds
functional agents for software, manuscripts and teaching. The current experts
cover these topics:

| Agent | Topics |
|---|---|
| `ontology` | applied ontology, ontology engineering and semantic interoperability, semantic similarity |
| `machine-learning` | neuro-symbolic AI (ontology embeddings, description logic embeddings, learning with symbolic knowledge) |
| `protein-function` | protein function prediction, metagenomics and microbial function |
| `genomics` | genomics |
| `rare-disease` | rare disease diagnostic support, phenotype informatics |
| `biomedical-informatics` | biomedical informatics |
| `drug-mechanisms` | drug mechanisms and systems biology |
| `bioengineering` | bioengineering |

The functional agents are `research-software` for software release and
reproducibility, `editor` for manuscript review, and `teaching` for courses and
lectures. They add responsibilities to the topic experts without changing the
research knowledge graph.

To add an agent, add its name and topic or functional assignment to `group` in
`cube.yaml`, then inspect the proposed files:

```sh
cube group plan --json
cube group apply --dry-run --json
```

Robert applies the checked plan with `cube group apply --apply`. Existing agent
files are preserved. `--reconcile` updates only topics, skills and the declared
node005 GPU allowance. It never changes a charter or memory. `cube agent new`
remains available for a one-off scaffold and accepts `--skill`, `--gpu-hours`,
`--host` and `--spend-usd`.

Group charters are generated from the read-only research knowledge graph. Their
mandate cites the topic briefs, projects include their years, and the reading
seed contains only identifiers found in those briefs with an accepted format.
Generated charters begin with `reviewed_by: null`. Robert reviews and edits the
file, records `reviewed_by: Robert Hoehndorf` in its front matter, and only then
allows the first workday. Replacing an existing placeholder with
`cube group apply --apply --reconcile --charters` keeps the old file as
`charter.md.bak`.

Use `cube group status --json` for one row per agent with journal, inbox,
proposal, resource, pipeline and charter-review state.

## Talk to agents

Standing agents are named identities under `agents/`; roles are the functional
instructions used for individual runs. The coordinator spans topics, reviews
goals, and routes work. An expert keeps a narrower research remit and its own
source-backed reading and proposal history. Group charters are generated from
the research knowledge graph and remain subject to Robert's review. A direct
`cube agent new` scaffold still contains a placeholder until it is replaced or
edited.

There is not yet a direct standing-agent command in the Cube menu. Use a host
shell from the cockpit:

1. **Cube ▸ Sessions ▸ New shell session (`C-c b $`).** List the available
   identities with `cube agent list`, and inspect one with `cube agent show
   NAME`.

2. **Cube ▸ Sessions ▸ New shell session (`C-c b $`).** Run `cube agent talk
   coordinator --apply` for the coordinator, or replace `coordinator` with an
   expert name. `talk` assembles the charter, role prompt, doctrine, installed
   skills, memory tail, and unread inbox, then opens or reuses a persistent
   `cube/agent-NAME` tmux session. Without `--apply` it only shows the plan.

3. **Cube ▸ Sessions ▸ Attach tmux session (`C-c b L`).** Select
   `agent-coordinator` or the expert session after `talk` has created it.

4. **Tell (`t` on an agent row, `C-c b ,` for the coordinator).** A tell
   appends to `agents/NAME/inbox.jsonl`. If the agent's tmux session is live the
   message is typed there. Otherwise the cockpit wakes the agent: it starts the
   session, which reads the unread inbox in its context and answers there
   (`cube-agent-tell-wakes`, default on; set it to nil to only queue for the
   07:00 workday). From a shell the same is `cube agent tell NAME 'TEXT'
   --apply`. Use `talk` (`T`) for a conversation, `tell` for an instruction.

5. **Force a read now (`w` on an agent row).** An agent that is not live reads
   its inbox only during its workday. The `cube-patrol-agent-workday` timer on
   ws ticks every hour and every standing agent (`workday.cron: hourly`) checks
   its inbox and assigned beads on each tick, runs at most `max_runs_per_tick`
   steps, and idles at no cost when nothing waits. Agents work 24/7; only people
   have working hours (see Contact hours).
   `w` runs a workday immediately (dry run first, then apply); from a shell on
   ws: `cube agent workday NAME --now --apply`.
   The workday runs on the agent's `host:`, so the tell has to land on that
   host's checkout; a message queued on the laptop is not seen by ws.

The durable journal is `agents/NAME/memory/journal.md`. Applied workdays prepend
a source-backed summary and mark inbox messages read once a step for them
succeeded; a failed model run (outage, exhausted subscription) leaves them
unread and records `inbox` under `blocked`. Reading notes accept only
verified identifiers. Research proposals become Beads items labelled
`kind:proposal`, `needs:robert`, and `agent:NAME`; they therefore return to the
attention and review workflow rather than starting a project by themselves.

Autonomy stops at the declarations in `agents/NAME.yaml`, the role, and central
policy. Each workday is bounded by its maximum run count. `outbound` is fixed to
`none`; IBEX, unknown compute, excess GPU use, and excess spend create approval
beads. `cube agent pause NAME --apply`, the global `state/KILL` switch, privacy
routing, and the review gate can all stop work. A standing identity cannot make
its role, tier, contact rights, or resource allowance broader than the checked
configuration.

### Fleet drill

The fleet drill is a content-free hello world that proves the whole fleet can
talk. It exercises four routes: coordinator to every agent, every agent back to
the coordinator, one expert to another expert without the coordinator in the
middle (`ontology` asks `machine-learning` about embeddings and relays the
answer), and the coordinator back to Robert as a bead comment plus a close.

Three commands, all from a host shell on ws:

1. `cube fleet drill start --apply` creates one bead `Fleet drill DATE: hello
   world` with xid `drill:DATE`, labels `kind:task agent:coordinator
   drill:DATE privacy:internal`, and a description that is the script for the
   coordinator with every `cube agent tell` line already written out and the
   bead id filled in. Running it twice on the same day reuses the open bead.
   `--agents a,b,c` narrows the roster; the default is every loaded agent
   except the coordinator and the laptop liaison.

2. `cube fleet drill status [BEAD|--date D]` reads the bead and every
   `agents/*/inbox.jsonl` and reports what actually happened. It runs no model
   and writes nothing.

3. `cube fleet drill run --apply` starts the drill and runs the coordinator's
   workday immediately so the tells go out now, then prints the status. The
   experts are not run: their hourly ticks answer.

A green status prints one line per agent with both ticks set, then
`coordinator to agent: n/n`, `agent to coordinator: n/n`, `agent to agent:
asked [x] answered [x] relayed [x]`, `agent to Robert: comment [x] closed [x]`,
and the word `complete` with an empty `missing` list. Anything less lists the
gaps in `missing`, for example `genomics has not replied to the coordinator`.

## Projects, roster and org files

These views answer different questions and deliberately read different sources:

- **Cube ▸ Projects ▸ Projects list (`C-c b e`)** reads the private project KG
  in `~/pa/kg/projects`, the public research KG, `~/org/papers.org`, cached or
  live GitHub activity, publication records, and project-labelled beads. A
  project view shows membership, grants, topics, directories, activity, and
  ready work; `a` assigns a bead with that project preselected.
- **Cube ▸ People ▸ Roster (`C-c b p`)** compares `~/org/staff.org`, the public
  website pages, the website repository's `people/roster.md`, the research KG,
  and `people.yaml`. **Roster ▸ Open person or conflict (`RET`)** shows the
  disagreeing source values.
- **Cube ▸ People ▸ Student dossier (`C-c b S`)** reads the Robert-facing
  operational record for one student, including milestones, meetings, runs,
  and open work. It does not make the notes visible to the student.
- **Cube ▸ People ▸ People board (`C-c b u`)** reads `cube people` and shows all
  current members, including their goal count, owed count, meeting age, and
  next milestone.

The roster of record for membership and role is the public website, as declared
under `roster.authority` in `cube.yaml`. `people.yaml` is the local join table
for stable slugs, Org filenames, and service identifiers, not a competing source
of truth. Program comes from the website then `staff.org`, start date comes from
`staff.org`, and the Org filename comes from `people.yaml` then `staff.org`.
Disagreement is shown as a conflict rather than resolved silently.

To reconcile the join table, use **Cube ▸ People ▸ Roster (`C-c b p`)**, then
**Roster ▸ Preview roster sync (`s`)**. Inspect the proposed `people.yaml` diff,
then use **Roster ▸ Apply roster sync (`S`)** only after resolving source
conflicts.

For safe notes, prefer **Cube ▸ People ▸ Org editing (`C-c b o`)**. Its `m`
meeting note, `t` todo toggle, and `s` property update call the lock-aware
`cube org` writer. Each write shows a dry-run diff and asks before `--apply`.
In remote mode there is no direct-buffer fallback if `ws` fails. Open files over
TRAMP, save unrelated manual edits first, and do not approve a stale diff. The
local direct-buffer fallback is offered only in explicit local mode and asks
again before writing.

## Budgets and models

The header's tier percentages are the larger of run-cap and cost-cap use,
bounded at 100 percent. The detailed view also shows runs, tokens, cost, active
runner, manual disablement, learned usage-window exhaustion, temporary backoff,
and OpenRouter credit information.

1. **Cube ▸ Dashboard ▸ Budget (`C-c b U`).** Open the current tier and runner
   summary. If the optional Budget dashboard section is enabled, the same data
   appears as bars below the other sections.

2. **Cube ▸ Control ▸ Tier controls (`C-c b T`).** The active entry in each
   tier is marked `*`. `d` disables a runner for a duration and optional reason,
   `e` clears its disabled or exhausted state, `p` prefers a runner in one tier,
   `r` resets all controls and preferences, and `g` refreshes. Every change is
   previewed and confirmed before `--apply`.

A swap is a reversible tier preference installed by the budget patrol. At the
configured soft cap, currently 85 percent, it prefers the next usable entry in
that tier until the learned subscription reset or the next midnight. Low
OpenRouter credits can trigger the same behavior. A swap does not disable the
runner globally, and its source, destination, reason, and expiry appear in
`cube budget` and `cube status`.

Bulk work selects the configured free OpenRouter models first. Implement work
uses Codex first, then free OpenRouter models before paid fallbacks. Plan and
review work remains on subscription models. From a shell, `cube tier free-first
TIER --dry-run` previews a preference for that tier's first free entry. Repeat
with `--apply`, or use `--off` to restore the configured order. Free-capacity
failures back off that model for ten minutes. When every configured free model
is backing off and routing selects a paid entry, the attention stream shows a
warning.

To stop all routing to one runner, use **Cube ▸ Control ▸ Tier controls (`C-c b
T`)**, press `d`, select the runner, and give a duration such as `5h` plus a
reason. Use `runner:model` at the CLI when only one model should be disabled.
This affects new runs. It does not terminate an already running process.

## Adopt an existing session

Adoption is for a Claude, Codex, or Hermes process that already runs in tmux but
was not started by borg-cube. The backend verifies the pane command, requires a
Git checkout as its working directory, searches the runner's local transcripts
for a matching resume ID, records the session, and renames a non-Cube tmux name.

For a Codex session working in the `kobayashi-marust` checkout:

1. **Cube ▸ Sessions ▸ Adopt session (`C-c b E`).** Enter the existing tmux
   session name. In the transient, press `p` and choose `kobayashi-marust`, use
   `b` for an optional `cube-NNN` bead, and leave the role as `programmer` or
   change it with `r`.

2. **Adopt ▸ Preview and adopt (`RET`).** The
   cockpit first runs the backend dry-run and displays `*cube-adopt-plan*`.
   Check that the detected runner is `codex`, `cwd` is the intended checkout,
   the selected resume ID belongs to that checkout, and the proposed name is
   `cube/kobayashi-marust-codex`. Alternatives are reported when more than one
   transcript matches. Confirm only after those fields are right.

   Confirming the prompt records the metadata, renames the tmux session if
   needed, refreshes the fleet, and attaches it automatically. The configured
   project profile uses Codex as the runner, works in the checkout directly,
   runs `./tools/workspace-preflight.sh` before future project runs, and sets
   its project-specific environment.

The shell equivalent is `cube adopt EXISTING_TMUX_NAME --project
kobayashi-marust --dry-run`, followed by the checked command with `--apply`.
Later, **Cube ▸ Sessions ▸ Attach tmux session (`C-c b L`)** reattaches the
recorded `kobayashi-marust-codex` session.

## When something looks wrong

### The host is unreachable

**Cube ▸ Control ▸ Doctor report (`C-c b D`)** is the first cockpit check, but it
also needs SSH. If it fails, test `ssh ws -- cube status --json` in a local
terminal. Restore the network, SSH configuration, and `ws` first. Do not switch
to local mode unless you intentionally have a complete local checkout, data
sources, ledger, and credentials. The remote tmux sessions are normally still
alive.

### The laptop and host disagree

**Cube ▸ Help ▸ About (menu only)** reports the backend version. The cockpit
runs the `cube` found on `ws` through `ssh ws -- cube`, not the laptop's Python
checkout and not an absolute `.venv/bin/cube` path. After every laptop commit,
pull that commit in `~/Public/software/borg-cube` on `ws`, run `uv sync
--all-extras` when dependencies changed, and check `ssh ws -- cube --version`.
Missing commands, unexpected JSON keys, and a permanently failing single
section are common signs of version skew or a stale command on `PATH`.

### A command or policy check fails

**Cube ▸ Control ▸ Doctor report (`C-c b D`)** runs the configured checks for
paths, tools, profiles, tokens, policy, tmux, and the ledger. From a shell,
`cube doctor --json` gives the same structured report. Correct the named check
instead of bypassing it.

### Work must stop

**Cube ▸ Control ▸ Kill switch on or off (`C-c b K`)** is the intended guarded
control, but the current Emacs call adds `--json` and the current `cube kill`
parser does not accept that option. Use **Cube ▸ Sessions ▸ New shell session
(`C-c b $`)** and run `cube kill on` or `cube kill off` on `ws` until the two
sides agree. The marker prevents future timer starts and is checked by workers,
patrols, and standing-agent workdays at their next boundary. It is not a promise
that arbitrary processes already running have been terminated, so inspect the
fleet after enabling it.

### Find the evidence

**Cube ▸ Help ▸ Doctor report (menu only)** gives the health report, and **Cube
▸ Dashboard ▸ Fleet (`C-c b l`)** shows live sessions and leases. The main
locations are:

- `*cube-log*` for cockpit command and reconnect messages.
- `state/events.jsonl` for the event stream and `state/audit.jsonl` for audited
  decisions and dispatches.
- `runs/YYYY-MM-DD/RUN-ID/` for `meta.json`, runner output, transcripts,
  artifacts, and review results.
- `state/leases/`, `state/cursors.json`, `state/tiers.json`, and
  `state/approvals/` for current control state.
- `journalctl --user -u 'cube-patrol@NAME' --since today` for a patrol service,
  and `journalctl --user -u 'cube-worker@3' --since today` for the worker.
