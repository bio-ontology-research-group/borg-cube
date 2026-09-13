---
name: reproducibility-check
description: Re-executes a computational result in a clean environment built only from the artifacts the authors shipped, compares the outputs against the reference outputs with a stated numeric tolerance per metric, lists every undocumented step the run needed, and grades the outcome in ACM artifact badging terms. Use when asked to "check if this reproduces", "rerun the analysis from the paper", "can we reproduce these numbers", "does this repo still build", "prepare the artifact for review", "we need the reproducibility badge", "verify the results before submission", or when a reviewer, collaborator or student hands over code and data that are supposed to produce a published figure or table. Researcher and software role; read-only on the repository under test; cluster runs follow the remote-connect skill.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and bash; a container runtime (docker, podman, apptainer or singularity) when the artifacts ship a container recipe; git for recording the commit; no network beyond fetching the deposited artifacts. Never modifies the repository under test.
metadata:
  borg-role: researcher
  grounding: acm-badging, balaban2021, brack2022, citation-file-format, fair4rs2022, google-code-review, gruning2018, hunter-zinck2021, jimenez2017, joss-docs, joss-review-checklist, joss-review-criteria, lee2018-documenting, list2017, nap2019-reproducibility, nust2020, openssf-scorecard, osborne2014, peng2011, romano2020, sholler2019, smith2016-software-citation, stodden2016, taschuk-wilson2017, turing-way, wilson2014, wilson2017
  hermes:
    category: research
    tags: reproducibility, containers, re-execution, acm-badging, artifact-review
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(bash *) Bash(git clone *) Bash(git -C * rev-parse *) Bash(docker build *) Bash(podman build *) Bash(apptainer build *) Bash(singularity build *)
---

# Reproducibility check

A reproducibility check is one experiment with one question: does the claimed
result come out again when someone else builds the environment from the
artifacts alone and runs the workflow? The answer is worth nothing without
two pieces of evidence: the record of how the environment was built and what
had to be improvised, and the comparison of produced outputs against reference
outputs at a stated tolerance. `scripts/repro_env.sh` produces the first,
`scripts/compare_results.py` the second, and the grade in
`references/acm-badges.md` maps them to a badge that can be defended.

## When to use

- A paper of ours is going to a venue with artifact review, or a JOSS or
  journal reviewer asks whether the code runs.
- A result is about to be published and nobody has run it outside the machine
  it was developed on.
- A student or collaborator hands over code and data that should regenerate a
  figure or a table.
- A repository has been idle and we need to know whether it still builds
  before someone else is asked to work on it.
- Someone asks for a reproducibility badge or claims one.

## Procedure

1. Name the target before touching anything: which figure, table or number,
   which command is supposed to produce it, and where the reference output
   lives. Write it into the report header. A check with no stated target is
   not a check.
2. Get the artifacts the way a stranger would. Prefer the deposited archive
   with its persistent identifier over the development repository; record
   which one you used and whether the identifier resolved. Clone into
   `runs/<id>/repo` and record the commit with `git -C runs/<id>/repo rev-parse HEAD`.
   Never work in a checkout someone is editing.
3. Build the environment: `scripts/repro_env.sh --repo runs/<id>/repo --work runs/<id>/env`
   to see the plan, then add `--build` to execute it. Read
   `runs/<id>/env/repro-env.json`: `strategy` says what the artifacts
   supported, `findings` lists every improvisation. If the script refuses,
   the artifacts do not describe an environment, and that is the result.
4. Run the workflow headlessly, inside the built environment, with the output
   directory bound from outside and the input data mounted read-only. Keep
   the exact command and its log. Every manual step you have to add here is a
   missing step; write it down as you take it, not afterwards.
5. Compare: `scripts/compare_results.py --reference <paper outputs> --produced runs/<id>/results --tolerance <abs> --metric '<name>=<abs>[,<rel>]' --json`.
   Set the tolerance per metric before you look at the produced numbers, and
   write down why each one is what it is.
6. Classify from the comparison output, not from impression: identical, within
   tolerance, or divergent. A divergent run names the items and the size of
   the difference and stops there; it is not a verdict about the authors.
