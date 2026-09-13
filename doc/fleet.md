# Autonomous research fleet

Researchers advance active goals within their charters. Literature handoffs feed
reproduction experiments; methods, code, environments and negative results belong
in private `borg-cube-fleet` repositories. Routine work does not require a DM.
See [ADR-0028](../adr/0028-autonomous-research-fleet.md) for boundaries and rollout.

## Resources

`cube fleet limits --json` shows central limits and reservations. Defaults allow
48 daily research runs (four per researcher), four concurrent Slurm jobs, 128
CPU-hours and eight GPU-hours daily. Each job is capped at eight CPUs, 32 GiB,
one GPU and four hours. Preserve 20 GiB, 10 percent free storage and 10,000 inodes.
Managed-tool limits are not OS isolation of trusted researchers.

Robert can say `limits set concurrent_slurm_jobs 2` in Mattermost. The concierge
records his instruction as evidence; exhausted budgets queue work without asking.

```sh
cube fleet submit ibex experiment.sh --agent ontology \
  --workdir /ibex/scratch/projects/c2014/reproduction \
  --needs '{"cpus":4,"memory_gib":16,"gpus":0,"walltime_hours":2}' --json
cube fleet job RESERVATION --json
cube fleet publish --json
```

These commands default to previews; `--apply` enacts them. `unimatrix01` is also
supported. Unknown submission outcomes retain reservations until reconciled.

## Decisions and documentation

Sysadmin proposes immutable bundles containing exact argv, rationale, impact,
checks, evidence and rollback. Reply `sys-ID approve`, `sys-ID deny`, or
`sys-ID modify ...` through Mattermost. Modifications need fresh approval.
Decision digests are batched twice daily; delivery failures retain inbox messages.

The liaison uses only `cube boundary` read tools, including bounded Gnus queries
and configured org/calendar paths. Additional directory requests name exact paths.
Tool extensions require reviewed dispatcher changes. Credential stores remain
closed. Screening is conservative pattern matching, not universal secret detection.

Run summaries queue automatically for `borg-cube-fleet/research-log`. Use
`cube fleet document`, `cube fleet issue` and `cube fleet pr` for source-backed
artifacts, bugs and improvements; `--help` describes their required evidence.
Commits use `Robert Hoehndorf (BORG Cube Fleet: ROLE)` and
`leechuck@leechuck.de`. Raw mail/org and local-only details are not published.
