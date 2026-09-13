---
name: grant-writing
description: 'Develop a funder-specific research grant package from a supplied call: a one-page specific-aims style summary, independent aims with success criteria and risks, a milestone and deliverable work plan, a budget narrative outline, reviewer-facing checks, and a submission checklist. Use when asked to "write a grant", "prepare specific aims", "plan a funding proposal", "check this call", "make a budget narrative", "review a grant draft", "apply for a KAUST internal call", "prepare an NIH application", or "prepare an ERC proposal". The current call is always the authority for requirements and eligibility.'
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; accepts UTF-8 text or Markdown drafts and a locally supplied call definition; no network and no external submission.
metadata:
  borg-role: researcher
  grounding: bourne-chalupa2006, erc-evaluation-criteria, heilmeier-catechism, hhmi-bwf-making-the-right-moves, kaust-internal-calls, nih-application-guide
  hermes:
    category: research
    tags: grant, specific-aims, budget, milestones, review, submission
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# Grant writing

Build a proposal around a real call, a falsifiable plan, and evidence a reviewer
can locate quickly. This skill prepares the package only. It never submits a
proposal, contacts a funder, uploads a file, or asserts eligibility without
Robert's approval and the current call text.

## Procedure

1. Obtain the current call, its source URL or local path, retrieval date, and
   applicant context. Extract its requirements verbatim into a local call
   definition based on `assets/call-definition.yaml.example`. Do not fill a
   missing deadline, eligibility rule, font, page limit, or annex from memory.
   Mark it `unverified` and ask Robert to confirm it.
2. Frame the work before prose. State the important gap, the central objective,
   what changes if the project succeeds, the current limitation, and why this
   team can execute it. Use the eight questions in `references/grant-writing.md`
   as a reviewer-facing completeness test.
3. Draft a one-page specific-aims style summary: title, problem and gap,
   long-term goal, central objective, rationale and feasibility evidence, two
   to four independent aims, expected outcome, and impact. Keep it a style
   deliverable, not a claim that a particular funder accepts this format.
4. For each aim, state the question, approach, measurable success criterion,
   feasibility evidence, deliverable, material risk, mitigation or fallback,
   and decision if the criterion is missed. An aim must retain value if another
   aim fails. Use `scripts/aims_lint.py --draft <aims.md> --strict` to expose
   missing evidence and house-style failures.
5. Map the aims into a work plan. Each row has an aim, milestone date,
   deliverable, owner, dependency, decision point, and risk response. Make
   dependencies explicit and shorten the work if the schedule lacks room for
   internal review.
6. Write a budget narrative outline. For each cost category, link each resource
   to a work-plan activity, a deliverable, quantity or basis of estimate, and
   the call's allowed-cost rule. Do not invent rates, indirect costs, quotes,
   personnel effort, or funder caps.
7. Review as a panelist would: can a non-specialist find the gap and payoff;
   can each aim succeed independently; does each promised outcome have a
   measure; does feasibility support scope; does every risk have a credible
   response; and does every budget item enable named work.
8. Run `scripts/call_checklist.py --call <call.yaml> --draft <draft.md>`.
   The draft must contain the evidence markers defined in the call YAML for
   font, page count, deadline, eligibility, and annexes. The script will call
   missing evidence unverified rather than guessing from a text draft. Use
   `--json` for a machine-readable result. It exits 1 when a mandatory item is
   unmet or unverified.
9. Give Robert the completed draft, the checklist result, the call source and
   date, and a list of every unverified item. Wait for approval before any
   upload, portal action, contact, signature, or submission.

## Required outputs

- A one-page specific-aims style summary with the gap, objective, rationale,
  aims, expected outcomes, and impact.
- An aims table with success criteria, feasibility evidence, deliverables,
  risks, mitigations, and decision points.
- A work plan mapping aims to dated milestones and deliverables.
- A budget narrative outline linked to work-plan activity and the actual call.
- Reviewer-facing checks and the output of both deterministic scripts.
- A submission checklist whose call-derived requirements cite the call source
  and retrieval date.

## Hard rules

- The actual current call controls its own eligibility, sections, page limits,
  font, annexes, budget rules, deadline, portal instructions, and review
  criteria. The examples and general sources never override it.
- A missing requirement is unverified, not optional. Never make up a funder
  rule, deadline, URL, eligibility determination, budget rate, or reviewer
  criterion.
- Keep aims independent. Shared inputs are acceptable; "Aim 2 after Aim 1
  succeeds" is a risk that needs a redesign or an explicit fallback.
- Scope claims must be supported by preliminary results, access to resources,
  prior work, or another named source of feasibility evidence. Do not imply
  that preliminary data exist when they do not.
- Keep the main argument self-contained within the allowed material. Do not
  rely on an unapproved supplement, a website, or a reviewer following a link.
- No external message, meeting request, system upload, form submission,
  signature, or grant submission happens from this skill. Prepare evidence and
  wait for Robert's approval.
- Do not put student assessments, contracts, visas, health information, or
  other local-only material in a grant draft or checklist. Use only the
  minimum authorized personnel information.

## Grounding

- `references/grant-writing.md`: grounded grant-planning rules, source limits,
  and the distinction between general advice and a call's binding requirements.

## Scripts and assets

- `scripts/call_checklist.py --help`: checks a call YAML against a text draft,
  reports every unmet or unverified mandatory requirement, supports `--json`,
  and never writes.
- `scripts/aims_lint.py --help`: checks stated gap, aims, independence,
  measurable outcomes, feasibility evidence, risks, mitigations, and house
  style; `--strict` makes advisory findings fail.
- `assets/call-definition.yaml.example`: documented schema and evidence-marker
  example for a call-specific checklist.
