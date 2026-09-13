---
topic: research-software-practice
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Research software practice

Sources
- wilson2014 (CC-BY-4.0; short excerpts allowed)
- wilson2017 (CC-BY-4.0; short excerpts allowed)
- taschuk-wilson2017 (CC-BY-4.0; short excerpts allowed)
- hunter-zinck2021 (CC-BY-4.0; short excerpts allowed)
- list2017 (CC-BY-4.0; short excerpts allowed)
- balaban2021 (CC-BY-4.0; short excerpts allowed)
- osborne2014 (CC-BY-4.0; short excerpts allowed)
- lee2018-documenting (CC-BY-4.0; short excerpts allowed)
- romano2020 (CC-BY-4.0; short excerpts allowed)
- nust2020 (CC-BY-4.0; short excerpts allowed)
- brack2022 (CC-BY-4.0; short excerpts allowed)
- jimenez2017 (CC-BY-4.0; short excerpts allowed)
- fair4rs2022 (CC-BY-4.0; short excerpts allowed; landing page only)
- sholler2019 (CC-BY-4.0; short excerpts allowed)
- turing-way (CC-BY-4.0; short excerpts allowed; landing page only, cited for general claims)
- google-code-review (CC-BY-3.0; short excerpts allowed)
- openssf-scorecard (Apache-2.0; short excerpts allowed)

## What the evidence says

### Version control and small changes

- Everything created by hand (code, raw observations, manuscript sources) belongs in version control; regenerable outputs, compiled binaries and intermediate files do not, and large binaries are better archived with their metadata versioned instead [wilson2014, taschuk-wilson2017, wilson2017].
- A good change is a group of edits you might want to undo in one step; a single "Revise script" commit touching hundreds of lines defeats change tracking. Share changes frequently, write log messages that explain the change, and do not commit half-done or broken code [wilson2017].
- Version control is not built for megabyte files; GitHub caps a single file at 100 MB. Data under legal restriction and credentials such as passwords or private keys must never be pushed to a shared repository [wilson2017].
- Once comfortable with basic commits, use a feature-branch workflow: branch per fix or feature, merge into the main branch after testing [taschuk-wilson2017].
- Host the repository on a collaborative service (GitHub, GitLab, Bitbucket), not an institutional or private server, and make it public from day one; the longer a project stays closed the harder it is to open [brack2022, jimenez2017].
- OpenSSF Scorecard treats checked-in binaries, missing branch protection, missing code review and fewer than a handful of commits in 90 days as high-risk signals [openssf-scorecard].

### Automated tests and continuous integration

- Defensive programming comes first: assertions and pre- and postconditions check inputs, outputs and invariants and halt the program at the first sign of trouble; they also act as executable documentation [wilson2014, hunter-zinck2021].
- Use an off-the-shelf unit test framework, turn every fixed bug into a regression test, and compare low-level routines against analytical solutions, prototypes or trusted earlier results [wilson2014, osborne2014].
- Write tests throughout development, not at the end; a unit test checks one behavior in isolation and runs fast. As a rule of thumb aim for at least 60 percent coverage, and prefer branch coverage over line coverage [hunter-zinck2021].
- End-to-end and regression tests record program outputs (or summary metrics with a tolerance) and catch changes caused by library or OS upgrades [hunter-zinck2021].
- Tests should run automatically on every commit or push through git hooks or a CI service such as GitHub Actions or GitLab CI; ad hoc manual checking that results "look roughly right" is the illusion of reliability [osborne2014, hunter-zinck2021].
- Every package should ship a small test set and an obvious runner such as runtests.sh whose output is one line per test plus a summary; missing dependencies should be reported once, not once per test [taschuk-wilson2017].
- Demo data that lets a user get a known correct output from a known input is a "build-and-smoke test" and is essential for anything published [wilson2017, list2017].
- Unit and integration tests, their input data and expected outputs live in source control, and the build and test steps are automated [brack2022].
- Wilson 2017 deliberately leaves unit tests, coverage and CI off its "good enough" list because solo exploratory researchers do not adopt them; the same authors call them essential for larger libraries [wilson2017].

### Documentation

