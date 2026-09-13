# Change log

One row per manuscript change. `where` is a section, figure, table, equation
or line range, and line ranges say which version they belong to. `prompted by`
lists the comment ids from `split_reviews.py`; leave it empty for a change we
made on our own. `run` holds the script, data version and seed behind any new
number.

| id | what changed | where | prompted by | run |
| --- | --- | --- | --- | --- |
| CL-1 | added the ablation over embedding size | Section 3.4, Table 2 | R1.2 | `scripts/ablate.py --seed 7`, data v3 |
| CL-2 | rewrote the scope paragraph | Introduction, lines 44 to 58 (revised) | R1.1, R2.1 | |
| CL-3 | corrected the axis label | Figure 3 | R2.5 | |
