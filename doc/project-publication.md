# Project publication

Robert's standing authorization of 2026-09-09 covers private project repositories
in `borg-cube-fleet` and regular publication of research work there. Use one stable
repository per project, shared by its collaborators, not one per agent or run.

At project start, publish a README with the sourced goal, methods and status.
At each meaningful checkpoint and before ending a session, publish actual code,
tests, commands, environments, manuscript/report drafts and measured results.
Negative results count. Short activity records in `research-log` are not a
substitute for project artifacts.

```sh
cube fleet document project-slug manifest.json --agent ontology \
  --message 'Research checkpoint' --evidence bead:cube-example --apply
```

The manifest is a JSON object mapping repository-relative paths to UTF-8 file
contents. The command screens and saves an immutable snapshot locally, then
attempts publication. A missing repository is created private and initialized.
Existing public repositories are rejected, never converted. GitHub commits carry
the role identity and Robert's email. Updates never force-push or delete files.
Collaborators must coordinate edits to shared filenames; publication does not
perform semantic merging of stale drafts.

The existing decisions patrol on ws retries pending snapshots every 15 minutes.
Snapshots are processed chronologically, and a failed project blocks its later
snapshots until retry, so older checkpoints cannot overtake newer ones. A queued
snapshot is not a published result. Patrol warnings expose upload failures without
printing credentials or private command output. No new Mattermost heartbeat is
introduced. `cube fleet publish --dry-run --json` previews pending work.

Raw mail, org/personnel records, credentials and local-only artifacts must not be
uploaded, even to private repositories. Local-only runs are rejected by this
artifact path and require a separately reviewed internal/public derivative.
Content screening is defense in depth, not a sandbox. Large datasets and model
checkpoints stay on research storage; publish provenance and checksums instead.

## Deployment requirement

The ws service account must have authenticated GitHub CLI access with permission
to create private repositories and write contents in `borg-cube-fleet`.
Authentication and real private-repository publication were verified on ws on
2026-09-09 (commit `9c3d4d93cf221b7d6958ad460aed2ae541cfba8a`). A later service-only
failure was traced to a comment-only `GH_TOKEN` from an old environment example
overriding that valid CLI login: systemd treats inline comments as values. Cube
now removes empty/comment-only token placeholders, preserving actual scoped
tokens, and the example uses standalone comments. Verify current authentication in
the service environment, not just an interactive shell. Never infer a current
outage from this historical note, and never paste tokens into chat or beads.

The system provides durable publication and prompts agents to checkpoint. It
does not fabricate artifacts for failed runs, automatically upload arbitrary
directories, or bypass tool execution restrictions. Existing historical private
artifacts need review before backfill.
