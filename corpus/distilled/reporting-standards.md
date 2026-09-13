---
topic: reporting-standards
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Reporting standards and submission statements

Sources
- icmje (proprietary web recommendations; summary only; the fetched page holds navigation only, claims from knowledge of the text)
- credit (CC-BY-4.0; role list fetched 2026-09-02)
- neurips-checklist (proprietary web page; summary only; fetched 2026-09-02)
- miro2018 (CC-BY-4.0; the fetch returned a JavaScript notice only, claims from knowledge of the paper)
- dome2021 (proprietary; summary only, from knowledge, not fetched)
- frassl2018 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- romano2020 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- zobel-writing-for-computer-science (book, proprietary; cite only, ideas from corpus/notes/zobel-writing-for-computer-science.md)

This topic covers what a manuscript must declare beyond its argument:
contributions, data and code availability, competing interests, funding,
limitations, and the field checklists that apply to machine learning in
biology and to ontologies. It feeds the submission checklist.

## What the evidence says

### Authorship, contributions and disclosures

- ICMJE authorship requires all four criteria (substantial contribution; drafting or critical revision; final approval; accountability for the whole work); all who meet them are authors and all authors must meet them; other contributors are acknowledged with their contribution named (from knowledge of the recommendations) [icmje].
- ICMJE asks every author to disclose financial and non-financial relationships and activities that could be seen as influencing the work, using the ICMJE disclosure form, and asks journals to publish funding sources and the funder's role (from knowledge of the recommendations) [icmje].
- ICMJE asks that manuscripts declare ethics approval and consent for work with human participants or animals, follow the applicable reporting guideline (CONSORT, STROBE, PRISMA and others listed on the EQUATOR network), and register clinical trials before enrollment (from knowledge of the recommendations) [icmje].
- ICMJE's 2023 and later updates ask authors to disclose any use of AI-assisted technology in writing or analysis in the methods or acknowledgments, and state that such tools cannot be authors because they cannot be accountable (from knowledge of the recommendations) [icmje].
- CRediT provides 14 roles: conceptualization, data curation, formal analysis, funding acquisition, investigation, methodology, project administration, resources, software, supervision, validation, visualization, writing original draft, writing review and editing; it complements authorship rather than replacing it and supports research assessment and accountability [credit].
- Frassl and colleagues ask for an author-order statement and attribution statements, and for all coauthors to confirm contributions and approve the text before each submission [frassl2018].

### Machine learning claims: the conference checklist

- The NeurIPS checklist is mandatory and published with the paper; each item is answered yes, no or n/a with a justification pointing to the section that supports it; a justified no is acceptable and is not by itself grounds for rejection [neurips-checklist].
- Claims: the abstract and introduction must reflect the contributions and scope, including assumptions and limitations; aspirational goals may motivate but must be marked as not attained [neurips-checklist].
- Limitations: a separate limitations section is encouraged; state strong assumptions, how robust results are to their violation, the scope of the claims (few datasets, few runs) and the factors that affect performance [neurips-checklist].
- Reproducibility: every submission must give some avenue to reproduce the main results; for an algorithm, enough to reimplement; for an architecture, a full description; for a model, access or a way to rebuild it [neurips-checklist].
- Code and data: include code, data and instructions with the exact command and environment for the main results, method and baselines alike; state which experiments are reproducible if not all; anonymize at submission [neurips-checklist].
- Experimental details: data splits, hyperparameters and how they were chosen; the important details in the main paper, the rest with the code or in an appendix [neurips-checklist].
- Statistical significance: report error bars, confidence intervals or tests at least for the experiments behind the main claims; say what variability they capture (splits, seeds), how they were computed, and whether they are standard deviation or standard error; do not draw symmetric bars that leave the valid range [neurips-checklist].
- Compute: state the hardware type, memory, execution time per run and total, and whether the full project used more compute than the reported experiments [neurips-checklist].
- Assets and licenses: cite the original paper for every dataset, model or code used, name its version and license, respect its terms; released assets carry documentation, license and consent information [neurips-checklist].
- Ethics: read the code of ethics; discuss negative societal impacts where a direct path exists; describe safeguards for high-misuse-risk releases; give instructions, screenshots and compensation for human-subject or crowdsourced work and state IRB approval [neurips-checklist].
- LLM usage: declare LLMs when they are an important or non-standard component of the method; use for writing or editing alone needs no declaration under this checklist [neurips-checklist].

### Supervised machine learning in biology: DOME

- DOME (data, optimization, model, evaluation) is a set of recommendations for reporting supervised machine learning in biology, framed as questions authors answer in a structured supplementary table (from knowledge of the paper) [dome2021].
- Data: source, size, splits, independence between training and test sets, redundancy reduction, class distribution and how negatives were obtained; optimization: algorithm, hyperparameters and how tuned, features and preprocessing, measures against overfitting; model: interpretability, availability, execution time; evaluation: metrics with confidence intervals, baselines and comparison methods, evaluation on independent data (from knowledge of the paper) [dome2021].

