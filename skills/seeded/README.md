# Seeded skills: existing skills referenced, not copied

borg-cube does not duplicate skills that already live elsewhere on Robert's
machines. `index.yaml` lists them with the path of the original, the role they
serve in the cube, a one-line description read from their SKILL.md
frontmatter, and whether they pass the agentskills.io spec checks of
`tools/skills_lint.py --spec-only`. `skills_lint` warns (without failing) when
a listed path no longer contains a SKILL.md, so the index doubles as a
presence check.

`discovered.yaml` in this directory is written by `cube seed` and is a
different thing: the machine-generated inventory of what the seeder found.
Edit `index.yaml` by hand; never edit `discovered.yaml`.

## Regenerating the compliance column

```
uv run python tools/skills_lint.py --spec-only --report --json ~/Public/software/skills/local/presentation
```

Run this per path (or the whole list) and update `agentskills_compliant` and
`lint` in `index.yaml`. Roles are assigned by hand and follow the borg-cube
role set (advisor, researcher, lecturer, auditor, lead, infra) plus `admin`
for secretary work and `personal` for skills outside the group's scope.

## Compliance summary at seeding time (2026-09-02)

Seven of seventeen pass the spec checks unchanged: infra-monitor,
semantic-web, kaust-compute, new-paper, presentation,
write-edit-scientific-paper, write-paper-review. Common failures in the rest,
all fixable in the originals:

- Extra frontmatter keys (`type`, `dependencies`, `homepage`): the spec allows
  only name, description, license, compatibility, metadata, allowed-tools.
  Move them under `metadata`.
- Name not equal to the directory (bcl-email-backup, workout-planning,
  `~/pa/skill`): rename the field or the directory. `~/pa/skill` is deployed
  under the name `personal-assistant` by symlink, so the field is right and
  the source directory is what differs.
- No frontmatter at all (both datawaha-backup copies).
- Invalid YAML: unquoted descriptions containing `: ` (email-contacts,
  social-media-agent). Quote the description or use a `>-` block.

These are reported, not enforced: the originals are owned by their own
repositories.

## Not seeded

`gog` (Google Workspace CLI) is a runtime dependency of email-contacts and
personal-assistant, not a group skill. Robert's personal-training and spam
filtering material stays out of the cube by decision (doc/plan.md).
