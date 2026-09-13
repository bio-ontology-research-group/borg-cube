---
topic: ml-rigor
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Rigor in machine learning studies

Sources
- kapoor-narayanan2023 (CC-BY-4.0; fetch returned no text, summarised from knowledge)
- reforms2024 (CC-BY-4.0; not fetched, summarised from knowledge)
- dome2021 (proprietary; not fetched, summarised from knowledge)
- chicco2017 (CC-BY-4.0; fetch returned no text, summarised from knowledge)
- ioannidis2005 (CC-BY-4.0; short excerpts allowed)
- kass2016 (CC-BY-4.0; short excerpts allowed)
- dodge2019 (CC-BY-4.0; short excerpts allowed)
- pineau2021 (CC-BY-4.0; short excerpts allowed)

Claims marked as summarised from knowledge were not verified against a fetched
text. They are usable for planning but must be checked before they are quoted
in a paper.

## What the evidence says

### Leakage is the main way a model study goes wrong

- A systematic review across many fields found a large number of published papers whose reported performance was inflated by leakage between training and evaluation, and the same errors recurred independently in each field (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].
- Leakage is grouped into three kinds: no clean separation between training and test data, the use of features that would not be available at prediction time, and a test set that does not come from the distribution the claim is about (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].
- The first kind includes preprocessing, imputation, normalization or feature selection performed over the whole dataset before splitting, duplicate records shared between splits, and tuning on the test set (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].
- The third kind includes temporal leakage, where the model sees data from after the prediction time, and dependence between train and test records such as the same patient, the same protein family or the same gene in both (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].
- Where leakage was corrected, complex models often lost their advantage over simple baselines, so the reported gain belonged to the error and not to the method (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].
- The proposed remedy is a model information sheet filled in before publication that forces the authors to state, for each leakage type, why it does not apply (from knowledge of the source, not verified against the text) [kapoor-narayanan2023].

### Consensus reporting standards for machine learning studies

- The consensus recommendations cover the study goals, computational reproducibility, data quality, data preprocessing, modeling including baselines and comparisons, data leakage, metrics and evaluation, and the limits of generalization (from knowledge of the source, not verified against the text) [reforms2024].
- The standard asks that model comparisons be made under comparable conditions and that uncertainty in the reported performance be quantified rather than a single number given (from knowledge of the source, not verified against the text) [reforms2024].
- The four reporting blocks for supervised learning in biology are data, optimization, model and evaluation; each block has questions an author answers so a reader can judge whether the result is credible (from knowledge of the source, not verified against the text) [dome2021].
- Under data, the recommendations ask for provenance, size, class balance, and independence between training and evaluation sets including redundancy between them; under optimization, for the hyperparameters, the search, the regularization and the evidence about overfitting; under model, for the type, the interpretability and where the code and trained model live; under evaluation, for the performance measure, the comparison against a baseline, the confidence intervals and the handling of class imbalance (from knowledge of the source, not verified against the text) [dome2021].
- Practical tips for machine learning in computational biology include checking class balance before anything else, keeping a validation set separate from the test set, comparing against a simple baseline method, preferring measures that survive class imbalance over plain accuracy, using cross-validation, scaling features consistently, and having a domain expert read the result for biological sense (from knowledge of the source, not verified against the text) [chicco2017].

### A comparison is only meaningful with its budget

- Test-set scores alone do not support a claim that one model is better; the model that wins can change with the computational budget spent on hyperparameter search [dodge2019].
- The authors show cases in the literature where the conclusion about which model is better would have been reversed with more or less search, and one case where about 18 GPU days of search were needed to reach the published number, a budget the original paper did not report [dodge2019].
- Their proposal is to report expected validation performance of the best model found as a function of the search budget, which needs no computation beyond the search already done [dodge2019].
- A comparison between a model with a large budget and one with a small budget cannot attribute the difference to the model; the difference may be the budget [dodge2019].
- In a sample of fifty conference papers with experiments, none reported every checklist item, and 10% or fewer reported hyperparameter search bounds, the number of search trials, or measures of central tendency and variation [dodge2019].
- A reproducibility checklist deployed at a large machine learning conference asks for a clear description of the model and setting, a description of how experiments were run, a clear definition of the measure used, error bars, and results with central tendency and variation [pineau2021].
- Of the submissions, 97% claimed a clear description of the setting and 89% a description of how experiments were run, but 36% judged error bars not applicable to their results while 87% saw value in defining the metric [pineau2021].
- Reviewers who read the checklist answers were more confident in their assessment, and the program combined the checklist with code submission and a reproducibility challenge rather than relying on any one of them [pineau2021].

### Why most published findings in a search-heavy field are false

- The probability that a research finding is true depends on the prior odds that the tested relationship is real, the power of the study, and the level of bias, not on the p-value alone [ioannidis2005].
- The smaller the studies in a field, and the smaller the effects, the less likely a positive finding is to be true [ioannidis2005].
- The greater the number and the lesser the selection of tested relationships, the less likely a finding is to be true; high-throughput discovery work that tests very many relationships has a very low probability of any single positive being real [ioannidis2005].
- The greater the flexibility in designs, definitions, outcomes and analytical modes, the less likely the findings are to be true, because flexibility turns negative results into positive ones [ioannidis2005].
- More teams working on the same hot question makes any single team's positive finding less likely to be true, because each team races to publish its most impressive positive result [ioannidis2005].
- Very large and very significant effects should prompt a search for what went wrong rather than excitement, because in most modern fields they are more likely to be signs of bias [ioannidis2005].
- The remedies named are better powered evidence, aiming large studies at questions where the prior probability is already high, adherence to common standards to reduce flexibility, upfront registration, and judging the totality of the evidence rather than one team's result [ioannidis2005].
- Data snooping invalidates the usual interpretation of an inference, and the only reliable answer is to record the procedure and repeat it on new data [kass2016].
- Standard errors that ignore dependence between observations substantially understate the real uncertainty [kass2016].

