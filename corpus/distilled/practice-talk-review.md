---
topic: practice-talk-review
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Practice talks and how to review them

Sources
- bourne2007-oral (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- naegle2021 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- erren-bourne2007 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- alley-assertion-evidence (web, proprietary; summary only; fetched 2026-09-02)
- alley-craft-of-scientific-presentations (book, proprietary; cite only, ideas from corpus/notes/alley-craft-of-scientific-presentations.md)
- doumont-trees-maps-theorems (book, proprietary; cite only, ideas from corpus/notes/doumont-trees-maps-theorems.md)
- tufte-cognitive-style-powerpoint (book, proprietary; cite only, ideas from corpus/notes/tufte-cognitive-style-powerpoint.md)

The review mode of the local `presentation` skill
(~/Public/software/skills/local/presentation/SKILL.md) is the authority on how
Robert reviews a deck: render every slide, read the paper and the code, check
narrative, mechanism, provenance, figures, definitions, style, the
advertisement test and timing, and propose restructuring before rewording.
This file gives the evidence for running a practice talk and for writing the
review in that style.

## What the evidence says

### Why rehearse, and how

- Practice matters most for inexperienced speakers; a rehearsed talk stays on its planned content, avoids tangents and avoids presenting unfamiliar material [bourne2007-oral].
- Important talks are given first to collaborators in a lab meeting before the real audience; more talks make better speakers [bourne2007-oral].
- Rehearsal checks two things: that the important points (titles, guideposts) are identified consistently every run, and that transitions between consecutive slides keep the story flowing [naegle2021].
- Rehearsal exposes the common defects: overstuffed slides that break the one-minute rule, non-essential detail, and forgotten references [naegle2021].
- Practicing in front of peers or lab members brings fresh eyes to content, design and coherence [naegle2021].
- Rehearse standing, out loud, with the real slides and a timer, several times; rehearse the transitions and the first minute until they are automatic (from knowledge of the book, see notes) [alley-craft-of-scientific-presentations].
- Recordings of one's own talks reveal rule violations that are easy to see and hard to fix; breaking habits takes deliberate work [bourne2007-oral].
- Time the talk: acknowledgments and questions need time too, so the timed run must include them [bourne2007-oral].

### What a good talk does, and therefore what a reviewer checks

- Talk to the audience: know their background, tailor the content to what they want, and keep eye contact [bourne2007-oral].
- Less is more: a clear main message that provokes questions; no questions means the talk was either incomprehensible or trivial [bourne2007-oral].
- Only talk when there is something to say: do not present preliminary or dull material to fill the slot [bourne2007-oral].
- The take-home message persists: the audience should recall three intended points a week later [bourne2007-oral].
- Be logical: a story with a beginning, middle and end, closing with an unmistakable take-home message [bourne2007-oral].
- Open with why the audience should listen (context, need, object of the talk), show the map, signpost transitions, and close by restating the messages [doumont-trees-maps-theorems, alley-craft-of-scientific-presentations].
- Each slide's title states its message; a distracted listener should get the main point from the slide alone [naegle2021].
- One minute per slide and one idea per slide; a slide that overruns in rehearsal is split or cut [naegle2021].
- Every element on a slide is discussed, or removed to a backup slide after the acknowledgments [naegle2021].
- Visuals appear about once a minute and provide evidence rather than duplicate the speech; the speaker does not read them [bourne2007-oral].
- A critical result must never sit under a reassuring title or at the bottom of a bullet hierarchy; the title states what the evidence shows [tufte-cognitive-style-powerpoint].
- For a defense, present a slice of the work at a followable pace and say plainly that it is a slice; place the slice in the whole with an overview diagram [alley-assertion-evidence].
- Acknowledge contributors meaningfully, at the start or when their contribution appears, without gratuitous lists [bourne2007-oral].
- Prepare for failure: export a PDF, keep screenshots of key video frames, avoid animations that may not play [naegle2021].

### Delivery and questions

- Treat the floor as a stage only in a way that fits the speaker's natural style; forced humor hurts [bourne2007-oral].
- Speak clearly at a steady pace and volume, more so when captioning is used [naegle2021].
- Handle a question by restating it, answering the part you can, and saying plainly what you do not know; rehearse the likely questions (from knowledge of the book, see notes) [alley-craft-of-scientific-presentations].
- Speakers who build sentence-headline slides understand their material better and project more confidence, which the audience sees [alley-assertion-evidence].

### Posters

- A poster review checks purpose (what the viewer should do), the ten-second sell, a headline that poses or answers the decisive question, an abstract-shaped layout with prominent conclusions, guided reading order, type of at least 24 point, figures readable at two levels, and contact details [erren-bourne2007].
- A poster rehearsal is a two-minute walk-through for a passer-by plus the answers to the three questions a specialist will ask [erren-bourne2007].

### The review deliverable

- Review from rendered slides, never from source alone; every page is looked at, and every figure is rendered large enough to check the caption against the plot (presentation skill; supported by the figure rules in [naegle2021]).
- Structure before wording: a bad deck is usually a structural problem (order, missing introduction of an experiment, mechanism appearing after the number) rather than a phrasing problem, so the review gives a diagnosis and a slide-by-slide plan first [doumont-trees-maps-theorems, bourne2007-oral].
- Slide-numbered comments let the speaker act on each point and let the reviewer check the fix on the re-rendered deck; the format is a numbered list keyed to slide numbers with one defect and one fix each (group practice, consistent with rehearsal checks in [naegle2021]).
- The advertisement test: a conference talk is an advertisement for the paper; the review checks for a hook in the first two slides, one memorable number, limitations stated plainly, and citation and repository at the end [bourne2007-oral, erren-bourne2007].
- Timing versus slide count: the count is compared with the minutes available at about one slide per minute, and each slide is timed in the rehearsal [naegle2021, bourne2007-oral].
- Q&A defensibility: every claim on every slide must survive a question using only the slide and the paper; this matters most when presenting a co-author's work [alley-craft-of-scientific-presentations, tufte-cognitive-style-powerpoint].

## Rules we adopt

1. Every conference talk, defense and job talk is rehearsed in front of the group at least once, at least one week before the event, with a timer, questions and a written review (from [bourne2007-oral], [naegle2021]).
2. The reviewer renders every slide to an image and reads the paper (and the code where the talk rests on it) before commenting; comments from the source file alone are not accepted (from [naegle2021], presentation skill).
3. The written review is a slide-numbered list; each entry names one defect and one fix, and structural problems come before wording (from [doumont-trees-maps-theorems], [bourne2007-oral]).
4. The review checks, in order: narrative (one message per slide, running example, nothing used before it is introduced), mechanism before number, provenance of each ingredient, figure audit against pixels, definitions, style, advertisement test, timing versus slide count (presentation skill; from [naegle2021], [bourne2007-oral], [tufte-cognitive-style-powerpoint]).
5. The speaker states the three take-home points before the rehearsal; the audience writes down what they remember afterwards; a mismatch is a review finding (from [bourne2007-oral]).
6. The timed run includes acknowledgments and a mock question period; a run more than 10 percent over time triggers cuts, not faster speech (from [bourne2007-oral], [naegle2021]).
7. Transitions and the first minute are rehearsed separately; the reviewer records where the story broke between slides (from [alley-craft-of-scientific-presentations], [naegle2021]).
8. Slides with a reassuring title over negative or ambiguous evidence, or with an undefined term, block sign-off until fixed (from [tufte-cognitive-style-powerpoint], [naegle2021]).
9. Posters get the same review with the poster-specific checklist: purpose, ten-second sell, headline, reading order, 24-point minimum, two-level figures, contact details, and a rehearsed two-minute walk-through (from [erren-bourne2007]).
10. The deck goes to the event as PDF with backup slides after the acknowledgments and screenshots of any video (from [naegle2021]).

## Where sources disagree

- Slide count: [naegle2021] plans one slide per minute; [bourne2007-oral] plans one visual per minute and warns that less is more; Robert's presentation skill budgets about 12 content slides per 15 minutes. We use the presentation skill's budget for conference talks and the one-per-minute rule as the upper bound.
- Entertainment: [bourne2007-oral] encourages treating the floor as a stage where it fits the speaker; [doumont-trees-maps-theorems] treats anything not carrying the message as noise. We judge anecdotes by whether they carry the message and fit the speaker; the review flags forced ones.
- Defense scope: [alley-assertion-evidence] presents a slice of the dissertation; KAUST committees expect the whole contribution to be visible. We present the whole in the map and the slice in depth, and say so on the map slide.
- Handouts: [tufte-cognitive-style-powerpoint] wants a dense handout instead of dense slides; the other sources do not. For talks we point to the paper; for lectures the lecture-design topic decides.

## Not covered

- No source tests how many rehearsals produce the largest gain or how far before the event they should happen; one week and one group rehearsal are group choices.
- No source treats online talks, hybrid rooms or pre-recorded videos.
- Reviewing a talk given in a second language, or for an audience with mixed language competence, is not covered.
- The sources give no guidance on how to review talks presented on behalf of a co-author beyond general defensibility; the presentation skill's rule stands alone.
- Nothing in the sources measures the effect of written slide-numbered reviews versus oral feedback; the format is group practice.
