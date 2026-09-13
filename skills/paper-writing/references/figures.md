---
topic: figures
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Figures for papers

Sources
- rougier2014 (CC0; excerpts allowed; fetched 2026-09-02)
- weissgerber2015 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- mensh2017 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- tufte-visual-display (book, proprietary; cite only, ideas from corpus/notes/tufte-visual-display.md)
- zobel-writing-for-computer-science (book, proprietary; cite only, ideas from corpus/notes/zobel-writing-for-computer-science.md)

This topic covers figures and tables in a manuscript: what each one is for,
which plot type fits which data, captions, and the integrity rules. Slide
figures are covered by `assertion-evidence` and `multimedia-principles`.

## What the evidence says

### Message first

- A figure exists to express one idea or result that words alone cannot; identify that message before designing, because the message guides every design choice [rougier2014].
- Know the audience: a figure for collaborators can skip steps, a figure for a journal must be correct and complete for a broad readership, a figure for students must explain a concept [rougier2014].
- Adapt the figure to the medium: a projected figure needs thicker lines, bigger text and fewer details; a journal figure can carry detail because the reader can study and zoom it; do not lift a paper figure into a talk unchanged [rougier2014].
- Figures and their titles are the most objective support for the steps of the argument and are viewed by readers who jump from the abstract; the figure title states the conclusion of the analysis and the legend explains how it was done [mensh2017].
- Drafting the figures and tables first and ordering them so that they alone tell the story is a way to fix the logical flow of the paper before writing [mensh2017].
- Zobel: every figure and table is referenced in the text and carries a self-contained caption; the plot type follows the message (lines for trends, bars for categories, log scales for wide ranges) (from notes) [zobel-writing-for-computer-science].

### Captions

- Captions are not optional: the caption explains how to read the figure, anticipates the questions a viewer would ask, and gives numeric values or points of interest that the graphic alone cannot convey [rougier2014].
- If numeric values matter, give them in the figure or elsewhere in the article; a reader must not have to estimate bar heights [rougier2014].

### Show the data, not only the summary

- In a review of 703 physiology papers, 85.6 percent used bar graphs for continuous data, mostly mean and standard error, while 13.4 percent used univariate scatterplots, 5.3 percent box plots and 8.0 percent histograms [weissgerber2015].
- Many different distributions produce the same bar graph; an apparent group difference can be driven by an outlier, a bimodal distribution or three observations, and the full data may point to a different conclusion than the summary [weissgerber2015].
- Bar graphs of paired data hide the pairing and whether changes are consistent within subjects; scatterplots of the paired values and of the differences show direction, magnitude and distribution of change [weissgerber2015].
- Showing standard error instead of standard deviation magnifies apparent differences, more so with unequal group sizes; summary statistics are only meaningful when there are enough data to summarize [weissgerber2015].
- Recommendation: for small samples show all points as univariate scatterplots; box plots and histograms need enough observations to be interpretable; choose the figure from the variable type, sample size and design (independent or paired) rather than field habit [weissgerber2015].
- Medians, not means, when a nonparametric test is used; for paired data report the median difference, since medians are not additive [weissgerber2015].

### Integrity

- A scientific figure is tied to its data; software defaults such as automatic rescaling can mislead even when axes are labeled, and pie charts and 3-D charts distort quantity comparisons; use the simplest plot that carries the message, with labels, ticks, a title and the full value range when relevant [rougier2014].
- Encoding a value in disc radius rather than area exaggerates ratios; truncating the y axis makes similar values look different, and labels do not undo the effect because the bars remain the most salient element [rougier2014].
- Tufte's lie factor: the size of the effect in the graphic must match the size of the effect in the data; show data in context, do not draw more dimensions than the data have, and mark any truncated axis (from notes) [tufte-visual-display].
- Tufte's graphical integrity extends to the data-ink ratio: erase non-data ink and redundant data ink; frames, gridlines, backgrounds and 3-D effects are the usual offenders (from notes) [tufte-visual-display].

### Defaults, color and clutter