7. Grade with `references/acm-badges.md`: which badge the evidence supports,
   which it does not, and what is missing. Name the terminology version.
8. Write the report from `assets/repro-report.md`. The missing-steps table and
   the comparison output are mandatory sections.
9. Turn the findings into beads for the authors' repository through the
   delegation skill. Sending anything to a person outside the group, including
   a reviewer response or an issue on someone else's repository, is an
   approval bead for Robert.

## Hard rules

- Never modify the repository under test. Read-only clone, no commits, no
  edits, no issues opened, no `--fix` runs. Findings are reported, not applied.
- Never fall back to the environment on this machine. If the container runtime
  is missing or no recipe exists, report that and stop; a run in the
  developer's environment proves nothing about the artifacts.
- A re-execution that needed undocumented steps is reported as not
  reproducible, with the missing steps listed, whatever the numbers did.
- No result is called reproduced without the comparison output that proves it,
  attached and readable, at a tolerance stated before the run.
- Tolerances are chosen and justified before the produced numbers are seen.
  Widening a tolerance after seeing a difference is falsification of the check
  and is recorded as such if it happens.
- Compute on a cluster follows the remote-connect skill's rules for hosts,
  partitions, storage and job submission; do not restate or work around them,
  and never run heavy work on a login node.
- Data that is not ours to redistribute never enters an image, a bead, a
  report or a shared working directory. Personal or controlled-access inputs
  make the run `local-only`.
- Every number in the report traces to a file the check produced: the
  environment JSON, the comparison JSON, or the run log. No remembered results.
- Grades use ACM's terms with their exact meaning; "results replicated" is
  never claimed from re-running the authors' own code.

## Running on the cluster

Large re-executions belong on IBEX, and the remote-connect skill is the
authority for how to get there: which host, which partition, where data and
scratch live, how jobs are submitted and how results come back. This skill
adds only what reproducibility needs on top:

- Use Apptainer or Singularity there; `repro_env.sh` detects `.def` and `.sif`
  and picks the runtime that exists. A `.sif` with no definition file is a
  finding: the image cannot be audited or rebuilt.
- Record the module environment, the node type and the allocation in the
  report header, because they are part of the computing environment.
- Bind-mount inputs read-only and write outputs to a directory outside the
  image, then copy them back for the comparison.
- Nondeterminism from GPUs, thread counts and BLAS libraries is expected;
  record the seed, the device and the thread count, and set the tolerance for
  it rather than pretending it away.

## Outputs

- `runs/<id>/env/repro-env.json` and `repro-env.txt`: strategy, source recipe,
  runtime, build command, build status and the list of improvisations.
- `runs/<id>/env/repro-env.log`: the build output.
- `runs/<id>/compare.json`: per-item absolute and relative differences, the
  tolerance that applied to each, and the outcome.
- `runs/<id>/repro.md`: the report from `assets/repro-report.md`, including the
  missing-steps table and the badge grade.
- Beads for the findings; an approval bead for anything that leaves the group.

## Grounding

- `references/reproducibility.md`: what reproducibility and replicability mean, how to capture a computing environment, pinning, mounted data, headless execution, cache-less rebuilds, and what to deposit.
- `references/acm-badges.md`: the three ACM badge families, what each certifies, and which badge the outcome of a check can and cannot support.
- `references/research-software-practice.md`: the practices a repository is judged against when the check asks why it did not build.
- `references/fair4rs-and-joss.md`: FAIR4RS principles, JOSS review expectations, software citation and deposit with a persistent identifier.

## Scripts

- `scripts/repro_env.sh --help`: chooses a container recipe, then a lock file, then a dependency list; records improvisations; refuses to reuse the developer's environment; writes only under `--work`; plan only unless `--build`.
- `scripts/compare_results.py --help`: compares CSV, JSON and plain numeric outputs item by item with per-metric tolerances; `--json`; exits 1 on divergence.

## Related skills

- `remote-connect` for anything that runs on IBEX or another remote host.
- `code-audit` when the question is repository quality rather than one result.
- `experiment-tracking` for the run manifest, seeds and figure provenance that
  make a later check cheap.
- `software-release` when the outcome is a deposit with a DOI.
