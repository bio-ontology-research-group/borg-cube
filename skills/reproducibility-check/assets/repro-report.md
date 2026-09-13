# Reproducibility check: {{TARGET}}

- checked on: {{DATE}}
- artifacts: {{ARTIFACT_SOURCE}} (persistent identifier: {{DOI}})
- repository under test: {{REPO}} at commit {{COMMIT}} (read-only clone)
- claim checked: {{CLAIM}}
- reference outputs: {{REFERENCE}}
- host: {{HOST}} ({{IBEX_NOTE}})
- checker: {{CHECKER}} (author team: {{AUTHOR_TEAM}})

## Outcome

**{{OUTCOME}}** ({{IDENTICAL_WITHIN_DIVERGENT}})

{{ONE_PARAGRAPH_SUMMARY}}

## Environment

- strategy: {{STRATEGY}} from {{ENV_SOURCE}}
- runtime: {{RUNTIME}}
- build command: `{{BUILD_COMMAND}}`
- build: {{BUILD_STATUS}}
- log: {{ENV_LOG}}

## Missing steps

Steps that were needed but were not documented in the artifacts. An empty list
here is required before the run can be called reproducible.

| step | how we found it | where it should have been documented |
| --- | --- | --- |
| {{STEP}} | {{EVIDENCE}} | {{WHERE}} |

## Improvisations

Anything the environment build had to decide for itself, from
`repro-env.json` findings.

| kind | detail |
| --- | --- |
| {{KIND}} | {{DETAIL}} |

## Comparison

- command: `{{COMPARE_COMMAND}}`
- tolerances: {{TOLERANCES}} (chosen because {{TOLERANCE_REASON}})
- items compared: {{N_ITEMS}} (exact {{N_EXACT}}, within {{N_WITHIN}}, outside {{N_OUTSIDE}}, missing {{N_MISSING}}, added {{N_ADDED}})
- comparison output: {{COMPARE_OUTPUT}}

{{COMPARISON_TABLE_OR_NOTHING_TO_REPORT}}

## Badge grade

Terminology: ACM Artifact Review and Badging version {{BADGE_VERSION}}.

| family | badge | supported by this check | evidence |
| --- | --- | --- | --- |
| Artifacts available | {{AVAILABLE}} | {{YES_NO}} | {{EVIDENCE}} |
| Artifacts evaluated | {{FUNCTIONAL_OR_REUSABLE}} | {{YES_NO}} | {{EVIDENCE}} |
| Results validated | {{REPRODUCED}} | {{YES_NO}} | {{EVIDENCE}} |

Not claimed and why: {{NOT_CLAIMED}}

## Findings for the authors

Each finding names a file or a command, the problem, and the fix. These become
beads for the programmer role after review; nothing is sent to anyone outside
the group without approval.

| id | location | problem | fix |
| --- | --- | --- | --- |
| {{ID}} | {{LOCATION}} | {{PROBLEM}} | {{FIX}} |

## Not checked

- {{WHAT_WAS_NOT_CHECKED}}
