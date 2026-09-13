---
name: talk-design
description: >-
  Designs and reviews scientific talks for the lecturer role: an assertion-evidence outline, a slide-numbered plan, and a practice-talk review in Robert Hoehndorf's style. Use when asked to "outline a talk", "plan my seminar", "turn this paper into a talk", "review my practice talk", "critique these slides", "make a slide plan", or "help me rehearse a presentation". It plans and reviews content; use the separate presentation skill for deck styling and construction.
license: CC-BY-4.0
compatibility: Requires python3 >= 3.12 for slide_lint.py. frames_to_png.sh uses bash; rendering a .tex deck also needs latexmk and pdftoppm. Both helpers are local only and never contact a service.
metadata:
  borg-role: lecturer
  grounding: alley-assertion-evidence, alley-craft-of-scientific-presentations, bourne2007-oral, doumont-trees-maps-theorems, erren-bourne2007, garner-alley2013, mayer-moreno2003, mayer-multimedia-learning, naegle2021, tufte-cognitive-style-powerpoint
  hermes:
    category: teaching
    tags: talk, slides, rehearsal, assertion-evidence, lecturer, review
    requires_toolsets: terminal, file
allowed-tools: Read Grep Glob Bash(python3 *) Bash(bash *)
---

# Talk design

Design the argument before making slides. A good result has three linked
artifacts: an assertion-evidence outline, a slide plan, and a review of a
timed practice talk. The separate `presentation` skill is the authority for
Robert's deck style, visual design rules, compilation, and full rendered-deck
review. Use it when building or restyling a deck. This skill does not repeat
or override those rules.

## When to use

- A speaker has a paper, results, or a research question and needs a seminar,
  conference talk, defense segment, journal-club talk, or keynote plan.
- Robert asks for an argument outline before slides are made, or a
  slide-numbered restructuring plan for an existing deck.
- A speaker has a practice recording or rendered slides and needs feedback on
  content, flow, timing, delivery, or questions.

Do not use this skill to choose themes, fonts, layouts, or deck mechanics.
Hand those choices to `presentation`. Use `lecture-design` for a class session
whose primary outcome is learning activity rather than a research talk.

## Required inputs

Ask for the audience, allotted speaking time, setting, central claim, and the
material that supports it. For a review, also ask for the deck source or PDF,
the underlying paper or data, and either a recording or observed timings. Do
not invent evidence, an audience's prior knowledge, or a result not supported
by the supplied material.

If the materials contain student assessments, personnel information, health,
or other local-only content, keep the whole review local-only and do not put
it in a bead. This skill never sends invitations, feedback, or the deck to an
audience.

## Procedure

1. State the audience's decision or question and the talk's three take-home
   points. Limit the argument to claims the speaker can defend in questions.
   Read the paper, figures, and code when they underlie the claims. Identify
   the mechanism before the headline number.
2. Make an assertion-evidence outline before planning slides. For each
   section, write: the audience question, its one-sentence answer, the visual
   or result that supports it, why it matters, and the transition to the next
   answer. Start with context and need, show the map, then close by returning
   to the three take-homes. Keep the outline at three to five top-level
   sections.
3. Turn the outline into a slide plan in this exact, slide-numbered form:

   ```text
   01. Assertion title: a complete, defensible sentence.
       Evidence: figure, diagram, table, or short demonstration and its source.
       Speaker move: what to explain, not a script to read.
       Time: estimated seconds. Transition: link to slide 02.
   ```

   Give each content slide one idea and a statement title. Plan about one
   minute per content slide as an upper bound, then reserve time for the
   opening, acknowledgments, questions, and pauses. Put details needed only in
   questions into backup slides after the conclusion. Use the same example or
   problem through the talk when it makes the mechanism concrete.
4. Before a deck is built, check the plan for dependency order: define every
   term, metric, baseline, dataset, and experiment before it is used. Each
   figure entry names its provenance, what varies, what is measured, and the
   claim its pixels support. Reorder or cut a slide whose assertion has no
   evidence.
5. Hand the approved plan to `presentation` for construction or visual
   changes. For a Beamer or Markdown draft, run:

   ```text
   python3 skills/talk-design/scripts/slide_lint.py path/to/deck.tex
   python3 skills/talk-design/scripts/slide_lint.py path/to/deck.md --json
   ```

   The linter treats statement titles, source and caption credits, slide
   numbers, sentence case, and em-dashes as errors. Its density thresholds are
   warnings: four bullets, twelve words per bullet, and forty body words per
   slide. Fix an error in the deck, not by suppressing the finding. The
   linter checks source conventions, not whether a figure's claim is true.
6. Run a practice talk standing up, aloud, with the actual deck, a timer, and
   questions. Render selected Beamer PDF pages for focused inspection:

   ```text
   bash skills/talk-design/scripts/frames_to_png.sh talk.tex \
     --frames 1,3-5 --out runs/talk-frames --apply
   ```

   The renderer is a local helper. Its selected frame numbers are rendered PDF
   page numbers, so overlays may occupy more than one page. It prints a clear
   dependency error if LaTeX or Poppler is unavailable. Use `presentation` to
   render and inspect every slide for a full deck review.
7. Deliver a practice-talk review in Robert's slide-numbered style. Start
   with a short diagnosis and timing result. Then write one actionable entry
   per issue, in priority order:

   ```text
   Slide 07: The result arrives before the experiment and metric are defined.
   Fix: insert the experiment map before this slide, then state the result as
   the answer to that map's question.
   ```

   Review structure before wording. Check the hook and map, dependency order,
   mechanism before results, provenance, title-to-evidence match, undefined
   terms, transitions, the three take-homes, timing, delivery, and likely
   questions. Separate blocking changes from optional polish. Record the
   slide number, observed problem, and concrete fix for every finding.
8. End the review with a re-run request: the revised deck, a new timed run,
   and three audience members' recalled take-homes. Do not treat faster speech
   as a timing fix. If the run exceeds the time by more than ten percent, cut
   or split material and rehearse again.

## Hard rules

- Every content title is a complete assertion, not a topic label. The body
  proves or explains that assertion. A title that is more confident than its
  evidence is rewritten or the slide is removed.
- Slide plans cite the source of every borrowed figure, data result, and
  diagram. A source label is not proof that the claim matches the figure;
  inspect the axes, comparisons, and uncertainty before approving the claim.
- Put an explicit map near the start, signal each major transition, and close
  with the take-homes. Do not introduce a number, method, acronym, or
  experiment before its explanation.
- Do not review a deck from source alone. Review rendered slides and the
  underlying evidence. When that evidence is missing, say so and limit the
  review to structure and presentation.
- Practice feedback is Robert-facing unless a valid contact grant authorizes
  its delivery. Preparing feedback does not authorize sending it.

## Grounding

- `references/talk-design.md`: evidence and adopted rules for argument,
  assertion-evidence structure, audience fit, and timing.

## Scripts

- `scripts/slide_lint.py --help`: read-only Beamer or Markdown linter with
  text and JSON reports. It exits 1 when it finds an error.
- `scripts/frames_to_png.sh --help`: renders selected PDF pages from a Beamer
  source or PDF after `--apply`; dry-run is the default.
