---
name: literature-review
description: Runs a literature review as a method with a record. A protocol written before searching, an append-only search log with the exact query strings and dates, two-stage screening where every exclusion carries a declared reason code, PRISMA-style flow counts that must reconcile, a synthesis matrix built by concept, and a bibliography whose every entry is verified against Crossref or PubMed. Use when asked to "review the literature on X", "what has been done on X", "find the related work", "write the background section", "is this idea novel", "build a reading list", "check these references", "screen these papers", "make a PRISMA diagram", or when a student needs a first-year literature chapter. Researcher role; reads papers, never contacts an author or posts anywhere.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12; cite_check.py needs network for Crossref and PubMed unless run with --offline; doi2bib and the Paperclip CLI or MCP are optional search and citation tools; everything else is local.
metadata:
  borg-role: researcher
  grounding: booth-sutton-papaioannou, carey2020, grant-booth2009, keshav2007, kitchenham-charters2007, pautasso2013, prisma2020, webster-watson2002
  hermes:
    category: research
    tags: literature, review, screening, prisma, bibtex, citations, search-log
    requires_toolsets: terminal, file, web
allowed-tools: Read Grep Glob WebFetch Bash(python3 *) Bash(doi2bib *) Bash(paperclip *)
---

# Literature review

A review is a method with a record, not a pile of citations. The protocol fixes
the question, the criteria and the reason codes before any searching;
`scripts/search_log.py` keeps the search and every screening decision in an
append-only log and renders the flow counts, refusing when an exclusion has no
reason code or the arithmetic does not add up; the synthesis matrix turns the
included papers into concepts; `scripts/cite_check.py` proves that every
reference exists before it reaches a draft.

## When to use

- A student or a paper needs related work, a background section, or a first-year literature chapter.
- Robert asks whether an idea is novel, or what the state of the art on a topic is.
- A draft's bibliography needs checking before submission or after revision.
- A `kind:review` bead names a topic, or the research-planning skill asks what is already known.

## Procedure

1. Fix the type first. Narrative, scoping, systematized, systematic, rapid or
   umbrella (`references/literature-review.md`, Grant and Booth typology). The
   label is a promise about the search, so choose the one you can actually
   deliver and say so in the output.
2. Write the protocol from `assets/protocol.md`: the question decomposed into
   concept blocks, the inclusion and exclusion criteria, the reason codes, the
   sources to search, who screens, the extraction fields and the synthesis
   method. Nothing in it changes after searching; changes are dated amendments.
3. Start the log:
   `python3 scripts/search_log.py init --log runs/<id>/search.jsonl --question "..." --review-type systematized --protocol runs/<id>/protocol.md`.
   It seeds the default reason codes; add your own with `add-code`.
4. Scoping search first: find the reviews that already exist and size the
   literature. If a good recent review covers the question, the job changes to
   updating it, and the output says which review it extends.
5. Search. For each database, build the string from the concept blocks
   (synonyms with OR inside a block, blocks with AND, controlled vocabulary plus
   free text), run it, and log it as run:
   `add-search --database PubMed --interface web --query '<exact string>' --filters '<limits>' --hits 412`.
   At least two databases, plus backward and forward citation chasing logged
   with `--source-kind other-methods`. Paperclip contributes candidates under
   `other-methods` only, never as a database with a hit count
   (`references/reference-hygiene.md`).
6. Deduplicate in the reference manager, on identifiers rather than titles, and
   log the count: `add-dedup --removed 118 --tool zotero`.
7. Screen on title and abstract, one decision per record:
   `add-screen --stage title-abstract --record <doi> --decision exclude --reason E1`.
   The script refuses an exclusion whose code was never declared, and refuses a
   second decision on the same record.
8. Retrieve full texts. Log every failure with a reason:
   `add-retrieval --record <doi> --status not-retrieved --reason "no access, interlibrary request open"`.
9. Screen on full text with the same command at `--stage full-text`, then read
   the survivors properly: one note per paper from `assets/paper-note.md`, the
   six questions, figure by figure, with a locator for every number the review
   will quote.
