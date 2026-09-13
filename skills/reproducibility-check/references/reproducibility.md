---
topic: reproducibility
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Computational reproducibility

Sources
- nust2020 (CC-BY-4.0; short excerpts allowed; full text fetched)
- turing-way (CC-BY-4.0; short excerpts allowed; only the welcome page was fetched, the rest is summarised from knowledge)
- gruning2018 (CC-BY-4.0; the fetched text file is empty, so claims are summarised from knowledge of the article)
- peng2011 (proprietary; not fetched, summarised from knowledge)
- stodden2016 (proprietary; not fetched, summarised from knowledge)
- nap2019-reproducibility (free to read, not fetched; summarised from knowledge, summary only)
- acm-badging (ACM policy page; not fetched, summarised from knowledge, no quotes)

## What the evidence says

### What the words mean

- The National Academies separate two ideas: reproducibility is getting
  consistent results from the same input data, computational steps, methods,
  code and conditions of analysis, and replicability is getting consistent
  results from a new study that answers the same question with new data
  (from knowledge of the report, not verified against the text)
  [nap2019-reproducibility].
- On that definition reproducibility is a property of the computational
  record, so a failure to reproduce is a defect in the artifacts or their
  documentation, not a scientific disagreement (from knowledge)
  [nap2019-reproducibility].
- The report attributes much non-reproducibility to inadequate description of
  methods, code and data, and recommends that publications report enough
  detail, including the computational environment, for an independent analyst
  to repeat the analysis (from knowledge) [nap2019-reproducibility].
- The Turing Way sets the same distinction in a two-by-two table over data and
  analysis: same data and same analysis is reproducible, different data and
  same analysis is replicable, same data and different analysis is robust, and
  different data and different analysis is generalisable (from knowledge of
  the handbook; the fetched page is only the welcome chapter) [turing-way].
- The handbook's stated aim is to make collaborative, reusable and transparent
  research "too easy not to do", and all of its material is CC-BY
  [turing-way].
- Peng places computational work on a spectrum rather than a binary, running
  from publication only, through code, then code and data, then linked and
  executable code and data, to full replication, and argues that
  reproducibility is the attainable minimum standard when replication is not
  practical (from knowledge of the article) [peng2011].
- ACM's badging terminology names three independent badge families: artifacts
  evaluated, artifacts available, and results validated (from knowledge of the
  policy page) [acm-badging].
- Artifacts evaluated has two levels: functional, meaning the artifacts are
  documented, consistent, complete and exercisable; and reusable, which adds
  that they are carefully documented and structured well enough for others to
  reuse and repurpose them (from knowledge) [acm-badging].
- Artifacts available means the artifacts sit in a publicly accessible
  archival repository with a persistent identifier; it says nothing about
  whether they work, because no one evaluated them (from knowledge)
  [acm-badging].
- Results validated has two levels: results reproduced, where a different team
  obtained the main results using the artifacts the authors supplied; and
  results replicated, where a different team obtained them without those
  artifacts (from knowledge) [acm-badging].

### Making the environment reproducible

- Nust and colleagues argue that a paper's contribution to knowledge includes
  the full computing environment that produced a result, so the environment
  has to be shared with the code and data [nust2020].
- They define the computing environment as the body of all software used
  directly or indirectly by a researcher, and treat a container recipe as the
  way to capture it in a human- and machine-readable form [nust2020].
- The recipe, not the built image, is the primary artifact: a Dockerfile shows
  where data and code came from, and it belongs in version control next to the
  code and every file copied into the image [nust2020].
- Software versions must be pinned: relying on `latest` or on the current
  release of a package is "a moving target for your computing environment that
  can break your workflow" [nust2020].
- Where pinning happens depends on the layer. System libraries mostly follow
  the base image tag, language packages are pinned in the Dockerfile or in a
  dependency file such as `requirements.txt`, `environment.yml`,
  `DESCRIPTION`, `package.json` or `Manifest.toml`, and source installs are
  pinned to a tag or commit hash [nust2020].
- Package managers that resolve versions themselves, Conda among them, will
  otherwise produce a non-reproducible build, so the dependency versions have
  to be pinned explicitly [nust2020].
