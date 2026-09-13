# Paper plan: <working title>

Plan file for one manuscript, kept next to the manuscript source (for example
`paper/PLAN.md`). The paper-writing skill fills it in the order of the
sections below and refuses to move on while a section above is empty. Every
fact in it carries a source (path, run id, or bead); nothing is invented.

## One message

- Contribution in one sentence (what is now known or possible that was not): <sentence>.
- Working title stating that contribution: <title>.
- Reader who will use this: <biologist, ontology engineer, ML researcher, clinician>.
- What the reader can do after reading that they could not before: <sentence>.
- Evidence that carries the message (the one figure or table a reader must see): <figure id, run id>.

## Audience and venue

| Candidate venue | Why it fits (mission, article type) | Page or word limit | Deadline | Statements required | Decision |
| --- | --- | --- | --- | --- | --- |
| <venue from assets/venues.md> | | | | | first choice / fallback |

Article type: <research article, application note, resource paper, software article>.
Preprint: <yes, server, when> or <no, reason>.

## Outline

One informal sentence per planned paragraph. Results paragraphs start from
the statements the figures support; each statement becomes a subsection
heading or a figure title.

| Section | Paragraph | One-sentence content | Evidence (figure, table, run id, source) | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Abstract | context | | | | |
| Abstract | gap | | | | |
| Abstract | approach | | | | |
| Abstract | result (with a number) | | | | |
| Abstract | implication | | | | |
| Introduction | field gap | | | | |
| Introduction | subfield gap | | | | |
| Introduction | specific gap | | | | |
| Introduction | contribution ("Here we ...") | | | | |
| Results | approach summary | | | | |
| Results | statement 1 | | Figure 1 | | |
| Results | statement 2 | | Figure 2 | | |
| Discussion | what was found, in meaning | | | | |
| Discussion | limitation 1 and how the literature or a check bounds it | | | | |
| Discussion | limitation 2 | | | | |
| Discussion | what the contribution enables | | | | |
| Methods | data | | | | |
| Methods | model or method | | | | |
| Methods | evaluation | | | | |

## Figure storyboard

One row per figure and table, written before the figure is made. The message
becomes the first caption sentence.

| Id | Message (a claim the figure supports) | Plot type and why it fits the data | Data source (file, run id) | n or number of runs | Error bars or interval (what, over what, how computed) | Script that regenerates it | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Figure 1 | | | | | | | |
| Table 1 | | | | | | | |

## Contributions

Fill `assets/credit-roles.md` (copied next to this plan as `CREDIT.md`) and
record here who agreed to authorship, when, and where (meeting note or
message permalink). Data providers who are not authors are acknowledged.

- Authorship agreed: <date, source>.
- Author order agreed: <date, source>.
- Non-author contributors to acknowledge: <name, contribution>.

## Timeline and writing strategy

- Final deadline (external or consensus): <date>.
- Milestones: outline agreed <date>; figures final <date>; full draft <date>; outside read <date, reader>; coauthor approval <date>; submission <date>.
- Writing strategy: <principal writer / subsections by expertise / core group>; lead: <name>.
- Data management statement (how data and code are deposited, who may access what, which deposit satisfies the venue): <sentence>.

## Submission readiness

Filled from `assets/submission-checklist.md`; every item points to a
section, file or identifier.
