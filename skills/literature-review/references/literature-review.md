---
topic: literature-review
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Literature review

Sources
- pautasso2013 (CC-BY-4.0; short excerpts allowed)
- carey2020 (CC-BY-4.0; short excerpts allowed)
- prisma2020 (CC-BY-4.0 statement; not fetched into corpus/text, summarized from knowledge of the checklist and flow diagram, pending verification)
- grant-booth2009 (proprietary; not fetched, summarized from knowledge, pending verification)
- kitchenham-charters2007 (proprietary technical report; not fetched, summarized from knowledge, pending verification)
- keshav2007 (proprietary; not fetched, summarized from knowledge, pending verification)
- webster-watson2002 (proprietary; not fetched, summarized from knowledge, pending verification)
- booth-sutton-papaioannou (book, proprietary; cite only, ideas from corpus/notes/booth-sutton-papaioannou.md)

## What the evidence says

### Why a review is a method, not a reading list

- The demand for reviews comes from publication growth: compared with 1991, in
  2008 Web of Science indexed three, eight and forty times more papers on
  malaria, obesity and biodiversity, so nobody can read every relevant new
  paper and summaries have to be compiled professionally [pautasso2013].
- Reviewing is not stamp collecting. A good review discusses the literature
  critically, identifies methodological problems and points out research gaps,
  so that a reader ends up knowing the major achievements, the main areas of
  debate and the outstanding questions [pautasso2013].
- Writing that is organized around authors ("Smith said, then Jones said")
  fails; a review is written concept by concept, with a concept matrix mapping
  concepts against articles as the bridge from reading to writing
  [webster-watson2002].
- A review earns its place by producing something the individual papers do not
  contain: a model or framework of what is known, and a statement of what is
  missing that motivates new research [webster-watson2002].
- Every review, including a thesis chapter or a grant background section,
  benefits from being explicit, transparent and repeatable, even when it is not
  a full systematic review [booth-sutton-papaioannou].

### Choosing the type of review

- Reviews differ along four dimensions: the search, the appraisal of what is
  found, the synthesis and the analysis; the SALSA framework describes fourteen
  named review types (among them critical review, mapping review, meta-analysis,
  rapid review, scoping review, state-of-the-art review, systematic review,
  systematized review and umbrella review) by what each does on those four
  dimensions [grant-booth2009].
- The label carries a promise about method: a review that calls itself
  systematic is expected to have an exhaustive, protocol-driven search with
  quality appraisal, while a systematized review does some but not all of that
  and should say so [grant-booth2009].
- Pautasso frames the same choice more informally as mini versus full review
  and descriptive versus integrative review, where integrative reviews look for
  common ideas across studies rather than describing each one, and notes that
  systematic reviews test a hypothesis against evidence gathered with a
  predefined protocol to reduce bias [pautasso2013].
- The choice depends on the material found, the target journal, the time
  available and the number of coauthors, and is made case by case
  [pautasso2013].
- A structured question comes before the search: PICO or PICOC, SPICE, or
  SPIDER for qualitative questions; the concept blocks in the question become
  the blocks of the search string [booth-sutton-papaioannou].
- In software engineering, a systematic review runs in three phases, planning
  (need, questions, protocol, protocol review), conducting (search, selection,
  quality assessment, extraction, synthesis) and reporting; the protocol is
  written and reviewed before any searching, because it is what stops the
  reviewer's expectations from shaping the result [kitchenham-charters2007].

### Searching and logging the search

- Keep track of the search items used so that the search can be replicated;
  keep a list of papers whose PDFs cannot be accessed immediately; use a
  reference manager from the beginning; define criteria for excluding
  irrelevant papers early, and describe them in the review; and look for
  previous reviews, not only research papers [pautasso2013].
- The usual search rules are to be thorough, to use different keywords and
  several databases rather than one, and to look at who has cited the relevant
  papers and book chapters already found [pautasso2013].
- Being up to date matters as much as being complete: a review should not name
  as a research gap something that has just been addressed in papers in press,
  and it should not overlook older, long-ignored work either; a fresh search at
  revision stage is worthwhile because peer review takes months [pautasso2013].
- A scoping search comes first, to size the literature and to find reviews that
  already exist; the strategy then balances sensitivity against precision,
  joining synonyms with OR inside a concept block and blocks with AND,
  combining controlled vocabulary such as MeSH with free text, and translating
  the strategy for each database interface [booth-sutton-papaioannou].
- Database searching alone is not enough: backward and forward citation
  chasing, hand searching of key journals and proceedings, author contact and
  grey literature all add records that the string missed
  [booth-sutton-papaioannou, kitchenham-charters2007].
- Webster and Watson give the same procedure for an information systems review:
  start from the leading journals and conferences, go backward through the
  references of the articles found, then go forward through the articles that
  cite the key articles, and stop when new sources stop adding concepts
  [webster-watson2002].