- Data belongs outside the image and is bind-mounted at run time; the image
  carries the software, and a small dummy or test dataset so the container can
  be exercised without the real data [nust2020].
- Sensitive or proprietary data must never be baked into an image, and adding
  the data directory to `.dockerignore` keeps it out of the build context by
  accident as well as on purpose [nust2020].
- A workflow has to be runnable headlessly, from a fixed set of commands; the
  authors go as far as saying a workflow that does not support headless
  execution may even be seen as irreproducible [nust2020].
- The default entrypoint should not start the analysis, because a user who
  runs the container to look around should not be surprised by a process that
  writes files; usage instructions belong in the recipe itself [nust2020].
- Rebuilding without the layer cache, every week or two for a container in
  daily use, is what exposes broken instructions and, in their words, reveals
  issues requiring manual intervention that are not documented in the
  Dockerfile [nust2020].
- A remembered but undocumented step is itself the signal: if you need to
  remember an undocumented step, that step should have been in the recipe
  [nust2020].
- At publication time the built image should also be exported and deposited in
  a public data repository beside the data, code and recipe, because it is
  unlikely that the image can be recreated precisely from the recipe years
  later [nust2020].
- Before submission the authors suggest having a colleague run the workflow on
  a machine of their own, as a check on the documentation [nust2020].
- Their scope is a single laptop or server, roughly under a terabyte of data;
  they state that workflows on high-performance computing infrastructures are
  out of scope and point to Singularity for that case [nust2020].
- Gruning and colleagues argue that practical reproducibility in the life
  sciences comes from combining three layers rather than one: a package
  manager that installs pinned software automatically, containers built from
  those packages, and a workflow system that records how the tools were
  chained; Bioconda recipes feeding automatically built containers is their
  worked example (from knowledge of the article; the fetched text is empty)
  [gruning2018].
- Their argument for the package-manager layer is that a container built by
  hand hides how its contents were installed, while a container generated from
  a versioned recipe can be rebuilt and audited (from knowledge)
  [gruning2018].
- The Turing Way makes the same layering explicit for a project: version
  control for code, an environment specification for software, a data
  management plan with persistent identifiers for inputs, and a documented
  path from raw data to each published figure (from knowledge) [turing-way].

### Publishing artifacts so someone else can check

- Stodden and colleagues propose reproducibility enhancement principles for
  journals: require the data, code and workflow details that support the
  results to be shared at review time, deposit them under persistent
  identifiers, describe the computational environment, and give explicit
  credit for the artifacts (from knowledge of the article) [stodden2016].
- They treat the journal, not the individual author, as the effective lever,
  because policy applied at submission is what changes practice at scale (from
  knowledge) [stodden2016].
- Peng argues that the reviewer of a computational claim needs the analytic
  data and the code, and that the middle of the spectrum, code plus data
  without an executable link between them, is where most published work sits
  (from knowledge) [peng2011].
- Under ACM's scheme the available badge and the validated badges are earned
  by different acts: depositing artifacts, and a third party running them
  (from knowledge) [acm-badging].

## Rules we adopt

1. Say which claim is being checked before running anything: name the figure,
   table or number in the paper, the command that is supposed to produce it,
   and the reference output it will be compared against. A re-execution with
   no stated target is not a reproducibility check. (from [peng2011],
   [nap2019-reproducibility])
2. Never modify the repository under test. Work on a fresh clone at a named
   commit, in a working directory of our own, and record the commit hash.
   Fixes go to the authors as findings, never as edits. (from
   [nap2019-reproducibility], [stodden2016])
3. Build the environment from the artifacts the authors shipped: a container
   recipe first, then a lock file, then a plain dependency list. Falling back
   to the environment already on the machine is not a re-execution and the
   check must refuse rather than do it silently. (from [nust2020],
   [gruning2018])
4. Record every improvisation. A package installed by hand, a version resolved
   rather than pinned, a missing system library, an undocumented flag: each
   one is a missing step, and the list of missing steps is part of the result.
   (from [nust2020])
