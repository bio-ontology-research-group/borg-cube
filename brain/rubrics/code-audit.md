# Rubric: code audit

Applied by the auditor to one repository. Each row scores 0 (absent), 1
(partial), 2 (meets) with a file:line or command-output citation.

| Area | Criterion | Grounding |
|---|---|---|
| Documentation | README states purpose, install, minimal example, citation | Lee 2018 (ten simple rules for documenting scientific software); Wilson et al. 2014 |
| Licence | OSI licence file present and consistent with dependencies | JOSS review checklist; FAIR4RS 2022 (Chue Hong et al.) |
| Citation | CITATION.cff or equivalent; software citation principles | Smith, Katz and Niemeyer 2016 |
| Tests | automated tests exist, run in CI, ratio to code documented | Wilson et al. 2017; Taschuk and Wilson 2017 (ten simple rules for making research software robust) |
| Reproducible environment | pinned dependencies, container or lockfile, versions recorded | Grüning et al. 2018; Nüst et al. 2020 (Dockerfiles) |
| Structure and hygiene | no committed notebook outputs or data blobs, sensible layout, small functions | Wilson et al. 2014 (best practices); List, Ebert and Albrecht 2017 |
| Security | no committed secrets, no unpinned curl-pipe-sh, dependency alerts on | OWASP Top Ten; CWE Top 25; OpenSSF Scorecard |
| Maintainability | issues triaged, contribution guide, release tags, changelog | Hunter-Zinck et al. 2021 (ten simple rules on writing clean and reliable open-source scientific software); Sholler et al. 2019 (open development) |
| Release | SemVer tags, Keep a Changelog, archived DOI (Zenodo), package index | Brack et al. 2022; JOSS criteria |
| Bio-ontology repos | OBO Foundry principles, MIRO reporting, ROBOT report clean | OBO Foundry principles; Matentzoglu et al. 2018 (MIRO) |
| Data and models | datasheets, model cards, DOME reporting for ML | Gebru et al. 2021; Mitchell et al. 2019; Walsh et al. 2021 (DOME) |
| Sustainability | bus factor, last commit date, dependency staleness | Balaban et al. 2021 (ten simple rules for quick and dirty scientific programming, inverted); Jiménez et al. 2017 (four simple recommendations) |

Severity: high (secrets, data-loss path, licence violation, silent wrong
results), medium (no tests, unpinned environment, missing licence or
citation), low (style, documentation gaps). Review style follows the Google
code review guide: comment on the code, propose a fix, no rewrites in the
review itself.
