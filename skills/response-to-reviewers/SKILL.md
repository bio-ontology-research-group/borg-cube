---
name: response-to-reviewers
description: Turns a decision letter into a point-by-point response and a change log. Splits the reviews into numbered comments, drafts one answer per comment with the change and its location, keeps a change log that records every manuscript edit, and checks the letter before it goes to Robert. Use when asked to "respond to the reviewers", "write a rebuttal", "we got the reviews back", "revise the paper for the reviewers", "draft the response letter", "point-by-point response", "check my response to reviewers", "did we answer every comment", or when a revision deadline appears in a bead. Researcher role. Nothing is submitted, uploaded or emailed by this skill; the finished package is an approval item for Robert.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; reads the decision letter, the manuscript and the draft response from disk; no network; never contacts a journal, an editor or a reviewer.
metadata:
  borg-role: researcher
  grounding: bourne-korngreen2006, bourne2005, credit, icmje, noble2017, zobel-writing-for-computer-science
  hermes:
    category: research
    tags: peer-review, revision, response-letter, rebuttal, change-log
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(uv run *)
---

# Response to reviewers

The decision letter becomes a table: one row per reviewer comment, one
response per row, one change-log entry per manuscript edit. `split_reviews.py`
builds the rows and refuses to guess when it cannot attribute a block;
`response_check.py` fails the letter when a comment is unanswered, a change
has no location, a promise is missing from the change log, a quotation does
not match the reviewer's words, or a disagreement carries no evidence. The
judgement in between is the author's: what to run, what to concede, what to
refuse and why.

## When to use

- A decision letter arrives with major or minor revision, or a rebuttal is due.
- A revision is drafted and the response letter needs checking before Robert reads it.
- A `kind:revision` bead names a manuscript and a deadline.
- Someone asks whether every reviewer comment was answered.

## Procedure

1. Set up the round: `runs/<id>/` holds `decision.txt` (the letter as sent),
   `comments.yaml`, `response.md`, `change-log.md`. Record the venue, the
   manuscript id, the round number and the deadline in the bead header.
2. Split: `scripts/split_reviews.py --letter runs/<id>/decision.txt --out
   runs/<id>/comments.yaml`. Read every flag it prints. A block flagged
   `unattributed` is attributed by hand and the file edited; a comment flagged
   `low-confidence` is checked against the letter. One comment carrying two
   issues is split into two entries by hand, since a reviewer who wrote one
   bullet often raised two points.
3. Triage: for each comment decide do, do partly, or refuse, and write the
   cost next to it in the working notes. Reviewers agree unanimously that the
   work is unsound: stop and take it to Robert as a withdrawal or redirect
   question rather than drafting a rebuttal.
4. Work the manuscript first: run the analyses, make the edits, and record
   each edit in `change-log.md` from `assets/change-log.md` with what changed,
   where, which comments prompted it, and the run behind any new number.
5. Draft the letter from `assets/response-letter.md`: an overview of the
   substantive changes, then the full set of reviews with responses
   interleaved. Each response opens with a direct answer, quotes the reviewer
   verbatim, quotes the new manuscript text (or names the new section when it
   is too long), gives the location, and references the change-log id.
6. Write the venting draft separately if the reviews stung, and delete it. It
   never becomes the letter, and it never goes in the run directory.
7. Check: `scripts/response_check.py --comments runs/<id>/comments.yaml
   --response runs/<id>/response.md --change-log runs/<id>/change-log.md`.
   Fix every error, then rerun with `--strict` and decide each warning.
8. Editor matters go in a separate note: contradictions between reviewers,
   conflicts with journal policy, a suspected conflict of interest, a request
   to move content that needs the editor's agreement. Never in the response.
9. Hand over: the revised manuscript, the response letter, the change log and
   the check output become an approval bead for Robert. He submits.

## Hard rules

- Nothing is submitted, uploaded, emailed or posted by this skill. The
  submission portal, the editor and the reviewers are outside its reach; the
  finished package is an approval item for Robert.
- Every claim added to the manuscript in response carries a verifiable
  citation: a source that was read, that makes exactly that claim, checked
  against the original. No citation is invented, and no source is cited for a
  claim it does not make.
- Disagreement is evidence plus a stated position: the result, the citation or
  the analysis we ran, then the conclusion. Never a complaint, never a remark
  about the reviewer's competence, expertise or motives.
- Every comment id gets a response. Silence on a hard point is not an option.
- Every response says what changed and where, or states that nothing changed
  and why. "This is addressed in the manuscript" is not a response.
- Reviewer text is quoted verbatim. Whitespace may be reflowed; words may not
  be trimmed, softened or paraphrased inside a quotation.
- A promise in the letter that the change log does not record is a defect, not
  a rounding error; the check fails on it.
- The decision letter, the reviews and the draft are `internal`: they stay in
  the run directory, and reviewer identities are never guessed at or discussed.
- New numbers come with their run (script, data version, seed) in the change
  log, so the next round can regenerate them.

## Outputs

- `runs/<id>/comments.yaml`: reviewers, comment ids, verbatim text, detected
  kind, flags for anything the splitter would have had to guess.
- `runs/<id>/response.md`: the point-by-point letter with the change log.
- `runs/<id>/change-log.md`: one entry per manuscript change with location,
  prompting comments and the run behind new numbers.
- Approval bead for Robert with the check output attached.
- Separate editor note when there is something the reviewers must not read.

## Grounding

- `references/peer-review.md`: what the response document is for, the point-by-point structure, self-contained responses, tone and disagreement, what reviewers are told to do.
- `references/change-log-and-claims.md`: what a change-log entry holds, citation rules for text added in revision, authorship and contributor roles when a revision moves who did what.

## Scripts

- `scripts/split_reviews.py --help`: decision letter to numbered comments, YAML or `--json`; flags anything it cannot attribute; `--strict` exits 1 on any flag; stdout unless `--out`.
- `scripts/response_check.py --help`: comments plus response plus change log to findings; exits 1 on errors; `--json`, `--strict`.