- Do not trust the defaults: library defaults are good enough for any plot and best for none; every plot needs some manual tuning of size, fonts, ticks and colormap [rougier2014].
- Color is used with a reason: highlight one element in color against gray or black, otherwise keep black; do not use rainbow or jet colormaps; choose sequential, diverging or qualitative colormaps by the data type and avoid similar hues because of color blindness [rougier2014].
- Chartjunk is any visual element that adds nothing to the message: excess colors, labels, colored backgrounds, useless grids, legends that overlap data; save ink [rougier2014].
- A dense multi-series overlay with a legend box and too many ticks is one of the worst designs; splitting the series into small panels with direct labels, three ticks and the other series drawn lightly behind works in the same area [rougier2014].
- Small multiples with shared scales let the viewer compare many cases at once and are among the most powerful designs for scientific data; label directly on the plot and set text horizontally (from notes) [tufte-visual-display].
- Message trumps beauty: a sketch-style figure with no tick labels is right when only the shape of a hypothetical curve matters; aesthetics never come before readability [rougier2014].
- Field conventions for figures ease comparison across studies and help spot errors; when no standard exists, adapt (do not copy) a strong design from the literature [rougier2014].
- Use the right tool and export data to it; the plotting tool need not be the analysis tool. Matplotlib, R, Inkscape, TikZ, GIMP, ImageMagick, D3, Cytoscape and Circos are named as open-source options [rougier2014].
- Zobel: tables for exact values, aligned, with few rules; fonts consistent with the text; no decorative 3-D (from notes) [zobel-writing-for-computer-science].

## Rules we adopt

1. Every figure in the storyboard has a one-sentence message written before it is made; the figure title or first caption sentence states that message as a claim. Checked by the paper-writing skill (storyboard) and `paper_lint.py` (caption present and not a bare label). (from [rougier2014], [mensh2017])
2. Every figure and table is referenced in the text, and every reference resolves to a figure or table. Checked by `paper_lint.py`. (from [zobel-writing-for-computer-science], [mensh2017])
3. Captions state what is plotted, how it was computed, the sample size or number of runs, and what error bars or intervals show. Robert enforces in review; the storyboard template asks for each item. (from [rougier2014], [weissgerber2015])
4. Continuous data from small samples (under about 20 per group) are shown as individual points, with paired designs drawn as paired; bar graphs are for counts and categories only. Robert enforces; the storyboard asks for plot type and n. (from [weissgerber2015])
5. Axes start at zero for bar-like encodings or the break is drawn and named in the caption; area, not radius, encodes magnitude; no pie or 3-D charts. Robert enforces. (from [rougier2014], [tufte-visual-display])
6. Sequential or diverging colormaps for quantitative data, never rainbow; color only where it carries meaning; every palette readable by color-blind readers. Robert enforces. (from [rougier2014])
7. Comparisons across conditions, datasets or seeds use small multiples with shared axes and direct labels rather than one overlay with a legend. Robert enforces. (from [rougier2014], [tufte-visual-display])
8. Remove non-data ink: no frames, backgrounds, gridlines or redundant tick labels unless they aid reading a value. Robert enforces. (from [tufte-visual-display], [rougier2014])
9. Every figure is produced by a script under version control from a data file that the paper's repository contains or cites; the paper figure and the talk figure are separate outputs of that script. Checked by the experiment-tracking skill when available; until then Robert enforces. (from [rougier2014], [mensh2017])
10. Tables give exact values with aligned columns and minimal rules; if a table only shows a trend, it becomes a figure. Robert enforces. (from [zobel-writing-for-computer-science])

## Where sources disagree

- How much detail a journal figure may carry: Rougier and colleagues say a journal figure can be detailed because readers can zoom [rougier2014]; Tufte praises high data density [tufte-visual-display]; Weissgerber and colleagues want the full data shown [weissgerber2015]. There is no real conflict; all three reject decoration and accept data density. We favor dense, direct-labeled figures in papers and separate simplified versions for talks.
- Means with error bars: Weissgerber and colleagues would replace mean-and-SE bars for small samples entirely [weissgerber2015]; Zobel accepts bars for categorical comparisons [zobel-writing-for-computer-science]. We use bars for categories and counts, points for continuous data, and never SE without saying so and giving n.
- Whether a caption should carry the conclusion: Mensh and Kording put the conclusion in the figure title [mensh2017]; Rougier and colleagues describe the caption as the explanation of how to read the figure [rougier2014]. We do both: first sentence the claim, remaining sentences the reading instructions.

## Not covered

- Ontology and knowledge graph visualizations (class hierarchies, embeddings), which none of the sources treat; leave to judgement and to the field conventions of ISWC and ICBO.
- Journal-specific figure requirements (resolution, file type, column widths); read the guide to authors and record it in `assets/venues.md`.
- Accessibility beyond color blindness (alt text, screen readers).
- Interactive and web figures.
