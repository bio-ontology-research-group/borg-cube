---
name: kaust-admin
description: Identifies and prepares a source-backed KAUST administrative workflow for a travel request, reimbursement, visitor invitation, purchase, or student status letter. Produces a complete redacted field table, missing-answer list, evidence map, step and signer summary, and approval bead text for Robert. Use when asked "which KAUST form do I need", "prepare this travel request", "build my reimbursement packet", "invite a visitor", "prepare a purchase request", or "request a student status letter". It drafts only and never submits, signs, approves, pays, or sends.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads local YAML definitions and answers; no network; prints a draft unless --apply writes an explicitly named output.
metadata:
  grounding: anthropic-building-effective-agents, cwe-top25, kaust-cemse-milestones, kaust-registrar-program-guide, owasp-top-ten, scrum-guide2020
  hermes:
    category: admin
    tags: kaust, secretary, forms, travel, reimbursement, visitor, purchase
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *)
---

# KAUST administrative preparation

This skill selects a workflow category, verifies its definition, and prepares
the material Robert needs to review. It does not act in a portal. Read
`references/kaust-admin.md` before using a KAUST rule or choosing a current
form.

## Route the request

Classify by the requested outcome, not by a remembered form name.

| Outcome | Category | What must be verified before drafting |
| --- | --- | --- |
| Authorization for planned business travel | `travel-request` | current form, eligible traveler, timing, attachments, signers, ordered steps |
| Repayment or reconciliation after an expense | `reimbursement` | current system, claim evidence, timing, cost object, approvers, ordered steps |
| Institutional invitation for a visitor | `visitor-invitation` | visitor category, identity evidence, host approvals, signers, ordered steps |
| Acquisition of goods or services | `purchase` | purchase route, quotations or justification, budget approval, signers, ordered steps |
| Official confirmation of student status | `student-status-letter` | available letter type, request route, evidence, issuer, ordered steps |

The categories are routing labels, not verified KAUST form names. If two
categories fit, ask Robert which outcome he needs. Do not select an exact form
until its definition records a source URL or local source path, a locator, and
a `verified_on` date.

## Required input

Use a form definition YAML with this shape:

```yaml
form:
  id: local-mock-request
  title: Local mock request
  workflow: travel-request
  source:
    path: skills/browser-forms/scripts/mock_form.py
    locator: GET /
    verified_on: 2026-09-02
  steps:
    - Prepare the draft
    - Robert reviews the draft
  signers:
    - role: requester
      stage: after review
      source: local mock definition
  evidence_requirements:
    - id: request-source
      description: Source request with dates and purpose
      required: true
      source: local mock definition
  submit_selector: "#submit"
fields:
  - id: purpose
    label: Purpose
    selector: "#purpose"
    control: textarea
    required: true
    sensitivity: none
```

The answer YAML maps every field id to a value and its evidence. A scalar
value is accepted but is marked as lacking evidence.

```yaml
request_id: cube-example
provenance:
  - source: request.yaml
    locator: request
answers:
  purpose:
    value: Discuss the project plan
    evidence:
      - source: request.yaml
        locator: purpose
```

Allowed controls are `text`, `textarea`, `email`, `tel`, `date`, `number`,
`select`, `checkbox`, `radio`, and `yes-no`. Use `sensitivity: personal` for
passport, salary, grade, health, visa, contract, medical, or comparable
fields. Password or credential fields are forbidden, even when a value is not
present.

## Procedure

1. Read the request bead and its provenance. Confirm the requested outcome,
   person or organization, date context, and requested deadline. Do not put
   personal data into the bead.
2. Find the current form definition in the authorized local source. Verify
   `form.source.path` or `form.source.url`, `locator`, and `verified_on`.
   Reject a definition with placeholders or an undated source.
3. Read each workflow step, evidence requirement, and signer from that source.
   If any is absent, list it as unknown. Never supply a signer, deadline,
   attachment, form name, or URL from memory.
4. Build the answer YAML from cited sources. Every answer has an evidence
   locator. Unknown values stay absent. A false checkbox value is an answer;
   a missing checkbox value is not.
5. Run `python3 scripts/form_prepare.py --form <definition.yaml> --answers
   <answers.yaml> --screenshot runs/<id>/form.png --field-table
   runs/<id>/form.md --json`. The command prints the complete preparation
   result. Add `--out runs/<id>/form.md --apply` only for a reviewed output
   location.
6. Resolve every item in `missing_required`, `missing_evidence`, and
   `definition_gaps`. Do not deliver a partially filled form. Every required
   field, Yes or No choice, radio group, and checkbox must have an explicit
   answer.
7. Hand the verified definition and answer YAML to `browser-forms`. It creates
   an ordered dry-run plan and stops before submit.
8. Capture a screenshot only after masking personal and credential-like
   values in the page. Save only the redacted screenshot.
9. Run `form_prepare.py` again with the screenshot and field-table paths. Put
   its `approval_bead_body` into a `kind:outbound` approval bead for Robert.
   The bead contains the redacted table and locators, never sensitive values.
10. Stop. Robert performs any submit, signature, approval, payment, purchase,
    or send himself. Approval never authorizes this skill or its scripts to
    click submit.

## Hard rules

- Never submit, sign, approve, purchase, pay, send, or publish anything.
- Every proposed submission becomes an approval bead for Robert with a
  redacted screenshot and a redacted field table.
- Never request, enter, read, log, or store credentials. Never handle a
  password. Reuse only a browser session Robert authenticated.
- Redact passport data, salary, grades, health information, credentials, and
  comparable personal data from every generated artifact and every bead.
- Never deliver a partial form. Missing answers and missing evidence are
  questions for Robert, never values to guess.
- Report a changed portal layout and stop. Never guess a selector, field
  meaning, or replacement form.
- A real portal is dry-run and read-only. Only the local mock form is used by
  automated tests.
- Never invent a KAUST rule, deadline, form name, signer, or URL. Preserve
  conflicting sources and ask Robert to resolve them.

## Outputs

- A workflow summary with the source, verification date, ordered steps,
  evidence requirements, and signers.
- A field table with proposed values redacted where required, completion
  state, and answer provenance.
- Lists named `missing_required`, `missing_evidence`, and `definition_gaps`.
- An `approval_bead_body` that references the redacted screenshot and field
  table and states that Robert must perform the external action.

## Grounding

- `references/kaust-admin.md`: verified coverage, workflow preparation rules, source conflicts, and explicit gaps for the five assigned administrative categories.

## Scripts

- `scripts/form_prepare.py --help`: validates a form definition and answer YAML, renders the redacted field table, and prepares approval bead text; never submits.
