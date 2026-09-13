---
topic: fair4rs-and-joss
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# FAIR for research software and JOSS-style release expectations

Sources
- fair4rs2022 (CC-BY-4.0; short excerpts allowed)
- joss-review-checklist (CC-BY-4.0; short excerpts allowed)
- joss-review-criteria (CC-BY-4.0; short excerpts allowed)
- joss-docs (CC-BY-4.0; short excerpts allowed)
- jimenez2017 (CC-BY-4.0; short excerpts allowed)
- citation-file-format (CC-BY-4.0; short excerpts allowed)
- smith2016-software-citation (CC-BY-4.0; not fetched, summarised from knowledge)

## What the evidence says

### FAIR4RS: what changes when FAIR is applied to software

- The FAIR4RS working group applied the FAIR data principles to research software by "treating software and data as similar digital research objects", so many principles carry over directly [fair4rs2022].
- Three properties of software forced revisions: it is executable, it is composite (built from and depending on other software), and it evolves continuously through versions [fair4rs2022].
- The principles were produced by a joint RDA, FORCE11 and ReSA working group after community consultation starting in 2019, and the RDA Software Source Code Interest Group maintains them [fair4rs2022].
- Findable principles (from knowledge of the document, not verified against the fetched text, which holds only the abstract): F1, software has a globally unique and persistent identifier; F1.1, components at different granularity get distinct identifiers; F1.2, different versions get distinct identifiers; F2, software is described with rich metadata; F3, metadata explicitly include the identifier of the software they describe; F4, metadata are FAIR, searchable and indexable [fair4rs2022].
- Accessible principles (from knowledge, not verified): A1, software is retrievable by its identifier over a standardized protocol; A1.1, the protocol is open, free and universally implementable; A1.2, it allows authentication and authorization where necessary; A2, metadata stay accessible even when the software itself is no longer available [fair4rs2022].
- Interoperable principles (from knowledge, not verified): I1, software reads, writes and exchanges data in ways that meet domain community standards; I2, software includes qualified references to other objects [fair4rs2022].
- Reusable principles (from knowledge, not verified): R1, software is described with many accurate and relevant attributes; R1.1, it has a clear and accessible license; R1.2, it is associated with detailed provenance; R2, it includes qualified references to other software (its dependencies); R3, it meets domain community standards [fair4rs2022].
- The reusable group differs most from FAIR for data: R2 on dependencies has no data counterpart, and the definition of reusable covers both running the software and understanding, modifying and building on it (from knowledge, not verified) [fair4rs2022].
- Jimenez and colleagues, writing before FAIR4RS, already mapped their open-source recommendations onto the FAIR data principles: registry metadata serves findability, public code serves accessibility, and a license serves reusability [jimenez2017].
- The same authors point out one deliberate divergence: FAIR accessibility admits restricted access (for privacy), whereas for software no such reason applies, so they direct toward full openness [jimenez2017].

### Jimenez's four recommendations

- The recommendations do not propose new practices; they are simple, monitorable rules that push developers toward existing best practices (version control, testing, documentation, citation) [jimenez2017].
- Recommendation 1: develop in a publicly accessible, version-controlled repository from the start of the project; "The longer a project is run in a closed manner, the harder it is to open it later" [jimenez2017].
- Opening code from day one gives a public record of contributions, invites scrutiny and contributions, and lets others reproduce results made with any prior version [jimenez2017].
- Recommendation 2: register software metadata (code location, contributors, license, version, identifier, references, how to cite) in a popular community registry such as bio.tools or DataCite, which exposes it in machine-readable form [jimenez2017].
- Recommendation 3: adopt an OSI-approved open-source license unless the institution requires otherwise, state it in the public repository, and comply with the licenses of all third-party dependencies; disclose known patents [jimenez2017].
- Code with no license cannot legally be used at all in some jurisdictions [jimenez2017].
- Recommendation 4: open source does not require collaborative development, but the project must state how contributions are made and accepted, who decides, and which communication channels exist [jimenez2017].
- The audience is funders, institutions, journals and group leaders as much as developers: the recommendations are meant to be adopted as policy and monitored [jimenez2017].
- Adoption is staged: endorsement (agree in principle), promotion (publicize and reward), then compliance (implement, monitor and report) [jimenez2017].
- Software is defined broadly: command-line tools, graphical applications, web services, APIs and the infrastructure scripts that run services all fall under the recommendations [jimenez2017].

### JOSS: what a submission must have

- JOSS is a peer-reviewed journal for research software; acceptance mints a CrossRef DOI for the short paper [joss-docs].
- The author guide has sections on what counts as research software, scope and significance, pre-review screening criteria (must-meet gates and positive signals), an AI usage policy, and a note on web-based software; editors have a template for rejection on failing the substantial scholarly effort test [joss-docs].
- The paper itself is short: authors and affiliations, a summary for non-specialists, a statement of need, a comparison with other packages, mentions of research using the software, and key references including a link to the software archive; API documentation belongs in the repository, not the paper [joss-review-criteria].
- The repository must be hosted where outsiders can freely open issues and propose changes; hosts that require approved or paid accounts are not accepted [joss-review-criteria].
- Software that re-implements a solved problem is acceptable if it meets the criteria and cites the prior work; reviewers are asked to point out relevant published work that is not yet cited [joss-review-criteria].
- Signals of scholarly significance include published research using the software, adoption by other groups, integration into established pipelines, demonstrated performance gains over alternatives, and clear potential for reuse; the scope decision rests with the editors [joss-review-criteria].
- Software built in a proprietary language or environment is acceptable if the reviewer can still install it and verify functionality [joss-review-criteria].
- Software developed privately first can still qualify if it has been public with demonstrated use for at least six months [joss-review-criteria].
- Reviews are checklist-driven and a review is incomplete until every box is checked [joss-review-checklist].

