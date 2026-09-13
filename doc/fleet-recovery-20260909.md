# Fleet recovery and agent review, 2026-09-09

Source: Robert's request to fix publication, schedule against measured local
throughput, review the agents with Terra, and consider a clean start. Work bead:
`cube-ekym`. Two Terra reviewers audited research, twin and operational roles;
the main agent inspected runtime evidence and the proposed interactions.

## Confirmed causes and changes

The old environment example had `GH_TOKEN= # comment`. Cube parsed this as empty,
but systemd supplied the comment as a token. GitHub returned 401 from scheduled
services despite a valid interactive login. Empty/comment-only placeholders are
now discarded by the CLI and publisher; actual scoped tokens are never discarded
or silently replaced by broader login credentials. The example was corrected.
The historical authentication note that agents quoted as current was corrected.

The workday patrol previously launched up to six agents at a two-session endpoint.
Alphabetical early agents repeatedly won capacity; later agents generated queued
attempts and did not process messages. A durable rotating local workday schedule
now admits a bounded wave before creating runs. Default wave size is one, centrally
adjustable with `local_workday_concurrency` (0, 1 or 2), bounded by the existing
physical concurrency limit. Coordination/sysadmin work stays outside this workday
queue; any such request routed locally still takes the physical semaphore.
Explicit nonlocal runners are not throttled by the local workday queue.

The dispatch timer checks every five minutes. Agent cron/daily budgets still apply.
A timer cannot overlap its own active service. Deferred agents are `scheduled`,
not failed model calls. Offers rotate even after idle or failed workdays so one
bad agent cannot monopolize the next tick. Manual runs and pipeline workers still
share the physical endpoint cap and can occupy its second session. This is a fair
standing-agent dispatcher, not a global token-aware scheduler for all callers.

Robert measured about 33 tokens/s for one session and 15 tokens/s per session with
two sharing the tensor-parallel server. That is 33 versus 30 tokens/s aggregate,
not two independent GPUs. One session is the initial production setting. Two can
help overlap tool waits, but should be selected from measured completion latency.
At 4,000 generated tokens a checkpoint needs roughly 2 or 4.4 minutes of generation
at those rates, excluding prefill, tools and retries. Daily run allowances are
ceilings, not targets. Do not manufacture tasks to fill them.

## Agent coverage and intended interactions

| Agents | Intended responsibility and audit disposition |
| --- | --- |
| bioengineering, biomedical-informatics, drug-mechanisms, genomics, machine-learning, ontology, protein-function, rare-disease | Domain owners using senior design/review tools. Issue testable worker briefs and review actual artifacts; do not pretend to be unrestricted implementers. |
| research-software | Specifications and reproducibility review; programmer executes. |
| physiomap-curator | Auditor findings feed design/implementation; read-only audit is not implementation. |
| literature | Public literature triage into project-specific handoffs, not repeated generic planning. |
| editor | Manuscript review, not rewriting; producer owns revisions. |
| coordinator | Small active-goal queue, one owner plus reviewer per checkpoint, published evidence over activity counts. No invented tasks for idle people. |
| hermes-ws | Robert's messages and batched decisions/reports; gateway-owned, no scheduled Mattermost polling. Preserve delivery acknowledgements. |
| sysadmin | Fixed diagnosis/proposal tools; exact approved change bundles only. |
| liaison | Laptop-only source retrieval, not autonomous research; excluded from researcher selection. |
| teaching | Course-scoped drafts from an explicit current assignment, not a generic research charter. |
| twins: the eleven current students | Local-only source-backed milestones, independent review before next milestone; generic charters are not evidence of a current topic. |
| counterparts: a research scientist, a postdoc, the lab manager | Same local-only boundaries; staff/postdoc research papers, methods and reports rather than invented thesis obligations. |
| student-supervisor | Independent local review for twins and grants; review capacity competes with production and must be monitored. |
| grants | Verified opportunities and source-backed proposal improvements, no autonomous application submission or contact. |

Normal project flow: literature -> domain owner/spec -> programmer -> independent
review -> private fleet checkpoint. Senior can return inline artifact contents
when file writing is unavailable. The programmer's stale blanket no-push prompt
now explicitly recognises authorised private fleet checkpoints. Private student
flows remain local until a separate reviewed internal/public derivative exists.
GitHub retries cannot publish artifacts that no worker has submitted. Automatic
artifact extraction and a mechanical publication completion gate remain follow-up
work; current prompts and queues alone do not enforce that end-to-end property.

## Earlier reset proposal, superseded

Robert subsequently explicitly approved a full runtime reset, including Beads,
memories, approvals, budgets and work folders. The following proposal is historical,
not the active reset policy. See [the executed reset](clean-slate-20260909.md).

A global erase would lose authoritative research and approval state and could
replay delivered messages. Do not do it. First validate the advisor gateway:
`hermes/profiles/advisor/config.yaml.tmpl` defaults to OpenRouter while its
pre-prompt hook attaches student context. That direct path is outside Cube's
local-only router. Verify live usage and correct or disable it before restart.

Proposed recoverable reset scope, subject to Robert's confirmation:

1. Pause new research dispatch and let live runs checkpoint and drain. Do not
   cancel cluster jobs, restart vLLM or reboot nodes.
2. Make a permission-restricted, dated local archive with a path/hash manifest.
3. Archive research-agent inboxes, generated context and resumable session
   pointers. Rebuild each research inbox from current authoritative assigned
   beads, one concise current mandate, and its project/reviewer/next artifact.
   Preserve unanswered Robert instructions explicitly rather than dropping them.
4. Do not wipe Beads/Dolt, approvals, immutable sysadmin bundles, budgets, job
   reservations, GitHub queues, research files/worktrees, source manifests,
   transcripts, deadlines or completed results. Do not reset Mattermost/event
   cursors, outbox receipts or announced-decision IDs. Reconcile stale leases
   only after their owning processes are confirmed gone.
5. Resume one bounded local wave; verify artifacts and publication before widening.

The gateway and laptop liaison require separate host-specific handling. A ws-only
reset must not reach into the laptop or replay student-facing conversations.
