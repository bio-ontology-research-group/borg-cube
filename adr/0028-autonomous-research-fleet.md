# ADR-0028: Autonomous research with two restricted roles

Status: accepted
Date: 2026-09-08
Source: Robert's Codex request implementing the code-review recommendations,
with literature, central resource, fleet GitHub, Mattermost and liaison amendments.
Supersedes the conflicting portions of ADR-0027 and older contact/author rules.

The fleet independently advances high-level goals. Literature digests route
relevant references to researchers. Idle researchers with active goals can take
one independent step per central interval, with daily fleet and researcher caps.
Experiments document hypotheses, methods, environments, commands, results and
limitations and obtain peer review. Routine research is not a Robert decision.

Central defaults are in cube.yaml; validated, audited overrides live in
state/fleet-limits.json. Research-run and Slurm reservations share a locked
ledger. Attempts count even after model failure. Slurm jobs reserve CPU/GPU time
and concurrency before submission, check disk bytes and inodes including expected
output, and stay reserved after uncertain submission until explicitly reconciled.
Only explicit terminal scheduler evidence releases an active slot. These are
managed-tool limits, not OS isolation of trusted researchers' arbitrary programs.

Research documentation is queued durably and published to the private
borg-cube-fleet/research-log repository. Repository creation is private and only
on an applied publication. Code and result artifacts can be committed atomically
to fleet repos; issues and draft PRs require evidence and deduplicate retries.
Existing branches are required for artifact commits and PR heads. Role authorship
uses Robert's specified identity and leechuck@leechuck.de. Local-only records
publish metadata only. Raw mail/org sources and detected credentials are refused.

Sysadmin and liaison models have only the fixed `cube boundary` dispatcher.
The Claude runner removes other tools, MCP servers and inherited setting sources,
uses a fresh session and installs a standalone fail-closed tool hook. The hook
validates exact argv and rejects shell composition, redirection, expansions and
environment overrides. This uses the documented
[PreToolUse contract](https://code.claude.com/docs/en/hooks#pretooluse).
Other harnesses are refused for these roles. Structured result application cannot
write control state, grant privilege labels, update other beads or create outbound
intents. This boundary trusts the installed harness, dispatcher code and host
account; it does not isolate against another trusted researcher editing that code.

Sysadmin diagnosis uses fixed commands; proposed changes contain exact commands,
rationale, expected impact, prechecks, postchecks, rollback and evidence. Approval
is bound to a digest of the entire bundle. Mattermost approve executes it once;
deny ends it; modify records the request and returns it to sysadmin for revision.
Failed or interrupted execution never automatically retries. Password automation,
interactive root shells and GPU-node reboots remain forbidden. Privileged operations need
pre-existing noninteractive grants or Robert's own interactive execution.

Liaison has standing read-only Gnus mail and ~/org/calendar access, plus the prior
research roots. Other reads require a scoped request on the synced ledger. No
generic Emacs Lisp, shell, Python, file transfer or bead-administration tool is
exposed. Secret path checks and disclosure screening occur before model access.
Sensitive personal sources remain local; public biomedical vocabulary is allowed.
Disclosure screening is conservative pattern matching, not a guarantee of detecting
every possible secret or personal fact. New tool capabilities need a reviewed
dispatcher change; a permission reply does not enable arbitrary tool execution.

Inbox messages have stable IDs, locking and selective acknowledgement. The outbox
sends one batch to Robert's configured DM and acknowledges only after delivery.
Delivery is at-least-once: a crash after remote success but before acknowledgement
can duplicate a message. Pending decisions are batched at most every twelve hours,
with exact duplicates announced once. Progress goes to Beads/GitHub; existing
completed-goal reports remain. No new Mattermost input polling is introduced.

## Rollout

This implementation does not deploy itself. After Robert approves a release,
update the ws and laptop checkouts, validate the installed Claude hook contract,
verify the Gnus socket and the authenticated Robert-only gateway, and confirm
private-repository access in borg-cube-fleet. Disable the superseded daily
literature DM cron. Preview limits, a job, an outbox batch and a system bundle
before enabling applied workflows. Service/cron changes need their own reviewed
commands and rollback. Existing diagnostic failures are not waived by passing tests.