### JOSS: the reviewer checklist items

- General checks: source at the stated repository URL; a plain-text LICENSE with an OSI-approved license; the submitting author made major contributions and the author list is complete; clear research impact or credible significance [joss-review-checklist].
- License: an actual file is required. "Not acceptable: A phrase such as 'MIT license' in a README file" [joss-review-criteria].
- Development history: sustained development over months or years rather than a recent burst; at least six months of public history with releases, issues or pull requests; contributions from several developers or other evidence of community engagement [joss-review-checklist, joss-review-criteria].
- Good practices: license, documentation, tests or verification, releases, and clear contribution and support pathways; a repository missing critical elements or looking like a one-time code dump is not acceptable [joss-review-criteria].
- Functionality: the reviewer installs the software following the documentation and confirms the functional and any performance claims [joss-review-checklist, joss-review-criteria].
- Documentation: a statement of need (problem, audience, relation to other work); installation instructions with dependencies handled by an automated procedure, ideally a package manager (Python packages pip-installable); example usage on real problems; API documentation of core functionality; community guidelines for contributing, reporting issues and seeking support [joss-review-checklist, joss-review-criteria].
- The installation bar scales with the language ecosystem: a Fortran project with a Makefile can pass where a Python project is expected to be pip-installable; unclear dependencies or a manual install fail in any language [joss-review-criteria].
- API documentation grades: all functions documented with example inputs and outputs is "Good", core API documented is "OK", an undocumented API is not acceptable; the judgment is left largely to the reviewer [joss-review-criteria].
- Tests: an automated suite on continuous integration is "Good"; documented manual steps with sample inputs are "OK"; no way to verify is not acceptable [joss-review-criteria].
- Paper sections now required: summary, statement of need, state of the field with a build-versus-contribute justification, software design with trade-offs, research impact statement with concrete evidence, and an AI usage disclosure (an explicit "none" counts); plus writing quality and complete references citing papers, data and software [joss-review-checklist, joss-review-criteria].
- Authorship: purely financial contributions do not qualify; the reviewer only checks that the list looks reasonable and raises questions if not [joss-review-criteria].
- Reviewers grade Accept, Minor Revisions or Major Revisions; JOSS does not reject for needing major revisions, but development-history failures can trigger desk rejection before review [joss-review-criteria].

### Citation metadata: CFF and software citation principles

- CITATION.cff is a plain-text file, readable by humans and machines, that tells others how to cite software or a dataset [citation-file-format].
- The minimal example holds cff-version, a message, authors (family and given names, ORCID), title, version, a DOI under identifiers, and date-released [citation-file-format].
- The file answers questions a citer cannot answer alone: the software's real name, the label of the version used, and who counts as an author; "Software and datasets have no title page, the relevant information is often less obvious" [citation-file-format].
- GitHub renders a CITATION.cff on the default branch as a citation box with BibTeX; Zenodo uses it to fill the record when a GitHub release is archived; Zotero imports it [citation-file-format].
- CFF can also list the references the software builds on, and the cffconvert tool converts to BibTeX, RIS and CodeMeta; cffinit is a form for creating a file [citation-file-format].
- Archives and registries can reuse the citation metadata from the file, so one authoritative CITATION.cff avoids diverging author lists across GitHub, Zenodo and reference managers [citation-file-format].
- The FORCE11 software citation principles (from knowledge of the source, not verified against the text) are: importance (software is a legitimate, citable product), credit and attribution, unique identification (a machine-actionable, globally unique persistent identifier), persistence (identifier and metadata outlive the software), accessibility (metadata and, where possible, the software itself are accessible), and specificity (cite the exact version used) [smith2016-software-citation].
- These principles motivate per-version DOIs and a citation file in the repository: specificity needs a version identifier, and credit needs an authoritative author list (from knowledge of the source) [smith2016-software-citation].

## Rules we adopt

Each rule is an audit check for the code-audit skill and a release step for the software-release skill. The artifact checked is named first. Enforcement: the audit script where the check is mechanical, Robert otherwise.

