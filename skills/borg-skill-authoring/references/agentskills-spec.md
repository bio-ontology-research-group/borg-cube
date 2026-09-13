# The agentskills.io skill format

Sources
- agentskills-spec (specification page; summarised, short excerpts of field names only)
- anthropic-context-engineering (Anthropic engineering post; summary only)

## Layout

A skill is a directory named after the skill. `SKILL.md` is the only required
file. Optional subdirectories are `scripts/` (executable helpers), `references/`
(documents loaded on demand) and `assets/` (templates and static files). Runtimes
discover skills by scanning for `SKILL.md` and read nothing else until the skill
is activated [agentskills-spec].

## Frontmatter fields

`SKILL.md` starts with YAML frontmatter between `---` lines. Fields
[agentskills-spec]:

| Field | Required | Constraint |
| --- | --- | --- |
| `name` | yes | 1 to 64 characters; lowercase letters, digits and hyphens; no leading, trailing or doubled hyphen; equal to the directory name |
| `description` | yes | 1 to 1024 characters; says what the skill does and when to use it |
| `license` | no | licence name or a pointer to a bundled licence file |
| `compatibility` | no | at most 500 characters; environment needs such as runtimes, packages, network |
| `metadata` | no | a mapping of extra properties; the spec describes string values, borg-cube nests `hermes` and `borg-role` under it and lint accepts that |
| `allowed-tools` | no | space-separated list of tools the skill may use; experimental, runtime support varies |

No other top-level key is permitted; `skills_lint` rejects unknown keys.

## Progressive disclosure

The format is built around three levels of context cost [agentskills-spec]:

1. Metadata (name and description, about 100 tokens) is loaded for every
   installed skill at start-up. The description therefore carries the trigger
   conditions.
2. The SKILL.md body is loaded when the skill is activated. Recommended size is
   under 500 lines and about 5000 tokens.
3. Files under `references/`, `scripts/` and `assets/` are read only when the
   body points at them. They may be as long as needed, but should be one level
   deep so the agent does not chase links.

Keeping the always-loaded part small and pushing detail outwards matches the
context-engineering advice to treat the model's attention as a finite budget
and to load just-in-time rather than up front [anthropic-context-engineering].

## Rules we adopt

1. Directory name, `name` field and the heading of SKILL.md agree.
2. SKILL.md holds the procedure and hard rules; everything longer goes to
   `references/` and is listed in a "Grounding" section (from [agentskills-spec]).
3. Scripts are invoked by path from SKILL.md and are self-describing via
   `--help`, so a runtime can use them without reading the source
   (from [agentskills-spec], [anthropic-context-engineering]).
