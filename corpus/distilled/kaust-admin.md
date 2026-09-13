---
topic: kaust-admin
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# KAUST administrative workflow preparation

Sources
- kaust-cemse-milestones (KAUST institutional page, proprietary; quote rules short, never republish)
- kaust-registrar-program-guide (KAUST institutional program guide, proprietary; quote rules short, never republish)
- anthropic-building-effective-agents (proprietary web article; summary only, no quotes)
- scrum-guide2020 (CC-BY-SA-4.0; short excerpts allowed)
- owasp-top-ten (CC-BY-SA-4.0; short excerpts allowed)
- cwe-top25 (proprietary web page; summary only, no quotes)

## What the evidence says

### What the KAUST pages establish

- The CEMSE page is a workflow-specific reference for graduate milestones. It sends students to the Program Guide for their admission year, the Registrar academic calendar for current deadlines, and the Graduate Program Student Advisor when a step is unclear [kaust-cemse-milestones].
- The CEMSE page presents milestone work as ordered stages. Its master's thesis example starts with a petition and supporting material, proceeds through committee approval and thesis sharing, and ends with result processing and archiving [kaust-cemse-milestones].
- The same page identifies evidence and approval roles for those academic workflows. Examples include an abstract and transcript with a master's petition, committee membership on result forms, GPSA signature circulation, and Dean approval of committees [kaust-cemse-milestones].
- The fetched Registrar guide is explicitly the 2025-2026 edition. It ties requirements to the student's program and cohort, names forms for some thesis and dissertation events, and sends readers to the academic calendar for date-sensitive deadlines [kaust-registrar-program-guide].
- The Registrar guide covers degree requirements, thesis applications, defenses, result forms, extensions, and related academic policy. It does not establish the travel, reimbursement, visitor, procurement, or student status-letter workflows assigned to this skill [kaust-registrar-program-guide].
- Neither fetched KAUST source verifies the current portal layout, browser selectors, institutional travel process, Concur process, visitor invitation process, purchase process, or status-letter process [kaust-cemse-milestones, kaust-registrar-program-guide].

### What the process sources add

- A predefined workflow gives consistency for a well-defined task, and routing is useful when distinct request categories need distinct downstream procedures [anthropic-building-effective-agents].
- A fixed sequence can place a programmatic check between steps, while an agent should use environmental results as ground truth and pause for human judgment at checkpoints or blockers [anthropic-building-effective-agents].
- Agent tools should expose clear interfaces and boundaries, and risky computer-use behavior should be tested in a sandboxed environment with guardrails [anthropic-building-effective-agents].
- An inspectable work product needs a shared completion condition. Scrum describes ordered, visible work and a Definition of Done that prevents incomplete work from being treated as complete [scrum-guide2020].
- OWASP treats its risk list as an awareness starting point rather than a complete security checklist, so a general web-security source cannot substitute for a KAUST policy or portal guide [owasp-top-ten].
- The fetched CWE page says common software weaknesses can enable data theft or system takeover, but it does not provide a KAUST credential-handling policy. The rule against passwords is a BORG safety rule, not a claimed KAUST rule [cwe-top25].

## Rules we adopt

