# Mattermost goal intake

Implemented on 2026-09-09 after Robert approved the gateway responsiveness fix.

## Cause

Hermes received the FLOPO goal at 12:02:56 but spent more than 24 model calls
investigating it inside the DM. Its default iteration ceiling was 500 and tool
progress was off. Domain-skill instructions competed with the fleet relay rule.
This was an OpenRouter chat loop, not a unimatrix01 inference timeout.

## New path

`hermes/plugins/cube-intake` uses the installed Hermes `pre_gateway_dispatch`
and plugin command interfaces. A `New goal:` message from Robert's exact
Mattermost user id and DM is rewritten to a one-use internal command ticket.
Other identities/channels are not intercepted. Direct attempts to forge the
internal command cannot supply a trusted payload. The normal gateway authorization
still applies. No Hermes core source is patched.

The asynchronous handler invokes `cube.gateway_intake` with JSON on stdin and
fixed argv, with a 30-second intake deadline. It saves the verbatim request as
a sourced `intake:goal` request bead, queues the coordinator and returns one
short acknowledgment containing the bead id. Receipts deduplicate by Mattermost
post id. Edited posts require a new message; existing saved text is not overwritten.
Credentials and grades/HR content are rejected by the existing screening helpers.
Screening is not a universal sensitive-data detector; normal privacy rules remain.

This is an intake record, not a fabricated dated goal. The coordinator owns scope,
missing dates, decomposition and source-backed follow-up. A private GitHub repository
is still external: laptop/mail/notes must follow the established liaison/privacy
rules. Intake itself performs no model call, filesystem research or outbound
contact besides the gateway's reply to Robert.

`cube-goal-coordinator.service` handles one saved goal in a bounded local
group-leader run. It explicitly selects the configured local Hermes model and
does not inject the full general-management workday context. Only successful runs
acknowledge their inbox message. A five-minute inactivity timer checks the local
inbox for remaining handoffs; it never polls Mattermost. Other research/source-scan
timers are not started by this change.

Ordinary chat has an eight-iteration ceiling and a prompt instruction to answer
or hand off after two tool calls. The latter is a soft instruction; the eight-turn
ceiling is the harness limit. `New goal:` is the deterministic trigger, not arbitrary
natural-language intent classification. Existing busy-session handling can delay
plugin-command dispatch while another chat turn is being interrupted/queued.

## Deployment and recovery

Copy the plugin directory to `~/.hermes/plugins/cube-intake`. Run
`tools/configure_gateway_intake.py` on ws while the gateway is stopped. It preserves
other configuration, enables this plugin, sets `agent.max_turns: 8`, and makes a
0600 backup of the previous config. Install the two `cube-goal-coordinator` systemd
units, reload units, enable the timer, and restart the gateway.

The stuck DM transcript was preserved and its routing session reset through the
Hermes SessionStore API. Hermes emitted a generic restoration reply on startup;
a separate concrete receipt for the recovered FLOPO request was therefore sent
once. FLOPO is intake `cube-dwv`, original post `<mattermost-post-id>`,
receipt post `<mattermost-post-id>`. Its 511-character request was recovered
from the original session, not rewritten from a summary.

Rollback: stop the dedicated timer/service and gateway, restore the private config
backup, and restart the gateway. Keep saved intake beads, inboxes and receipts;
do not erase accepted goals during rollback.

## Evidence and limits

The installed Hermes loader registered the plugin. Its real lifecycle hook and
command handler processed the existing FLOPO post in 0.38 seconds without a model
call or test message send, returning the same saved bead. An actual operational
receipt was then delivered to Robert's DM. Gateway logs confirm max_iterations=8
and an authenticated Mattermost WebSocket. Unit tests cover authorization, ticket
reuse, durable deduplication, screening, failure behavior and local model selection.

The first general-workday handoff exposed unrelated workday defects: oversized
argv, a cloud model pin sent to a local runner, and a missing post-reset memory
directory. Intake now uses the narrower goal dispatcher instead. These observations
are not evidence that every general agent workday is repaired. Background research
completion and end-to-end autonomous publication are separate from quick intake.