- A README is often the only documentation a user reads. Minimum content: what the software does, required dependencies, installation, all input and output files with their formats, a few example commands, attribution and license [taschuk-wilson2017]; Lee adds configuration, where to find full documentation, how to run the tests, acknowledgments and a quickstart [lee2018-documenting].
- High-level documentation should answer three questions: what does the software do, who is it for, and what problem does it solve [brack2022].
- Every program, however short, starts with a comment that includes at least one usage example and reasonable parameter values [wilson2017].
- Command-line tools print terse usage on --help (syntax, purpose, common arguments with defaults, where to find more) and print name and version on --version; usage goes to standard output and exits with a proper code [taschuk-wilson2017, lee2018-documenting, brack2022].
- Document interfaces and reasons, not mechanics; comments that restate the code are useless; embed reference documentation in the source so it changes with the code, and refactor code rather than explain it [wilson2014].
- Write comments as you code, aiming for "not too many and not too few"; when in doubt err toward more [lee2018-documenting]. Balaban prefers self-documenting names and structure during exploration and defers external documents until the code stabilizes [balaban2021].
- Each public function documents input types, output type and the errors it raises; documentation is generated by a tool (Sphinx, Roxygen, Doxygen) and rebuilt on push; doctests keep examples honest [lee2018-documenting].
- Documentation is versioned with the software; a changelog lists new features, changed defaults and bug fixes, with breaking changes marked explicitly [lee2018-documenting, brack2022].
- Error messages state what went wrong, what state the software was in, and how to fix it or where to read more [lee2018-documenting]; descriptive errors for out-of-range values and duplicate identifiers are part of usability [list2017].
- A software paper should describe design and results; usage documentation belongs in versioned online documentation the paper links to, because code printed in a paper is a permanent support commitment [romano2020].

### Dependencies, environments and containers

- Make dependencies explicit in a machine-readable file such as requirements.txt or a "Getting started" section, install from that description yourself, and avoid depending on locally built tools that exist nowhere else [wilson2017, taschuk-wilson2017].
- Dependencies should be explicit, not implicit: an installer must not assume anything is preinstalled, and version numbers of dependencies should be managed [brack2022].
- "Latest" is a moving target. Pin versions of base images, system packages and language modules; a package manager that resolves versions itself (Conda is the example) gives non-reproducible builds unless versions are pinned [nust2020].
- Use official or well-maintained base images and only images whose Dockerfile you can read; save a copy of that Dockerfile in your project [nust2020].
- Keep the Dockerfile and every file it COPYs in the same version-controlled repository; mount datasets at run time rather than baking them in; never put sensitive data in an image; use .dockerignore; include small test data so the container can be verified without the real dataset [nust2020].
- Document inside the Dockerfile: comments explaining choices, OCI labels for authors, license, version and documentation URL, and build and run instructions at the top or bottom [nust2020].
- The default entrypoint should not start a long analysis by surprise; something like --help is a reasonable default command. Order instructions from least to most likely to change, rebuild without cache every week or two, and deposit the image in a public repository when results are published [nust2020].
- Reuse well-maintained libraries instead of rewriting, but test a library before relying on it and weigh the integration cost; a large user base and recent updates are good quality signals [wilson2017, taschuk-wilson2017, balaban2021].
- Scorecard checks whether dependencies are declared and pinned, whether an update tool is used, and whether known vulnerabilities remain unfixed [openssf-scorecard].

### Licensing, citation, releases and discoverability

- A LICENSE file in the project root is required; "Lack of an explicit license does not mean there isn't one", it means all rights are reserved and nobody may reuse the code [wilson2017]. Without a license many organizations cannot use the software at all [list2017, jimenez2017].
- Choose an OSI-approved license; Wilson recommends permissive licenses (MIT, BSD, Apache) for code and CC-0 or CC-BY for data and text; Brack lists Apache 2, BSD 2-Clause and GPL 3.0 as widely understood choices; use SPDX identifiers if several licenses coexist. Comply with the licenses of every third-party dependency [wilson2017, brack2022, jimenez2017].
- A CITATION file in the root says how to cite the project and its DOI-bearing parts; Lee recommends the machine-readable Citation File Format (CITATION.cff) plus a DOI, BibTeX entry and written reference in the README [wilson2017, lee2018-documenting].
- Deposit code in a DOI-issuing repository (Zenodo integrates with GitHub) when the paper is submitted; release-tagged archives with DOIs are the main defense against link rot [wilson2017, romano2020].
- Make official releases, stamp them with semantic versions, print the version on --version and in all output, keep old releases available, and release at the same time as the paper so results can be reproduced [taschuk-wilson2017, brack2022].
- Publish on at least one package index so users install with a single command; CI can automate publication [romano2020, brack2022].
- Register software metadata (source location, contributors, license, version, identifier, how to cite) in a community registry such as bio.tools [jimenez2017].
- The FAIR4RS principles apply FAIR to software while revising the data principles for software's executability, composite nature and continuous versioning [fair4rs2022].
- Write a software management plan: who maintains the code when affiliations change, what it costs to keep online, who owns the IP, whether updates will come, and when and how the software is archived [romano2020].

