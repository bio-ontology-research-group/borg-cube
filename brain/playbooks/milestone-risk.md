# Playbook: milestone risk

When: the daily milestones patrol (07:00) finds a KAUST milestone within 180,
90 or 30 days, or a rule-versus-estimate mismatch.

KAUST CEMSE rules (cohorts from Fall 2023): PhD qualifying exam by the end of
semester 3; proposal defense by the end of semester 5; PhD in 4 years plus at
most 1 extension; a missed milestone means dismissal. MS thesis: 4 semesters
plus summer; thesis application by the first week of semester 3. Committees:
3 members for the proposal, 4 including an external for the dissertation;
dissertation to the committee 6 weeks before the defense.

1. 180 days: finding bead, informational; advisor adds a line to the next
   digest.
2. 90 days without an artefact (proposal draft, thesis chapter, committee
   form): `needs:robert` bead; advisor drafts an agenda item and the list of
   forms the secretary would prepare.
3. 30 days: `needs:robert` with the full checklist (committee confirmed, room
   and form status, document to committee date).
4. Mismatch between `kaust_rules.py` and `staff.org`: `kind:conflict` bead;
   never silently trust either.
5. Robert decides what the student hears; the system never tells a student
   they are at risk.

Sources: KAUST CEMSE milestones page and registrar programme guide (verified
date in `skills/phd-milestones/assets/programs.yaml`).
