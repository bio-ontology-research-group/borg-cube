# Playbook: administrative form

When: an email trigger, Mattermost event or Robert creates a request bead
(travel request, exception request, Concur report, purchase, visitor
invitation, student form, admissions step, JBMS letter, CMS edit). Role:
secretary.

1. Identify the workflow in `~/pa/protocols/` (travel-requests,
   travel-justification-form, exception-request-form, btr-web-form-fields) or
   the relevant pa script (`reimburse_track`, `concur_ledger`,
   `travel_bundle`) and the policy references in `skills/kaust-admin/`.
2. Gather field values from KG and pa data (dates, destinations, budgets,
   people). Anything unknown is listed as a question, not guessed.
3. Pre-fill in the browser session Robert authenticated (`claude-in-chrome`
   on the laptop or the dedicated Chrome profile on ws). `browser-forms`
   helpers run `--dry-run` and stop before submit.
4. Verify completeness programmatically: no required field empty, no Yes/No
   or checkbox left with neither option, answers sanity-checked. Save the
   field-by-field table and a screenshot to `runs/<id>/form.md`.
5. Create the `kind:outbound` approval bead with the table, screenshot and
   the deadline (CEMSE travel: 30 calendar days ahead; exceptions in advance).
6. Robert approves in the cockpit or via the Concierge; signatures need the
   one-time authorisation phrase.
7. Submit, approve or sign; record the confirmation number and receipt PDF as
   provenance; update pa overlays (`reimbursements.yaml`) through the existing
   scripts.

Never: deliver a partially filled form; submit without approval; type or
store a password; act after an SSO session expired (stop and ask).
