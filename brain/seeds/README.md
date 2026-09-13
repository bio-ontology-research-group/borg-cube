# Seeds

`cube seed` imports skills, doctrine and facts from material that already
exists on Robert's machines, with provenance pointers back to the originals.
Nothing is duplicated as a source of truth: skills are symlinked or rsynced
with `seed_from:` in the frontmatter or manifest, runbooks become summaries
with links, facts carry `source:`. The seed is idempotent; `cube seed --diff`
shows drift between originals and seeded copies. Secrets are never seeded.

## Skills (into `skills/seeded/` as an index, originals untouched)

- `~/Public/software/borg-infrastructure/hermes-infra/skills/{infra-monitor,semantic-web,kaust-compute}` (sysadmin role)
- `~/Public/software/borg-infrastructure/skills/datawaha-backup` (sysadmin role)
- `~/Public/software/skills/local/*`: presentation, new-talk, remote-connect, email-contacts, new-paper, bcl-email-backup, datawaha-backup
- `~/Public/software/skills/claw/showboat`
- `~/.codex/skills/write-edit-scientific-paper`
- `~/.claude/skills/write-paper-review`
- `~/pa/skill` (personal-assistant)
- social-media-agent (`~/Public/software/social-agent/social-media-agent`)

Lint checks that every original still exists.

## Doctrine and runbooks (into `brain/` as summaries plus links)

- `hermes-infra/AGENTS.md` (hard rules, skill routing) and `borg-infrastructure/AGENTS.md` (admin account, root shell procedure, IBEX ownership table)
- `borg-infrastructure/README.md`, `PAVS*.md`, `RUBALKHALI*.md`, `borg-server2-migration.md`
- `borg-infrastructure/deployment/*.md` (ip_addresses, DOMAIN_HOSTING, unimatrix_cluster)
- `borg-infrastructure/unimatrix/{CLUSTER_CONFIG_JAN2026,KNOWN_ISSUES,SLURM_INSTALL,INSTRUCTIONS}.md`
  (the seed redacts the access section; credential files live outside the repository and are referenced by path only)
- `borg-infrastructure/office-ws/README.md`
- `~/pa/CLAUDE.md` (autonomy policy, hard rules, tool patterns)
- `~/org/CLAUDE.md` (org conventions)
- `~/.codex/AGENTS.md` (PATO/FLOPO ontology contribution checklist, feeds `ontology-review`)
- `~/Public/software/skills/CLAUDE.md`

## Facts (into `bd remember` via `cube brain push`)

`cube brain push` reads every `brain/facts/*.yaml` (top-level `facts:` list
of `{text, source}`) and calls `bd remember` once per fact, idempotently.
Sources:

- the memories in `~/.claude/projects/<home>/memory/` of type
  project, feedback and reference; user-type memories only where relevant to
  the group; `feedback_spam_filtering` and `project_personal_training`
  excluded
- `hermes-infra/scripts/services.yaml` registry entries (name, section,
  scope, host, description)
- unimatrix GPU and driver caps (`project_unimatrix_cluster.md`)
- roster and milestone estimates from `~/org/staff.org` and
  `borg-website/people/roster.md`, provenance-tagged, conflicts kept as
  conflicts
- `brain/facts/bd-remember.yaml` (hand-written operational facts, this repo)

## Never seeded

Password files, `.env`, secret directories, `.github_token`, htpasswd
files, `~/.codex/auth.json`, browser profiles, the signature asset. They are
listed in `brain/doctrine.md` as reference-by-path only.
