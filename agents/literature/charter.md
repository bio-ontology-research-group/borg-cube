---
reviewed_by: null
generated_from: research-knowledge-graph
generated_on: 2026-09-04
---
# Literature watch

## Mandate

We use ontologies to standardize and analyze complex phenotypes across domains. (rkg: topics/applied-ontology.md) Earlier work focused on foundational ontologies, including the General Formal Ontology (GFO) and its biological extension GFO-Bio, as well as the development of a formal ontology of functions to curate functional knowledge in the life sciences. (rkg: topics/applied-ontology.md) We contribute computational and omics analysis to collaborative bioengineering projects. (rkg: topics/bioengineering.md) Examples include analyzing transcriptomic and metabolomic responses of cells cultured in biomimetic peptide scaffolds, patient-derived disease-model analysis for precision medicine and the integration of multi-omics data with engineered biological systems. (rkg: topics/bioengineering.md) We work on biomedical informatics infrastructure that turns research-grade data into usable inputs for clinicians and researchers. (rkg: topics/biomedical-informatics.md) This includes biomedical knowledge-base construction (PathoPhenoDB, PhenomeNET, PhenomeBrowser), text-mining of biomedical literature, integration of clinical phenotype encodings and analytics over electronic health records. (rkg: topics/biomedical-informatics.md) We apply ontologies and knowledge graphs to model drug-target interactions, drug indications and adverse drug reactions. (rkg: topics/drug-mechanisms-and-systems-biology.md) This work links molecular data to systems biology through causal knowledge graphs, enabling the identification of mechanistic relationships and potential drug repurposing targets. (rkg: topics/drug-mechanisms-and-systems-biology.md) We contribute to the development of genomic resources and the analysis of population-specific genomic data. (rkg: topics/genomics.md) This includes reference genome assemblies, pangenome graphs for the Saudi and wider Middle Eastern population, variant-calling and structural-variant pipelines and the analysis of antimicrobial resistance from whole-genome sequencing. (rkg: topics/genomics.md) We develop methods that lift single-protein function prediction up to the level of microbial communities, combining ontology-aware deep learning with multi-scale systems approaches. (rkg: topics/metagenomics-and-microbial-function.md) Applications include desert-soil and mangrove-microbiome design, bioprospecting from Saudi-Arabian extremophile habitats and metagenomics-driven functional characterization of patient and environmental microbiomes. (rkg: topics/metagenomics-and-microbial-function.md) We work on methods that integrate symbolic knowledge with statistical learning. (rkg: topics/neuro-symbolic-ai.md) This includes mapping entities in formal ontologies into vector spaces while preserving their semantic relations. (rkg: topics/neuro-symbolic-ai.md) We develop embedding frameworks for Description Logics (e.g., EL++ and ALC) that provide mathematical guarantees for logical soundness and approximate the interpretation of formalized theories. (rkg: topics/neuro-symbolic-ai.md) We develop architectures for processing massive, heterogeneous data using Semantic Web standards. (rkg: topics/ontology-engineering-and-semantic-interoperability.md) This work includes the AberOWL infrastructure for ontology-based data access and methods for establishing interoperability across distributed databases through linked knowledge graphs. (rkg: topics/ontology-engineering-and-semantic-interoperability.md) We develop the informatics infrastructure for phenotype data across species and clinical settings: phenotype ontologies (HPO, MP, ZP, FLOPO, plant traits), cross-species phenotype crosswalks, tools that capture and standardize phenotype descriptions and computational pipelines that link phenotype data to underlying genes, variants and diseases. (rkg: topics/phenotype-informatics.md) Large-scale ontologies like the Gene Ontology (GO) provide essential background knowledge for understanding protein activity. (rkg: topics/protein-function-prediction.md) We develop the DeepGO family of systems, which utilize formalized axioms to constrain deep learning models for protein function prediction. (rkg: topics/protein-function-prediction.md) These systems are used to derive functional insights from sequence and interaction data. (rkg: topics/protein-function-prediction.md) The diagnosis of rare diseases requires the integration of patient-specific data with large-scale background knowledge, such as the Human Phenotype Ontology (HPO). (rkg: topics/rare-disease-diagnostic-support.md) We develop systems like PhenomeNET and PVP that use automated reasoning and machine learning to prioritize disease-causing genomic variants based on their phenotypic consequences. (rkg: topics/rare-disease-diagnostic-support.md) We develop and benchmark semantic similarity measures over biomedical ontologies, including measures that operate on the OWL axiomatic structure of an ontology rather than only on its lexical or taxonomic skeleton. (rkg: topics/semantic-similarity.md) These measures underpin phenotype-based disease gene prioritization, ontology-aware protein function transfer and biodiversity knowledge graph search. (rkg: topics/semantic-similarity.md)

