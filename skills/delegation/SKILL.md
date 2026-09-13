---
name: delegation
description: Turns a goal into work beads with testable acceptance criteria, explicit dependencies, one owner role each, a scoped worker brief and a review gate, following the orchestrator-worker pattern and the group's decomposition rules. Use when asked to "break this down", "plan the work", "create beads for", "delegate this", "write a brief for the programmer", "who should do what", "check the dependencies", or when the group-leader role designs the weekly backlog. Lead role; beads are drafts until Robert approves in the cockpit.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads only the files given; prints bd commands but never runs them; no network.
metadata:
  borg-role: lead
  grounding: agentskills-spec, anthropic-building-effective-agents, anthropic-context-engineering, anthropic-multi-agent-research, anthropic-writing-tools, crossley2025, google-code-review, google-small-cls, grove-high-output-management, hhmi-bwf-making-the-right-moves, hunter-zinck2021, invest-wake2003, openssf-scorecard, scrum-guide2020, wilson2014
  hermes:
    category: lead
    tags: delegation, beads, planning, acceptance-criteria, worker-brief
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(bd *)
---

# Delegation

A goal becomes a plan (`assets/plan-template.md`), the plan becomes beads
(`scripts/beads_from_plan.py`, which rejects any bead without a checkable
acceptance criterion), the beads get an execution order
(`scripts/dependency_check.py`) and each worker gets a scoped brief
(`scripts/worker_brief.py`). The evidence for why briefs, criteria and review
gates look like this is in `references/agent-orchestration.md` and
`references/task-decomposition.md`; the review standard is in
`references/code-review-practice.md`.

## When to use

- A finding, a paper task, an audit or a course needs to become work for the programmer, auditor, editor, scribe or advisor roles.
- Robert asks for a plan, a breakdown or "beads for this".
- A worker reports back and the lead must decide whether the criteria are met or a new bead is needed.
- The weekly backlog design after the Monday repos patrol and the Thursday student digest.

## Procedure

1. State the goal as an outcome in one sentence, with its provenance (bead id, org heading, Message-ID, permalink). No provenance, no plan.
2. Choose the pattern and write it in the plan header: `single` when one well-scoped call does it; `chain`, `route` or `parallel` when the subtasks are known in advance; `orchestrator-workers` only when the subtasks depend on the input (`references/agent-orchestration.md`, rules 1 and 2).
3. Decompose into beads with `assets/plan-template.md`. Each bead: one owner role, one deliverable that someone can inspect end to end, small enough for one session, dependencies listed, out-of-scope stated with the neighbouring bead that owns it, privacy class, effort budget (`references/task-decomposition.md`, rules 1 to 8).
4. Write the acceptance criteria before any work starts, as pass/fail checks another person can run (`assets/acceptance-criteria-examples.md`). Put commands in backticks and name files and thresholds.
5. Run `scripts/beads_from_plan.py --plan runs/<id>/plan.md --out runs/<id>/beads.json --strict`. Fix every error in the plan, never in the JSON. Use `--bd-commands` to print the `bd create` lines for the approval bead; the engine or Robert runs them.
6. Run `scripts/dependency_check.py --beads runs/<id>/beads.json`. Cycles and unknown dependencies are errors; role clashes within a wave are a hint to re-sequence.
7. Brief each worker: `scripts/worker_brief.py --beads runs/<id>/beads.json --bead <id> --out runs/<id>/briefs/<id>.md --apply`. The brief carries objective, deliverable, criteria, allowed sources, out of scope, dependencies, provenance, escalation rules and reviewer. Nothing else from the lead's context goes to the worker.
8. Set the review gate: `review_by` is a tier at least as strong as the worker (plan reviews implement; plan reviews plan). The reviewer judges the outcome against the criteria and the reasonableness of the process, approves when the work improves the whole even if imperfect, and separates blockers from nits (`references/code-review-practice.md`).
9. After the run, record in the plan what was delivered against each criterion, what was reopened, and at most two process changes for the next cycle.

## Hard rules

- No bead without an acceptance criterion, an owner role, an output, provenance and a privacy class; `beads_from_plan.py` exits 2 and writes nothing.
- One bead, one owner. Shared work is two beads with a dependency.
- Workers see only their brief and the sources it lists; the lead's history, other beads' content and Robert's notes stay out.
- Review by a tier at least as strong as the worker; nothing closes without the gate. The reviewer is never the author.
- Outbound actions (message, email, post, issue, PR, form, deletion, restart) are never delegated as work; they become `kind:outbound` or `needs:robert` approval beads (`assets/escalation-rules.md`).
- People consequences (a student's progress, conduct, authorship) go to Robert only; a bead visible to a worker never assesses a person.
- Every autonomous run has a stopping condition (effort budget) and a human checkpoint before anything irreversible.
- `bd` commands are printed for approval; this skill never creates, claims or closes beads on its own.

## Outputs

- `runs/<id>/plan.md`: goal, pattern, provenance, reviewer, beads with criteria.
- `runs/<id>/beads.json`: validated beads shaped like `assets/bead.schema.json`; optional `bd create` lines.
- Dependency report: order, waves, longest chain, role clashes.
- `runs/<id>/briefs/<bead>.md`: one scoped brief per worker.

## Grounding

- `references/agent-orchestration.md`: workflows versus agents, orchestrator-worker delegation, context scoping, evaluation, tool design and the group's delegation rules.
- `references/task-decomposition.md`: INVEST and Scrum properties of good work items, small changes, scoping student projects, action items with owner and date.
- `references/code-review-practice.md`: the review standard used at the gate: actionable findings with severity, small changes, reviewer not the author.

## Scripts

- `scripts/beads_from_plan.py --help`: plan (Markdown or YAML) to validated beads JSON; exit 2 on a bead without a criterion; `--bd-commands` prints, never runs.
- `scripts/dependency_check.py --help`: cycles, unknown dependencies, topological order, parallel waves; exit 1 on errors.
- `scripts/worker_brief.py --help`: scoped brief per bead from the template; dry run unless `--apply`.
