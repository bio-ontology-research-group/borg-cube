# Mapping a check outcome to an ACM badge

Sources
- acm-badging (ACM policy page; not fetched, summarised from knowledge, no quotes)
- nap2019-reproducibility (free to read, not fetched; summarised from knowledge, summary only)
- peng2011 (proprietary; not fetched, summarised from knowledge)

The badges below are ACM's, described from knowledge of the version 1.1
terminology page rather than from a fetched copy. Read the page at
`https://www.acm.org/publications/policies/artifact-review-and-badging-current`
before putting a badge claim in writing, and name the version you used.

## The three badge families

ACM's scheme has three independent families. A paper can carry one badge from
each; they answer different questions and none implies another [acm-badging].

| Family | Badge | What it certifies | Who does the work |
| --- | --- | --- | --- |
| Artifacts available | Artifacts Available | The artifacts sit in a publicly accessible archival repository with a persistent identifier | The authors deposit; nobody evaluates |
| Artifacts evaluated | Functional | Artifacts are documented, consistent, complete and exercisable | A reviewer exercises them |
| Artifacts evaluated | Reusable | Everything Functional requires, plus documentation and structure good enough for others to reuse and repurpose | A reviewer exercises them |
| Results validated | Results Reproduced | A different team obtained the paper's main results using the artifacts the authors supplied | A third party re-runs |
| Results validated | Results Replicated | A different team obtained the paper's main results without the authors' artifacts | A third party rebuilds |

Three things that are easy to get wrong [acm-badging]:

- Available says nothing about whether the artifacts run. A deposited archive
  that fails to build still earns it.
- Reusable is not "ran twice". It is a judgement about documentation and
  structure, made by someone who tried to build on the artifacts.
- Reproduced and Replicated differ only in whether the authors' artifacts were
  used. Version 1.0 of ACM's scheme used these two words in the opposite
  senses; version 1.1 aligned them with the National Academies, where
  reproducibility is the same data and the same analysis and replicability is
  new data [acm-badging, nap2019-reproducibility].

## What our check can and cannot support

A reproducibility check of the kind this skill runs is a single team
re-executing the authors' artifacts on the authors' data. It produces evidence
for Artifacts Available, for the Functional level of Artifacts Evaluated, and,
when the check is run by someone outside the author team, for Results
Reproduced. It cannot produce evidence for Results Replicated, which requires
an independent implementation and usually new data [acm-badging, peng2011].

| Outcome of our check | Badge the evidence supports | What is still missing |
| --- | --- | --- |
| Artifacts are deposited with a DOI or other persistent identifier | Artifacts Available | Nothing, if the identifier resolves and the deposit is archival |
| Environment built from the shipped recipe or lock file, workflow ran headlessly, outputs produced | Functional, if documentation and completeness also hold | A judgement on documentation quality, and a target comparison |
| Functional, plus outputs identical or within the stated tolerance for every claimed result | Results Reproduced, when the checker is not an author | Independence: a check run by the paper's own group is internal evidence only |
| Functional, plus the artifacts were readable and modifiable enough that a new question could be asked of them | Reusable | A reviewer's judgement, written down with what was reused |
| Environment built only after undocumented steps | None | The missing steps; the artifacts are not complete as shipped |
| Outputs diverge beyond tolerance | None | The divergence report, and an explanation from the authors |

A run whose environment could not be built from the artifacts is reported as
not reproducible with the list of missing steps, whatever the numbers looked
like afterwards [nap2019-reproducibility]. Grading stops at the weakest link.

## Rules we adopt

1. State the badge family, the badge name and the terminology version in every
   grade; never write "reproducible" as a bare adjective (from
   [acm-badging]).
2. Claim Results Reproduced only when the checker is outside the author team
   and the comparison output is attached (from [acm-badging],
   [nap2019-reproducibility]).
3. Never claim Results Replicated from a re-execution of the authors' code
   (from [acm-badging], [peng2011]).
4. Treat Available as a check on the deposit and its identifier, resolved and
   downloaded, not on the repository the work was developed in (from
   [acm-badging]).
5. Record what a badge would need that we did not check, so the grade is
   readable as evidence rather than as a verdict (from
   [nap2019-reproducibility]).
