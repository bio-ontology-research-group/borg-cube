# Playbook: paper to submission

When: a `kind:paper` epic reaches `READY_TO_SUBMIT` in `~/org/papers.org`, or
Robert asks. Roles: editor (verdict), senior (experiments check), programmer
(repro fixes), secretary (submission portal, only after approval).

1. Sync: `cube sync --dry-run` shows the paper epic and its open experiment
   and review beads. A paper with open `kind:experiment` beads that block
   submission stops here with a `needs:robert` note.
2. Readiness review: `cube run editor --bead <review>` runs two independent
   reviews (Claude, Codex) against `rubrics/paper-readiness.md`, then a merged
   verdict `submit|revise|hold` in `runs/<id>/review.md`. Robert reads it
   first.
3. Reference integrity: every DOI resolved through Crossref; mismatches are
   listed, never fixed silently.
4. Reproducibility statement: code and data availability, versions, seeds;
   missing pieces become `stage:design` beads for the senior.
5. Venue checklist: author list and CRediT, ORCIDs, formatting, word limits,
   ethics and funding statements, preprint policy. Missing items are a table
   for Robert.
6. Robert decides. `revise` spawns follow-up beads; `hold` records why.
7. Submission: the secretary pre-fills the portal, saves the field table and
   screenshot, creates the `kind:outbound` bead; Robert approves; only then
   submit; confirmation recorded as provenance; `papers.org` state moves to
   `SUBMITTED` through the org sync after approval.
8. Announcement: the `new-paper` skill runs only when the paper is published,
   and every post is an approval bead.

Never: send to co-authors, upload, or post without approval; invent a
reference; change the manuscript text itself in the review run.
