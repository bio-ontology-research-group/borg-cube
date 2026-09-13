# Grant seeker and writer

The `grants` agent finds funding and improves existing proposals, initially
CRG2026. It appears in the explorer with ordinary activity, token, memory metadata
and trigger controls. The existing workday timer picks it up without a new service.

```sh
cube agent workday grants --dry-run --json
cube agent workday grants --apply --json
```

Funding discovery runs at most weekly; proposal improvement gets at most one new
milestone daily. Inbox requests and revisions take priority. All work stays within
central fleet limits, and the fleet switch disables autonomous generation.
Results live under `state/agents/grants/work/`, with source references on Beads.
CRG2026's actual sources, status and call requirements must be established first.

The opportunity register records official call ID/URL, verification date,
eligibility, fit, deadline/timezone, amount, duration, partners and requirements.
Unknown eligibility is not an endorsement. Proposal work produces a compliance
matrix, ranked gaps, reviewable changes and responses to domain-expert feedback.
Routine requests are batched; only worthwhile shortlists and necessary decisions
reach Robert through the existing digest.

The agent and independent senior review run locally. Private proposal material
cannot go into cloud expert inboxes or GitHub. Use local-only work beads for
private expert contributions and public context for public literature requests.
Publication is metadata-only until a separate artifact release review. Mail and
laptop-only sources use the liaison, never an inbound connection from ws.
No application, signature, funder contact, spending or institutional commitment
is authorised by this role. Existing approval rules still apply.
