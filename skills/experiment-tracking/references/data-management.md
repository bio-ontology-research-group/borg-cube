---
topic: data-management
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Data management

Sources
- hart2016 (CC-BY-4.0 per the manifest; the PLOS article itself carries a CC0 dedication, so excerpts are allowed either way)
- michener2015 (CC-BY-4.0; short excerpts allowed)
- goodman2014 (CC-BY-4.0; short excerpts allowed)
- rule2019 (CC-BY-4.0; short excerpts allowed)
- sandve2013 (CC-BY-4.0; short excerpts allowed)
- gebru2021-datasheets (proprietary; summary only, no quotes)

## What the evidence says

### Decide the shape of the data before collecting it

- Most of the trouble met during analysis, management and release is avoidable by answering a few questions before acquisition starts: how the raw data arrives, what format the analysis software expects, whether a community standard format exists for this data type, and how much data will accumulate over what period [hart2016].
- The use case has to be settled just as early: whether raw data will be archived, whether the analysis input is prepared once or regenerated each time, whether manual corrections can be replaced by programmatic ones, how changes to the data will be tracked and where that log lives, what will be released and in what format, what privacy restrictions apply, whether institutional validation is needed before release, and what the funder and the target journal mandate [hart2016].
- Storage volume must be estimated for both the analysis phase and the archive. A few megabytes can be managed locally with a simple plan; gigabytes to petabytes require planning and preparation [hart2016].
- Metadata planning belongs at the start: what will be collected, how it will be maintained, where it will be stored [hart2016].
- Every part of a data management plan depends on knowing the types, sources, volume and formats of the data. Sponsors often define data broadly enough to include software, code, physical collections and curriculum materials [michener2015].
- When the types, sources, volume and formats cannot be known in advance, the answer is to update the plan iteratively rather than to leave it vague [michener2015].

### Keep raw data raw

- Processing algorithms improve and compute gets cheaper, so access to unprocessed data enables analyses that were impossible when the work was first done. If only derived data survives, others cannot confirm results, assess the statistical models, or compare findings across studies [hart2016].
- What counts as sufficiently raw is not always clear, but data should be stored as close to its original state as possible, and any derivation should be documented by archiving the code and the intermediate datasets alongside [hart2016].
- Generate a cryptographic hash of the raw data and distribute it with the data. Hashes catch silent corruption or manipulation during storage and transfer, and for large enough datasets silent corruption is likely [hart2016].
- SHA-2 is preferred to MD5, which is no longer secure; every hashing algorithm remains vulnerable to brute force [hart2016].
- Rule et al. and Sandve et al. both treat the ability to regenerate derived data from raw data plus recorded code as the property that makes a result inspectable at all [rule2019, sandve2013].

### Formats, structure and identifiers

- Archive in formats with freely available specifications, so that access never requires proprietary software, hardware or a paid license. Proprietary formats change, their vendors fail, and license fees make old data unaffordable to read [hart2016].
- Open formats named as examples are CSV for tables, HDF and NetCDF for hierarchical scientific data, PNG for images, KML or another OGC format for spatial data, and XML for documents; DWG, PSD, WMA and XLS are named as closed ones. Even when daily work uses a closed format, the archived copy is converted [hart2016].
- Open is not sufficient: the format also has to be machine-processable. A table inside a PDF or a scanned image of a table meets neither test [hart2016].
- Structure data so that each variable is a column, each observation a row and each type of observational unit its own table. This reduces duplication and makes subsetting and summarising straightforward [hart2016].
- Map variable names onto an existing community standard where one exists, because clearly defined terms let one dataset be joined and reused across institutions and disciplines [hart2016].
- Michener recommends nonproprietary formats based on open standards and widely used in the field, giving CSV over Excel as the example, and adds that uncompressed, unencrypted files with standard character encodings survive longest [michener2015].
- Data used in a publication should carry a unique persistent identifier, a DOI, ARK or PURL; several services issue them [hart2016].
- Datasets evolve, so each version needs a distinct name carrying a version identifier. ISO 8601 date stamps (YYYY-MM-DD) avoid regional ambiguity, and semantic versioning of the form major.minor.patch is the richer option: a major bump means an analysis written for the previous version may no longer run, a minor bump means it still runs, a patch fixes a typo or a bug [hart2016].
- Goodman et al. argue that the safest way to release data with a long-term guarantee is deposit in the archive that is the standard destination for the field, because a trustworthy archive assigns an identifier, requires documentation and metadata, and curates the deposit; most URLs published in papers stop working within a few years [goodman2014].

### Metadata, provenance and documentation

