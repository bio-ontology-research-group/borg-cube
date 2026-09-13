# Change log, claims and the record

Sources
- noble2017 (CC-BY-4.0; short excerpts allowed)
- zobel-writing-for-computer-science (book, proprietary; cite only, ideas from corpus/notes/zobel-writing-for-computer-science.md)
- icmje (proprietary web recommendations; summary only, no quotes)
- credit (CC-BY-4.0; short excerpts allowed)

## Why a change log exists

- The response letter has to say, for every change, what changed relative to
  the previous version, because a reviewer cannot otherwise tell whether the
  text quoted at them is new or was there all along [noble2017].
- A self-contained response quotes the changed text and gives the location,
  stating whether line numbers belong to the original or to the revised
  manuscript [noble2017].
- Changes that are too long to quote, such as a whole new section, are named
  rather than reproduced, so the log is the only place where the full extent
  of the revision is visible [noble2017].
- The log is the artifact that lets a second person check the letter against
  the manuscript, which is what `response_check.py` automates: a promise in
  the letter with no entry in the log is a promise nobody verified
  [noble2017].

## What one entry holds

Each entry has an id (`CL-<n>`), what changed in one sentence, where it
changed (section, figure, table, equation or line range with the version the
numbers belong to), and the comment ids that prompted it. One entry per
change; a change prompted by two reviewers lists both ids, which is also how
the letter can point out that several reviewers raised the same criticism
[noble2017].

## Claims added during revision

- Cite only sources you have read, never cite a source for a claim it does not
  make, and cite the original source of an idea rather than a later paper that
  repeats it [zobel-writing-for-computer-science].
- Prefer archival sources (journals, refereed proceedings, theses) to web
  pages, and give an access date when a web page is unavoidable; check every
  reference against the original before submitting
  [zobel-writing-for-computer-science].
- Reviewers are expected to check that the references exist and support what
  is claimed, so an unverifiable citation added under time pressure is likely
  to be found [zobel-writing-for-computer-science].
- A new number in the manuscript needs the run behind it: the script, the
  data version and the seed, recorded in the log next to the change, so the
  result can be regenerated when the next round of review asks
  [zobel-writing-for-computer-science].

## Authorship, contributions and the record

- CRediT is a community taxonomy of 14 contributor roles, approved in 2022 as
  an ANSI/NISO standard and licensed CC-BY-4.0, used to describe who did what
  on a research output [credit].
- When a revision adds work by someone who was not an author, or drops the
  contribution that justified an authorship, the contributor roles and the
  author list are revisited before resubmission rather than after acceptance
  [credit], [icmje].
- The ICMJE recommendations carry the sections that govern this: defining the
  role of authors and contributors, disclosure of financial and non-financial
  relationships and conflicts of interest, responsibilities in the submission
  and peer review process, and corrections and version control [icmje].
- Since the January 2026 update, the ICMJE recommendations also carry separate
  sections on the use of artificial intelligence by authors and by reviewers;
  read them from the source before making a disclosure statement, because the
  fetched page in the corpus gives only the section titles [icmje].

## Rules we adopt

1. Keep one change log per revision round, entries `CL-1`, `CL-2` and so on,
   each with what changed, where, and the comment ids that prompted it. (from
   [noble2017])
2. A response that states a change references the log entry that records it;
   `response_check.py` fails the letter otherwise. (from [noble2017])
3. Every claim added in the revision carries a citation to a source that has
   been read and that makes exactly that claim, checked against the original.
   (from [zobel-writing-for-computer-science])
4. Every new number carries its run: script, data version, seed, in the log
   entry. (from [zobel-writing-for-computer-science])
5. Revisit authorship and CRediT roles whenever the revision moves who did
   what, and record the decision before the package goes to Robert. (from
   [credit], [icmje])
6. Disclosure statements about conflicts of interest and about tool use are
   written from the venue's current policy text, never from memory. (from
   [icmje])
