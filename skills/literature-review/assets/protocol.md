# Review protocol: <short title>

Written before the first search. Nothing below is changed after searching; a
change is appended as a dated amendment with its reason.

- Review type: narrative | scoping | systematized | systematic | rapid | umbrella
- Written by: <name>, <date>
- Log: `runs/<id>/search.jsonl`
- Synthesis matrix: `runs/<id>/matrix.md`
- Bibliography: `runs/<id>/refs.bib`

## Question

One sentence. Then the concept blocks it decomposes into.

| Block | Concept | Synonyms and controlled vocabulary |
| --- | --- | --- |
| P | <population, task or data> | |
| I | <method or intervention> | |
| C | <comparison, if any> | |
| O | <outcome or metric> | |
| C | <context, venue, field> | |

## Inclusion criteria

1. <criterion>
2. <criterion>

## Exclusion criteria and reason codes

Every exclusion at either stage uses one of these codes. Codes are declared in
the log with `search_log.py add-code` before they are used.

| Code | Stage | Meaning |
| --- | --- | --- |
| E1 | both | not about the review topic |
| E2 | both | wrong publication type (editorial, abstract, poster) |
| E3 | both | outside the date or language limits |
| E4 | full-text | no method or no results reported |
| E5 | full-text | duplicate report of an already included study |
| E6 | full-text | full text not in a language we read |

## Sources to search

| Source | Interface | Planned string | Filters |
| --- | --- | --- | --- |
| PubMed | web | | |
| Scopus or Web of Science | | | |
| DBLP or arXiv | | | |
| Other methods | citation chasing, hand search, Paperclip | | |

## Screening

- Stage 1 on title and abstract, stage 2 on full text.
- Second screener on <all | a sample of N> records; disagreements resolved by <who>.

## Extraction fields

<field, field, field>: the columns of the synthesis matrix.

## Appraisal

Which checklist, and whether quality is used to weight or to exclude. If to
exclude, the threshold is stated here, before any paper is read.

## Synthesis

Narrative | tabular | thematic | framework | statistical, and why.

## Amendments

| Date | Change | Reason |
| --- | --- | --- |
