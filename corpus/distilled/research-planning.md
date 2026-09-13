---
topic: research-planning
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Research planning

Sources
- schwab2022 (CC-BY-4.0; short excerpts allowed)
- kass2016 (CC-BY-4.0; short excerpts allowed)
- osborne2014 (CC-BY-4.0; short excerpts allowed)
- platt1964 (proprietary; not fetched, summarised from knowledge)
- heilmeier-catechism (web page, public domain; questions quoted)

This file covers turning a chosen question into a written plan. Choosing the
question itself is covered in `problem-choice.md`; the machine learning
validity rules are in `ml-rigor.md`.

## What the evidence says

### The plan is a document written before the data are seen

- A study protocol records at minimum the research question and hypothesis, the population, the targeted sample size, inclusion and exclusion criteria, the design, the data collection, the data processing and transformation, and the planned statistical analyses [schwab2022].
- Registering the protocol reduces publication bias and hindsight bias, and lets a reader compare what was reported against what was planned; discrepancies such as outcome switching become visible [schwab2022].
- Registration does not freeze the work: a more detailed analysis plan may be amended before the data are observed or unblinded, and exploratory analyses stay allowed as long as they are reported as exploratory [schwab2022].
- Registered reports move peer review to before the results exist, so reviewers can still change the design and the analysis [schwab2022].
- The level of detail a plan needs depends on whether the study is confirmatory or exploratory; exploratory work should not be reshaped into a confirmatory frame afterwards [schwab2022].
- Planning has to happen earlier than the question "what should my n be": an experienced statistician steps back and asks what the ideal outcome of the experiment would be and how it would be interpreted [kass2016].
- Fisher's remark, quoted by Kass and colleagues, is that consulting a statistician after the experiment is often asking for a post mortem [kass2016].

### Hypotheses and the experiment matrix

- Strong inference is a loop: write out alternative hypotheses, devise an experiment whose possible outcomes each exclude at least one of them, run it cleanly, then repeat with the hypotheses that survive (from knowledge of the source, not verified against the text) [platt1964].
- The plan takes the shape of a conditional tree written before the work starts: at each node the outcome decides which branch is taken next, so the next experiment is already chosen when the result arrives (from knowledge of the source, not verified against the text) [platt1964].
- Holding several working hypotheses at once protects against attachment to one idea, and the operational test of a planned experiment is the question of what result would disprove the hypothesis (from knowledge of the source, not verified against the text) [platt1964].
- Analytical thinking about which experiment would be decisive is cheap compared with running experiments, so time spent on the tree pays for itself (from knowledge of the source, not verified against the text) [platt1964].
- The method should be chosen from the scientific question, not from the shape of the data; inexperienced users ask which test to use, while experienced ones start from the question and consider several ways the data might answer it [kass2016].
- Statistical software provides tools to assist analyses, not to define them, and a paper must explain why a method answers the question rather than only naming the package [kass2016].
- Simplicity first: start with simple approaches and add complexity only as needed, and only as little as seems essential; good design often lets simple analyses give strong results [kass2016].

### Checkpoints, thresholds and cost

- Two of the eight Heilmeier questions ask "How much will it cost?" and "How long will it take?", and the last asks "What are the mid-term and final 'exams' to check for success?" [heilmeier-catechism].
- The catechism also asks "What are the risks?", which places a risk list inside the plan rather than in a post hoc discussion [heilmeier-catechism].
- The questions exist to make the proposer understand context, cost and effort before the program starts [heilmeier-catechism].

### Sample size, variability and assumptions

- An underpowered study is a problematic study whatever its outcome: it risks a false negative, and when a small study does reach significance the effect size is likely overestimated [schwab2022].
- Sample size calculation needs a primary outcome and the magnitude of effect that would matter; power is usually set at 80% or more, and the calculation should be run under several assumptions with the largest result taken as the safer bet [schwab2022].
- Planning by desired precision, for example the width of a confidence interval for the targeted effect, is a worthwhile alternative to planning by null hypothesis testing [schwab2022].
- Every reported number would change if the measurements were repeated; each new day, lab, batch or protocol change adds a source of variability that has to be accounted for and reported [kass2016].
- Standard errors computed as if observations were independent usually understate the real uncertainty, and independence is the assumption that most often fails [kass2016].
- Big data does not remove these problems: uncertainty assessments in large collections tend to be overly optimistic, and many measurements on few samples are usually dependent [kass2016].