1. LICENSE: the repository root holds a plain-text LICENSE or COPYING file containing the full text of an OSI-approved license; a license name in the README alone fails (from [joss-review-criteria], [joss-review-checklist], [jimenez2017], [fair4rs2022]).
2. Dependency manifest: every third-party dependency is declared with a version constraint in the language's package file, and its license is compatible with ours; the audit lists any dependency whose license is unknown (from [jimenez2017], [fair4rs2022]).
3. Repository: the code is public on a host where anyone can open issues and pull requests, from the first commit, not just at paper time (from [jimenez2017], [joss-review-criteria]).
4. CITATION.cff: the root holds a valid CITATION.cff with cff-version, title, authors with ORCIDs, version, a DOI identifier and date-released; the version and DOI match the latest release (from [citation-file-format], [smith2016-software-citation]).
5. Release with DOI: every release is a git tag with a semantic version, archived so that each version has its own DOI (Zenodo via the GitHub integration), and the archive DOI is linked from the README (from [fair4rs2022], [smith2016-software-citation], [citation-file-format]).
6. README statement of need: the README opens with what problem the software solves, for whom, and how it relates to existing tools (from [joss-review-criteria], [joss-review-checklist]).
7. README installation: installation is one package-manager command (pip, conda, cargo, npm or equivalent) or a documented script; the audit runs it in a clean environment and fails if it does not complete (from [joss-review-criteria], [joss-review-checklist]).
8. README example usage: at least one worked example with real input and expected output, runnable as written (from [joss-review-checklist], [joss-review-criteria]).
9. API documentation: every public function, class or command has a docstring or help text; core functionality has rendered documentation with inputs and outputs (from [joss-review-criteria]).
10. Tests and CI: an automated test suite covers the core functionality and runs on every push in continuous integration; the audit fails if there is no test directory or no CI configuration (from [joss-review-criteria], [joss-review-checklist]).
11. CONTRIBUTING and support: a CONTRIBUTING file or README section states how to contribute, how to report issues, where to ask for support, and who makes decisions; the issue tracker is enabled (from [joss-review-checklist], [jimenez2017]).
12. Registry metadata: when a domain registry exists (bio.tools for life science tools, the language package index otherwise), the software is registered there with license, version, identifier and citation, and the entry matches CITATION.cff (from [jimenez2017], [fair4rs2022]).
13. Standard formats: inputs and outputs use community standard formats where they exist (OBO or OWL for ontologies, FASTA, VCF, JSON-LD) and the README names them (from [fair4rs2022]).
14. Development history before a JOSS submission: the repository shows at least six months of public commits, at least one tagged release, and public issues or pull requests; if the history is a single burst, delay submission rather than submit (from [joss-review-criteria], [joss-review-checklist]).
15. JOSS paper: paper.md holds the required sections (summary, statement of need, state of the field, software design, research impact statement, AI usage disclosure) and a bibliography that cites the software archive and every tool compared against; the submitting author is a major committer and the author list follows the group's authorship rule (from [joss-review-criteria], [joss-review-checklist], [joss-docs]).

## Where sources disagree

- Which license counts: FAIR4RS R1.1 asks only for a clear and accessible license (from knowledge) [fair4rs2022]; Jimenez advises an OSI-approved license unless the institution requires otherwise [jimenez2017]; JOSS requires an OSI-approved license file with no exceptions [joss-review-criteria]. We follow JOSS because the check is mechanical and JOSS is the venue we target; a non-OSI license needs Robert's sign-off and blocks JOSS submission.
- Openness versus controlled access: FAIR for data and FAIR4RS A1.2 allow authentication where necessary (from knowledge) [fair4rs2022], while Jimenez argues software has no privacy reason for restricted access and should be public from day one [jimenez2017]. We follow Jimenez for code; only data with human-subject restrictions stays controlled, and the code that processes it is still public.
- Tests: JOSS accepts documented manual verification steps as "OK" [joss-review-criteria]; FAIR4RS says nothing about tests [fair4rs2022]. We require automated tests in CI (rule 10) because manual steps rot and an audit cannot rerun them.
- Where citation metadata lives: Jimenez puts metadata in a community registry [jimenez2017]; CFF puts it in a file in the repository [citation-file-format]. We require the file (it travels with the code and feeds Zenodo and GitHub) and treat the registry as an additional step when a domain registry exists.
- Collaboration: Jimenez states open source does not require collaborative development [jimenez2017]; current JOSS criteria treat a single author with no external engagement as not acceptable [joss-review-criteria]. We do not require multiple committers for the audit, but the release skill flags a single-author repository as a JOSS risk and asks for evidence of external use in the paper.

## Not covered

- How to score partial compliance: the sources give pass or fail (JOSS) or principles without metrics (FAIR4RS), so the audit's weighting of findings is our choice.
- FAIR4RS says how software should be described but not how to test that it runs years later; containerization, environment lock files and archived dependencies are outside these sources.
- None of the sources says how to handle software whose dependencies are unlicensed or license-incompatible beyond "comply"; the remediation path (replace, vendor, ask the author) is left to judgment.
- Authorship order and the threshold for co-authorship on a software paper are explicitly left to the authors by JOSS; the group's authorship rule lives elsewhere.
- The sources do not cover data or model releases (trained weights, embeddings) that accompany software; the release skill needs a separate source for those.
- Long-term maintenance after publication (deprecation, handover when a student leaves) is not addressed.
- The fetched FAIR4RS text is the abstract only; the principle wording above comes from knowledge and should be checked against the PDF before the audit cites individual principle numbers.