- Record every search with the database, the interface, the date, the full
  query string, the filters and the hit count, and record the deduplicated
  total across databases [booth-sutton-papaioannou].
- PRISMA turns this into a reporting requirement: state every database,
  register and website searched and the date each was last searched, and
  present the full search strategy for every source, not a summary of it
  [prisma2020].
- Kitchenham and Charters require the search strategy, including the trial
  searches used to develop it, to be documented well enough that a reader can
  assess its completeness, and expect selection to be piloted and applied by
  more than one person, with disagreement measured rather than settled quietly
  [kitchenham-charters2007].

### Screening, reasons and the flow of records

- Screening happens in two stages, first titles and abstracts and then full
  texts, against inclusion and exclusion criteria written before screening;
  a second screener works on at least a sample, and a reason is recorded for
  every full-text exclusion [booth-sutton-papaioannou].
- The PRISMA 2020 flow diagram accounts for every record from identification to
  inclusion: records identified per database and register, duplicates removed
  before screening, records screened and excluded, reports sought for retrieval
  and not retrieved, reports assessed for eligibility and excluded with the
  reasons and their counts, and the studies finally included, with a parallel
  arm for records found by other methods [prisma2020].
- The counts on that diagram have to add up, and exclusions at full text are
  reported by reason, which is why the reasons have to be a fixed vocabulary
  decided in the protocol rather than free text invented per paper
  [prisma2020, kitchenham-charters2007].
- Appraisal of the included studies uses a checklist suited to the study
  design, and serves to weight and interpret the evidence, not only to exclude
  studies [booth-sutton-papaioannou].

### Reading the papers you kept

- Read with a goal, because what you want from an article decides how you read
  it: entering a new field means reading the introduction and the conclusion,
  tracking a technique means reading the methods, reviewing means asking
  whether the data support the interpretation [carey2020].
- Ask six questions of the paper as a whole and of every figure and table: what
  did the authors want to know, what did they do, why that way, what do the
  results show, how did the authors interpret them, and what should be done
  next [carey2020].
- The data are the paper. Work through each figure axis, color scheme,
  statistical approach and plotting choice, and go back into the methods as
  often as needed to see how the presented data were obtained [carey2020].
- Published papers are not settled truth, and this applies equally to
  high-profile journals, to well-known authors, to papers that agree with your
  hypothesis and to papers that refute it; the reader has to look for equally
  likely alternative explanations, for limits to generalizability, and for the
  reader's own bias toward results that confirm what they already believe
  [carey2020].
- Understanding a paper often costs a term lookup, a trip into the
  supplement, or reading a cited reference; a common recommendation is three
  readings, once without pressure, once for understanding, once taking notes
  [carey2020].
- Keshav gives the same idea as a budgeted three-pass method: a first pass of
  five to ten minutes over title, abstract, introduction, headings and
  conclusions to decide category, context, correctness, contributions and
  clarity; a second pass of about an hour that reads the body and the figures
  but skips proofs and marks references to follow; and a third pass that
  reconstructs the work assumption by assumption and takes several hours
  [keshav2007].
- Keshav applies the same passes to building a review: use the first pass over
  recent survey papers and highly cited work to find the shared citations and
  repeated author names that mark the key papers, then read those, then check
  the recent proceedings of the venues where they appeared [keshav2007].
- Take notes while reading rather than after: write down the interesting
  pieces, the organizing ideas and the impressions as they occur, so that by
  the end of the reading a rough draft already exists; mark anything copied
  verbatim with quotation marks and rewrite it later, and record the reference
  at the moment of the note to avoid misattribution [pautasso2013].
- Talking about a paper in a journal club or with colleagues forces the active
  reading that silent skimming does not [carey2020].

### Synthesis and writing

- Extract into tables with common fields first, then choose the synthesis
  method, narrative, tabular, thematic, framework or statistical, according to
  the question and the kind of data; analysis then goes beyond summary to
  patterns, contradictions and gaps [booth-sutton-papaioannou].
- Kitchenham and Charters warn that quantitative synthesis is only meaningful
  when the studies are comparable in question, design and metric; otherwise the
  synthesis stays descriptive and reports the heterogeneity as a finding
  [kitchenham-charters2007].
- The introduction, methods, results and discussion structure rarely works for
  a review, but a general introduction to the context and a recapitulation of
  the main points at the end do; drawing a conceptual diagram or mind map of
  the review helps to find the order of the sections and can be worth including
  as a figure [pautasso2013].
- Keep the review focused: material included for its own sake produces a review
  that tries to do too many things at once, and for an interdisciplinary review
  the focused choice is to treat in detail only the studies at the interface of
  the two fields, while discussing the wider implications for breadth
  [pautasso2013].
- Reviewers of the literature usually have published on the topic, which is a
  conflict of interest in both directions, overstating their own work or
  dismissing it; in a multi-author review the fix is to assign a coauthor's
  results to a different coauthor to review [pautasso2013].
