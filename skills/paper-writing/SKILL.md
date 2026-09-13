---
name: paper-writing
description: Structure-and-checks layer for a research manuscript, on top of the local write-edit-scientific-paper skill (which owns the prose). Produces the one-message sentence and working title, the paragraph-level outline, the figure storyboard, the CRediT contributions table, a venue shortlist from assets/venues.md and the submission checklist, and runs scripts/paper_lint.py (abstract shape, contribution paragraph, section order and balance, unreferenced figures, orphan citations, undefined acronyms, missing statements, house style) and scripts/cite_check.py (every bibliography entry against Crossref and PubMed; offline consistency mode). Use when asked "plan the paper", "what is the one message", "outline the paper for X", "storyboard the figures", "who is an author and in what role", "which venue should this go to", "is this ready to submit", "lint the manuscript", "check the references". Never rewrites prose, never reviews other people's papers, never submits or announces.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 and PyYAML; paper_lint.py needs no network; cite_check.py reaches api.crossref.org and eutils.ncbi.nlm.nih.gov unless --offline; reads only the manuscript directory it is pointed at.
metadata:
  borg-role: researcher
  grounding: bourne2005, credit, dome2021, frassl2018, gopen-swan1990, heard-scientists-guide-to-writing, icmje, mensh2017, miro2018, neurips-checklist, plaxco2010, romano2020, rougier2014, schimel-writing-science, tufte-visual-display, weissgerber2015, whitesides2004, zhang2014, zobel-writing-for-computer-science
  hermes:
    category: research
    tags: paper, manuscript, outline, figures, credit, venue, submission, citations
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(git log *) Bash(git diff *)
---

# Paper writing

This skill owns the skeleton of a paper and the deterministic checks on it:
one message, outline, figure storyboard, contributions, venue, submission
checklist, `paper_lint.py` and `cite_check.py`. Everything written in
sentences is done by `write-edit-scientific-paper`; everything after
acceptance is done by `new-paper`. The evidence behind the skeleton is in the
three references.

## Related skills

- `write-edit-scientific-paper` (`~/.claude/skills/write-edit-scientific-paper`): owns drafting and rewriting, the section-specific structures (introduction argument, methods for reproduction, results in hypothesis-how-finding-meaning-bridge order, discussion), the five editing passes, AI-marker removal and Robert's prose style (`references/robert-scientific-style.md` there). When a finding here is about wording or paragraph logic, hand it to that skill by name; do not fix prose in this skill.
- `new-paper` (`~/.claude/skills/new-paper`): owns everything once a paper is accepted or out: Crossref metadata, both BibTeX trees, the knowledge graph, both websites, the social thread. This skill stops at the approval bead for submission.
- `write-paper-review` (`~/.claude/skills/write-paper-review`): owns referee reports on other people's papers, including the hidden-text scan. This skill is author-side only; an internal pre-submission read of a group manuscript in Robert's referee voice is that skill's job, invoked on the PDF.
- `delegation`: turns the plan's milestones into beads. `code-audit`: the software and repository checks behind a software paper's availability statement. `presentation`: talk figures; the storyboard here is for the paper only.

## When to use

- A project has results and someone asks what the paper is, where it goes, or who writes what.
- Before drafting: the outline and storyboard are agreed before prose exists.
- Before an internal review, a resubmission or a submission: the two scripts run and the checklist is filled.
- A student asks "is this ready" or Robert asks "what is missing from this manuscript".

## Procedure

