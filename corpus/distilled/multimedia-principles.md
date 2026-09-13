---
topic: multimedia-principles
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Multimedia principles for slides and figures

Sources
- mayer-multimedia-learning (book, proprietary; cite only, ideas from corpus/notes/mayer-multimedia-learning.md)
- mayer-moreno2003 (proprietary; summary only, from knowledge, not fetched)
- naegle2021 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- rougier2014 (CC-BY-4.0; short excerpts allowed; fetched 2026-09-02)
- tufte-visual-display (book, proprietary; cite only, ideas from corpus/notes/tufte-visual-display.md)
- tufte-cognitive-style-powerpoint (book, proprietary; cite only, ideas from corpus/notes/tufte-cognitive-style-powerpoint.md)
- garner-alley2013 (proprietary; summary only, from knowledge, not fetched)

## What the evidence says

### How people process a slide

- Words and pictures are processed in two channels (verbal and pictorial), each with limited capacity, and learning needs active selection, organization and integration; design that ignores the limits wastes the audience's capacity [mayer-multimedia-learning].
- Three kinds of processing compete for capacity: extraneous processing caused by poor design, essential processing needed to hold the material, and generative processing that makes sense of it; the design goal is to cut the first, manage the second and leave room for the third [mayer-multimedia-learning].
- Mayer and Moreno describe overload scenarios and a remedy for each: off-loading words to narration when the visual channel is full, segmenting and pre-training when essential material is too much, weeding and signaling when extraneous material is present, aligning words with pictures and eliminating redundancy when both channels carry the same words (from knowledge of the source, not verified against the text) [mayer-moreno2003].
- Reading and listening share the verbal channel, so full sentences on a slide compete with the speaker; images and video use the pictorial channel and can accompany speech without overload [naegle2021].
- Assertion-evidence slides outperform bullet slides in comprehension tests, consistent with a sentence headline acting as a signal and visual evidence using the free channel (from knowledge of the source, not verified against the text) [garner-alley2013].

### Reducing extraneous processing

- Coherence: remove interesting but irrelevant words, pictures and sounds; decoration lowers transfer [mayer-multimedia-learning].
- Signaling: cues that show the organization (a sentence headline, arrows, highlighting) improve learning; the slide title is the strongest signal [mayer-multimedia-learning, naegle2021].
- Redundancy: graphics plus narration beats graphics plus narration plus the same text on screen; the effect reverses when the words are technical, the pace is slow, or the audience is non-native [mayer-multimedia-learning].
- Spatial contiguity: labels placed next to the part of the picture they describe beat legends or captions placed away from it [mayer-multimedia-learning].
- Temporal contiguity: show a picture at the moment it is spoken about, not several slides before or after [mayer-multimedia-learning].
- Chartjunk is unnecessary or confusing visual material (extra colors, labels, backgrounds, gridlines); remove elements that do not carry new information, while judging by context, because a gridline that clarifies a range in one figure is junk in another [rougier2014].
- Non-data ink and decoration lower the data-ink ratio; erase it, and never let the visual effect of a graphic exceed the size of the effect in the data [tufte-visual-display].
- Animations are universally disliked in surveys, burden visually impaired viewers and fail across software versions; use them only to direct attention to critical content, and never for decoration [naegle2021].

### Managing essential processing

- Segmenting: material presented in learner-paced pieces beats one continuous presentation; one idea per slide is this principle applied [mayer-multimedia-learning, naegle2021].
- Pre-training: introducing the names and properties of the key components before the explanation improves understanding; this is the basis for defining symbols, baselines and metrics before the slide that uses them [mayer-multimedia-learning].
- Modality: when pacing is fast, spoken words with graphics beat printed words with graphics; the speaker's voice carries the explanation, the slide carries the evidence [mayer-multimedia-learning].
- A multipanel figure from a paper is typically one panel per slide; a slide that cannot be presented in a minute has too many or too complex graphics [naegle2021].
- Slides hold far less information than a page, so a comparison chopped across slides is lost; a single figure with enough resolution to allow comparison beats several sparse ones [tufte-cognitive-style-powerpoint].

### Figures on slides

