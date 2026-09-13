# Submission checklist

Filled per manuscript before every submission and resubmission. Each item is
answered with a pointer (section, file, identifier) or with "no" and a reason;
an empty cell means not ready. Items marked lint are also checked by
`scripts/paper_lint.py`; items marked cite by `scripts/cite_check.py`. The
rules behind each item are in `references/reporting-standards.md`,
`references/paper-writing.md` and `references/figures.md`.

## Structure (lint)

| Item | Pointer or reason |
| --- | --- |
| Title states the contribution | |
| Abstract: context, gap, approach, result with a number, implication; no citations; within the venue's word limit | |
| Introduction ends with the contribution paragraph | |
| Results subsections or figure titles are statements | |
| Discussion opens with the findings, gives each limitation a paragraph, ends with what the work enables | |
| Every figure and table referenced; every reference resolves | |
| Acronyms defined at first use | |
| No em-dashes, no meta phrases, sentence-case headings unless the template forbids | |

## Figures (storyboard)

| Item | Pointer or reason |
| --- | --- |
| Every figure regenerates from a script and a data file in the repository | |
| Small-sample continuous data shown as points; bars only for counts and categories | |
| Axes, units, n and the meaning of error bars in every caption | |
| No truncated axes without a marked break; no pie or 3-D charts; no rainbow colormaps | |
| Figure files meet the venue's format, resolution and width rules | |

## References (cite)

| Item | Pointer or reason |
| --- | --- |
| Every entry verified against Crossref or PubMed (title, year, first author) | |
| No retracted works cited as evidence | |
| No orphan entries, no undefined keys | |
| Datasets, models and tools cited to their original paper with version and license | |
| Web sources carry an access date | |

## Statements

| Item | Pointer or reason |
| --- | --- |
| Author contributions in CRediT roles; all authors meet the ICMJE criteria | |
| Author order statement where the venue asks for one | |
| Data availability with a persistent identifier for a versioned deposit | |
| Code availability with repository and archived release DOI (Zenodo or equivalent) | |
| Competing interests | |
| Funding with grant numbers | |
| Ethics approval and consent basis for human or animal data | |
| Disclosure of AI-assisted writing or analysis where the venue asks (written by Robert) | |

## Field checklists

| Item | Pointer or reason |
| --- | --- |
| Machine learning claims: NeurIPS checklist items on claims, limitations, reproducibility, experimental details, statistical significance, compute, assets answered in the plan | |
| Supervised ML on biological data: DOME table in the supplement | |
| Ontology paper: MIRO must-level items covered; ontology has a dereferenceable IRI, license and versioned release | |
| Software paper: usage examples out of the main text; versioned release with DOI cited; software management plan in the repository | |

## Process

| Item | Pointer or reason |
| --- | --- |
| Outside read completed (name, date) | |
| Every coauthor confirmed contributions and approved this version (date, source) | |
| Venue's guide to authors read; template, page limit and file formats met | |
| Cover letter drafted; suggested reviewers listed if requested | |
| Preprint posted or deliberately withheld (reason) | |
| Approval bead for the submission opened for Robert | |