### Usability and robustness

- Commonly changed parameters (input and output paths, filters, seeds, verbosity) are command-line options; infrequently changed values live in configuration files; nothing changeable is hard-coded. "if users have to edit your software in order to run it, you have done something wrong" [taschuk-wilson2017].
- Check all input values at startup rather than failing after two hours because an output directory does not exist [taschuk-wilson2017]; expect users to make mistakes and validate ranges and identifiers [list2017].
- Expose only mandatory parameters by default, put advanced ones in an expert section, and choose and justify conservative defaults [list2017].
- On start, echo all parameters and software versions to standard output or a log; a given version with the same inputs and parameters must give the same results; allow the user to set the random seed, and echo an internally chosen seed [taschuk-wilson2017, list2017, brack2022].
- Do not require root to install or run; allow installation under a home directory [taschuk-wilson2017, brack2022].
- Follow conventions: data on stdout, logs and errors on stderr, exit code 0 on success and non-zero on failure, community-standard file formats (or JSON/XML), UTF-8 text. Accept lenient input, write strictly standard output [brack2022, list2017].
- Workflow-readiness: every option settable at run time and overriding any config file; input and output paths as explicit arguments; concurrent instances independent (unique temp directories, no shared state); clean up temporary files; do not saturate all cores by default; one tool does one thing [brack2022].
- Byte-level reproducibility of output is the ideal; checksums, consistent serialization and fixed decimal formatting make it testable [brack2022].

### Code organization and naming

- Write programs for people: a reader should hold only a handful of facts at once; names are consistent, distinctive and meaningful; style and formatting are consistent [wilson2014].
- Pick one style guide and enforce it with a linter or formatter [hunter-zinck2021].
- Decompose into functions of at most a page (about 60 lines) with no more than five or six parameters [wilson2017]; Hunter-Zinck suggests 40 lines and parameter objects for co-occurring arguments [hunter-zinck2021].
- Do not repeat yourself: modularize instead of copy-pasting, give every datum one authoritative representation, and if you write the same code twice make it a function [wilson2014, wilson2017, osborne2014, balaban2021].
- Do not comment and uncomment code to control behavior; use if/else and options [wilson2017]. Remove dead and commented-out code during refactoring [hunter-zinck2021].
- Refactor frequently in small steps with tests in place; code smells (duplication, long functions, long parameter lists, synchronized edits) are the trigger [hunter-zinck2021, balaban2021].
- Optimize only after the code is correct, and profile first; write in the highest-level language possible and drop to C only for measured bottlenecks [wilson2014, balaban2021].

### Project and data organization

- One directory per project containing README, CITATION, LICENSE, requirements.txt, data/ (raw data and metadata), doc/, results/ (generated files), src/ and bin/; file names describe content, never sequence numbers or figure positions [wilson2017].
- Save raw data read-only and backed up in more than one location; record every processing step as a script; keep intermediate products as files; use a unique identifier for every record [wilson2017].
- A controller script (runall) or a build tool such as Make regenerates everything from raw data with one command [wilson2017, wilson2014]. After exploration, a scripted workflow (Bash, notebook, Snakemake, Nextflow) must reproduce each publishable result [balaban2021].
- Save both raw and intermediate data forms and separate results by publication [wilson2017].

### Collaboration and community

- Pre-merge code review is the most cost-effective way to find bugs and spreads knowledge in labs with turnover; use an issue tracker so tasks are not dropped; pair program when onboarding [wilson2014]. Reviewers look at design, functionality, complexity, tests, naming, comments, style and documentation [google-code-review].
- Keep a shared to-do list or issue tracker with items newcomers can understand; write a CONTRIBUTING file covering setup, tests and guidelines; decide communication channels [wilson2017].
- Newcomer-friendly projects tag starter issues, publish contribution guidelines in CONTRIBUTING.md, adopt and enforce a code of conduct, make setup easy, state governance, and acknowledge every contribution in LICENSE and CITATION files [sholler2019, jimenez2017].
- Expect support requests after release and treat them as usability feedback [list2017].
- The Turing Way is a community handbook for reproducible, ethical and collaborative research, built in the open under CC-BY [turing-way].
- Scorecard also checks for a security policy file and for contributors from more than one organization [openssf-scorecard].

### Quick and dirty code, and when it must grow up

