# Student research twins

The fleet creates an explicitly synthetic research counterpart for each current
student. It shares the research goal, not the person's identity or authorship.

`twins.yaml` additionally selects a postdoc, the lab manager and a research
scientist by existing roster ID, bringing the selection to 14 counterparts.
Their current roles and project sources govern their work, not student milestones.
The draft phase produces research artifacts instead of thesis chapters. They share
the local-only runtime, independent senior review and central fleet limits.
Unknown, pending and former roster entries cannot be selected. Source bundle
pushes cover these selected members as well as current students. Adding a member
does not overwrite existing twins' charters or memory or send a notification.

On ws:

```sh
cube twins sync --dry-run --json
cube twins sync --apply --json
cube agent workday twin-<roster-id> --dry-run --json
```

`sync` is idempotent. It creates missing agents without replacing existing
charters or memory, and refreshes private source-reference manifests under
`state/twins/<student>/sources.json`. Current membership comes from `people.yaml`,
the existing source-derived join table. Pending and former members are excluded.
Review any roster conflicts through the existing roster workflow.

For the existing curated student source bundles, run on the laptop:

```sh
CUBE_HOST=laptop cube twins push-sources --bead <tracking-bead> --dry-run --json
CUBE_HOST=laptop cube twins push-sources --bead <tracking-bead> --apply --json
```

This pushes only the latest matching liaison bundle for each current student to
the configured private ws drop. It never prints source content. Re-run `twins
sync` on ws to include the verified drop paths. Missing theses, papers or research
mail are requested from the liaison as a single source bundle; no ws laptop pull
and no new mailbox backend. Tool/directory permission exceptions still use
Mattermost. No source text is sent there.

The normal workday timer starts bounded milestones automatically. The explorer
lists each twin and the local student supervisor, including activity, tokens,
memory metadata and trigger controls. Private content remains withheld from its
publications and ordinary summaries. Local runtime files hold the actual drafts.

The cycle is source map and research plan, literature synthesis, reproduction,
thesis chapter draft, research report, then refinement. Every milestone uses
the existing independent review gate. Revisions return to the twin before more
work is generated. Reviewers require artifacts and evidence, not just prose
claiming success. Research drafts are not submitted or attributed to the student.

Local-only means configured local inference or queue, including inbox-only runs.
There is no cloud fallback. Private sources and derived content stay off GitHub;
Hermes private turns use a per-run isolated profile with no automatic auxiliary
calls, compaction, global memory, plugins or provider fallbacks. Cloud credential
environment variables and dotenv loading are disabled. This isolates automatic
inference routing, not the network access of arbitrary shell programs.
metadata-only progress still follows the existing fleet documentation queue.
Use central `cube fleet limits` through Mattermost to change workload. Defaults
in `cube.yaml` allow 144 research attempts/day, 8 per researcher, and a two-hour
autonomous interval. Existing Slurm and storage safeguards still apply.

Inspect run outcomes as well as activity: a busy model with repeated timeouts is
not useful research. Hermes now has a 12-iteration cap, checkpoint instructions
and access to the correct Cube CLI on PATH. A valid result envelope and a reviewable
artifact are the completion evidence; increasing token consumption is not.
