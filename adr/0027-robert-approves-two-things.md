# ADR-0027: Robert approves two things; the cube reports on finished goals

Status: accepted
Date: 2026-09-08
Extends: ADR-0023 (the cube runs itself), ADR-0024 (decisions on Mattermost),
ADR-0025 (the laptop liaison channel), doctrine 7a

## Context

After ADR-0023 and ADR-0024 Robert still received too much. Between
2026-09-07 07:00 and 2026-09-08 07:20 the outbox cron posted thirteen
decisions to his DM: two sysadmin change bundles (borg-server reboot,
unimatrix01 upgrades), but also a permission ask about probes, an escalation
about a journal line, a milestone warning, a question about a colleague's sudo,
two FLOPO status DMs waiting for approval, two overdue personal deadlines from
`deadlines.md`, and file-change approvals for edits inside the repo. Sixteen
decisions were pending on ws that morning; two of them (`cube-b09l`,
`cube-rowz`) carried both `triage:routed` and `needs:robert`, because the
agent had put the label back and the triage patrol never routes a bead twice.

Robert, 2026-09-08: the cube is largely autonomous. He approves (a) changes
to running systems (borg-server, ontolinator, leechuck.de) and (b) data
retrieval from his laptop through the liaison; otherwise it runs on its own.
He wants larger reports, mainly when larger goals finish. And the liaison
should have a tool for read-only operations on the laptop, allowed for whole
directories such as `~/Documents/papers` and `~/Public/software`.

Two other things were noise of a different kind. hermes-ws's gateway posted
every tool call ("Running ls ...", "Running code from hermes_tools ...") and
asked for approval of an `execute_code` script that only ran `ls | grep`.
And the cube's most frequent error, "error: no JSON object in output", was in
every case a timeout: the Hermes worker profile on unimatrix01 assumed a
larger context window and asked for 65536 output tokens, so every call past
65k input tokens failed with "maximum context length is 131072 tokens" (78
times in the worker log), the loop retried until the 1800s deadline, and the
runner reported the empty stdout as a parse error. The workers' own
`python3 -c` and heredoc scripts were the most blocked commands (60 of 66
blocks), each a wasted turn on the way to that deadline.

## Decision

1. What Robert decides, exactly. `decisions.systems` in `cube.yaml` lists the
   running systems. A bead or escalation that names one of them (whole word,
   title or body), or an approval that names one in its summary, subject or
   target paths (a diff that mentions ws in a comment is still a checkout
   change), is his; so is a laptop read outside the
   readable directories (below), and the CLAUDE.md floor stays: contact with a
   person, a person's data, a secret or local-only material leaving the local
   tier, a deletion, spend over the budget. Everything else is answered by the
   policy or settled by the coordinator. Robert named borg-server, ontolinator
   and leechuck.de; unimatrix01 and ws stay on the list because CLAUDE.md
   still gates every restart, deletion and config edit there and nobody else
   executes such a change. Striking a name is one edit.
2. Policy and triage carry it. Three policy rules: a `file_change` approval
   that names no system is approved (a reversible git change behind the review
   gate; deletions still trip the guard); a `mattermost_dm` to Robert himself
   is approved (a message to Robert is not contact with a person, so the
   outbound guard exempts him); a sysadmin proposal that names no system is
   accepted. Triage rules route to the coordinator every question, finding,
   request, proposal and prepared change that carries `needs:robert` without a
   critical flag and names no system; a deadline finding is deferred into the
   digests. `cube question new` files for the coordinator unless `--critical
   security|privacy` says why the matter is Robert's; the coordinator itself
   cannot ask without the flag. A routed bead that comes back with
   `needs:robert` is routed once more (`triage:routed-twice`); a third ask
   stands.