1. Classify the request by purpose as travel request, reimbursement, visitor invitation, purchase, or student status letter before selecting a form definition. If the purpose fits more than one category, stop and ask Robert which outcome is intended (from [anthropic-building-effective-agents]).
2. Name an exact form, deadline, attachment, signer, approval route, or portal URL only when a dated official page or Robert's local protocol supports it. Put that source and locator in the form definition (from [kaust-cemse-milestones], [kaust-registrar-program-guide]).
3. Check the applicable program, cohort, and source edition for student workflows. Do not transfer a requirement from one program or admission year to another (from [kaust-cemse-milestones], [kaust-registrar-program-guide]).
4. Record the workflow as an ordered list of steps. For each step, record its required evidence, responsible party, signer or approver, and source locator. Mark absent information as unknown rather than inferring it (from [anthropic-building-effective-agents], [scrum-guide2020]).
5. Build a field table that contains every field in the form definition, its proposed answer, its answer provenance, and its completion state. Treat any unanswered required field, Yes or No choice, radio group, or checkbox as incomplete (from [scrum-guide2020]).
6. Prepare only a draft. Never submit, sign, approve, purchase, pay, or send anything. Put every proposed submission into an approval bead for Robert with the redacted field table and a redacted screenshot (from [anthropic-building-effective-agents]).
7. Reuse only a browser session that Robert authenticated. Never request, read, enter, log, or store a password or other credential (from [owasp-top-ten], [cwe-top25]).
8. Redact passport data, salary, grades, health information, credentials, and comparable personal data from every generated table, plan, screenshot, log, and bead. Keep sensitive source material out of beads (from [owasp-top-ten], [cwe-top25]).
9. Compare the current page with the dated form definition before filling. If a selector is absent, duplicated, or attached to a different label or control, report a changed layout and stop rather than guessing (from [anthropic-building-effective-agents]).
10. Treat a deadline or policy conflict as a source conflict. Show both dated sources to Robert and use neither silently. The current official calendar or responsible KAUST office must resolve the conflict (from [kaust-cemse-milestones], [kaust-registrar-program-guide]).
11. Use the local mock form for executable tests. A real portal remains read-only and dry-run only; approval of a future first submission does not change the present scripts, which have no submission capability (from [anthropic-building-effective-agents]).

## Where sources disagree

- The CEMSE milestone page says some defense result forms should be processed within three days, while the fetched Registrar guide uses two days for some program-specific defense results. Both also defer to academic-calendar deadlines. We preserve the conflict, select the student's applicable program and cohort, and ask the GPSA or Registrar when the current sources do not align [kaust-cemse-milestones, kaust-registrar-program-guide].
- The CEMSE page is a current procedural overview, while it tells students to use the Program Guide for their admission year as the official source for degree requirements. We use the CEMSE page for navigation and the applicable guide for cohort-specific academic rules, then verify date-sensitive steps against the current calendar [kaust-cemse-milestones, kaust-registrar-program-guide].
- General agent guidance permits autonomy in trusted environments, but browser form submission is an irreversible external action. We use the guidance's human checkpoint and stopping-condition pattern and prohibit submission in these skills [anthropic-building-effective-agents].

## Not covered

- Travel request: the official form name, portal URL, eligibility, lead time, required evidence, signers, and step order are unverified. Page URL: `[Robert to supply official page URL]`. Verified on: `UNVERIFIED` [kaust-cemse-milestones, kaust-registrar-program-guide].
- Reimbursement: the current Concur workflow, claim deadline, receipt rules, cost-object rules, approvers, and tracking states are unverified. Page URL: `[Robert to supply official page URL]`. Verified on: `UNVERIFIED` [kaust-cemse-milestones, kaust-registrar-program-guide].
- Visitor invitation: the official workflow, visitor categories, required identity evidence, signers, and order are unverified. Page URL: `[Robert to supply official page URL]`. Verified on: `UNVERIFIED` [kaust-cemse-milestones, kaust-registrar-program-guide].
- Purchase: the current procurement route, thresholds, quotation rules, budget approvals, signers, and order are unverified. Page URL: `[Robert to supply official page URL]`. Verified on: `UNVERIFIED` [kaust-cemse-milestones, kaust-registrar-program-guide].
- Student status letter: the official request route, available letter types, identity checks, required evidence, issuer, and turnaround are unverified. Page URL: `[Robert to supply official page URL]`. Verified on: `UNVERIFIED` [kaust-cemse-milestones, kaust-registrar-program-guide].
- Robert's local `pa` protocols and the `feedback_complete_forms` memory are named by the project plan but do not have distinct fetched manifest ids for this topic. Their rules must be added to the corpus or cited through a source-backed form definition before they can establish a KAUST rule here [kaust-cemse-milestones, kaust-registrar-program-guide].
