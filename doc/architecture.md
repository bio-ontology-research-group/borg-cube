# Cockpit architecture

borg-cube keeps the interface on the laptop and the durable work on `ws`. The
workstation is the Beads writer, runner host, tmux host, scheduler, and source
adapter. The laptop can disconnect without ending a remote session.

```text
 +---------------- laptop ----------------+       +---------------- ws ----------------+
 | Emacs cockpit                          |       | cube CLI --[3]--> Beads ledger     |
 | fleet | session | dashboard            |-[1]-> |    |                            |
 |                                        |       |    +--[4]--> router and runners    |
 |                                        |-[2]-> | tmux sessions                      |
 |                                        |       |                 | [5]              |
 |                                        |       |                 v                  |
 |                                        |       |           headless run dirs         |
 |                                        |       |                                    |
 |                                        |       | systemd timers --[6]--> patrols     |
 |                                        |       |                          | [7]       |
 |                                        |       |                          v           |
 |                                        |<-[9]--| events, digests, cursors, Beads     |
 +----------------------------------------+       +---------+------------------+-------+
                                                          ^ [8a] read          | [8b]
                                                          |                    v
 +-------------------------------------------------------------------------------------+
 | External group model: ~/pa, ~/org, research KG, website roster, GitHub, calendar   |
 | Most sources are read-only                              guarded Org write path       |
 +-------------------------------------------------------------------------------------+
```

**[1] Laptop to CLI.** With the default `cube-remote-host` value, every normal
cockpit request becomes `ssh ws -- cube COMMAND --json`. Emacs renders the JSON
but does not own a second ledger or copy the group model. The `cube` executable
on the host must therefore match the interface on the laptop.

**[2] Laptop to tmux.** Interactive Claude, Codex, Hermes, shell, and attached
role sessions use an SSH terminal connected to `cube/*` tmux sessions on `ws`.
Closing Emacs, sleeping the laptop, or losing the network removes the view, not
the remote tmux process.

**[3] CLI to Beads.** `cube` reads and updates the Beads ledger through `bd`.
Beads contains work, dependencies, assignment labels, provenance, and status;
it does not contain the private group model. `ws` is the single operational
writer so a laptop never creates a divergent ledger.

**[4] CLI to router and runners.** `cube run`, goal spin, assignment with
`--run`, and the worker all pass through the same context builder, privacy
check, tier router, budget controls, and result validator. The selected runner
may be Claude, Codex, Hermes, OpenRouter, a local model, or the test stub.

**[5] Runners to sessions and run directories.** Interactive work has a tmux
session. Headless work writes a dated directory under `runs/` with metadata,
output, artifacts, and review evidence. A lease under `state/leases/` prevents
two runs from owning the same bead at once.

**[6] Timers to patrols.** systemd user timers start deterministic patrols on
`ws`. Patrols inspect milestones, deadlines, papers, repositories, calendar,
infrastructure, leases, and budgets. They do not call a model merely to decide
whether something changed.

**[7] Patrols to operational state.** A patrol can derive Beads work, update a
cursor, create a digest, or append a cockpit event when it is run with apply
enabled. A timer or command in dry-run mode reports the same plan without
persisting it. Judgment work is handed to a role through a bead.

**[8a] Sources to cube.** Source adapters read `~/pa`, `~/org`, the public
research knowledge graph, the website roster, GitHub, and calendar data. These
remain the sources of record. `cube sync` derives work and records conflicts;
it does not replace these repositories with a private borg-cube copy.

**[8b] Cube to Org.** Org is the deliberate exception to the normal read-only
source path. Meeting notes, todo changes, and property changes use the
lock-aware `cube org` path, show a diff, and ask Robert before applying. Other
draft changes remain in Emacs buffers for Robert to review and save. Direct
model writes to the authoritative Org files are not part of the architecture.

**[9] Events to the laptop.** The cockpit tails `state/events.jsonl` over SSH
and also polls attention. Hook events and patrol events update session glyphs,
notifications, the mode line, and dashboard caches. The tail reconnects after
an interruption; it is an update channel, not a command or contact channel.

## What is deliberately not automated

- **Contact.** No message, email, social post, GitHub comment, or Mattermost
  action reaches another person without a matching contact grant and Robert's
  approval. Ordinary approval still requires a separate delivery action.
- **Submissions and signatures.** Forms, papers, grants, portal actions, and
  signatures may be prepared for review, but they are not submitted or signed.
- **Restarts and deletions.** A sysadmin role can diagnose a problem and quote
  exact commands. It does not restart a service, cancel a job, delete data, or
  make another irreversible change without an explicit request and approval.
- **Grades and personnel judgments.** Grades and HR details never enter Beads.
  Sensitive assessments stay on the local-only path and remain Robert's
  decision.
