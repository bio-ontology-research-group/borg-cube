# Model card: <model name>, version <n>

One card per model version, not per project. Fields come from Mitchell et al.
2019 (`references/experiment-tracking.md`). A field that cannot be answered is
marked `unknown` with the reason; it is never filled by guessing. Nothing in a
card is a claim without a run id behind it.

- Card written: <date>
- Card written by: <name>
- Run ids behind every number in this card: <run ids from the manifest>

## Model details

- Developed by: <person or group, and the entity on whose behalf>
- Model date: <date the model was trained>
- Model version: <version, and how it differs from the previous one>
- Model type: <architecture in one line>
- Training algorithm, parameters, fairness constraints, features: <one paragraph>
- Paper or resource: <DOI or URL>
- Citation: <how to cite this model>
- License: <license of the weights and of the code>
- Contact: <where to send questions>

## Intended use

- Primary intended uses: <the tasks this model was built for>
- Primary intended users: <who is expected to run it>
- Out-of-scope uses: <what it must not be used for, and the nearest model that fits those cases>

## Factors

- Relevant factors: <groups, instrumentation, environment that could change performance, and how they were identified>
- Evaluation factors: <the factors actually reported below, and why these; state why relevant and evaluated factors differ when they do>

## Metrics

- Performance measures: <metrics reported, and why these rather than others>
- Decision thresholds: <thresholds used, and why>
- Uncertainty and variability: <how the numbers were estimated: number of seeds, cross-validation folds, confidence intervals>
- Budget: <hyperparameter trials, search method, search bounds, selection criterion, runtime, hardware>

## Evaluation data

- Datasets: <name and version of each evaluation set>
- Motivation: <why these sets>
- Preprocessing: <what was done to the data before evaluation>
- Datasheet: <link to the datasheet for each set>

## Training data

- Datasets and versions: <name and version, or the distribution over factors when the data cannot be described in full>
- Splits: <how train, validation and test were separated, and what prevents leakage between them>
- Datasheet: <link>

## Quantitative analyses

- Unitary results: <performance per evaluated factor, with variation>
- Intersectional results: <performance across combinations of factors, with variation>
- Baselines: <what the model is compared against, at what budget>

| slice | n | metric | value | variation | run id |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |

## Ethical considerations

- Sensitive data: <does the model use data about people or other protected categories>
- Human life: <could the model inform decisions about health, safety or livelihood>
- Mitigations: <what was done to reduce risk during development>
- Risks and harms: <who could be harmed, how likely, how badly; state explicitly when this is unknown>
- Fraught use cases: <known applications that would be problematic>

## Caveats and recommendations

- <groups absent from the evaluation data>
- <further testing the results suggest>
- <ideal characteristics of an evaluation set for this model>
- <known failure modes>

## Reproduction

- Commit: <git commit, and whether the tree was clean>
- Seeds: <every seed>
- Environment: <lock file and its hash>
- Command: <the exact command that trained this model>
- Manifest: <path to the run manifest entry>