5. Pin at every layer or say that you could not: base image tag, language
   package versions, source installs by tag or commit. An unpinned dependency
   is reported as a reproducibility defect even when the run succeeds. (from
   [nust2020], [gruning2018])
6. Mount data, do not copy it into the environment, and keep the real inputs
   read-only. Sensitive data never enters an image or a shared environment.
   (from [nust2020])
7. Run headlessly, from a single documented command, with the output directory
   given from outside. If the workflow only runs interactively, that is a
   finding. (from [nust2020])
8. Compare outputs mechanically, with a stated numeric tolerance per metric,
   and keep the comparison output as the evidence. No result is called
   reproduced without it. (from [nap2019-reproducibility], [peng2011])
9. Distinguish the three outcomes in the report: identical outputs, agreement
   within the stated tolerance, and divergence. Divergence names the items and
   the size of the difference, not a verdict about the authors. (from
   [nap2019-reproducibility])
10. Grade with ACM's terminology and use it accurately: artifacts available is
    about deposit with a persistent identifier, artifacts evaluated is about
    the artifacts being functional or reusable, and results reproduced means a
    different team got the main results using the authors' artifacts. Do not
    claim a badge level the evidence does not support. (from [acm-badging])
11. A re-execution that needed undocumented steps is reported as not
    reproducible, with the steps listed, even if the numbers matched in the
    end. (from [nust2020], [nap2019-reproducibility])
12. Rebuild without the layer cache before a release, a submission or a
    reproducibility claim, and re-run the comparison. A result that only holds
    against a cached environment is not evidence. (from [nust2020])
13. Deposit the recipe, the lock file, the exported image and the reference
    outputs together under a persistent identifier when the work is published,
    and cite them from the paper. (from [stodden2016], [nust2020])
14. Have a second person, or the reproducibility check itself, run the
    workflow on a different machine before submission. (from [nust2020],
    [stodden2016])

## Where sources disagree

- Terminology: ACM's earlier badging version used "reproduced" and
  "replicated" in the opposite senses to the National Academies, and version
  1.1 aligned them, so older papers carrying ACM badges may use the earlier
  meaning [acm-badging, nap2019-reproducibility]. We use the National
  Academies definitions in prose and name the ACM badge and its version
  explicitly when we grade.
- Where the environment is defined: Nust and colleagues put the environment in
  a hand-written container recipe [nust2020]; Gruning and colleagues prefer a
  package manager whose recipes generate the container, so the install steps
  stay machine-readable [gruning2018]. We take the package manager or lock
  file as the source of truth for versions and the container as the way to
  ship them, which satisfies both.
- Image size and clarity: Nust and colleagues accept a larger image for the
  sake of an inspectable one, keeping install scripts inside [nust2020], while
  the packaging recommendations they cite favour small production images
  [gruning2018]. We follow inspectability, because our images are read by
  reviewers rather than deployed at scale.
- Scope: Nust and colleagues explicitly exclude high-performance computing
  from their rules [nust2020], while much of our work runs on a cluster. We
  apply the rules that transfer, recipe in version control, pinned versions,
  mounted data, headless execution, and use Apptainer or Singularity images on
  the cluster.

## Not covered

- Numeric tolerance: none of the sources say how close is close enough for a
  metric, or how to set a tolerance per quantity. That stays a judgement call
  recorded per check.
- Nondeterminism from hardware and libraries: GPU kernels, thread counts,
  BLAS implementations and random seeds are not treated by these sources.
- Cluster execution: scheduler settings, node heterogeneity, module systems
  and shared filesystems are out of scope for nust2020 and thin in the others.
- Data that cannot be shared: the sources assume artifacts can be deposited,
  and say little about checking work built on controlled-access or
  personal data.
- Long-term decay: how to tell a genuine irreproducibility from a dependency
  that disappeared from a registry years later.
- The gruning2018 and turing-way texts were not fetched in usable form, and
  nap2019-reproducibility, peng2011, stodden2016 and acm-badging were not
  fetched at all; claims attributed to them here come from knowledge of the
  sources and need checking against the originals before a decision rests on
  one of them alone.
