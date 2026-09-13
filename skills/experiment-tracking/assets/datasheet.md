# Datasheet: <dataset name>, version <n>

Questions come from Gebru et al. 2021 (`references/experiment-tracking.md`),
grouped by stage of the dataset lifecycle. Answer as many as apply; a question
that cannot be answered is marked `unknown to the authors of this datasheet`
with the reason, never skipped silently and never guessed. Questions marked
`people` are answered only when the dataset relates to people, which includes
any dataset of text written by people.

- Datasheet written: <date>
- Datasheet written by: <name>
- Dataset version and identifier: <semantic version or date stamp, and DOI or path>
- Privacy class: <public | internal | local-only>

## Motivation

- For what purpose was the dataset created, and what gap does it fill?
- Who created it, and on behalf of which entity?
- Who funded the creation? Name the grant if there is one.

## Composition

- What do the instances represent, and are there several types of instance?
- How many instances are there, of each type?
- Is this all possible instances or a sample? If a sample, of what larger set, and how was representativeness checked?
- What does each instance consist of: raw data or extracted features?
- Is there a label or target per instance?
- Is any information missing from individual instances, and why?
- Are relationships between instances made explicit?
- Are there recommended splits, and what is the rationale?
- What errors, sources of noise or redundancies are known?
- Is the dataset self-contained, or does it rely on external resources that may change, disappear or carry their own restrictions?
- Does it contain confidential data?
- Does it contain data that could be offensive, insulting, threatening or distressing to view?
- people: Does it identify subpopulations, and what are their distributions?
- people: Can individuals be identified, directly or by combination with other data?
- people: Does it contain sensitive categories (race or ethnicity, sexual orientation, religion, politics, union membership, location, financial or health data, biometric or genetic data, government identifiers, criminal history)?

## Collection process

- How was the data for each instance acquired: directly observed, reported by subjects, or inferred? If reported or inferred, how was it validated?
- What mechanisms or procedures collected it, and how were they validated?
- If it is a sample of a larger set, what was the sampling strategy?
- Who was involved in collection, and how were they compensated?
- Over what timeframe was the data collected, and does that match the timeframe of the events it describes?
- Was there an ethical review, and what was the outcome?
- people: Was the data collected from individuals directly or obtained from third parties?
- people: Were individuals notified, and how?
- people: Did they consent, and to what exactly?
- people: Can consent be revoked, and by what mechanism?
- people: Has an impact analysis on data subjects been conducted?

## Preprocessing, cleaning and labeling

- What preprocessing, cleaning or labeling was done?
- Was the raw data kept alongside the processed data, and where?
- Is the software that did the processing available, and where?
- What is the hash or version of each processed artifact, and which run produced it?

## Uses

- What has the dataset been used for so far?
- Is there a repository listing papers or systems that use it?
- What other tasks could it be used for?
- Does anything about its composition, collection or processing limit future uses, and what could a consumer do to mitigate the risk?
- Are there tasks for which it should not be used?

## Distribution

- Will it be distributed outside the group, and to whom?
- How will it be distributed, and does it have a DOI?
- When will it be distributed?
- Under what license or terms of use?
- Have third parties imposed restrictions on the underlying data?
- Do export controls or other regulations apply?

## Maintenance

- Who hosts and maintains it, and how are they contacted?
- Is there an erratum?
- Will it be updated, how often, by whom, and how will that be announced?
- people: Are there retention limits on the data, and how are they enforced?
- Will older versions stay available, and for how long?
- Can others extend or contribute to it, and how are contributions validated and distributed?

## Provenance

- Runs that produced this dataset: <run ids from the manifest>
- Commit and dirty flag for each: <values>
- Seeds for any sampling or splitting: <values>
- Checksums: <path to the checksum file>
