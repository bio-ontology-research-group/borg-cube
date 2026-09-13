---
name: experiment-tracking
description: Records what produced every experimental result (run id, command, commit and dirty flag, seeds, data versions, environment, timing, exit status, output hashes), maps the figures of a manuscript back to the runs behind them, and writes model cards and datasheets. Use when asked "which run made this figure", "can we reproduce this number", "set up experiment tracking", "audit the runs directory", "what seed was that", "is this result reproducible", "write a model card", "write a datasheet for this dataset", or before a paper, a release or a thesis chapter cites a number. Also runs unattended as a nightly Hermes audit over a runs tree. Researcher role; read-only, offline, never repairs or deletes a run.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12, PyYAML and git on PATH; reads only the runs directory and the checkout it is pointed at; never writes into a run; no network.
metadata:
  borg-role: researcher
  grounding: dodge2019, gebru2021-datasheets, goodman2014, hart2016, heil2021, michener2015, mitchell2019-model-cards, pineau2021, rule2019, sandve2013
  hermes:
    category: research
    tags: reproducibility, provenance, seeds, runs, figures, model-card, datasheet
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git log *) Bash(git status *) Bash(git rev-parse *)
---

# Experiment tracking

A result is a claim about what a program did to some data. The claim holds only
if the run id, command, commit, seeds, data versions, environment and output
hashes were all recorded at the time. `scripts/runs_manifest.py` collects those
facts from a runs tree and reports every gap as a finding with a severity;
`scripts/figure_provenance.py` joins the manifest to an explicit figure-to-run
mapping and reports figures with no traceable run and runs no figure uses. The
templates in `assets/` turn a finished model or dataset into a model card or a
datasheet. Neither script repairs anything: an unreproducible result is
reported as unreproducible.

## When to use

- Before a number, table or figure enters a manuscript, a thesis chapter, a talk or a release.
- When someone asks which run produced a figure, what seed was used, or which data version a result rests on.
- Setting up a new project's runs directory, or adopting an existing one that has no descriptors.
- The nightly Hermes audit over a group runs tree (collector only, read-only, findings to Robert).
- Before publishing a model or a dataset, when a card or datasheet is needed.
- When a reviewer, a collaborator or a student cannot reproduce a published number.

## Procedure

1. Fix the scope: which runs tree, which git checkout the runs came from, and whether the results are heading for publication. Copy `assets/run.yaml.example` into the project as the descriptor format if the tree has none.
2. Collect: `python3 scripts/runs_manifest.py --runs <tree> --repo <checkout> --out runs/manifest.json --json`. Add `--infer` only for a legacy tree without descriptors, and say so in the report, because inferred fields are weaker evidence than recorded ones.
3. Read the `limits` block before the findings. A truncated scan (`--max-runs`, `--max-files`, `--max-hash-bytes`) means the manifest is partial, and the report says which part is missing rather than implying completeness.
4. Triage the findings by severity. High findings (`seed.missing`, `commit.missing`, `commit.dirty`, `input.unversioned`, `status.failed`, `input.missing`) mean the run cannot be reproduced from what is recorded; medium and low findings mean the record is thin. Never fill a missing seed, commit or version from memory or from a neighbouring run.
5. Trace the figures: write the mapping file from `assets/figure-map.yaml.example`, then `python3 scripts/figure_provenance.py --manifest runs/manifest.json --map <map> --manuscript <main.tex> --out runs/figures.json`. Read `figure.untraceable`, `figure.edited` and `run.unused` first.
6. Judge what the scripts cannot see: whether the recorded command actually produces the recorded output, whether the splits leak, whether the comparison is at a stated budget, whether the claim in the caption matches the number in the artifact (`references/experiment-tracking.md`).
7. Report the machine learning results in full: infrastructure, runtime, splits, the validation number beside each test number, code link, hyperparameter bounds, best configuration, number of trials, search method, selection criterion, and variation across trials (`references/experiment-tracking.md`, rule 8).
8. For a model or dataset that will be released, fill `assets/model-card.md` or `assets/datasheet.md`. Every number in a card cites the run id it came from; a field that cannot be answered is marked unknown with the reason.
9. Open beads for what is missing: one `kind:task` bead per unreproducible run that still matters, with the acceptance criterion that a rerun from a clean commit with a recorded seed reproduces the number. A result that cannot be re-derived and still supports a claim in a draft becomes a `needs:robert` bead.
10. Under the nightly audit, stop at step 4 and hand Robert the changes since the previous manifest: new high findings, runs that became unreproducible, figures that stopped matching their run output.

## Hard rules

- Never rewrite, move, prune or delete an experiment output, a descriptor or a log. Both scripts are read-only; corrections are new runs with new ids, and the superseded run keeps its record.
- A result without a recorded seed, commit and data version is reported as unreproducible. It is never fixed up, back-filled, guessed at, or quietly re-derived and presented as the original.
- No data content leaves the machine. The manifest, the report, the beads and the briefing carry paths, sizes, hashes, versions and counts, never rows, samples, labels or anything about a person.
- Large scans are bounded and say so. `--max-runs`, `--max-files` and `--max-hash-bytes` appear in the output, and a truncated scan is reported as partial rather than presented as a full audit.
- A figure whose bytes differ from the run output it claims is reported as edited after the run, whatever the reason given.
- A claim that one method beats another states the budget it holds at; results obtained at different budgets are not merged into one comparison.
- Runs over data in the local-only privacy class are audited on the local tier only, and their findings go to Robert, never to a channel or a shared briefing.
- The audit never triggers a rerun, submits a job, or touches the scheduler. Recomputation is proposed as a bead and waits for approval.
- Nothing is written outside the repository unless `--apply` explicitly permits an external `--out` path. Without `--out` both scripts only print.

## Outputs

- `runs/manifest.json`: one record per run (id, command, git, seeds, config hash, inputs, environment, timing, exit status, outputs, findings) plus a `limits` and `summary` block.
- `runs/figures.json`: figure-to-run provenance, per-figure findings, unused runs.
- `assets/model-card.md` filled per released model version, and `assets/datasheet.md` filled per dataset we create.
- Beads: one per unreproducible result that still supports a claim, plus a `needs:robert` bead when a draft cites a number no run can produce.
- For the nightly audit, a changes-only summary: new high findings, newly unreproducible runs, figures that stopped matching.

## Grounding

- `references/experiment-tracking.md`: what to record per run, seeds and randomness, raw data behind plots, notebook hygiene, the Dodge and NeurIPS reporting checklists, model card and datasheet fields.
- `references/data-management.md`: raw data immutability, hashes and dataset versioning, open formats, metadata and provenance, backup and preservation, privacy and anonymization.

For the quality of the code the runs execute (version control, tests, pinned
dependencies, containers, project layout) use the code-audit skill, which
carries `research-software-practice` as its own reference.

## Scripts

- `scripts/runs_manifest.py --help`: runs tree to manifest; read-only and offline; `--json`, `--out`, `--apply`, `--infer`, `--fail-on`, `--example`; bounded by `--max-runs`, `--max-files`, `--max-hash-bytes`.
- `scripts/figure_provenance.py --help`: manifest plus mapping file to figure provenance; `--manuscript` and `--figures` to collect the figures actually used; `--json`, `--out`, `--fail-on`, `--example`.

## Assets

- `assets/run.yaml.example`: the run descriptor, with a comment per field.
- `assets/figure-map.yaml.example`: the figure-to-run mapping.
- `assets/model-card.md`: model card template, fields from Mitchell et al. 2019.
- `assets/datasheet.md`: datasheet template, questions from Gebru et al. 2021.
