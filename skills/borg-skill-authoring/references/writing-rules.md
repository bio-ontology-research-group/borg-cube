# Writing rules for skills and references

Sources
- anthropic-writing-tools (Anthropic engineering post; summary only)
- anthropic-context-engineering (Anthropic engineering post; summary only)

These rules apply to every Markdown file under `skills/` and to
`corpus/distilled/`. `skills_lint` enforces the first four mechanically; the
rest are checked in review.

## Enforced by lint

1. No em-dash (U+2014) anywhere, prose or code. Use a comma, semicolon, colon
   or parentheses, chosen by the sentence, or split the sentence.
2. Sentence-case headings: only the first word and proper nouns are
   capitalised. `## Rules we adopt`, not `## Rules We Adopt`. Acronyms and
   names in `skills/lint-allowlist.txt` are allowed.
3. No meta labels. The banned phrases are `Note that`, `Key insight`,
   `Importantly` and `Honest` (as in a label such as `Honest assessment`).
   Say the thing instead of announcing it.
4. Frontmatter description between 1 and 1024 characters, SKILL.md under 500
   lines and about 5000 tokens.

## Checked in review

- Plain language. Short sentences, concrete nouns, one idea per paragraph.
  Agents follow explicit, unambiguous instructions better than rhetoric; write
  the way you would write a good tool description [anthropic-writing-tools].
- American English spelling (organize, behavior, license as the noun).
- Imperative mood for procedures ("Run the linter"), declarative for evidence
  ("The sources agree that ...").
- No filler openers ("In order to", "It is worth noting"), no hedging stacks,
  no praise of the reader.
- Every rule states who enforces it: lint, a script, a test, or Robert.
- Put detail where it is read: trigger phrases in the description, procedure
  in SKILL.md, evidence in references, templates in assets. Loading everything
  into SKILL.md wastes the agent's context [anthropic-context-engineering].
- Tables for lookups, numbered lists for sequences, bullets for unordered
  rules. Do not use bold as a heading substitute.

## Rules we adopt

1. Lint runs before every commit and before every deploy; a style failure
   blocks deployment like a spec failure.
2. Reviewers fix wording in the distilled original, never in the synced copy.
