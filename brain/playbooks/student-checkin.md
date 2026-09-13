# Playbook: student check-in

Two modes. Robert-facing (Phases 1 to 3, no grant needed) and student-facing
(Phase 4, only for a student with a `mattermost_dm` grant with scope
`weekly-checkin` in `contacts.yaml`).

Robert-facing, weekly per student (student-digest patrol, Thursday 12:00):

1. Evidence: commits and PRs in the student's repositories since last week,
   draft changes in paper directories, new headings in `~/org/<person>.org`,
   the pa KG "Status as of" date.
2. Milestones: status from `kaust_rules.py` against `staff.org` estimates;
   rule-versus-estimate mismatches are conflict beads.
3. Draft for Robert: evidence table, milestone line, three suggested agenda
   points and questions that test understanding, open action items from the
   last meeting. Written to `briefings/students/<date>-<id>.md`, Robert-only.
4. If Robert asks: a draft message to the student, delivered to Robert, not
   the student.
5. Meeting notes Robert types or dictates go through the scribe into the org
   file after `cube approve`.

Student-facing, Phase 4 pilot (Hermes cron, Wednesday 10:00, granted students):

1. The advisor bot sends three questions (what moved, what is blocked, what
   is next) plus one milestone-aware prompt.
2. The reply is a `privacy:local-only` transcript; the scribe drafts an org
   entry tagged `:cube:`, a "Status as of" paragraph and a mentoring bead, on
   the local tier.
3. Written only after `cube approve` during the pilot.
4. The bot tells the student what it will summarise for Robert.

Escalation in both modes: two missed check-ins, a milestone under 90 days
without an artefact, or a self-reported blocker create a `needs:robert` bead
and a briefing paragraph. The system never delivers an assessment to a
student. Rubric: `rubrics/progress-assessment.md`.