### Data and its quality are part of the plan

- Pre-processing has effects that easily go unnoticed, so the plan states how the data are cleaned, what the units are, how missing values are coded and what rule handles non-detects [kass2016].
- Why data are missing matters: loss through a mechanism related to the outcome, such as the most affected participants dropping out, produces misleading results [kass2016].
- Exploratory plots and simple summaries early on reveal quality problems and outliers, and cut losses before a large analysis is built on bad data [kass2016].
- Using a single dataset both to generate and to test a hypothesis is a problem the plan has to solve in advance [kass2016].
- A data management plan is one of the ten rules of good research practice, alongside the protocol and the sample size justification [schwab2022].

### Planning the computation

- Before writing code, check what already exists: a software literature review over repositories and the surrounding research network establishes whether the method has been implemented already [osborne2014].
- Build a prototype, a simplified version of the full system, to gain insight and guide the next steps, and build up incrementally so each element can be tested [osborne2014].
- Keep a logbook of commands and decisions from the start, and automate by the rule of three: once you have done the same thing twice, automate it [osborne2014].
- Understand the numerical and mathematical methods being used, including convergence and stability, so that results are not artefacts of the method [osborne2014].
- Version control everything, test everything with a framework rather than by looking at whether results seem roughly right, and turn each fixed bug into a test [osborne2014].
- Plan the visual components from day one; figures are how hypotheses are developed and checked, not only how they are presented [osborne2014].
- Plan to share code, data and results, and treat "people would find mistakes in it" as an argument for sharing rather than against [osborne2014].
- Reproducibility is the achievable standard when independent replication is not: given the same data and a complete description of the analysis, the tables, figures and inferences can be regenerated [kass2016].
- Replication with new data is the only reliable answer to data snooping; where it is impossible, reproducibility is the minimum [kass2016].

### Failure modes the plan has to design against

- Questionable research practices named in the literature include low statistical power, pseudoreplication, repeated inspection of data, p-hacking, selective reporting and hypothesizing after the results are known [schwab2022].
- Low power and pseudoreplication are prevented at the planning stage, by the sample size calculation and by choosing methods that do not treat dependent data as independent [schwab2022].
- Bias enters at every stage: in the design, in the execution and in the reporting, and specific designs prevent specific biases, such as randomization with allocation concealment against allocation bias and objective rather than self-reported measurements against information bias [schwab2022].
- Inference after an extensive look at the data no longer has its usual meaning; Kass and colleagues compare it to painting a target around where the arrow landed [kass2016].
- A statistically significant p-value does not imply a relevant effect, and dichotomizing at 0.05 invites cherry-picking; exact p-values interpreted in a graded way are the recommendation [schwab2022].
- A nonsignificant result is not a null result: absence of evidence is not evidence of absence, and only when every value in the interval is practically unimportant may a result be described as null [schwab2022].
- Negative findings must be reported; in one analysis 96% of records reported at least one significant p-value, and positive studies were four times more likely to be published [schwab2022].
- Reporting guidelines exist for each study type and are listed by the EQUATOR network; the plan names the guideline it will follow before the work starts [schwab2022].

## Rules we adopt

