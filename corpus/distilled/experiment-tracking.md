---
topic: experiment-tracking
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Experiment tracking

Sources
- sandve2013 (CC-BY-4.0; short excerpts allowed)
- rule2019 (CC-BY-4.0; short excerpts allowed)
- dodge2019 (CC-BY-4.0; short excerpts allowed)
- pineau2021 (CC-BY-4.0; short excerpts allowed)
- mitchell2019-model-cards (proprietary; summary only, no quotes)
- gebru2021-datasheets (proprietary; summary only, no quotes)
- heil2021 (proprietary; not fetched, summarised from knowledge, verify before quoting)

## What the evidence says

### Every result needs a record of how it was produced

- Whenever a result may be of interest later, record how it was produced: for each step, the program name and version, the exact parameters and the exact inputs. Getting from raw data to a final result usually involves many interrelated steps, and the pre- and post-processing steps are often as critical as the central one [sandve2013].
- Prose documentation of a sequence of steps drifts out of sync with the analysis as it was actually run. Specifying the workflow in an executable form (a shell script, a makefile, a workflow system) keeps the specification and the run identical [sandve2013].
- The stated minimum is to record enough about programs, parameters and manual procedures that you could approximately reproduce the result yourself in about a year [sandve2013].
- Manual data manipulation is inefficient, error-prone and hard to reproduce. Replace format tweaking and copy-paste between documents with converters that can be re-enacted; when a manual step is unavoidable, note which files were modified or moved and why [sandve2013].
- Sandve et al. treat exact archiving of external program versions as necessary because input and output formats change between versions, a newer version may not run at all on the old inputs, and old versions are often hard to obtain later [sandve2013].
- Version control every custom script. Without a systematic archive of a script's evolution, backtracking to the code state that produced a given result can be hopeless, which casts doubt on whether the result came from a bug [sandve2013].
- Record intermediate results, in standard formats where possible. They expose discrepancies early, show the effect of alternative parameter choices, allow parts of a pipeline to be rerun, and let an inconsistency be traced to the step where it arose [sandve2013].

### Seeds and randomness

- Analyses that involve randomness give slightly different results on every run, but the same initial seed makes all drawn random numbers equal and the run exactly repeatable, so the seed must be recorded [sandve2013].
- Observing that a result reproduced exactly is strong evidence that the procedure was reproduced; observing approximate agreement supports almost nothing. The minimum is to note which steps involve randomness so that an expected level of discrepancy is known in advance [sandve2013].
- In machine learning, the random seed is part of the hyperparameter space rather than a detail outside it, alongside architecture sizes and learning rates [dodge2019].
- Reported gains have failed to survive different random initializations of the same models, which is one of the documented sources of the reproducibility gap in machine learning [pineau2021].

### Figures, tables and the raw data behind them

- A figure is modified many times between first generation and publication. If the raw data behind each figure is stored so that it can be retrieved for a given figure, the plotting step can be changed without redoing the analysis, and fine values can be read from the numbers rather than the image [sandve2013].
- Where plotting is more than direct visualization, store both the underlying data and the processed values that are actually drawn; for a histogram that means the pre-binning values and the bin counts. With a command-based plotting system, store the plotting code too [sandve2013].
- The minimum for any plot is a note of which data formed its basis and how that data could be reconstructed [sandve2013].
- Textual claims and the results supporting them live in separate places, notes and emails on one side, files on a server on the other. Connect a statement to its underlying result at the moment the statement is first written, by file path or result id, because reconstructing the link later is difficult and error-prone [sandve2013].
- Rule et al. advise producing publication-ready figures from the analysis code rather than tweaking figures by hand in desktop publishing tools [rule2019].

### Notebooks

- Interactively editing and rerunning cells can delete steps or introduce hidden state that confounds the analysis and confuses readers; notebooks cannot be rerun by others unless dependencies are frozen, data shared and the environment described [rule2019].
- Document explorations as they happen, including the dead ends, rather than waiting for a solid result. By then the reason for a parameter value, the source of a copied block or what was interesting about an intermediate result has usually been forgotten [rule2019].
- Manage dependencies with a package or environment manager that can emit a file such as `environment.yml` or `requirements.txt`, work only inside an environment created from that file so no undocumented dependency creeps in, and additionally print the versions of critical dependencies inside the notebook itself [rule2019].
- Notebooks are JSON, so version control diffs are unreadable; use a notebook-aware diff tool or commit a converted `.py` form [rule2019].
- Restart the kernel and run all cells as a habit and as the final test of a result, because interactivity makes accidental deletion of a step easy [rule2019].
- Keep a static HTML or PDF rendering of every executed notebook in the archived repository; if the execution stack stops working in twenty years, that rendering is still the readable record [rule2019].

### Reporting a machine learning experiment