- Adapt the figure to the medium: for a talk, keep the design simple, make the message visually salient, use thicker lines, larger text and strong contrast, and avoid vertical text; make a separate version from the paper figure rather than reusing it [rougier2014].
- Identify the message of the figure before designing it; the message drives every choice, and a figure whose message is visible at first glance keeps the audience [rougier2014].
- Do not trust defaults: size, fonts, colors, ticks and markers are set for the plot, not left to the library [rougier2014].
- Use color to highlight, keeping other elements gray or black; choose sequential, diverging or qualitative colormaps by data type; check for color-blind readers [rougier2014].
- Do not mislead: avoid pie charts and three-dimensional plots, show full value ranges, watch automatic rescaling, include labels, ticks and titles, and ask a colleague what they read from the figure [rougier2014].
- Captions are not optional; they say how to read the figure and give the numbers that matter; on a slide the spoken caption states setup, what varies, what is measured and what to see [rougier2014, naegle2021].
- Message beats beauty: follow domain conventions so results can be compared, and be wary of infographic aesthetics that put style before content [rougier2014].
- Label directly on the plot rather than in a legend, set text horizontally, use small multiples with shared axes for comparisons across conditions, and never truncate an axis without a visible break and a sentence saying so [tufte-visual-display].
- Accessibility: high-contrast colors, simple backgrounds, sans-serif type at large sizes including figure legends, bold rather than italics or underlining or capitals for emphasis, and color-blind-safe palettes [naegle2021].

### Fostering generative processing and delivery

- Multimedia principle: words plus pictures beat words alone, which is why a text-only slide is the weakest slide [mayer-multimedia-learning].
- Personalization and voice: a conversational style and a human voice beat formal text and machine voice; a static picture of the speaker adds nothing [mayer-multimedia-learning].
- The principles matter most for novices and fast-paced presentations; experts are less affected and can be hurt by scaffolding they do not need [mayer-multimedia-learning].
- Speak clearly and at a steady pace, especially when captions are on; the slide carries the evidence, the voice carries the explanation [naegle2021].

## Rules we adopt

1. Slides carry visual evidence and spoken explanation; no slide contains a sentence the speaker will read aloud, and on-slide words are the title, labels and short guideposts (from [mayer-multimedia-learning], [naegle2021], [garner-alley2013]).
2. Remove every element that does not carry the slide's message: decoration, logos beyond the template, side stories, unused panels, gridlines and frames on plots (from [mayer-multimedia-learning], [rougier2014], [tufte-visual-display]).
3. Labels sit next to what they label; legends are replaced by direct labels where space allows (from [mayer-multimedia-learning], [tufte-visual-display]).
4. Define components before the explanation: every symbol, metric, baseline and acronym is introduced on or before the slide that uses it (from [mayer-multimedia-learning]).
5. One panel per slide from multipanel paper figures, unless the comparison itself is the message, in which case one figure with shared axes shows the comparison on one slide (from [naegle2021], [tufte-cognitive-style-powerpoint]).
6. Talk figures are rebuilt from the paper figure with thicker lines, larger type, horizontal text, strong contrast and a color-blind-safe palette; the paper version is not pasted in (from [rougier2014], [naegle2021]).
7. Every figure slide states, in the spoken caption or a one-line guidepost, the setup, what varies, what is measured and what to see; the claim must match the pixels (from [rougier2014], [naegle2021]).
8. No pie charts, no three-dimensional plots, no truncated axes without a visible break; the visual effect never exceeds the data effect (from [rougier2014], [tufte-visual-display]).
9. No animations except to direct attention to a critical element; decks are exported to PDF (from [naegle2021]).
10. Sans-serif type, high contrast, bold for emphasis, no italics or all capitals, and figure text legible from the back of the room (from [naegle2021], [rougier2014]).

## Where sources disagree

- Redundant text: [mayer-multimedia-learning] finds on-screen text redundant with narration harmful in general, but reports the effect reverses for technical terms, slow pacing and non-native audiences; [naegle2021] finds brief redundant text improves retention. We allow short guideposts and labels that repeat key terms, and forbid sentences that repeat the narration.
- Density: [tufte-visual-display] praises high data density and dense handouts, while [naegle2021] limits slides to about six elements. We follow the six-element limit for slides and keep density for the paper and the handout; a dense comparison figure counts as one element when it has one message.
- Audience expertise: [mayer-multimedia-learning] reports weaker effects for experts; [garner-alley2013] and the 2023 pilots report gains for expert audiences too. We keep the rules for every audience and relax only the element count for specialist committees.
- Legends: [rougier2014] accepts legends with a good colormap, [tufte-visual-display] prefers direct labels. We prefer direct labels and accept a legend when the plot has too many series to label.

## Not covered

- No source gives effect sizes for the multimedia principles measured on scientific conference audiences; the evidence base is classroom and laboratory learning.
- Interactive figures, live demonstrations and notebook walkthroughs are not treated by any source.
- No source gives guidance on equations on slides beyond treating them as visual evidence.
- Dark versus light themes, projector color shifts and room lighting are not covered; the render-and-look step in the presentation skill is the only check.
- Accessibility guidance in [naegle2021] is a set of recommendations, not tested rules; no source gives measured thresholds for font size or contrast on projected slides.
