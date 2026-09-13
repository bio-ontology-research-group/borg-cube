# ADR-0024: Robert's decisions go out and come back through Mattermost

Status: accepted
Date: 2026-09-07
Extends: ADR-0019 (decisions, not a queue), ADR-0020 (hermes-ws is the fleet's
voice on Mattermost), ADR-0023 (what Robert decides)

## Context

After ADR-0023 what waits for Robert is short: approvals with the commands
ready, questions, people and integrity findings, critical escalations. They
sat in `cube decisions` and the cockpit, which Robert opens from the laptop.
Robert, 2026-09-07: can `needs:robert` run through the agent that has access
to Mattermost, so he can approve or not on Mattermost. hermes-ws already
carries the fleet's messages to his DM (the `cube-outbox` cron drains its
inbox every fifteen minutes) and relays his words to the coordinator.

## Decision

1. Out. The decisions patrol (every fifteen minutes), after the policy
   answers, announces every pending decision it has not announced before
   into hermes-ws's inbox, sender `cube`, as one message: `Decision <id>
   (<kind> from <asker>, <age>): <title>`, the summary, and the reply shapes
   (`"<id> approve" or "<id> reject"`, the question's options, or `"<id>:
   <your words>"`). `state/agents/hermes-ws/decisions-announced.json` holds
   what was announced; a decision that stops pending leaves it, so a reopened
   one is announced again. Without a hermes-ws agent on the host nothing is
   written. The outbox cron posts the message to Robert's DM unchanged.
2. Back. `cube decide --reply "<message>"` parses Robert's reply: the first
   decision id in it (`cube-...` or `apr-...`) must be pending; the rest is
   the answer. A word that is one of the decision's options, or a synonym
   (yes, approve, accept; no, reject, deny) mapped onto them, is the choice;
   anything else is free text where the decision allows it. The answer then
   takes the same path as `cube decide <id>`: routed to the asker, recorded,
   duplicates answered together.
3. hermes-ws's standing instructions: a message from Robert that names a
   decision id is a decision. hermes-ws runs exactly `cube decide --reply
   "<his message verbatim>" --apply` and posts the result line back. It never
   chooses, never rewords, and never does this for anyone but Robert in his
   DM.

## Consequences

- Robert approves the sysadmin's change bundles, answers questions and
  settles people matters from his phone; the cockpit stays the full view.
- Identity is the gateway's `MATTERMOST_ALLOWED_USERS` list plus the
  instruction to act only on Robert's DM. The infrastructure postdoc is on that list for
  ~infra-alerts; the residual risk is a relay of his words from that
  channel, bounded by the instruction and by the fact that every decision
  names its asker and is logged in `state/decisions.jsonl` with the reply.
- Latency is the outbox cron's fifteen minutes; no schedule polls Mattermost.
- `~/.hermes/AGENTS.md` on ws is not under git; the rule was added there by
  hand on 2026-09-07 and mirrored in `agents/hermes-ws/charter.md`.
