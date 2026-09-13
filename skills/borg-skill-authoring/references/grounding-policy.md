# Grounding policy for borg-cube skills

Sources
- anthropic-building-effective-agents (Anthropic engineering post; summary only)
- anthropic-writing-tools (Anthropic engineering post; summary only)
- anthropic-context-engineering (Anthropic engineering post; summary only)
- agentskills-spec (specification page; summary only)

## Why skills carry sources

A skill tells an agent how the group works. When the procedure rests on
published evidence (how to finish a PhD, how to review code, how to run a lab
meeting) the skill must say which evidence, so a reader can check it and so the
next author can update it when the evidence changes. Anthropic's guidance for
agent tooling makes the same point for prompts: state the rationale and the
source, keep the instruction minimal, and let the agent read further only when
needed [anthropic-writing-tools, anthropic-context-engineering].

## What counts as grounding

- A grounding id is an entry in `corpus/sources.yaml`. Nothing else counts:
  no bare URLs, no "well known" claims.
- Ids are declared in `metadata.grounding` (comma-separated) and each must be
  cited in the Sources block of at least one `references/*.md` in the skill.
- Shared references come from `corpus/distilled/<topic>.md` via
  `references/manifest.txt` and `just skills-sync`. The sync rewrites
  `metadata.grounding` as the union of ids cited by all references, so authors
  normally never edit the grounding line by hand.

## How much

| Skill kind | Minimum ids |
| --- | --- |
| Default | 3 |
| `borg-role: advisor` or `lecturer` | 5 |
| Writing skills: paper-writing, thesis-writing, literature-review, response-to-reviewers, grant-writing | 5 |

More is welcome when each id is used. Padding with ids that no reference cites
fails lint.

## Licences and what may be copied

| Manifest `license` / `excerpt_ok` | In a reference file |
| --- | --- |
| CC-BY (`excerpt_ok: true`) | paraphrase; quotes of at most 25 words with attribution |
| CC-BY-NC, NAP free-to-read, paywalled (`excerpt_ok: false`) | paraphrase only |
| KAUST pages (`excerpt_ok: quote-rules-only`) | quote the rule text briefly, never the page |
| Books (`type: book`) | cite; the evidence comes from `corpus/notes/<id>.md` written by Robert |

Distilled files are the group's own words. A second agent run
(`corpus-distill --check`) verifies that every claim has an id, and Robert's
`reviewed_by` line records the human review before commit.

## Rules we adopt

1. No claim in a reference without an id in square brackets (from
   [anthropic-writing-tools]: instructions an agent follows must be checkable).
2. References are one level deep and start with their Sources block, so an
   agent knows the provenance before reading the content (from
   [agentskills-spec], [anthropic-context-engineering]).
3. Prefer a small number of primary sources the skill uses over an exhaustive
   bibliography; the agent's context is the scarce resource (from
   [anthropic-building-effective-agents], [anthropic-context-engineering]).
