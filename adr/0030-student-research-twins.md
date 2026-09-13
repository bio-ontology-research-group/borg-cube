# ADR-0030: Student research counterparts on the local tier

Date: 2026-09-08
Status: accepted, implementing Robert's student-twin request in Codex.

## Decision

Derive one `twin-<student>` standing research agent for every current student in
the roster join table. Exclude pending membership and former members. Do not
duplicate the student database: charters point to a private source-reference
manifest, while facts stay in org, PA, papers, code and the research KG.

The counterpart has the student's research topic and goal, not their identity.
It reads research evidence, maintains memory, studies literature, reproduces
results and produces thesis chapters and reports as explicitly synthetic drafts.
Public KG topics feed the existing literature-to-researcher handoff. Missing
sources go to the liaison as a bundled request. No fabricated student views,
results or citations, no student contact, no submissions in the student's name.

Milestones cycle through source mapping, literature, reproduction, thesis drafting
and reporting. Only one unfinished milestone per twin is generated. The existing
review gate dispatches to a separate `student-supervisor`, using the
`student-reviewer` role. Revisions return to the original twin. Routine rejection
stays with the supervisor, not Robert. A review is a different scientific role
on the same local model, not a claim of stronger model capability.

## Privacy and source custody

Robert additionally requested counterparts for a postdoc, the lab manager and
a research scientist on
2026-09-08. Select these current members by roster ID in `twins.yaml`, not by
copying their dossiers or enabling all staff. Retain the shared researcher and
reviewer runtime roles, privacy floor and budget. Nonstudent counterparts draft
project-appropriate research artifacts rather than thesis chapters. The same
bounded inbound source-bundle transport covers the explicit selection.

Twins and their reviewer have a local-only privacy floor, including no-bead inbox
turns. The router permits only explicitly configured local-provider tool harnesses
for local-only work; it queues when those are unavailable and never falls back to
cloud inference. This fixes the former combination of chat-only local routing
and a tool requirement that could never be satisfied.

Private Hermes turns use isolated per-run profile state. Disable compression,
title generation, background review, global memory, plugins and fallback chains;
the deployed Hermes auxiliary auto-discovery otherwise permits cloud providers
even when the main model is local. Strip inherited credential variables and set
`PYTHON_DOTENV_DISABLED=1`. This is automatic inference isolation, not an OS
network sandbox for the unrestricted research shell. Interactive private-agent
chat is refused because it bypasses the routed engine.

The same privacy-floor fix exposed a contradictory liaison declaration:
local-only memory but a pinned cloud model. The laptop's configured local
endpoint now answers HTTP 200. Pin the liaison to `claude@local`, retain its
protected tool hooks, and queue if that endpoint becomes unreachable. No raw
mail or student context is sent to its former cloud provider.

Raw mail and org records are not GitHub artifacts. Derived private drafts remain
local-only too. Fleet publication receives metadata-only progress until there is
a separately reviewed, releasable research artifact. Grades and HR are excluded
from research processing and the work ledger.

Robert's request grants inbound use of existing curated per-student liaison
bundles on KAUST ws for local inference. `cube twins push-sources` is the narrow
transport: laptop only, current-student filenames under the liaison answers
directory and readable roots, fixed configured `ws` destination, mode 0600 files
and 0700 directories, SHA-256 verification, provenance-only ledger comments.
It cannot pull from the laptop, choose another host or accept arbitrary paths.
General `cube drop` privacy restrictions remain unchanged. Further mail reads
use read-only Gnus through the liaison, and directory/tool exceptions continue
through the batched Mattermost decision workflow.

## Productive local work

Live inspection on ws found running workdays, not a stopped timer. At inspection,
today's local records contained 25 failures and 3 completed runs, with seven
agents still running. Failures were 1800-second timeouts, including earlier
mislabelled no-JSON errors. Hermes had a 500-turn default; observed unfinished
sessions made 18 to 37 calls. Worker PATH omitted the checkout's Cube executable.

Use at most 12 Hermes iterations and explicitly reserve the final iterations
for a checkpoint and result envelope. Add the checkout's `.venv/bin` to worker
PATH. This bounds waste but cannot guarantee a model follows the result schema.
Configured research defaults become 144 attempts/day fleet-wide, 8 per researcher
and a two-hour autonomous interval. Paid spend stays at $10/day and Slurm/disk
limits are unchanged. Actual local GPU load and completion rates, not merely
token consumption, determine whether these limits should be raised further.

## Operation and rollback

See `doc/student-twins.md`. Tests use fake Beads and the stub runner. Runtime
activation is explicitly requested research work, not a real-send smoke test.
Pause an individual agent with `state/agents/<name>/PAUSED`; use `state/KILL`
for the whole fleet. Revert the implementation and restore the prior configured
limits to roll back behavior; retain private artifacts and provenance.
