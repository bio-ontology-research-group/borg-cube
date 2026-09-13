---
name: research-planning
description: Turns a research question into a written plan with competing hypotheses, an experiment matrix in which every experiment names its baseline, success threshold and kill criterion, a risk list, dated checkpoints, and beads with testable acceptance criteria. Use when asked to "plan this project", "design the experiments", "what experiments do we run", "write the research plan", "set success criteria", "when do we stop", "draft the proposal", "turn this plan into beads", or when a student starts a thesis project or a paper is scoped. Researcher role; the plan is a document, not a run, and beads are printed for approval rather than created.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; `bd` on PATH only for `--apply`; reads and writes files inside the repository; no network.
metadata:
  borg-role: researcher
  grounding: alon2009, anthropic-multi-agent-research, booth-craft-of-research, chicco2017, crossley2025, dodge2019, dome2021, google-small-cls, grove-high-output-management, gu2007, hamming1986, heilmeier-catechism, hhmi-bwf-making-the-right-moves, invest-wake2003, ioannidis2005, kapoor-narayanan2023, kass2016, kaust-proposal-format, osborne2014, pineau2021, platt1964, reforms2024, schwab2022, scrum-guide2020
  hermes:
    category: research
    tags: planning, hypotheses, experiments, baselines, kill-criteria, beads
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(bd *)
---

# Research planning

A research plan is one YAML file: the question, at least two competing
hypotheses, an experiment matrix in which every row names its baselines, its
success threshold and its kill criterion, a risk list with mitigations, and
dated checkpoints. `scripts/plan_to_beads.py` refuses the plan when any of
those is missing and, when it passes, prints the exact `bd create` commands
with the repository's YAML provenance header and stable xids. The evidence for
why plans look like this is in the four references below.

## When to use

- A student starts a thesis project, a rotation or a short project and the question is chosen.
- A paper is scoped: which experiments go in, what counts as enough, what would sink it.
- A proposal or a grant section needs the plan behind it (`assets/proposal-outline.md`).
- A reviewer, a collaborator or Robert asks what would make us abandon a line of work.
- An existing plan drifted and the experiments no longer test the hypotheses.

## Procedure

1. Facts first. The question, the prior work and the feasibility come from the problem-choice step (`references/problem-choice.md`); this skill starts once a question exists. Record provenance for the question: an org heading, a bead id, a paper, a meeting note. No provenance, no plan.
2. Write the hypotheses. At least two that could both be true a priori and that different results would separate. For each, write what it predicts we would see. A single hypothesis with no rival is a survey, not an inference (`references/research-planning.md`, rule 2).
3. Build the experiment matrix, one row per experiment: which hypotheses it tests, which hypothesis each outcome excludes, the data, the baselines, the metric, the success threshold as a number, the kill criterion, the owner role, the effort budget and the deadline. Start from `assets/plan.yaml.example`.
4. Choose baselines before methods. At least one simple baseline (frequency, similarity transfer, linear model, majority) and the published state of the art where one exists, both given the same search budget as the new method (`references/ml-rigor.md`, rules 1 and 7).
5. Set the threshold from what would matter scientifically, and write the reasoning in one sentence. A threshold the method is merely expected to reach tests nothing.
6. Write the kill criterion in the same breath: the result, the date or the cost at which this line of work stops. The plan says what happens next in that case (rewrite, fall back, write up the negative result).
7. Run the leakage checklist over every experiment before it is scheduled: split before preprocessing, split at the level of the dependence structure, duplicates counted, no feature unavailable at prediction time, the test set used once (`references/ml-rigor.md`, rules 2 to 6). Write the answers into the plan's data section.
8. Justify the size: a power calculation, a precision target, or a statement that the dataset is fixed and what that costs. State how uncertainty will be reported (seeds, folds, bootstrap) for every number the plan promises.
9. List risks with likelihood, impact, mitigation, and where possible a check that someone can run. Risks without a check stay in the plan and produce no bead.
10. Set checkpoints with dates: what is measured, and which result means continue, revise or stop.
11. Validate and generate: `python3 scripts/plan_to_beads.py --plan runs/<id>/plan.yaml --strict --out runs/<id>/beads.json`. Fix every error in the plan, never in the output. The script prints the `bd create` commands and creates nothing.
12. Show Robert the plan and the printed commands. Only after approval run `--apply`, or let the engine create the beads.
13. Re-read the plan at every checkpoint and at each semester review. Changes after the data are seen are recorded as dated amendments with a reason, never as a silent edit.

## Hard rules

- No experiment without a baseline, a success threshold and a kill criterion. `plan_to_beads.py` exits 2, names the experiment and the missing field, and writes nothing.
- No bead without a testable acceptance criterion, an owner role, provenance and a privacy class. Criteria that state no command, path or number are warnings and are errors under `--strict`.
- Beads are printed for approval. The script creates nothing without `--apply`, and `--apply` runs only after Robert has seen the commands.
- Thresholds, splits and analyses are fixed before the data are seen. A threshold changed afterwards is an amendment with a date and a reason, and the paper says so.
- The test set is used once. Model selection happens on validation data; a result that followed further looks is labelled exploratory and is not a claim.
- Exploratory experiments are marked exploratory in the plan and carry no significance claim.
- Every claim in a plan cites a source: a path with a locator, a DOI, a bead. No invented citations, no remembered numbers for published baselines.
- Plans that name a student's assessment, contract or health are `privacy:local-only` and stay out of beads; the plan holds the work, never the person.
- Outbound actions (preprint posting, registration on a public registry, a message to a collaborator) never happen from this skill; they become approval beads for Robert.

## Outputs

- `runs/<id>/plan.yaml`: the plan, shaped like `assets/plan.yaml.example`.
- `runs/<id>/beads.json`: validated beads with xids, headers, acceptance criteria and dependencies.
- The printed `bd create` commands, one per experiment, checked risk and checkpoint.
- `assets/proposal-outline.md` filled in when the plan has to become a proposal or a grant section.

## Grounding

- `references/research-planning.md`: what a plan contains, protocols and amendments, sample size, thresholds and checkpoints, data quality, planning the computation, the failure modes to design against.
- `references/ml-rigor.md`: leakage and its remedies, baselines and search budgets, uncertainty, metrics under class imbalance, reporting checklists, why search-heavy fields produce false findings.
- `references/problem-choice.md`: choosing the question the plan starts from, the feasibility test, the eight catechism questions, and the origin of the mid-term exams that become checkpoints.
- `references/task-decomposition.md`: what makes a work item deliverable in one session, acceptance criteria written before the work, one owner per item, explicit dependencies.

## Scripts

- `scripts/plan_to_beads.py --help`: plan YAML to bead creation commands; exits 2 on an experiment without a baseline, threshold or kill criterion; dry run unless `--apply`; `--json` and `--out` for the machine-readable form.