- Coding fast is a legitimate way to handle explorative research, but "if coding quickly means coding sloppily, then bugs, false conclusions, and article retractions may be the result" [balaban2021].
- Balaban's compromise: think and search for existing tools first; build a minimal prototype and expand in short cycles; reuse code; modularize even when fast; avoid premature optimization; unit test only components with scientific consequences (a P value, a solver) rather than everything; refactor often; prefer self-documenting code and add a README when sharing; grow libraries from proven project code; be rigorous at publication [balaban2021].
- Code run once on one dataset needs neither comprehensive documentation nor flexible configuration. Once a script is "dusted off and run three or four times", is crucial to a publication or a lab, or is handed to someone else, it is time to make it robust; software described in a paper must at minimum meet the ten robustness rules [taschuk-wilson2017].
- Nobody should think a task is a one-off; you will find bugs, change a parameter and repeat the whole process. Once you have done something twice, automate it [osborne2014].
- PIs can require students to show and share code in lab meetings and make computational methods sections complete [wilson2017]. Practices should improve over time rather than all at once [hunter-zinck2021, brack2022].

## Rules we adopt

Each rule names the artifact an audit looks for. The code-audit script collects the facts; Robert judges severity in review. Rules 1 to 5 apply to every repository. Rules 6 to 15 apply to anything cited in a paper, used by someone other than its author, or run more than a few times; rule 16 defines the exemption.

1. Keep the project in git on a hosted service; commits are small with descriptive messages. Artifact: .git history, remote URL. Fail if any committed file exceeds 50 MB or matches a secret pattern (keys, tokens, passwords); fail if restricted data is present. Enforced by the code-audit script (from [wilson2017], [openssf-scorecard]).
2. Ship a LICENSE file in the root with an OSI-approved license and check third-party license compatibility; prefer MIT, BSD or Apache, but do not flag GPL. Artifact: LICENSE, license field in packaging metadata. Enforced by the code-audit script (from [wilson2017], [brack2022], [jimenez2017]).
3. The README states what the software does and for whom, dependencies, installation, one worked example with shipped test data and expected output, input and output formats, how to run the tests, how to cite, and the license. Artifact: README with these sections. Enforced by the code-audit script and Robert (from [taschuk-wilson2017], [lee2018-documenting], [brack2022]).
4. Declare dependencies in a machine-readable file with pinned versions (lock file, requirements with ==, environment.yml with versions, pyproject with bounds plus a lock). Artifact: the file; fail on unpinned entries for anything cited. Enforced by the code-audit script (from [wilson2017], [taschuk-wilson2017], [nust2020]).
5. No hard-coded paths, parameters or seeds: inputs, outputs and tunables are command-line arguments; the program validates them at startup, prints --help and --version, echoes version and parameters at run time, writes logs to stderr and exits non-zero on failure. Artifact: argument parser, grep for absolute paths. Enforced by the code-audit script (from [taschuk-wilson2017], [brack2022], [list2017]).
6. Tests exist in a tests directory using the language's standard framework, include a small test dataset, and run in CI on every push; coverage is reported and at least 60 percent for library code. Artifact: tests/, CI config, coverage report. Enforced by the code-audit script (from [hunter-zinck2021], [osborne2014], [taschuk-wilson2017]).
7. Every number in a paper is reproducible by a scripted workflow (runall, Makefile, Snakemake, Nextflow) from raw data, and at least one end-to-end test checks a published value within a stated tolerance. Artifact: workflow file, end-to-end test. Enforced by Robert at paper submission (from [wilson2017], [balaban2021], [hunter-zinck2021]).
8. Commit notebooks with outputs stripped and results regenerable; do not version intermediate or generated files that the workflow rebuilds. Artifact: nbstripout hook or clean .ipynb, .gitignore for results. Enforced by the code-audit script (from [wilson2017], [taschuk-wilson2017]).
9. Anything cited in a paper has a release tag with a semantic version, an archived DOI (Zenodo), and a CITATION.cff; the README shows the DOI and a BibTeX entry, and the paper points at the release. Artifact: git tag, CITATION.cff, DOI badge. Enforced by Robert at paper submission (from [taschuk-wilson2017], [wilson2017], [lee2018-documenting], [romano2020]).
10. If a Dockerfile exists it is version-controlled with every file it copies, uses version-tagged base images (never latest), bakes in no data or secrets, carries usage instructions and OCI labels, and its default command does not start the analysis. Artifact: Dockerfile, .dockerignore. Enforced by the code-audit script (from [nust2020]).
11. A linter or formatter is configured and passes; functions fit on a page; no dead or commented-out code; no duplicated blocks; no commenting out to change behavior. Artifact: linter config, lint run. Enforced by the code-audit script (from [hunter-zinck2021], [wilson2017], [wilson2014]).
12. Every public function has a docstring giving inputs, outputs and raised errors; API docs are generated by a tool; a CHANGELOG marks breaking changes and changed defaults. Artifact: docstring coverage, docs config, CHANGELOG. Enforced by the code-audit script (from [lee2018-documenting], [brack2022], [wilson2014]).
13. Follow the standard layout: data/ for raw data (read-only), src/, results/, doc/, tests/; file names describe content. Artifact: directory listing. Enforced by the code-audit script (from [wilson2017]).
14. Shared code has an issue tracker enabled, a CONTRIBUTING file, pre-merge review (branch protection on the default branch), and a code of conduct once external contributors are expected. Artifact: repository settings, CONTRIBUTING.md, CODE_OF_CONDUCT.md. Enforced by the code-audit script and Robert (from [wilson2014], [wilson2017], [sholler2019], [google-code-review]).
15. State maintenance status: either a commit within the last 90 days and answered issues, or a README line saying the project is archived and who to contact. Anything published names a maintainer. Artifact: last commit date, open issue age, maintenance note. Enforced by the code-audit script (from [openssf-scorecard], [brack2022], [romano2020]).
16. Exploratory code used by one person on one dataset may skip rules 6, 7, 9, 12 and 14, but must still satisfy rules 1 to 5 and test any component whose error would change a scientific conclusion. The exemption ends when the code is cited, handed to another person, or run more than three times. Enforced by Robert in review (from [balaban2021], [taschuk-wilson2017], [osborne2014]).

