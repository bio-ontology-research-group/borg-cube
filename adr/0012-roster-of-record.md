# ADR-0012: The public profiles page is the roster of record

Status: accepted
Date: 2026-09-02

## Context

Three sources describe who is in the group: the `* Group <season> <year>`
section of `~/org/staff.org` (Robert's working note), the public profile
pages at https://borg.kaust.edu.sa/profiles/by-profile-group/ (students,
research scientists, postdoctoral fellows, research staff, principal
investigators), and `people.yaml`, a join table generated from the website
repository's `roster.md` on 2026-08-30. On 2026-09-02 they disagreed:
`people.yaml` still listed seven people who had left, lacked five who are
present, and gave one student a different programme than the site.

## Decision

Robert's decision, 2026-09-02, recorded here as the source for the
reconciliation: the public profiles pages are the roster of record for
membership and role. `staff.org` remains Robert's working note (start dates,
milestones, alumni). `people.yaml` is derived, never edited by hand.

Consequences applied on the same day, on Robert's word:

- One intern left the group (listed in staff.org summer 2026, absent from
  the site).
- Seven former students and staff (two research scientists, a postdoc, a
  research specialist, a software engineer and two students) left the group
  and are not active members; `people.yaml` moves them to a `former:` block
  so their org files and history stay addressable without them appearing as
  current members.
- Two people appear in no current source and are treated as former members
  until a source says otherwise.
- One student's programme follows the site (Ph.D., Bioengineering); the
  earlier PhD-CS entry is superseded.

## Rules

- `cube roster` compares all sources and reports every disagreement.
- `cube roster sync` writes membership and role from the site, and keeps
  programme, start date and milestone fields from `staff.org` where the site
  is silent. A disagreement on a field both sources state is still a
  `kind:conflict` bead, never a silent choice; this ADR is the recorded
  resolution for the cases listed above only.
- Website fetches are cached under `state/website/` with the fetch time; a
  parse failure is reported, never an empty roster.
- Nobody is deleted: former members keep their entry with `left:` and the
  source of that fact.

## Provenance

Robert Hoehndorf, in conversation, 2026-09-02: "borg.kaust.edu.sa profiles is
what is correct; [the intern] left. [The seven people named above] all left the
group, are not active."
