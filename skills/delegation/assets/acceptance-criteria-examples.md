# Acceptance criteria that can be checked

A criterion is acceptable when someone other than the owner can run it and get
a pass or fail without asking the owner. Each example names how it is checked.

## Good

| Kind | Criterion | How |
| --- | --- | --- |
| implement | `uv run pytest -q tests/skills/test_delegation_scripts.py` exits 0 | command |
| implement | `tools/skills_lint.py skills/delegation` reports 0 errors | command |
| implement | `scripts/beads_from_plan.py --plan tests/skills/fixtures/plan.md` exits 2 when a bead has no acceptance criterion | test |
| audit | `runs/<id>/audit.md` exists and every finding line matches `path:line severity fix` | file |
| research | `runs/<id>/search-log.md` lists at least 3 queries with database, date and hit count | file |
| writing | `paper/methods.tex` has a subsection for every dataset named in `data/README.md` | review |
| design | `runs/<id>/plan.md` names the pattern (chain, route, parallel, orchestrator-workers) and each bead has one owner | review |
| metric | Precision at 10 on `data/dev.tsv` is at least 0.62, computed by `scripts/eval.py --split dev` | metric |
| review | Reviewer (senior) confirms every changed function has a test that fails when the change is reverted | review |
| meeting-note | `runs/<id>/entry.org` has a `- source:` line and every `- [ ]` item has an owner in parentheses | file |

## Not acceptable, and how to fix them

| Vague | Why it fails | Rewrite |
| --- | --- | --- |
| Improve the documentation | no observable end state | README gains an Installation and a Usage section, each with one runnable command |
| Make the code cleaner | reviewer taste, not a check | `ruff check` and `mypy` exit 0; no function longer than 60 lines in `cube/` |
| Investigate the bug | open-ended | `runs/<id>/notes.md` names the failing input, the first bad commit (`git bisect`), and a one-line cause |
| Talk to the student about the data | outbound action, not a criterion | Approval bead for Robert with the question written out; criterion is that the bead exists |
| Finish the experiments | unbounded | Runs listed in `experiments.yaml` have a result row in `results.tsv`, or a `failed` row with the error |
| Be thorough | not measurable | Checklist in `assets/code-audit-report.md` fully ticked or marked not applicable |

## Rules of thumb

1. Name the artifact and the property (file exists, section present, exit code, number and threshold).
2. Put the command in backticks so the reviewer can paste it.
3. One criterion per line; several small checks beat one compound sentence.
4. If the criterion needs the owner to explain it, it is not a criterion yet.
5. Criteria are written before the work starts and are not edited afterwards; a change is a new bead.