## Where sources disagree

- Quick and dirty versus robust: [balaban2021] argues for minimal prototypes, testing only critical components and deferring documentation, while [taschuk-wilson2017], [hunter-zinck2021] and [osborne2014] ask for full test suites, CI, coverage targets and complete READMEs. The papers agree more than they seem to: Balaban's rule 10 and Taschuk's conclusion both draw the line at publication and hand-over. We adopt that line (rule 16): quick and dirty is fine for exploration, and anything cited in a paper or used by another person meets the full checklist.
- Who needs unit tests and CI: [wilson2017] leaves them off the "good enough" list for newcomers doing solo analysis; [hunter-zinck2021] and [osborne2014] treat them as baseline. We side with the robustness papers for group code because our repositories are shared and cited, and we keep Wilson's advice as the on-ramp for students in their first months.
- License choice: [wilson2017] recommends permissive licenses over the GPL for ease of integration; [brack2022] lists GPL 3.0 among acceptable well-known licenses and [romano2020] says adopt the most permissive license the institution allows. We require OSI-approved, prefer permissive, and do not flag GPL as a finding.
- Comments: [lee2018-documenting] says err toward more comments; [wilson2014] and [balaban2021] say refactor rather than explain and document reasons, not mechanics. We follow Wilson: docstrings on interfaces are required (rule 12), inline comments are for intent and references, and comments that restate code are a finding.
- Pinning: [taschuk-wilson2017] and [brack2022] show version ranges in dependency files; [nust2020] asks for exact pins for reproducible builds. We require exact pins in a lock file or environment file for anything that reproduces a published result, and accept ranges in library packaging metadata.

## Not covered

- Notebook hygiene beyond "do not version regenerable output": execution order, hidden state and notebook testing are not addressed by these sources.
- Numeric thresholds for a tests-to-code ratio; only [hunter-zinck2021] gives a coverage figure, and none of the papers gives a ratio an auditor can apply mechanically.
- Turning findings into an overall score: [openssf-scorecard] warns that aggregate scores hide which behaviors are present, and no source proposes a severity scale for research code. Severity in the audit remains Robert's judgment.
- HPC and cluster specifics (Slurm, Singularity, module systems, GPU driver pinning); [nust2020] declares HPC out of scope.
- Machine learning artifacts: model weights, dataset versioning, GPU nondeterminism and experiment tracking.
- Ontology and knowledge-graph tooling (OWL files, reasoner versions, SPARQL endpoints) that our group depends on.
- Handling of human or otherwise restricted data beyond the warning not to commit it.
- Security practices beyond the Scorecard checklist: secret scanning, dependency vulnerability monitoring and supply-chain signing are named but not explained for a research setting.
- Code produced with LLM assistance and how review or attribution should change for it.