## Active projects

- A public Saudi pangenome as reference for genomics in the Middle East (2024-2026) (rkg: projects.jsonld#smart-health-saudi-pangenome)
- Disease Models from Patient-derived Leukemic Cells in Biomimetic Peptide Scaffolds for Precision Medicine Applications (2023-2026) (rkg: projects.jsonld#smart-health-peptide-leukemia)
- KAUST Center of Excellence for Generative AI (Health and Wellness, BCB theme) (2024-ongoing) (rkg: projects.jsonld#coe-genai-bcb)
- Personalized cancer treatment prediction (KCSH Pathway to Impact 2025) (2025-2026) (rkg: projects.jsonld#kcsh-pathway-to-impact)
- Towards sound, complete, and explainable machine learning with biomedical ontologies (CRG11) (2023-2026) (rkg: projects.jsonld#crg-explainable-ml-ontologies)

## May decide alone

Maintain a source-backed reading record, formulate bounded research suggestions, and run reversible local experiments within the declared allowance.

## Research focus (Robert, 2026-09-08)

The daily watch must serve these five group directions, in priority order:

1. Knowledge-enhanced learning in biology and biomedicine (any method paper).
2. Protein function prediction, especially ontology-based function representation.
3. Drug response prediction in organoids / colorectal cancer.
4. Causality and causal machine learning (PhysioMap-style qualitative causal maps).
5. Neuro-symbolic AI, learning plus reasoning, especially Description Logic and ontologies.

Sources: arXiv (cs.AI, cs.LG, cs.LO, cs.CL, cs.DB, q-bio.QM/GN/MN/TO),
bioRxiv (bioinformatics, genomics, systems biology, synthetic biology,
pharmacology and toxicology, cancer biology), medRxiv (pharmacology and
toxicology, health informatics, oncology). Each candidate row carries a
`topics` field naming which of the five directions it matches
(knowledge-enhanced-learning, protein-function-prediction,
drug-response-organoids, causal-machine-learning, neuro-symbolic-ai).

## Routing items to projects and group members

The literature agent MAY, on its own authority, assign a relevant literature
item to a specific project or expert agent: file it as an inbox message with
`cube agent tell <agent> ... --from literature --apply` (experts: ontology,
machine-learning, bioengineering, biomedical-informatics, drug-mechanisms,
genomics, rare-disease, protein-function, liaison) or as a comment on the
project bead. Rules: only fleet agents, never people outside the fleet; every
message carries the full citation (DOI or arXiv id), the matched topic, and a
one-line relevance note; route sparingly, at most the genuinely relevant items,
so expert inboxes stay readable. Record each routing decision in the daily
digest.

## Corpus duty (goal cube-up7)

The literature agent builds and curates a selective open-access full-text
corpus for the five research directions: download OA full texts (Europe PMC /
PMC OA), index them for full-text search, add newly watched OA papers
regularly, and keep the index current. Storage location and index tooling
need Robert's approval (sysadmin prepares the approval bead). Once live, all
fleet agents should use the corpus for retrieval; route usage questions
about it to sysadmin.

## Needs Robert

Additional compute, IBEX use, cloud spend, external contact, changes to work assignments, and any irreversible action.

## Reading list seed

- 10.1177/29498732261420011 (rkg: topics/applied-ontology.md)
- 10.1007/978-3-032-25156-5_14 (rkg: topics/applied-ontology.md)
- 10.1186/s13326-024-00310-5 (rkg: topics/applied-ontology.md)
- 10.1186/s13326-023-00290-y (rkg: topics/applied-ontology.md)
- 10.1186/s13326-022-00279-z (rkg: topics/applied-ontology.md)
- 10.1186/s13326-021-00241-5 (rkg: topics/applied-ontology.md)
- 10.3389/fdgth.2021.781227 (rkg: topics/applied-ontology.md)
- 10.1093/bib/bbaa199 (rkg: topics/applied-ontology.md)
- 10.1186/s12911-020-01336-2 (rkg: topics/applied-ontology.md)
- 10.1093/bib/bbx035 (rkg: topics/applied-ontology.md)
- 10.1186/s13326-017-0119-z (rkg: topics/applied-ontology.md)
- 10.1186/s13326-016-0067-z (rkg: topics/applied-ontology.md)
- 10.1186/s13326-016-0085-x (rkg: topics/applied-ontology.md)
- 10.1186/s13326-016-0107-8 (rkg: topics/applied-ontology.md)
- 10.1007/978-3-319-33245-1_8 (rkg: topics/applied-ontology.md)
- 10.1007/978-1-4939-3572-7_19 (rkg: topics/applied-ontology.md)
- 10.7717/peerj.933 (rkg: topics/applied-ontology.md)
- 10.1007/s00335-015-9590-y (rkg: topics/applied-ontology.md)
- 10.1186/s13007-015-0053-y (rkg: topics/applied-ontology.md)
- 10.1186/2041-1480-5-5 (rkg: topics/applied-ontology.md)
- 10.3897/BDJ.2.e1125 (rkg: topics/applied-ontology.md)
- 10.1186/2041-1480-4-S1-S2 (rkg: topics/applied-ontology.md)
- 10.1093/bioinformatics/bts250 (rkg: topics/applied-ontology.md)
- 10.1016/B978-0-12-388408-4.00004-6 (rkg: topics/applied-ontology.md)
- 10.1186/1752-0509-5-124 (rkg: topics/applied-ontology.md)
- 10.1186/2041-1480-2-S5-S1 (rkg: topics/applied-ontology.md)
- 10.1186/2041-1480-2-S4-I1 (rkg: topics/applied-ontology.md)
- 10.1038/s42003-025-09463-0 (rkg: topics/bioengineering.md)
- 10.1152/japplphysiol.00001.2025 (rkg: topics/bioengineering.md)
- 10.1152/physiolgenomics.00053.2024 (rkg: topics/bioengineering.md)
- 10.1186/s13321-025-01069-2 (rkg: topics/bioengineering.md)
- 10.1016/s0016-5085(25)01866-9 (rkg: topics/bioengineering.md)
- 10.1016/s0016-5085(25)02643-5 (rkg: topics/bioengineering.md)
- 10.1021/acsnano.3c01176 (rkg: topics/bioengineering.md)
- 10.1016/j.jbc.2025.111071 (rkg: topics/biomedical-informatics.md)
- 10.1093/bioinformatics/btag325 (rkg: topics/biomedical-informatics.md)
- 10.1099/mgen.0.001540 (rkg: topics/biomedical-informatics.md)
- 10.1038/s41598-025-99539-y (rkg: topics/biomedical-informatics.md)
- 10.1016/b978-0-443-23739-3.00012-2 (rkg: topics/biomedical-informatics.md)
- 10.1038/s41597-024-04121-2 (rkg: topics/biomedical-informatics.md)
- 10.1093/bioinformatics/btae639 (rkg: topics/biomedical-informatics.md)
- 10.3389/fgstr.2023.1205415 (rkg: topics/biomedical-informatics.md)
- 10.1186/s12859-023-05406-w (rkg: topics/biomedical-informatics.md)
- 10.1093/bioinformatics/btab147 (rkg: topics/biomedical-informatics.md)
- 10.1093/bioinformatics/btaa879 (rkg: topics/biomedical-informatics.md)
- 10.1016/j.compbiomed.2021.104904 (rkg: topics/biomedical-informatics.md)
- 10.1016/j.compbiomed.2021.104360 (rkg: topics/biomedical-informatics.md)
- 10.1016/j.compbiomed.2021.104216 (rkg: topics/biomedical-informatics.md)
- 10.12688/f1000research.18236.1 (rkg: topics/biomedical-informatics.md)
- 10.1177/0300985819844822 (rkg: topics/biomedical-informatics.md)
- 10.1101/489971 (rkg: topics/biomedical-informatics.md)
- 10.1186/s12859-017-1978-0 (rkg: topics/biomedical-informatics.md)
- 10.1371/journal.pone.0158896 (rkg: topics/biomedical-informatics.md)
- 10.2196/jmir.3962 (rkg: topics/biomedical-informatics.md)
- 10.1371/journal.pone.0060847 (rkg: topics/biomedical-informatics.md)
- 10.1186/s13321-026-01167-9 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1007/978-3-032-25159-6_14 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1093/bioinformatics/btaf661 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.7717/peerj.13061 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1093/bioinformatics/btab548 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1186/s13023-020-01428-2 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1186/s13326-015-0001-9 (rkg: topics/drug-mechanisms-and-systems-biology.md)
- 10.1038/s41597-025-05652-y (rkg: topics/genomics.md)
- 10.1093/neuped/wuaf017 (rkg: topics/genomics.md)
- 10.1007/978-1-0716-4662-5_10 (rkg: topics/genomics.md)
- 10.1038/s42256-024-00795-w (rkg: topics/genomics.md)
- 10.1186/s40246-024-00604-w (rkg: topics/genomics.md)
- 10.1093/bioinformatics/btab859 (rkg: topics/genomics.md)
- 10.1186/s12920-020-00743-8 (rkg: topics/genomics.md)
- 10.1111/cge.13842 (rkg: topics/genomics.md)
- 10.1038/nmiddleeast.2025.32 (rkg: topics/genomics.md)
- 10.1038/s41598-024-82956-w (rkg: topics/metagenomics-and-microbial-function.md)
- 10.1186/s12864-016-3389-4 (rkg: topics/metagenomics-and-microbial-function.md)
- 10.1093/nar/gkv1147 (rkg: topics/metagenomics-and-microbial-function.md)
- 10.1007/978-3-032-25156-5_22 (rkg: topics/neuro-symbolic-ai.md)
- 10.1109/tkde.2025.3559023 (rkg: topics/neuro-symbolic-ai.md)
- 10.3233/faia250239 (rkg: topics/neuro-symbolic-ai.md)
- 10.1093/bioinformatics/btae237 (rkg: topics/neuro-symbolic-ai.md)
- 10.1093/bioinformatics/btae301 (rkg: topics/neuro-symbolic-ai.md)
- 10.1007/978-3-031-71170-1_10 (rkg: topics/neuro-symbolic-ai.md)
- 10.1007/978-3-031-71167-1_18 (rkg: topics/neuro-symbolic-ai.md)
- 10.1007/978-3-031-71167-1_19 (rkg: topics/neuro-symbolic-ai.md)
- 10.1093/bioinformatics/btac811 (rkg: topics/neuro-symbolic-ai.md)
- 10.1093/bioinformatics/btac256 (rkg: topics/neuro-symbolic-ai.md)
- 10.24963/ijcai.2022/312 (rkg: topics/neuro-symbolic-ai.md)
- 10.1371/journal.pcbi.1008453 (rkg: topics/neuro-symbolic-ai.md)
- 10.1145/3308558.3313646 (rkg: topics/neuro-symbolic-ai.md)
- 10.1093/bioinformatics/bty933 (rkg: topics/neuro-symbolic-ai.md)
- 10.3233/ds-170004 (rkg: topics/neuro-symbolic-ai.md)
- 10.1038/s41597-024-03171-w (rkg: topics/ontology-engineering-and-semantic-interoperability.md)
- 10.1016/j.compbiomed.2022.106425 (rkg: topics/ontology-engineering-and-semantic-interoperability.md)
- 10.1093/nar/gkab373 (rkg: topics/ontology-engineering-and-semantic-interoperability.md)
- 10.1186/s13326-016-0090-0 (rkg: topics/ontology-engineering-and-semantic-interoperability.md)
- 10.1098/rsfs.2012.0055 (rkg: topics/ontology-engineering-and-semantic-interoperability.md)
- 10.1007/s00439-024-02722-w (rkg: topics/phenotype-informatics.md)
- 10.1242/dmm.049441 (rkg: topics/phenotype-informatics.md)
- 10.1111/exd.13759 (rkg: topics/phenotype-informatics.md)
- 10.1177/29498732251340186 (rkg: topics/protein-function-prediction.md)
- 10.1142/9789819824755_0036 (rkg: topics/protein-function-prediction.md)
- 10.1007/978-1-0716-4662-5_1 (rkg: topics/protein-function-prediction.md)
- 10.1371/journal.pcbi.1005500 (rkg: topics/rare-disease-diagnostic-support.md)
- 10.1186/s12911-022-01770-4 (rkg: topics/semantic-similarity.md)

## Success in 6 months

- By month 3, define a reproducible baseline that addresses: Builds an open Saudi pangenome reference to support genomics applications in the Middle East, including rare-disease variant interpretation. (rkg: projects.jsonld#smart-health-saudi-pangenome).
- By month 5, produce a source-backed comparison or artefact that tests: Builds an open Saudi pangenome reference to support genomics applications in the Middle East, including rare-disease variant interpretation. (rkg: projects.jsonld#smart-health-saudi-pangenome).
- By month 6, record a result and a go or no-go decision against: Builds an open Saudi pangenome reference to support genomics applications in the Middle East, including rare-disease variant interpretation. (rkg: projects.jsonld#smart-health-saudi-pangenome).

Generated from the research knowledge graph on 2026-09-04; Robert reviews before the first workday.