- Test-set scores alone do not support a claim that one model beats another. Which model wins depends on the computational budget spent searching hyperparameters, and Dodge et al. show published comparisons whose conclusion would flip at a different budget [dodge2019].
- Their reporting checklist asks, for every experimental result: a description of the computing infrastructure, the average runtime of each approach, the train, validation and test splits, the validation performance corresponding to each reported test number, and a link to the code [dodge2019].
- For experiments with hyperparameter search it additionally asks for the bounds of each hyperparameter, the configuration of the best model, the number of search trials, the method used to choose values and the criterion used to select among them, and a measure of the mean and variance as a function of the number of trials [dodge2019].
- Reporting is not the same as running more experiments: the expected validation performance curve is computed from runs already carried out during hyperparameter search, at no extra compute [dodge2019].
- In a sample of fifty EMNLP 2018 papers with modeling experiments, no paper reported every checklist item. Splits were reported by 92% and best hyperparameter assignments by 74%, but code by 30%, computing infrastructure by 18%, search strategy by 14%, score distribution by 10%, number of trials by 10%, and search bounds by 8% [dodge2019].
- Because a claim of superiority is only valid at a stated budget, a comparison against a leaderboard entry that reports test scores alone cannot be checked without spending test evaluations. Dodge et al. therefore ask leaderboards to report validation performance too [dodge2019].
- Pineau et al. list the recurring causes of irreproducible machine learning results: no access to the same training data, under-specified models or training procedures, missing or buggy code, under-specified metrics, improper statistics, selective reporting with adaptive overfitting, and conclusions that outrun the evidence [pineau2021].
- Their terminology separates four things: reproducible (same data, same tools), replicable (different data), robust (same data, different analysis or reimplementation) and generalisable (different data and different tools) [pineau2021].
- The NeurIPS 2019 machine learning reproducibility checklist asks for a clear description of the mathematical setting, algorithm and model; for every figure and table of empirical results, a description of how the experiments were run; a clear definition of the measure or statistic reported; error bars; and results stated with central tendency and variation [pineau2021].
- Author responses showed the gap between wanting rigor and reporting it: 87% said they defined their metrics clearly, yet 36% judged error bars not applicable to their results [pineau2021].
- Availability of code is not a guarantee that the code is correct, and reimplementation from the description has its own value; but verifying a result with the original code is far easier than producing it from nothing [pineau2021].
- Confidential data and proprietary libraries are the standard objections to a code submission policy. One workable mitigation is to report the same method on an open benchmark alongside the results on the closed data [pineau2021].
- Heil et al. propose graded reproducibility standards for machine learning in the life sciences, with a lowest tier of data, model and code being available, a middle tier adding recorded seeds, versions and data splits, and a highest tier where a single command re-executes the analysis end to end [heil2021].

### Model cards and datasheets

- Mitchell et al. propose a short document accompanying a trained model whose sections are model details (developer, date, version, type, training algorithm and parameters, paper, citation, license, contact), intended use (primary intended uses, primary intended users, out-of-scope uses), factors, metrics (performance measures, decision thresholds, approaches to uncertainty and variability), evaluation data (datasets, motivation, preprocessing), training data, quantitative analyses (unitary and intersectional results), ethical considerations, and caveats and recommendations [mitchell2019-model-cards].
- Their factors section separates the factors believed relevant from the factors actually evaluated, and asks why they differ when they do; groups, instrumentation and environment are the three families they name [mitchell2019-model-cards].
- They ask explicitly how metric values were estimated, for example whether a number is an average of five runs or ten-fold cross-validation, and for confidence intervals on disaggregated metrics [mitchell2019-model-cards].
- Training data details may be impossible to release for proprietary or legal reasons; the model card then carries the distribution over factors rather than nothing, and the section is not a demand to publish private information [mitchell2019-model-cards].
- Comparing the two versions of a toxicity classifier in their examples shows how much a model changes between releases, which is their argument for a card per model version [mitchell2019-model-cards].
- Gebru et al. propose a datasheet per dataset, with questions grouped by lifecycle stage: motivation, composition, collection process, preprocessing and cleaning and labeling, uses, distribution, and maintenance [gebru2021-datasheets].
- The composition questions include what an instance represents, how many there are, whether the set is a sample of a larger population and how representative it is, whether splits are recommended and why, what errors and noise are known, and whether the dataset depends on external resources that may change or disappear [gebru2021-datasheets].
- The preprocessing questions ask whether the raw data was kept alongside the cleaned data to support unanticipated future uses, and whether the cleaning software is available [gebru2021-datasheets].
- The uses section asks what the dataset should not be used for, and what a consumer needs to know about its composition or collection to avoid unfair or harmful applications [gebru2021-datasheets].
- Questions that apply only to data about people are grouped at the end of each section, and Gebru et al. ask for a broad reading of what relates to people: any dataset of text written by people qualifies [gebru2021-datasheets].
- They recommend answering as many questions as possible, marking unanswerable ones as unknown, rather than skipping the datasheet [gebru2021-datasheets].

### Public access at the end