1. Facts: locate the manuscript source, its repository, the runs and figure scripts behind the results, and the project entry in `~/pa` or `~/org`. Every plan row cites one of these; unknowns are questions for the author.
2. One message: create `PLAN.md` next to the manuscript from `assets/paper-plan.md` and fill the first section (contribution sentence, working title that states it, reader, what the reader can do afterwards, the one figure that carries it). If the sentence cannot be written, stop and open a bead; the paper is not ready to outline.
3. Venue: from `assets/venues.md` list two or three candidates with article type, limit, deadline and required statements, one line of reasoning each. Robert decides. Copy the chosen venue's constraints from its guide to authors into the plan.
4. Outline: one informal sentence per paragraph in the plan table, results statements first (each becomes a subsection heading or figure title), then approach summary, introduction paragraphs narrowing to the gap, discussion paragraphs (findings, one limitation each, what the work enables), abstract in five moves. Each row names its evidence and owner. The paragraph-internal structure is the write-edit skill's business.
5. Storyboard: one row per figure and table with message, plot type and why it fits the data, data source, n, what error bars show, and the regenerating script. No figure is made without its row.
6. Contributions: copy `assets/credit-roles.md` to `CREDIT.md`, list authors by the ICMJE criteria, assign CRediT roles, record author order and acknowledged non-authors, and note when and where authorship was agreed. Disagreements become a `needs:robert` bead.
7. Timeline: final deadline, milestones with owners (outline, figures, draft, outside read, coauthor approval, submission), writing strategy, data management statement. Milestones go to the delegation skill as beads.
8. Draft: invoke `write-edit-scientific-paper` per section from the outline rows. When the outline changes during drafting, update the plan first.
9. Lint: `python3 scripts/paper_lint.py paper/main.tex` (or `.md`; `--bib` when the bibliography is not declared in the source, `--acronyms` for venue terms, `--json` for the cockpit). Fix errors at their file:line in the manuscript or the plan, never in the script; wording findings go to the write-edit skill. A warning that is wrong in context is recorded in the checklist with the reason.
10. References: `python3 scripts/cite_check.py paper/refs.bib --only-cited paper/main.tex --cache runs/<id>/cites.json --mailto <robert's address>`. Mismatches, unresolvable DOIs and retractions are fixed by correcting or removing the entry. `--offline` when the network is unavailable or the manuscript is local-only; say so in the checklist.
11. Checklist: copy `assets/submission-checklist.md` to `CHECKLIST.md` and fill every row with a pointer or a reason. Field checklists apply by paper type: NeurIPS items for any machine learning claim, DOME for supervised learning on biological data, MIRO for an ontology, the software items for a tool paper.
12. Approval: one bead for Robert quoting the checklist, the lint summary line, the cite_check summary line and the coauthor approval evidence. Submission, coauthor mail and editor enquiries are Robert's; after acceptance, `new-paper` takes over.

## Hard rules

- No outbound contact: coauthor approval requests, editor enquiries and submissions are prepared as text in an approval bead; Robert sends them.
- No invented facts: every plan row, statement and reference has a source; an entry `cite_check.py` cannot verify is flagged, never kept silently.
- The scripts never modify the manuscript or the bibliography; they report file:line, severity and fix.
- Manuscripts with patient, student or personnel data are privacy `local-only` until Robert clears them; `cite_check.py` runs `--offline` on them.
- Disclosure statements about AI assistance are written by Robert, never generated.
- Venue templates win over house style where they conflict (Title Case headings in a template are not an error); no em-dashes and no meta phrases hold everywhere.
- This skill does not write or rewrite sentences and does not restate the write-edit skill's rules; it names that skill and hands over.

## Outputs

- `PLAN.md`, `CREDIT.md`, `CHECKLIST.md` next to the manuscript, from the three asset templates.
- Lint and reference reports on stdout or `--json`, kept under `runs/<id>/` when a bead drives the work.
- Beads: milestones for the delegation skill; `needs:robert` for authorship disagreements, venue choice and the submission approval.

## Grounding

- `references/paper-writing.md`: one message, context-content-conclusion, abstract and introduction shape, time allocation, venue choice, authorship (ICMJE, CRediT) and the collaborative process.
- `references/figures.md`: message-first figures, captions, showing the data rather than bars, integrity (lie factor, truncated axes, color), small multiples, chartjunk.
- `references/reporting-standards.md`: required statements, the NeurIPS checklist, DOME, MIRO, software and data availability.

## Scripts

- `scripts/paper_lint.py --help`: structural lint of a .tex or .md manuscript; file:line, severity, fix; `--json`; exit 1 on errors; read-only.
- `scripts/cite_check.py --help`: BibTeX consistency and Crossref/PubMed verification; `--offline` for consistency only; `--only-cited`, `--cache`; exit 1 on errors; writes only its cache file.

## Assets

- `assets/paper-plan.md`: plan template (one message, venue, outline, storyboard, contributions, timeline).
- `assets/credit-roles.md`: the 14 CRediT roles, table template and statement wording.
- `assets/submission-checklist.md`: filled before every submission.
- `assets/venues.md`: hand-maintained venue table; the current rows are examples for Robert to correct.
- `assets/acronyms.txt`: acronyms `paper_lint.py` accepts without a definition.