- Feedback from a variety of colleagues, and normal peer review, catch the
  inaccuracies and ambiguities that rereading your own text does not
  [pautasso2013].
- The methods of a review are reported so that the review can be repeated, a
  protocol is the first written product, a flow diagram of records is part of
  the report, and there is a plan for updating [booth-sutton-papaioannou].

## Rules we adopt

1. Write the question, the review type and the inclusion and exclusion criteria
   before the first search, and put them in a protocol file that the review
   later reports (from [kitchenham-charters2007], [booth-sutton-papaioannou],
   [grant-booth2009]).
2. Log every search as it happens: date, database or tool, the exact query
   string, the filters and the hit count. A search that is not in the log did
   not happen (from [pautasso2013], [booth-sutton-papaioannou], [prisma2020]).
3. Report the search date and never present a stale search as current. Rerun
   the search before submission and again at revision (from [pautasso2013],
   [prisma2020]).
4. Search at least two databases and add backward and forward citation chasing;
   a single-database search is reported as a limitation (from [pautasso2013],
   [webster-watson2002], [booth-sutton-papaioannou]).
5. Screen in two stages against the written criteria, and give every exclusion
   a reason code from a fixed list declared in the protocol. No reason code, no
   exclusion (from [booth-sutton-papaioannou], [prisma2020]).
6. Make the numbers reconcile: identified minus duplicates equals screened;
   screened minus excluded equals sought; sought minus not retrieved equals
   assessed; assessed minus excluded equals included. Render the flow counts
   and refuse to publish a review whose counts do not add up (from
   [prisma2020]).
7. Summarize a paper only after reading the paper. An abstract, a title, a
   citation in another paper or a memory of the work is not a source for a
   claim about what the work did (from [carey2020], [keshav2007]).
8. Use the reading budget deliberately: first pass to decide whether the paper
   is in scope, second pass for the papers that survive screening, third pass
   only for the papers the review's argument rests on (from [keshav2007]).
9. Take notes while reading, in a per-paper record that carries the identifier,
   the six questions, the numbers the review will quote and any verbatim text in
   quotation marks (from [pautasso2013], [carey2020]).
10. Synthesize by concept, not paper by paper. Build the extraction table and
    the concept matrix first, and let the section structure follow the concepts
    (from [webster-watson2002], [booth-sutton-papaioannou]).
11. State what is known, what is contested and what is missing. A review that
    names no gap and no disagreement is not finished (from [pautasso2013],
    [webster-watson2002]).
12. Criticize the work, not the authors, and treat published results as
    provisional regardless of the venue or the author's reputation (from
    [carey2020]).
13. Declare the conflict when the review covers our own work, and have a
    coauthor write the passage about it (from [pautasso2013]).
14. Name the review type honestly. Call a narrative review narrative and a
    systematized review systematized; the word systematic is reserved for a
    protocol-driven, exhaustive, appraised search (from [grant-booth2009]).

## Where sources disagree

- How exhaustive a search must be: [kitchenham-charters2007] and [prisma2020]
  expect an exhaustive, documented and repeatable search, while [pautasso2013]
  accepts a focused mini-review that leaves relevant material out because of
  space, and [grant-booth2009] treats both as legitimate review types. We
  follow the typology: exhaustiveness is a property of the review type chosen,
  and the review states which type it is, so a reader knows what the search
  covered.
- Whether appraisal excludes or weights: [kitchenham-charters2007] uses quality
  assessment as an inclusion criterion in some reviews, while
  [booth-sutton-papaioannou] treats appraisal mainly as a way to weight and
  interpret. We appraise to weight by default and exclude on quality only when
  the protocol said we would, with the threshold stated in advance.
- How to spend reading time: [carey2020] recommends reading an article three
  times, unhurried first, then for understanding, then for notes;
  [keshav2007] budgets the three passes by minutes and hours and expects most
  papers to be dropped after the first. We use Keshav's budget for screening
  and Carey's depth for the papers that reach full-text assessment.
- Where structure comes from: [webster-watson2002] derives it from a concept
  matrix built before writing, while [pautasso2013] suggests it emerges from
  notes taken during reading and from a conceptual diagram. We take the
  concept matrix as the required artifact and the diagram as an optional aid.

## Not covered

- None of these sources says how to search or cite preprints, or how to treat a
  preprint that was later published in changed form.
- None of them covers retractions, expressions of concern or corrections as a
  screening step, nor how to check a bibliography against a registry.
- Machine-assisted screening, embedding search and agent-run literature search
  are outside all of these sources; the reliability of a tool that ranks by
  semantic similarity rather than a Boolean string is untested here, and its
  output is treated as a candidate list to be screened, never as a result.
- Reference-manager mechanics, BibTeX hygiene and identifier resolution are not
  addressed; we cover those in the skill's own reference.
- Deduplication across databases is named but not specified; we do not have a
  source for how to decide that two records are the same work.
- None of them gives a rule for when a review is out of date and needs to be
  redone rather than updated.