10. Render the flow: `python3 scripts/search_log.py flow --log runs/<id>/search.jsonl --out runs/<id>/flow.md`.
    Exit 2 means the log does not reconcile; fix it by appending entries, never
    by editing the file.
11. Build the synthesis matrix from `assets/synthesis-matrix.md`, extraction
    table first, then the concept matrix. Read the matrix by column and write
    the gaps from its empty regions.
12. Write by concept, not paper by paper. General introduction, the concepts in
    the matrix order, then what is known, what is contested and what is missing.
13. Build the bibliography from identifiers (`doi2bib`, or the registry record),
    then verify:
    `python3 scripts/cite_check.py runs/<id>/refs.bib --cache runs/<id>/cites.json`.
    Exit 1 blocks the draft until a person has resolved each error.
14. Hand back the review, the flow counts, the matrix, the log and the citation
    check together. A review without its log is not finished.

## Hard rules

- No reference enters a draft, a briefing, a bead or a bibliography without a
  verified identifier. `cite_check.py` must resolve the DOI, PMID, PMCID or
  arXiv id and find the title and year in agreement. An entry with no
  identifier is checked by hand against the publisher page and the check is
  recorded with URL and date.
- A review reports its search date and its exclusion reasons. Every search
  carries the database, the exact query string, the filters and the date; every
  exclusion carries a code from the protocol; the flow counts appear in the
  output. A search older than the draft is rerun before submission.
- Summaries of a paper are drawn from the paper. An abstract, a title, a
  citation in another paper, a search-tool snippet or a memory of the work is
  never the source of a claim about what a paper did, found or measured. Every
  number quoted has a locator (table, figure, section or page).
- The counts reconcile or nothing is rendered: identified minus duplicates
  equals screened, screened minus excluded equals sought, sought minus not
  retrieved equals assessed, assessed minus excluded equals included.
- The log is append-only. It carries a hash chain; `validate` reports any edit
  made in place. Corrections are new entries.
- Call the review what it is. The word systematic is used only for a
  protocol-driven, exhaustive, appraised search with a second screener.
- Criticize the work, not the authors, and treat published results as
  provisional whatever the venue or the author's standing.
- No outbound contact. The skill never emails an author for a full text, never
  posts a reading list to a channel and never files anything. Those become
  approval beads for Robert.
- Hosted search tools see the query text. Nothing `local-only` (student names,
  unpublished internal text, grant or personnel material) goes into a Paperclip
  or web search.
- When the review covers our own work, say so in the text, and have a coauthor
  write that passage.

## Outputs

- `runs/<id>/protocol.md`: the question, criteria, reason codes, sources and synthesis plan, dated before the first search.
- `runs/<id>/search.jsonl`: the append-only log of searches, deduplication, screening decisions and retrieval attempts, hash chained.
- `runs/<id>/flow.md`: PRISMA-style flow counts, the exclusion reasons with their counts, and the table of searches as run.
- `runs/<id>/matrix.md`: extraction table, concept matrix, reading by column and numbered gaps.
- `runs/<id>/notes/<record>.md`: one reading note per included paper.
- `runs/<id>/refs.bib` and `runs/<id>/cites.json`: the bibliography and its verification cache.

## Grounding

- `references/literature-review.md`: review types and what each promises, protocol before search, search strategy and logging, two-stage screening with reasons, the flow of records, how to read a paper in passes, and synthesis by concept.
- `references/reference-hygiene.md`: what counts as a verified identifier, registries and their limits, BibTeX from identifiers with doi2bib, and the rules for Paperclip and other semantic search tools.

## Scripts

- `scripts/search_log.py --help`: append-only search log (`init`, `add-code`, `add-search`, `add-dedup`, `add-screen`, `add-retrieval`, `validate`, `flow`); refuses an undeclared reason code and refuses to render counts that do not reconcile; writing outside the checkout needs `--apply`.
- `scripts/cite_check.py --help`: checks BibTeX consistency and verifies entries against Crossref and PubMed; `--offline` opens no network connection; `--only-cited` limits the check and `--cache` stores registry responses; exit 1 on errors.