- Metadata is the contextual information required to interpret data. It should be comprehensive, follow the standards of the discipline, be machine readable, and travel with the data wherever it is stored [hart2016].
- How to attach metadata depends on the format: XML or JSON sidecars for text data, embedded metadata for self-documenting formats such as NetCDF and HDF5, labelled and linked tables plus a schema in a relational database, and for flat files a versioned compressed archive that contains the metadata [hart2016].
- Michener's documentation strategy has three steps: identify what a researcher like you would need to discover, access, interpret, use and cite the data; adopt a community metadata standard if one exists, often the one the target repository recommends; and pick tools to create and manage the metadata, falling back to a `readme.txt` header when no tool fits [michener2015].
- Rows and columns of numbers mean nothing undocumented, and the utility and longevity of a dataset track how complete its metadata is [michener2015].
- A named person should maintain an electronic lab notebook holding all project details, reviewed and revised by another team member and duplicated; the metadata recorded there is the basis for the metadata that ships with the data products [michener2015].
- Provenance in the W3C sense is the sum of the processes, agents and documents that produced a piece of information. Perfect provenance is rarely achieved, and the higher its quality the higher the chance the data can be reused [goodman2014].
- Data can be reused when three things are present together: the data, the metadata describing it, and information about the process that generated it, such as the code [goodman2014].
- Decide the level of reuse being aimed at and plan accordingly: full reproducibility needs working pipeline code, a platform to run it on and verifiable versions of the data; inspectability may be satisfied by intermediate products and pseudocode; wide usability argues for standard formats and metadata standards from the start. The minimum in all three cases is careful tracking of versions of data and code with their dates [goodman2014].
- Publish the workflow as context, at minimum a sketch of how data flows across the software and how intermediate and final products are generated. Even when the data comes from a well documented archive, document the query that produced the extract and every operation applied afterwards [goodman2014].
- Publish the code that produced the data even when it is short or ugly, because in many cases the best documentation of a dataset's provenance is the software that generated it [goodman2014].
- Gebru et al. make the same argument at dataset level: a datasheet records why the dataset was created, who created and funded it, how instances were acquired and by whom, over what timeframe, what preprocessing was applied, whether raw data was kept, and who maintains the dataset and how it will be updated [gebru2021-datasheets].

### Storage, backup and preservation

- Every storage medium fails and every failure can lose data, so back up at all stages of the research process and use more than one backup system. The recommended layout is two on-site copies and one off-site copy, with the off-site copy as secure as the on-site ones [hart2016].
- Test backups regularly. The named failure modes are faulty backup software, misconfiguration such as skipped subdirectories, encryption whose password was lost, and media errors [hart2016].
- Michener's version of the same rule is at least three copies in at least two geographically distributed locations, on a regular duplication schedule, with the schedule including tests that stored files can actually be retrieved [michener2015].
- Preservation asks three separate questions: how long the data must stay accessible, how it is stored and protected during the project, and how it is preserved and made available afterwards. Not all data must be retained, and not forever: unrepeatable observations may need indefinite storage while easily repeated experiments need little, and a simulation may need only source code, initial conditions and verification data [michener2015].
- Assuming a personal computer and a project website will live forever is the common mistake of inexperienced and experienced researchers alike [michener2015].
- The storage method follows the data volume, the cost of storage and access over time, transfer time, intended use and privacy. For large data the cost of retrieving from commercial cloud storage can exceed the cost of regenerating the data [hart2016].
- When data is too big or slow to move, analyze it in place, push computation into the database, or use a large-memory node; inactive data migrates to cheaper long-term storage that is slower to retrieve [hart2016].

### Privacy

- Datasets with privacy implications need a protection plan that considers all stakeholders: funders, human subjects, collaborators and yourself [hart2016].
- For small datasets, replacing identifying fields with a unique id that maps to sensitive data held in a separate external table is enough to anonymize a limited amount of personal information [hart2016].
- Hashing is not anonymization. Hart et al. cite the New York City taxi release, where a simple MD5 scheme over 173 million rides was undone within hours [hart2016].
- Ask a trusted colleague or a security specialist to try to break the anonymization before public release, because the person who produced the data is poorly placed to check their own procedure; better still, remove sensitive fields that the analysis does not need before distribution [hart2016].
- Some data is identifying by nature, human genomic data being the standard case, and there the mitigations are technical: storing differences against a reference, or bringing the computation to the data instead of moving the data [hart2016].
- A privacy plan has to exist before acquisition, because it determines and limits how the data may be stored [hart2016].
- Michener adds the policy layer: licensing of pre-existing material, plans for retaining, licensing, sharing and embargoing data and code, and the legal and ethical restrictions on human subject and other sensitive data, with the institutional review board consulted before the work starts [michener2015].
- Gebru et al. ask dataset creators to record whether individuals were notified, whether they consented, whether consent can be revoked, and whether an impact analysis was run, and to treat any dataset containing text written by people as relating to people [gebru2021-datasheets].

