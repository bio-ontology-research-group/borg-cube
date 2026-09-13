---
topic: lookup-boundaries
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Bounded lookups

Sources
- agentskills-spec (proprietary; short excerpts of field names only)
- anthropic-building-effective-agents (proprietary; summary only)
- anthropic-context-engineering (proprietary; summary only)
- owasp-top-ten (summary only)

## What the evidence says

- A tool should be the simplest thing that works and should return only what
  the next step needs; a lookup that lists, greps and quotes lines beats a
  tool that dumps whole trees into the context [anthropic-building-effective-agents].
- Context is a finite budget: tool results that are bounded (a capped number
  of entries, numbered lines, a truncation marker) keep the agent's working set
  small and its answers checkable [anthropic-context-engineering].
- Access control failures, the first item of the current top ten, come from
  code paths that trust a name rather than a resolved identity; a read
  boundary must be checked on the resolved path, and a deny list must win
  over an allow list [owasp-top-ten].
- A skill's frontmatter names the tools it needs (`allowed-tools`) and the
  conditions under which it applies (`description`), so a harness can route to
  it without reading the body [agentskills-spec].

## How the skill applies it

- `cube lookup` resolves every path (symlinks followed) and proves it lies
  under a readable directory and under no closed one before it reads. The
  closed list exists because `~/pa` on the laptop is a symlink into
  `~/Public/software`.
- Claude Code's Read tool is bounded by path rules (`Read(//root/**)` allowed,
  `Read(//closed/**)` denied); Grep and Glob are not path-bounded, so the role
  does not list them and `cube lookup grep` and `find` stand in.
- Output is capped (entries, matches, lines) and says when it was truncated.