3. The liaison reads the readable directories on its own. `hosts.laptop.readable`
   lists them (`~/Documents/papers`, `~/Public/software`); `unreadable` lists
   what stays closed inside them, and it matters: on the laptop `~/pa` is a
   symlink to `~/Public/software/pa`, so the private KG sits inside the
   software root. Credential stores and harness homes are closed everywhere.
   The new `liaison` role has `read_roots: host`: the Claude Code runner adds a
   path-bounded `Read(//root/**)` rule per readable directory and a deny rule
   per closed one (deny wins; both verified with `claude -p` on 2026-09-08).
   Grep and Glob are not path-bounded, so the role lists neither; `cube lookup
   ls|find|grep|head|git-log` searches instead, resolving every path (symlinks
   followed) and refusing anything outside a root, under a closed directory,
   or secret-shaped. The `laptop-lookup` skill documents the procedure.
4. Every other laptop read waits for Robert. `classify_request` decides from
   the question text alone, the same on both hosts: a request whose every named
   path lies under a readable directory is a lookup; one that names mail, a
   personal source, a closed directory, a path outside, or no path at all is
   personal. `cube request liaison` files a personal request already labelled
   `needs:robert laptop-read:approval`, so the decisions patrol announces it at
   its next tick; the liaison workday re-checks at the gate and never runs an
   unapproved one. Robert's "yes" adds `approved:robert` and keeps the bead
   open; the next laptop tick runs the mail path or the senior-role step with
   the full protocol prompt. "No" closes it. Naming the path is therefore part
   of asking: hermes-ws and the coordinator write the absolute path into the
   request.
5. A finished goal is one report. The goals patrol, on the tick it first sees
   a goal closed as achieved, writes `briefings/goals/<id>.md` (success
   criteria, close reason, what was done and by whom, what stayed open) and
   leaves the text in hermes-ws's inbox; the outbox cron posts it once. The
   patrol's own cursor keeps it idempotent. Status updates belong there and on
   the beads, not in DMs.
6. Errors name their cause. `failure_error` in the runners reports a timeout
   as "timeout after Ns; no result before the deadline" and an empty stdout as
   "produced no output"; "no JSON object in output" is kept only when there
   was output to parse. The cube-worker Hermes profile sets
   `model.context_length: 131072`, `model.max_tokens: 8192` and
   `compression.threshold: 0.4`, and allows the two script-execution classes
   in `command_allowlist` (the hardline patterns still block; `-q` mode still
   denies everything else flagged).
7. hermes-ws's gateway. `display.tool_progress: 'off'` in `~/.hermes/config.yaml`
   on ws stops the per-tool-call messages; it is a display setting, hot
   reloaded, and was applied on 2026-09-08 with a dated backup. `approvals.mode:
   smart` would let an auxiliary model wave through low-risk flagged commands
   such as the `ls | grep` script; that changes the gateway's security
   posture, so it went to Robert as approval bead `cube-pe17`. Approved and
   applied on 2026-09-08 (backup `config.yaml.bak-20260908-smart`).

## Consequences

- Robert's DM carries: sysadmin change bundles for the listed systems, laptop
  reads outside the readable directories, people and integrity matters, the
  daily literature brief, the coordinator's replies to his own instructions,
  and one report per finished goal.
- The coordinator now also answers questions from other agents and settles
  prepared changes that name no system; its workday prompt already says to
  decide what it can and to record why on the bead.
- The liaison's readable lookups leave the laptop for OpenRouter as before
  (ADR-0025); the request text and extracted lines are what leaves. The deny
  list is enforced by Claude Code's permission rules and by `cube lookup`; a
  harness without path rules (Hermes, Codex) is not used for the liaison, and
  the role loader refuses a `read_roots` role that lists Read, Grep or Glob.
- Existing pending beads: the next triage tick routes the ones that name no
  system to the coordinator (once more for the two that came back), defers the
  deadline findings, and leaves the borg-server, unimatrix01 and ws bundles.
- `just deploy` for the worker profile: `cube hermes render cube-worker
  --apply` on ws after the checkout is updated; the render was applied on
  2026-09-08 from the laptop copy of the template so the timeouts stop before
  the commit lands.
- The `reports: weekly` field on agents is still unimplemented; the weekly
  agent report is a follow-up.