### Ontologies: MIRO

- MIRO (minimum information for the reporting of an ontology) lists what an ontology paper must state so that readers can assess and reuse the ontology: basics (name, owner, license, URL, repository), motivation (need, competition, target audience), scope and requirements, knowledge acquisition (sources, methods, experts), content (representation language, development environment, size, imports, reuse of other ontologies, axiom patterns, dereferenceable IRIs), management (sustainability, versioning, entity deprecation, community feedback), and quality assurance (testing, evaluation, examples of use) (from knowledge of the paper) [miro2018].
- MIRO assigns each item a level (must, should, optional) and was derived from a community survey of ontology developers and users (from knowledge of the paper) [miro2018].

### Software and data availability

- Romano and Moore: archive the software release described in the paper with a DOI (Zenodo for tagged GitHub releases, FigShare for data and scripts), link version-specific documentation, and state how to cite the software [romano2020].
- Romano and Moore: a software management plan answers who maintains the software after affiliations change, what hosting costs and who pays, who owns the intellectual property and under what license, whether updates will be provided, and how and when the software is archived [romano2020].
- Frassl and colleagues: the data management plan states how data and metadata will be deposited to meet the journal's open data requirement, with all data providers agreeing [frassl2018].
- Zobel: describe data, parameters and hardware so that others can repeat the work; report negative results; do not select favorable runs (from notes) [zobel-writing-for-computer-science].

## Rules we adopt

1. Every manuscript carries an author contributions statement in CRediT roles, a data availability statement, a code availability statement (or a combined availability statement where the venue uses one), a competing interests statement and a funding statement; the skill drafts them from the plan. Checked by `paper_lint.py` (presence) and the submission checklist. (from [icmje], [credit], [romano2020])
2. Data and code availability statements name a persistent identifier (DOI or accession) for a versioned deposit, not a bare URL; "available on request" needs a stated reason (privacy class, third-party license). Checked by the submission checklist; Robert decides exceptions. (from [romano2020], [frassl2018])
3. Any machine learning claim comes with the NeurIPS checklist items on claims, limitations, reproducibility, experimental details, statistical significance, compute and assets, answered in the plan even when the venue does not require the checklist. Checked by the submission checklist. (from [neurips-checklist])
4. Supervised machine learning on biological data fills a DOME table as a supplement. Checked by the submission checklist. (from [dome2021])
5. An ontology paper covers the MIRO must-level items, and the ontology has a dereferenceable IRI, a license and a versioned release before submission. Checked by the submission checklist; the ontology-review skill will check the artefact. (from [miro2018])
6. Error bars and intervals state what they are (SD, SE, CI), over what (seeds, splits, samples) and how computed, in the caption or the methods. Checked by the storyboard and Robert in review. (from [neurips-checklist])
7. Every dataset, model and tool used is cited to its original paper with version and license; every tool the group releases carries a license and a citation file. Checked by the submission checklist and the code-audit skill. (from [neurips-checklist], [romano2020])
8. Human-subject or patient data: the ethics approval and consent basis are stated in the methods, and the manuscript is privacy class local-only until Robert clears it. Robert enforces. (from [icmje], [neurips-checklist])
9. Use of AI tools in writing or analysis is disclosed where the venue requires it, and any such disclosure is written by Robert, never by the agent. Robert enforces. (from [icmje])
10. Before every submission and resubmission, each coauthor confirms their CRediT roles and approves the text; the skill prepares the request as an approval bead and Robert sends it. (from [frassl2018], [icmje])

## Where sources disagree

- Authorship for data or resource provision: ICMJE requires all four criteria, so provision alone does not qualify [icmje]; Frassl and colleagues report that groups differ and advise inclusiveness when in doubt [frassl2018]. We follow ICMJE and record the decision, with the CRediT role Resources, in the acknowledgments when authorship is not given.
- Whether "no" answers are acceptable: NeurIPS states a justified no is acceptable and not grounds for rejection [neurips-checklist]; MIRO marks some items as must (from knowledge) [miro2018]. We treat NeurIPS items as questions to answer in the plan and MIRO must-items as blockers for an ontology paper.
- LLM disclosure: NeurIPS does not require disclosing LLM use for writing [neurips-checklist]; ICMJE asks for disclosure of AI-assisted writing (from knowledge) [icmje]. We disclose where the venue asks and always let Robert write the disclosure.

## Not covered

- Clinical reporting guidelines (CONSORT, STROBE, PRISMA) in detail; ICMJE points to EQUATOR and the group rarely needs them.
- Journal-specific statement wording and placement; recorded per venue in `assets/venues.md`.
- Preregistration and registered reports for computational work.
- ICMJE, MIRO and DOME were not fetched as text; their claims here are from memory and need checking against the originals before a skill relies on them alone.
- What counts as sufficient anonymization at double-blind submission for a group whose tools are public on GitHub.
