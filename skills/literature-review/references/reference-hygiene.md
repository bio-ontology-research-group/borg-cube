---
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Reference hygiene and search tools

Sources
- prisma2020 (CC-BY-4.0 statement; not fetched into corpus/text, summarized from knowledge, pending verification)
- pautasso2013 (CC-BY-4.0; short excerpts allowed)
- booth-sutton-papaioannou (book, proprietary; cite only, ideas from corpus/notes/booth-sutton-papaioannou.md)
- kitchenham-charters2007 (proprietary technical report; not fetched, summarized from knowledge, pending verification)

## What the sources require of a bibliography

- A review reports the full search strategy for every source it searched and the
  date each source was last searched, which means the record of the search has
  to survive from the first query to the final manuscript [prisma2020].
- Use a reference manager from the beginning of the work, and record the
  reference at the moment the note is taken, so that nothing is misattributed
  later [pautasso2013].
- Import every hit into the reference manager, deduplicate there, and keep the
  record of every decision made about a record [booth-sutton-papaioannou].
- Documentation of the search has to be complete enough that a reader can judge
  how complete the search was, which makes the log part of the deliverable
  rather than a private working file [kitchenham-charters2007].

## Identifiers, and what counts as verified

The sources above do not specify identifier checking, and none of them covers
retractions. The following is a group rule, adopted because a language model
that writes a plausible citation is indistinguishable from one that writes a
real one, and because a retracted paper cited as evidence is a factual error in
our own work.

A reference is verified when its identifier resolves in a registry and the
registry record agrees with the entry:

| Identifier | Registry | Resolves through |
| --- | --- | --- |
| DOI | Crossref, DataCite | `https://api.crossref.org/works/<doi>` |
| PMID | PubMed | NCBI E-utilities `esummary` |
| PMCID | PubMed Central | NCBI E-utilities |
| arXiv id | arXiv | arXiv API `query?id_list=` |
| ISBN | book, no automatic registry | manual check against the publisher record |

Agreement means the registry title matches the entry title once both are
normalized to lowercase alphanumerics, and the registry year matches the entry
year. A DOI that does not resolve, a title that does not match, a year that is
off by more than the print or online publication gap of one year, or a record
flagged as retracted or withdrawn, all make the entry unusable until a person
resolves it.

Entries with no identifier at all are the dangerous class. A book chapter, a
technical report or a thesis may genuinely have no DOI; a hallucinated paper
also has none. Anything without an identifier is checked by hand against the
publisher or repository page and the check is written into the log with the
URL and the date.

## BibTeX from an identifier, never by hand

`doi2bib` (`https://www.doi2bib.org/bib/<doi>`, or the local `doi2bib` command)
returns a BibTeX entry generated from the registry record. Take the entry from
there rather than typing one, then fix only what the registry gets wrong:
capitalization inside a protected `{}` group, page ranges, and the journal name
if the registry abbreviated it. Never edit the title, the author list, the year
or the DOI to match what you expected to find; a mismatch is a signal that the
identifier is wrong, not a formatting problem.

For PubMed-only records without a DOI, `efetch -db pubmed -id <pmid> -format
medline` gives the fields; the entry then carries `pmid` and no `doi`.

## Paperclip as a search tool

Paperclip (github.com/GXL-ai/paperclip) is a hosted biomedical literature search
CLI and MCP server. It runs BM25 and vector search over bioRxiv, medRxiv, arXiv,
PMC, FDA documents and trial registries, exposes results as a virtual file
system, and supports `map` and `reduce` over a result set. It installs as a
skill for Claude Code and Codex.

Rules for using it:

- It is a discovery tool, not a database of record. Its ranking is semantic, so
  a result set is a candidate list to be screened, not a search result that can
  be reported as a query with a hit count. Every Paperclip session that
  contributes records is logged as an `other-methods` source with the prompt or
  query used, the date and the number of records taken forward.
- Any claim about a paper found through Paperclip is checked against the paper
  itself, and its identifier is verified through Crossref or PubMed before the
  reference enters a bibliography.
- A review that reports itself as systematic still needs the reproducible
  Boolean searches on named databases; Paperclip supplements them, in the same
  slot as citation chasing and hand searching.
- Paperclip needs an account and sends the query text to a hosted service. Do
  not point it at anything `local-only`: no student names, no unpublished
  internal text, no grant or personnel material. Check the terms before a
  student agent is pointed at it.

## Rules we adopt

1. No reference enters a draft, a briefing, a bead or a bibliography without a
   verified identifier, or a hand check recorded with URL and date (group rule;
   the sources require reproducibility [prisma2020, kitchenham-charters2007],
   not identifier checking).
2. Generate BibTeX from the identifier with `doi2bib` or the registry record;
   hand-typed entries are treated as unverified (from [pautasso2013]).
3. Run `scripts/cite_check.py` over the bibliography before every submission,
   and again after any revision that added citations; a title mismatch, a wrong
   year, a retraction or an unresolvable identifier blocks the submission until
   a person has looked at it (group rule).
4. Every record that reaches the log carries the identifier it was found by, so
   that deduplication and the flow counts work on identifiers rather than on
   titles (from [booth-sutton-papaioannou]).
5. Semantic search tools contribute candidates under `other-methods` in the
   search log, with the tool, the prompt and the date; they never appear as a
   database search with a hit count (group rule, consistent with
   [prisma2020]).

## Not covered

- No source here tells us how long a verification stays valid. We recheck at
  submission and at revision.
- Retraction coverage differs between Crossref and PubMed and neither is
  complete; a clean check is not proof that a paper stands.
- Deduplication of the same work across a preprint server and a journal is left
  to judgement; we keep the published version and record the preprint id on the
  same entry.
