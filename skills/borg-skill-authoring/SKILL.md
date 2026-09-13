---
name: borg-skill-authoring
description: How to write, ground, lint, test and deploy a skill in the borg-cube repository (skills/<name>/ with SKILL.md, references, scripts, assets). Use whenever asked to "create a new skill", "add a skill to borg-cube", "ground a skill", "fix skills-lint failures", "sync references", or "deploy skills" to Claude Code, Codex or Hermes. Covers the agentskills.io frontmatter, the corpus grounding policy, the house writing rules, and the just recipes that enforce them.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12, uv and just in the borg-cube checkout; rsync and ssh for deployment; no network otherwise.
metadata:
  borg-role: infra
  grounding: agentskills-spec, anthropic-building-effective-agents, anthropic-context-engineering, anthropic-writing-tools
  hermes:
    category: infra
    tags: skills, authoring, lint, deploy, borg-cube
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(uv run *) Bash(just *) Bash(python3 *)
---

# Authoring a borg-cube skill

A skill is a directory `skills/<name>/` that any of the three runtimes (Claude
Code, Codex, Hermes) loads unchanged. It carries a procedure, its hard rules,
and pointers to evidence; the evidence itself lives in `corpus/` and reaches
the skill as `references/*.md`. Everything here is enforced by
`just skills-lint`, so read the failure messages as the spec.

## When to use

- Robert or a bead asks for a new skill from the catalog in `doc/plan.md`.
- An existing skill fails `skills-lint`, `skills-sync --check` or `deploy-skills`.
- A distilled corpus topic changed and skills that copy it must follow.

## Procedure

1. Pick the name from the catalog (`doc/plan.md`, "Skill catalog"). Names are
   lowercase words joined by single hyphens, at most 64 characters, and equal
   to the directory name.
2. Copy `assets/SKILL-template.md` to `skills/<name>/SKILL.md`. Fill the
   description first: what the skill does and when to trigger it, with the
   phrases a user would say, in at most 1024 characters. The description is
   the only text a runtime reads before deciding to load the skill.
3. Decide the grounding. List the manifest ids from `corpus/sources.yaml`
   that the procedure rests on. At least three; at least five for advisor and
   lecturer skills and for the writing skills (see `references/grounding-policy.md`).
   Missing sources go into the manifest first, never invented.
4. Add references. Shared topics: list them in `references/manifest.txt` and
   run `just skills-sync`, which copies `corpus/distilled/<topic>.md` in and
   rewrites `metadata.grounding` as the union of cited ids. Skill-specific
   references: copy `assets/reference-template.md`; the file must begin with a
   Sources block naming manifest ids and their licences.
5. Write the body: procedure, hard rules, then a "Grounding" section naming
   every `references/*.md` on one line each. Keep SKILL.md under 500 lines and
   about 5000 tokens; move detail into references (one level deep, never
   nested).
6. Scripts under `scripts/*.py` use the standard library plus PyYAML only,
   answer `--help`, default to dry runs when they write outside the repo, and
   each has a test under `tests/skills/`.
7. Run `just skills-lint`, `just skills-test`, `just skills-sync --check`.
   Fix until clean.
8. Deploy: `just deploy-skills` prints the plan; `just deploy-skills --apply`
   symlinks into `~/.claude/skills`, copies into `~/.codex/skills`, and with
   `--hermes ws[:profile]` rsyncs into the Hermes skills tree by
   `metadata.hermes.category`. Deployment refuses while lint fails.

## Hard rules

- Frontmatter keys are exactly: `name`, `description`, `license`,
  `compatibility`, `metadata`, `allowed-tools`. Runtime-specific settings go
  under `metadata.hermes.*`; `metadata.hermes.category` is one of advising,
  research, teaching, software, lead, infra, admin.
- Every grounding id exists in the manifest and is cited in a Sources block
  of some `references/*.md`. Lint fails otherwise.
- Synced references are byte-identical copies of `corpus/distilled/`. Edit
  the original and rerun the sync; never edit the copy.
- House style (see `references/writing-rules.md`): no U+2014, sentence-case
  headings, no meta labels, American English, plain language.
- No secrets, no personal data about students, no copies of copyrighted text.
  Books are cited; their notes live in `corpus/notes/`.
- Never commit a distilled file without its `reviewed_by` line; lint warns
  until Robert has reviewed it.

## Grounding

- `references/agentskills-spec.md`: the SKILL.md format, fields, limits and progressive disclosure.
- `references/grounding-policy.md`: how many sources, which licences, how ids flow from corpus to skill.
- `references/writing-rules.md`: the prose rules lint enforces and the ones it cannot.

## Tooling

| Recipe | Tool | Purpose |
| --- | --- | --- |
| `just skills-lint` | `tools/skills_lint.py` | spec, grounding, references, style, hermes, scripts checks; `--json`, `--report`, `--spec-only` |
| `just skills-sync` | `tools/skills_sync.py` | copy distilled topics in, refresh grounding; `--check` fails on drift |
| `just skills-test` | pytest `tests/skills` | tool and script tests |
| `just deploy-skills` | `tools/deploy.py` | dry-run plan by default, `--apply` to execute |
| `just corpus-verify` | `tools/corpus_verify.py` | Crossref title match for every DOI in the manifest |
