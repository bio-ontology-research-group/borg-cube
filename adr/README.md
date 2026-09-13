# Architecture decision records

One file per decision, numbered, never rewritten once accepted; a superseding
decision gets a new number and links back. Format: title, status, date,
context, decision, consequences, alternatives considered. Written in plain
language, no em-dashes, sentence-case headings.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-beads-as-work-ledger.md) | Beads is the work ledger, wrapped behind one Python module | accepted |
| [0002](0002-group-model-stays-external.md) | The group model stays external and read-only | accepted |
| [0003](0003-one-shared-advisor-bot.md) | One shared advisor bot with per-user sessions, gated by contact grants | accepted |
| [0004](0004-systemd-watchers-hermes-cron-judgment.md) | systemd timers for watchers, Hermes cron only for judgment and delivery | accepted |
| [0005](0005-model-router-tiers.md) | Model router with four tiers and strict fallback order | accepted |
| [0006](0006-subscription-usage-boundaries.md) | Subscription usage boundaries | accepted |
| [0007](0007-privacy-classes.md) | Three privacy classes on every bead and source path | accepted |
| [0008](0008-ws-orchestration-host-laptop-thin-client.md) | ws is the orchestration host, the laptop is a thin client | accepted |
| [0009](0009-contact-policy-default-deny.md) | Contact policy is default-deny with per-person, per-channel grants | accepted |
| [0010](0010-gas-town-for-coding-rigs.md) | Gas Town for the coding fleet, decided after a Phase 3 spike | proposed |
| [0011](0011-local-inference-on-node005.md) | Local inference on unimatrix node005 as the `local` tier | accepted |
| [0012](0012-roster-of-record.md) | The public profiles page is the roster of record | accepted |
| [0013](0013-deterministic-research-pipeline.md) | Deterministic research pipeline | accepted |
| [0014](0014-cost-aware-budget-routing.md) | Cost-aware budget routing | accepted |
| [0015](0015-free-openrouter-defaults.md) | Free OpenRouter defaults | accepted |
| [0016](0016-agentic-harnesses-on-openrouter.md) | Agentic harnesses on OpenRouter | accepted |
| [0023](0023-autonomous-cube-robert-decides-security-and-privacy.md) | The cube runs itself; Robert decides security and privacy | accepted |
| [0024](0024-decisions-on-mattermost.md) | Decisions go out and come back through Mattermost | accepted |
| [0027](0027-robert-approves-two-things.md) | Robert approves two things; the cube reports on finished goals | accepted |

`brain/decisions.md` is the agent-facing index of the same decisions with
one-line summaries.
