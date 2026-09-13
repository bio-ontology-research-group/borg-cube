# Glossary

**Bead.** A durable work item, dependency, or decision in the Beads ledger. It
lives in `bd`; inspect it with `bd show ID` or `cube bead-show ID`.

**Goal.** A `kind:goal` Beads epic with a target, success criteria, people, and
optional project, whose child beads carry the actual work. It is created and
inspected with `cube goal new`, `cube goal show`, and `cube goals`.

**Role.** A functional contract for how one piece of work is done, including
runtime, tier, skills, permissions, outputs, and reviewer. Roles live in
`roles/*.yaml` with prompts in `roles/prompts/*.md`; list them with `cube roles`.

**Standing agent.** A named, persistent coordinator or expert with a charter,
topics, inbox, and source-backed memory, separate from the role used for a run.
It lives in `agents/NAME.yaml` and `agents/NAME/`; inspect it with `cube agent
show NAME`.

**Tier.** A semantic model-routing class: `plan`, `implement`, `bulk`, `local`,
or `none`. Tier order and runners live in `cube.yaml`; inspect and control them
with `cube tier`.

**Runner.** An adapter that invokes an execution backend such as Claude, Codex,
Hermes, OpenRouter, the local vLLM, or the test stub. Runner implementations
live in `cube/runners/`, and `cube run ROLE --dry-run` shows the selected command.

**Patrol.** A deterministic scheduled or manual check that observes sources and
derives findings, beads, cursors, digests, or events without delegating the
observation itself to a model. Patrols live in `cube/patrols/`; list and preview
them with `cube patrol --all`.

**Approval.** Robert's recorded decision on an outbound or irreversible intent;
for ordinary items it does not itself deliver the action. Records live in
`state/approvals/`; use `cube approvals`, `cube approve`, `cube reject`, and
`cube deliver`.

**Provenance.** The source and locator that support a fact or work item, such as
a path and heading, Message-ID, or permalink. It is stored in every bead's YAML
header and is required by `cube create` and the source derivation code.

**Privacy class.** `public`, `internal`, or `local-only` determines where the
work may be processed; `local-only` must use the local model tier or queue. The
enum lives in `cube/model/__init__.py`, routing policy in `cube.yaml`, and each
bead carries a `privacy:*` label and header field.

**xid.** A stable external identifier used to make source-derived work
idempotent across repeated syncs. It lives in the fenced YAML header of every
bead and can be set explicitly with `cube create --xid`.

**Lease.** A short-lived claim that prevents two runs from working the same bead
at once and records run, role, process, host, tier, and expiry. Lease files live
in `state/leases/`; inspect live leases with `cube fleet`.

**Worktree.** An isolated Git checkout and `cube/BEAD` branch used for code work
when the role and project profile request one. The default path is
`.cube/wt/BEAD`, implemented in `cube/engine/worktree.py`; project overrides live
under `projects` in `cube.yaml`.

**Review gate.** The rule that validated output must be reviewed at an adequate
tier before its bead closes or an irreversible result is applied. Reviewer
ownership lives in `roles/*.yaml` as `review_required_by`; run it with `cube
review BEAD`.

**Digest.** A deterministic changes-only briefing built from attention, patrol
cursors, and recent events. `cube digest --apply` writes
`briefings/digest-YYYY-MM-DD.md`; student digests live under
`briefings/students/`.

**Incident.** A service or infrastructure failure represented as a
`kind:incident` bead and, at P0 or P1, a cockpit banner. It is derived by the
infrastructure patrols and listed with `cube incidents`.

**Conflict.** A disagreement between sources that the system refuses to settle
silently, represented as `kind:conflict` work for Robert. Derivation lives in
`cube/sync/derivers.py`; inspect current conflicts with `cube conflicts` or the
roster view.

**Roster of record.** The authoritative source for group membership and role,
currently the public website, while field-specific precedence handles program,
start date, and Org filename. The policy lives under `roster` in `cube.yaml`;
compare sources with `cube roster`.

**Grant (contact).** A scoped, evidenced permission for one person, channel,
action class, and optional expiry; absence means no contact. It lives in
`contacts.yaml` and is checked with `cube contact check` or managed with `cube
contact grant` and `cube contact revoke`.

**Grant (funding).** A research funding award linked to a project, people,
topics, and dates; it is descriptive project data, not permission for contact
or autonomous spending. It lives in the private or public project knowledge
graphs and appears in `cube projects`.