## Rules we adopt

1. Every experiment names its baseline before it runs, and the baseline is a method a reader would expect to work: the published state of the art where one exists, and always at least one simple method (a linear model, a frequency or similarity rule, a random or majority predictor). A result without a baseline is not reported. Checked by `scripts/plan_to_beads.py`. (from [kapoor-narayanan2023], [chicco2017], [dome2021])
2. Splits are made before any preprocessing, imputation, normalization, feature selection or class balancing, and every such step is fit on the training split alone. (from [kapoor-narayanan2023], [chicco2017])
3. The split is made at the level of the dependence structure, not the row: by patient, by gene, by protein family or sequence identity, by species, by document, by time. The plan names the grouping and the reason. (from [kapoor-narayanan2023], [dome2021])
4. Duplicates and near duplicates are searched for across splits and the count is reported, including redundancy between training and evaluation sets. (from [kapoor-narayanan2023], [dome2021])
5. Any feature that would not exist at prediction time, or that encodes the label through a proxy, is listed and excluded; the plan states for each leakage type why it does not apply. (from [kapoor-narayanan2023])
6. The test set is used once, at the end. Model selection and hyperparameter search use a validation split or cross-validation. A test result that follows more looks is labelled as such and does not become a claim. (from [chicco2017], [kass2016], [ioannidis2005])
7. Model comparisons state the search budget for every model compared, including the baselines, and the budgets are comparable. A claim that a model is better than one given a smaller budget is not made. (from [dodge2019])
8. Reported performance carries uncertainty: variation over seeds, folds or bootstrap samples, with the number of runs given. A single number with no spread is not a result. (from [dodge2019], [pineau2021], [kass2016])
9. Metrics are chosen for the class balance and the use of the prediction, and the balance is reported. Accuracy alone is not used on imbalanced data. (from [chicco2017], [dome2021])
10. Hyperparameter ranges, the search method, the number of trials and the selected values are recorded for every model in the comparison, baselines included. (from [dodge2019], [dome2021])
11. Data, code, environment and trained model are archived so that every table and figure can be regenerated from the recorded commands. (from [pineau2021], [dome2021], [kass2016])
12. The plan states the distribution the claim is about and what would break it; a claim of generalization needs an evaluation set from that distribution, for example a later time period, another cohort or another organism. (from [kapoor-narayanan2023], [reforms2024])
13. The number of comparisons made across the whole project is tracked, and a finding from a search over many relationships is treated as a hypothesis to test, not as a result. (from [ioannidis2005], [kass2016])
14. A large and surprising improvement triggers a leakage check before it is written up: recheck the split, the features, the duplicates and the evaluation code. (from [ioannidis2005], [kapoor-narayanan2023])
15. Before submission, the reporting checklist for the venue is filled in, plus the data, optimization, model and evaluation questions, and every item answered "not applicable" carries a reason. (from [dome2021], [reforms2024], [pineau2021])
16. A domain expert reads the result and says whether it makes biological sense; a model that is right for a reason nobody can state stays a preliminary result. (from [chicco2017])

## Where sources disagree

- The value of checklists: [pineau2021] reports that only about a third of reviewers found the checklist answers useful and gives no evidence that the program improved paper quality, while [reforms2024] and [dome2021] propose exactly such instruments. We use the checklist as an internal gate before submission rather than as a claim of quality.
- What to do about many comparisons: [ioannidis2005] treats the number of tested relationships as a reason to distrust findings and asks for larger, better powered studies; [kass2016] accepts extensive exploration as informative and asks for replication afterwards. We follow [kass2016] for exploration and [ioannidis2005] for the interpretation, which is why an exploratory finding is a hypothesis until it is re-tested.
- Fair comparison: [dodge2019] argues there may be no simple way to make a comparison fair, since hyperparameter spaces and implementation effort differ; [dome2021] and [chicco2017] ask plainly for a comparison against a baseline. We require both a baseline and the budget that was spent on it, and we state the caveat rather than claiming fairness.

## Not covered

- None of these sources covers evaluation of ontology embeddings, knowledge graph completion or semantic similarity, where the dependence structure between train and test entities is graph shaped and neither a patient split nor a time split applies.
- Leakage through a shared pretraining corpus, where an evaluation set may already be inside a foundation model's training data, is not addressed by sources of this age.
- The sources give no rule for how much of an improvement over a baseline is worth reporting, only that a baseline must exist.
- Evaluation of generative and free-text outputs, where there is no ground truth label, is outside all of these sources.
- Four of the sources ([kapoor-narayanan2023], [reforms2024], [dome2021], [chicco2017]) were not available as text in the corpus and are summarised from knowledge; their exact items and wording must be checked against the originals before they are cited in a paper.