### Sharing, credit and roles

- Michener recommends making data available with the fewest possible restrictions at publication or project completion, through a repository, a journal supplement or a data paper, rather than by mail on request [michener2015].
- Standard waivers and licenses such as those from Creative Commons and Open Data Commons should be preferred; nonstandard licenses and waivers are a significant barrier to reuse [michener2015].
- A data management plan names the individuals and organizations responsible for collection, entry, quality control, metadata, backup, submission to an archive and systems administration, with time allocations and required expertise [michener2015].
- Goodman et al. ask authors to state explicitly how they want to be credited for data and code, in the paper or the metadata, and to cite the sources of data they use in the preferred format [goodman2014].
- Quality assurance and quality control measures belong in the plan: training, instrument calibration and verification, double-blind entry, and statistical or graphical error detection, where simple scatterplots and maps are invaluable for spotting anomalies [michener2015].
- Sponsor requirements differ sharply between funders and even between divisions of one funder, so the current call and the sponsor's site are checked each time rather than a previous plan reused [michener2015].

## Rules we adopt

1. Raw data is immutable. It is written once, hashed with SHA-256, and never edited in place; every derived product is regenerated from raw data by recorded code (from [hart2016], [sandve2013]).
2. Every dataset we depend on has a version: a content hash for a file, or an explicit version string or ISO 8601 date stamp for a directory, snapshot or database extract. A path alone is not a data version (from [hart2016]).
3. Bump the major version of an internal dataset when an analysis written for the previous version would break, the minor version when it would still run, and the patch version for fixes (from [hart2016]).
4. Archive in open, machine-readable formats: CSV or Parquet for tables, HDF5 or NetCDF for arrays, PNG or SVG for images, plain text or JSON for metadata. Convert closed working formats before archiving (from [hart2016], [michener2015]).
5. Metadata travels with the data. Every dataset directory carries a README or sidecar recording what the data is, where it came from, how it was processed, who to ask, and the license (from [hart2016], [michener2015]).
6. Three copies in at least two locations, one off-site, with a restore tested on a schedule. A backup that has never been restored is not a backup (from [hart2016], [michener2015]).
7. Record the archive query and every operation applied afterwards whenever data is extracted from a public resource, so the extract can be reconstructed (from [goodman2014]).
8. Publish the code that produced a dataset alongside the dataset, however small it is (from [goodman2014]).
9. Deposit released data in the standard repository for the field, or a general repository when none exists, and get a persistent identifier. A project website is not a data archive (from [goodman2014], [hart2016]).
10. Every dataset we create ships with a datasheet covering motivation, composition, collection, preprocessing, uses, distribution and maintenance (from [gebru2021-datasheets]).
11. Data about people is local-only. Remove fields the analysis does not need before any distribution, never treat hashing as anonymization, and have someone other than the producer attempt to break the anonymization first (from [hart2016]).
12. The privacy class, license and retention period are settled before collection starts, not at submission (from [hart2016], [michener2015]).
13. A data management plan names a responsible person per task and is revised when the data turns out different from the plan (from [michener2015]).
14. Audits and briefings report paths, sizes, hashes and counts. They never carry data content (from [hart2016], and the repository privacy rules).

## Where sources disagree

- Number of copies: [hart2016] says two on-site plus one off-site, [michener2015] says at least three copies across at least two geographically separated locations. The difference is emphasis rather than substance; we follow Michener because geographic separation is the property that matters for the office workstation.
- Hashing: [hart2016] recommends a cryptographic hash for integrity in Rule 3 and warns in Rule 8 that hashing does not anonymize. We treat these as two distinct uses and never let an integrity hash stand in for de-identification.
- What must be archived: [hart2016] presses for raw data whenever technically possible, while [michener2015] accepts that easily repeatable experiments need only short retention and that a simulation may need only code, initial conditions and verification data. We follow Michener for simulation inputs we can regenerate deterministically and Hart for anything measured.
- Where documentation lives: [michener2015] centres an electronic lab notebook maintained by a named person, [goodman2014] centres provenance attached to the deposited data and code. We do both, with the notebook as the working record and the metadata sidecar as the artifact that ships.

## Not covered

- None of these sources gives concrete guidance for KAUST-specific storage tiers (IBEX scratch, DataWaha, encrypted volumes) or the transfer rules between them.
- Sequencing-scale and imaging-scale cost models are only sketched; there is no evidence here on when hashing or checksumming a multi-terabyte input stops being worthwhile.
- Retention obligations under Saudi or EU law, and KAUST's own contractual obligations for collaborator data, are outside every source listed.
- No source covers data management for knowledge graphs and ontologies specifically, where versioning is by release artifact and IRI rather than by file.
- How to version data that lives only inside a running service (a database an application writes to continuously) is not addressed.