- The final rule of Sandve et al. is that input data, scripts, versions, parameters and intermediate results should all be publicly and easily accessible, with the minimum being main data and source code as supplementary material plus a willingness to answer requests [sandve2013].
- Rule et al. propose a tiered release when the raw data is too large or too sensitive to publish: a public copy of an anonymized or medium-sized subset with a DOI, plus further processed datasets alongside the notebooks, so the later stages of the analysis stay reproducible [rule2019].

## Rules we adopt

1. Every run writes a manifest before it writes results: run id, command line, git commit and dirty flag, seeds, config hash, input paths with sizes and hashes, environment, start and end time, exit status, output artifacts with hashes (from [sandve2013], [dodge2019], [pineau2021]).
2. Set and record a seed for every step that uses randomness, including data splits, initializations and sampling. A run with an unrecorded seed is reported as unreproducible; the seed is never invented after the fact (from [sandve2013], [dodge2019]).
3. Never rewrite or delete an experiment output. Corrections are new runs with new ids; the superseded run keeps its manifest and is marked superseded (from [sandve2013]).
4. A result produced from a dirty working tree carries the dirty flag in its manifest and in any figure caption derived from it, and it is not cited in a paper until it has been reproduced from a clean commit (from [sandve2013], [heil2021]).
5. Record the data version, not just the path: a hash for a file that fits, plus an explicit version or date stamp for a directory or database snapshot that does not (from [sandve2013], [gebru2021-datasheets]).
6. Every figure and table in a manuscript maps to one run id through an explicit mapping file. A figure with no traceable run is a finding, not a formatting detail (from [sandve2013]).
7. Store the numbers behind every plot next to the plot, and generate the final figure from code rather than by hand editing (from [sandve2013], [rule2019]).
8. Report the whole Dodge checklist for any machine learning result we publish: infrastructure, runtime, splits, validation performance beside each test number, code link, hyperparameter bounds, best configuration, number of trials, search method and selection criterion, and variation across trials (from [dodge2019]).
9. Report central tendency and variation with the number of runs behind them. A single run without a stated seed and count is a preliminary observation, never a comparison (from [pineau2021], [dodge2019]).
10. A claim that one method beats another states the budget under which the comparison holds; results at different budgets are reported as such rather than merged (from [dodge2019]).
11. Freeze dependencies in a lock or requirements file, run only inside the environment created from it, and record the resolved versions of the key packages in the run manifest (from [rule2019], [pineau2021]).
12. Restart and run all cells before a notebook result is quoted anywhere, and archive a rendered copy of the executed notebook with the run (from [rule2019]).
13. Every released model gets a model card with the Mitchell sections, and every dataset we create gets a datasheet with the Gebru sections; a card is written per model version, not per project (from [mitchell2019-model-cards], [gebru2021-datasheets]).
14. An unanswerable card or datasheet field is marked unknown with the reason. It is never filled by guessing (from [gebru2021-datasheets]).
15. The audit reports paths, sizes and hashes only. Data content, sample rows and anything about people never leave the machine on which the run lives (from [gebru2021-datasheets], and the repository privacy rules).

## Where sources disagree

- How much to store: [sandve2013] asks for all intermediate results to be archived whenever storage allows, while [rule2019] accepts a tiered release in which only serialized key intermediates and a processed subset survive. We follow Sandve locally (keep intermediates on the group storage while a project is active) and Rule for publication (tiered release with a DOI on the shareable tier).
- What reproducibility requires: [pineau2021] treats sharing the original code as central, but also records the objection that shared code reproduces its own mistakes and that reimplementation from the description tests something different. We ship the code and treat an independent reimplementation as a stronger, separate result rather than a substitute.
- Effort versus deadline: [sandve2013] concedes that publication pressure creates a real trade-off, since most analyses never yield a result, while [rule2019] and [heil2021] push documentation up front. We resolve this by making the manifest automatic and cheap, so the tracked path is the path of least effort.
- Comparison fairness: [dodge2019] argues there may be no way to make a comparison fair, because hyperparameter spaces, prior human tuning and per-trial cost all differ, and therefore focuses on reporting what was actually run. [pineau2021] leans more on checklists that imply comparable practice. We report the budget and the search space and decline to claim a fair comparison we cannot construct.

## Not covered

- No source gives a manifest schema. The field list in `assets/run.yaml.example` is our choice, assembled from the reporting checklists.
- None of these sources covers cluster job records (Slurm ids, node names, GPU models) or how to reconcile a scheduler's accounting with a run manifest.
- Hashing policy for very large inputs is unaddressed: [hart2016] recommends hashes for integrity but none of these sources says what to do when hashing a multi-terabyte input costs more than the run.
- How long to keep superseded runs, and who deletes them, is a group storage decision with no evidence here.
- None of these sources addresses experiments whose outputs are themselves models too large to archive, or the provenance of a fine-tuned model derived from a third-party checkpoint.
- Nothing here covers privacy-restricted experiments where even the input path names are sensitive; that case falls under the repository's local-only class.
