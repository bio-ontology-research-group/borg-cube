---
name: laptop-lookup
description: Read-only lookups on Robert's laptop inside the readable directories (~/Documents/papers, ~/Public/software) for the laptop liaison. Use when a kind:request bead asks what a file, paper, checkout or directory on the laptop contains, lists, or last changed, and every path it names lies under a readable directory. Lists, finds, greps, quotes lines and shows git history through `cube lookup`; reads whole files through the bounded Read tool; writes the answer on the bead with path:line or commit provenance. Never reads mail, ~/pa, ~/org, memories or any other path; such a request waits for Robert's approval first (ADR-0027).
license: CC-BY-4.0
compatibility: Requires the borg-cube checkout on the laptop (`cube lookup`, `bd`); Claude Code with path-bounded Read rules (the liaison role); no network.
metadata:
  borg-role: infra
  grounding: agentskills-spec, anthropic-building-effective-agents, anthropic-context-engineering, owasp-top-ten
  hermes:
    category: infra
    tags: laptop, liaison, lookup, read-only, provenance
    requires_toolsets: terminal
allowed-tools: Bash(cube lookup *) Bash(bd *) Bash(cube drop *)
---

# Laptop lookup

The liaison answers a request from Robert's laptop by reading, never by
remembering. Reads are bounded to the readable directories in `cube.yaml`
(`hosts.laptop.readable`); the closed ones (`hosts.laptop.unreadable`, the
credential stores) stay closed even when a readable directory contains them.
Everything else on the laptop is a read Robert approves first.

## When to use

- A `kind:request agent:liaison` bead whose Question names paths under
  `~/Documents/papers` or `~/Public/software`: what a paper says, which files a
  checkout has, what changed last, where a term occurs.
- The workday hands the step to the `liaison` role; the readable directories
  are listed at the end of the prompt.

## When not to use

- The question needs mail, the calendar, contacts, `~/pa`, `~/org`, Claude
  memories or any path outside the readable directories. Comment that on the
  bead and stop; the request is labelled `needs:robert` and waits.
- The answer would carry grades, a contract, a visa, health or HR material.
  Write nothing; label the bead `needs:robert`.

## Procedure

1. Read the Question line: `bd show <id>`. Note every path it names.
2. Confirm each path with `cube lookup ls <path>`. A refusal (`outside the
   readable directories`, `stays closed`, `looks like a secret`) ends the
   lookup for that path; quote the refusal on the bead.
3. Search and quote with `cube lookup`:
   - `cube lookup find <dir> --name '*.tex'` lists files by name.
   - `cube lookup grep '<regex>' <dir> --include '*.md'` finds lines.
   - `cube lookup head <file> --start 120 --lines 40` quotes numbered lines.
   - `cube lookup git-log <checkout> -n 10` shows recent commits.
   - The Read tool opens whole files (PDFs included) under a readable
     directory and nowhere else.
4. Write the answer on the bead: `bd comment <id>` with an `answer:` block,
   one statement per line, each ending in its source (`path:line` or a commit
   hash). No line without a source; nothing from memory.
5. Close when answered in full: `bd close <id> --reason 'Liaison recorded a
   source-backed answer.'`. Leave it open, with the exact path tried, when a
   source is missing.
6. An artifact too large for a comment (a table, a PDF) goes to ws with
   `cube drop <id> <file> --apply`; a checkout with `--repo`.

## Grounding

- `references/lookup-boundaries.md`: why lookups are bounded on the resolved path, why the closed list wins, and why output is capped.

## Rules

- Read only; no file changes, no contact, no network.
- Absolute paths; `~` is fine, relative paths are not.
- Never quote `.env`, `auth.json`, `password*`, keys or tokens, wherever they
  sit; `cube lookup` refuses them and so do you.
- One request, one answer, one close. A follow-up question is a new request.
