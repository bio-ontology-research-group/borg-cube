---
name: browser-forms
description: Plans a field-by-field dry run against an existing authenticated browser session from a form definition YAML and answer YAML, verifies selectors, redacts sensitive values, captures approval evidence, and stops before submit. Use when asked to "prefill this browser form", "make a dry-run fill plan", "check these portal fields", "reuse my logged-in session", or "show me the form before submission". Local mock forms may be tested; real portals remain read-only and dry-run. It never handles credentials or submits, signs, approves, pays, purchases, or sends.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; mock_form.py uses stdlib http.server on loopback only; fill_plan.py is dry-run only and may inspect a local mock URL.
metadata:
  grounding: anthropic-building-effective-agents, cwe-top25, kaust-cemse-milestones, kaust-registrar-program-guide, owasp-top-ten, scrum-guide2020
  hermes:
    category: admin
    tags: browser, forms, dry-run, approval, secretary, redaction
    requires_toolsets: terminal, file, browser
allowed-tools: Read Grep Glob Bash(python3 *) mcp__claude-in-chrome__* mcp__playwright__*
---

# Browser form dry runs

This skill turns a verified form definition and answer YAML into an ordered
plan, applies it field by field in a session Robert already authenticated,
captures redacted approval evidence, and stops before submit. Read
`references/kaust-admin.md` when the form is a KAUST workflow.

## Session rules

- On a laptop, attach to Robert's existing authenticated Chrome session with
  the available browser integration. On the workstation, attach to the
  dedicated existing browser profile over its configured CDP connection.
- Never open a login flow for Robert, ask for MFA, or type a credential. If
  the session is unauthenticated or expired, stop with `needs:robert`.
- Do not export cookies, storage, browser profiles, tokens, or authentication
  state. A session may be reused in place but never copied into an artifact.
- Real portals are read-only dry runs. Automated tests use only
  `scripts/mock_form.py` on loopback.

## Procedure

1. Receive a verified form definition and answer YAML from `kaust-admin`.
   Reject password fields, credential fields, placeholder selectors, missing
   source dates, or any submit action embedded among the fields.
2. Start with the deterministic plan:

   ```bash
   python3 scripts/fill_plan.py \
     --form definition.yaml \
     --answers answers.yaml \
     --json
   ```

3. Confirm the browser is already on the expected authenticated form. Read
   the page title and URL without navigating through login. Do not put a URL
   containing query secrets or personal identifiers into a report.
4. Check each selector before any fill. It must resolve to exactly one element
   with the expected label and control. If it is absent, duplicated, hidden,
   disabled unexpectedly, or attached to another label, report the layout
   change and stop.
5. Apply plan entries in order. Use `fill` for text-like controls,
   `select_option` for selects, `check` or `uncheck` for checkboxes,
   `click_choice` for radio and Yes or No choices, and `skip_missing` only
   while preparing questions. Never execute the terminal `stop_before_submit`
   entry.
6. Read each field back from the page after filling. Compare it with the
   answer source in memory. Record only `matched`, `missing`, or `mismatch` in
   generated artifacts for sensitive fields.
7. Mask values for passport, salary, grades, health, visa, contract, medical,
   credential-like, and comparable fields in the page before taking a
   screenshot. Ensure no tooltip, autocomplete menu, URL, or page message
   exposes them. Save only the redacted screenshot.
8. Render the field table from `kaust-admin/scripts/form_prepare.py`. Confirm
   that it has no missing required answers, missing evidence, or definition
   gaps and that every personal value is redacted.
9. Create the approval bead for Robert with the redacted screenshot, redacted
   field table, source locators, and exact external action Robert would need
   to perform.
10. Stop before submit. Do not click submit even after Robert approves the
    bead. Robert performs the submission, signature, approval, payment,
    purchase, or send.

## Local mock check

Run the mock server in one terminal:

```bash
python3 scripts/mock_form.py --port 8765
```

Then verify the form definition's simple selectors against it:

```bash
python3 scripts/fill_plan.py \
  --form definition.yaml \
  --answers answers.yaml \
  --check-url http://127.0.0.1:8765/ \
  --json
```

`--check-url` accepts loopback hosts only. It reports missing or duplicate
simple id and name selectors as layout changes. It never checks a real
portal. The mock page rejects POST requests.

## Hard rules

- Never submit, sign, approve, purchase, pay, send, or publish anything.
- Every proposed submission becomes an approval bead for Robert with a
  redacted screenshot and a redacted field table.
- Never request, enter, read, log, or store credentials. Never handle a
  password. Session reuse is the only authentication mode.
- Redact passport data, salary, grades, health information, credentials, and
  comparable personal data from every generated artifact and every bead.
- Never guess at a changed portal layout. Report it and stop.
- Never place cookies, tokens, authorization headers, session storage, or
  browser-profile data in YAML, command arguments, logs, screenshots, or
  beads.
- The ordered plan always ends with `stop_before_submit`; no script in this
  skill has a submit operation.
- Real portals remain dry-run only. Robert's approval of a first submission
  cannot change the behavior of these scripts without a separate reviewed
  implementation change.

## Outputs

- Ordered dry-run plan entries with selector, action, redacted value, field
  id, and provenance state.
- Layout-change findings for selectors that do not match the expected local
  mock element.
- Redacted screenshot and field table paths for the approval bead.
- No receipt or confirmation number, because this skill never submits.

## Grounding

- `references/kaust-admin.md`: source validation, preparation rules, privacy constraints, and known gaps for KAUST administrative workflows.

## Scripts

- `scripts/fill_plan.py --help`: creates an ordered JSON or Markdown dry-run plan, redacts sensitive values, optionally checks loopback selectors, and always stops before submit.
- `scripts/mock_form.py --help`: serves a deterministic mock form on loopback with POST disabled for local tests.
