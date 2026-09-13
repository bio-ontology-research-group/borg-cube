# Proposal outline

The order follows the eight catechism questions, which is also the order in
which a reader decides whether to keep reading. Use it for the KAUST research
proposal, a grant section or a one-page project brief. Confirm the required
sections, page limit and committee rules with Robert before submission; the
manifest entry for the KAUST format carries no verified source yet.

## Sections

1. Objective (about half a page). What we are trying to do, in plain language, with no term a computer scientist or biologist outside the subfield would have to look up.
2. Current practice and its limits (1 page). How the question is answered today, by whom, and where those answers fail. Every claim carries a citation verified by DOI.
3. Approach (2 to 3 pages). What is new, and why it should work. The competing hypotheses, and for each the result that would exclude it.
4. Significance (half a page). Who can do or understand something new if this succeeds, and what they can do with it.
5. Experiment matrix (2 pages). One row per experiment: hypotheses tested, data, baselines, metric, success threshold, kill criterion, owner, effort, date. The table from `plan.yaml` renders directly here.
6. Data and reproducibility (half a page). Sources, licences, privacy class, splits and the dependence structure they respect, the leakage checks, where code and results are archived.
7. Risks (half a page). Likelihood, impact, mitigation or fallback for each; the risks that would end the project stated first.
8. Cost and timeline (half a page). Compute, storage, person days and wall time per experiment, against the degree or grant timeline.
9. Checkpoints (quarter page). Dates, what is measured on each date, and which result means continue, revise or stop.
10. References. Verified by DOI, in the venue's style.

## Checks before submission

- Every experiment in the matrix has a baseline, a threshold with a number, and a kill criterion.
- The objective section survives being read aloud to someone outside the field.
- No claim about prior work rests on memory; each has a citation that was checked.
- The timeline leaves slack for at least one failed experiment.
- The reporting guideline the work will follow is named.