1. Every project has a written plan before the main experiments run: question, hypotheses, experiment matrix, data, analysis, thresholds, risks, kill criteria, owners and dates. The plan is dated and kept in the repository. Checked by the research-planning skill. (from [schwab2022], [heilmeier-catechism])
2. The plan names at least two competing hypotheses and, for each experiment, the outcome that would exclude one of them. An experiment whose every possible outcome is compatible with every hypothesis is cut. Checked by `scripts/plan_to_beads.py`. (from [platt1964])
3. Every experiment in the matrix carries a baseline it must be compared against, a success threshold stated as a number before the run, and a kill criterion that says what result ends this line of work. Missing any of the three, the plan is rejected. Checked by `scripts/plan_to_beads.py`. (from [heilmeier-catechism], [platt1964], [kass2016])
4. Thresholds are set from what would matter scientifically, not from what the method is expected to reach; the plan states the reasoning in one sentence. (from [schwab2022], [kass2016])
5. The plan states for each experiment whether it is confirmatory or exploratory. Exploratory experiments carry no significance claim and are reported as exploratory. (from [schwab2022])
6. Sample size or dataset size is justified before the work: a power calculation, a precision target, or an explicit statement that the dataset is fixed and what that costs in power. Checked by the research-planning skill. (from [schwab2022], [kass2016])
7. The analysis is chosen from the question and written down before the data are seen, including how missing data, batches and dependence between observations are handled. Later changes are recorded as dated amendments with a reason. (from [kass2016], [schwab2022])
8. Every reported quantity is planned together with its uncertainty; a plan that promises a single number without a spread is incomplete. (from [kass2016])
9. Simple first: the plan starts from the simplest model or analysis that could answer the question and adds complexity only where the plan says why it is needed. (from [kass2016])
10. The data section names the source, the licence and privacy class, the cleaning steps, the unit conventions, the missing value coding, and the split that keeps hypothesis generation apart from hypothesis testing. (from [kass2016], [schwab2022])
11. Before implementing anything, the plan records the search for existing implementations and says why a new one is needed. (from [osborne2014])
12. Each computational experiment is planned as a prototype first, under version control, with tests and a logbook entry, so a result can be regenerated from the recorded commands. (from [osborne2014], [kass2016])
13. The plan lists risks with a probability and an impact, and each risk that would end the project has a mitigation or a fallback experiment. (from [heilmeier-catechism], [schwab2022])
14. The plan names mid-term checkpoints with dates: what will be measured, by when, and which result means continue, revise or stop. Checkpoints become beads with acceptance criteria. Checked by `scripts/plan_to_beads.py`. (from [heilmeier-catechism], [platt1964])
15. Cost is planned: compute, storage, licences, wall time and the person days, with the budget stated per experiment. (from [heilmeier-catechism], [osborne2014])
16. The plan names the reporting guideline it will follow and commits to reporting every experiment in the matrix, including the ones that failed. (from [schwab2022])
17. A result that came out of repeated looks at the same data is labelled as such in the plan's log and is confirmed on held-out or new data before it becomes a claim. (from [kass2016], [schwab2022])

## Where sources disagree

- How much to fix in advance: [schwab2022] wants a registered protocol with planned analyses, while [kass2016] describes exploratory data analysis, the "tinkering", as often the most informative part of the work. We resolve this by planning both: the confirmatory experiments are fixed in the plan, and exploration is allowed and labelled, with any finding from it re-tested before it becomes a claim.
- Where planning effort goes: [platt1964] puts it into the logical tree of hypotheses and crucial experiments, [schwab2022] into the protocol and sample size, [osborne2014] into prototypes, tests and version control. These are complementary layers, and our plan template has a section for each.
- Statistical significance as a threshold: [schwab2022] argues against dichotomizing at 0.05 and asks for graded interpretation, while practical planning needs a stated success threshold before the run. We keep a numeric threshold as a stopping rule for the group's own decisions and require the paper to report effect sizes with uncertainty rather than a significance verdict.
- Complexity: [kass2016] asks for the simplest adequate model, [osborne2014] warns against underestimating the complexity of the computational task. We read them as consistent: the scientific model stays simple, the engineering around it is planned as larger than it looks.

## Not covered

- None of these sources tells us how to plan a project whose main risk is that a dataset arrives late from a collaborator, which is the most common cause of slippage in this group.
- The sources give no rule for how many experiments a matrix should hold, or how to choose between breadth over baselines and depth on one comparison.
- Kill criteria are not treated in any source as a research management device; the concept here comes from the catechism's "exams" question plus the group's own practice, and the wording of the rules is our choice.
- Planning for ontology and knowledge graph work, where the artefact is a resource rather than an experiment, is not covered; success criteria for such projects are set by hand.
- The proprietary and unfetched sources ([platt1964]) are summarised from knowledge, and the details should be checked against the text before a claim rests on them alone.
- Cost planning for GPU compute, queue time and storage at KAUST is not addressed by any source here.
