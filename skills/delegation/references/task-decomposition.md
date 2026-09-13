---
topic: task-decomposition
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Task decomposition

Sources
- crossley2025 (CC-BY-4.0; short excerpts allowed)
- google-small-cls (CC-BY-3.0; short excerpts allowed)
- scrum-guide2020 (CC-BY-SA-4.0; short excerpts allowed)
- invest-wake2003 (proprietary blog post; summary only, no quotes)
- anthropic-multi-agent-research (proprietary; summary only, no quotes)
- hhmi-bwf-making-the-right-moves (proprietary; not fetched, summarised from knowledge)
- grove-high-output-management (book, proprietary; cite only, ideas from corpus/notes/grove-high-output-management.md)

## What the evidence says

### Properties of a good work item

- Wake's INVEST acronym lists six properties of a good user story: independent
  (schedulable in any order, non-overlapping), negotiable (captures the
  essence, details settled in conversation), valuable (to the customer, not
  only to the developer), estimable (understood well enough to size), small
  (at most a few person-weeks, some teams a few days) and testable (the author
  could write a test for it) [invest-wake2003].
- Wake pairs INVEST for stories with SMART for the tasks a story is broken
  into: specific, measurable (the team can agree it is done), achievable by its
  owner, relevant to the story, and time-boxed so people know when to ask for
  help [invest-wake2003].
- Wake treats an estimate of more than a month as a symptom that the scope is
  not understood, and recommends splitting off a time-boxed spike to learn
  enough to estimate the rest [invest-wake2003].
- Wake argues that a customer who cannot say how to test a story reveals that
  the story is unclear or not valuable; writing the tests before implementation
  makes teams more productive [invest-wake2003].
- When a story is split, Wake recommends slicing vertically through all layers
  so each slice delivers something the customer can see, rather than
  finishing one layer at a time [invest-wake2003].

### Scrum: goal, backlog, done, review

- Scrum orders all work into a single Product Backlog; items are refined by
  "breaking down and further defining Product Backlog items into smaller more
  precise items", adding description, order and size [scrum-guide2020].
- A Product Backlog item is ready for a Sprint only when the team can finish it
  within that Sprint; the people doing the work are responsible for sizing it
  [scrum-guide2020].
- Sprint Planning answers three questions: why the Sprint is valuable (the
  Sprint Goal), what can be done, and how; the how is usually settled by
  "decomposing Product Backlog items into smaller work items of one day or
  less" [scrum-guide2020].
- "The Sprint Goal is the single objective for the Sprint." Scope within the
  Sprint may be renegotiated as the team learns, but not in a way that
  endangers the goal [scrum-guide2020].
- The Definition of Done is a formal, shared description of the quality state
  an increment must reach; work that does not meet it cannot be released or
  even shown at the Sprint Review and returns to the backlog [scrum-guide2020].
- The Sprint Review is a working session in which the team and stakeholders
  inspect what was done and decide what to do next; the Sprint Retrospective
  inspects how the team worked, including its Definition of Done, and picks
  the most useful improvements for the next Sprint [scrum-guide2020].

### Small changes are reviewed faster and better

- Google's engineering practices state that small changes are reviewed more
  quickly and more thoroughly, are less likely to introduce bugs, waste less
  work when rejected, merge more easily and roll back more simply
  [google-small-cls].
- "The right size for a CL is one self-contained change": it addresses one
  thing, includes its tests, leaves the system working, and carries everything
  a reviewer needs in the change and its description [google-small-cls].
- About 100 changed lines is usually reasonable and 1000 is usually too large;
  spread across many files a change counts as larger; when in doubt, make it
  smaller than you think you need [google-small-cls].
- Splitting strategies: stack dependent changes so review does not block work;
  split by file groups that need different reviewers; split horizontally with
  shared stubs between layers; split vertically into full-stack sub-features;
  put refactorings in their own change; land tests for existing behavior
  before refactoring it [google-small-cls].
- Plan the split before coding when a piece of work will span several
  dependent changes; each change in a dependent chain must leave the build
  working [google-small-cls].

### Scoping a short student project

- Crossley and Maini's rule 1: a good short project is achievable in the
  allotted time and tailored to the student's background, goals and capacity;
  keep the core topic within the student's skills and add extension questions
  that reach beyond them [crossley2025].
- Rule 2 (define the scope, then halve it): "If the initial scope feels 'about
  right', it is probably too big." Keep the core goal simple, and "avoid
  designing a project that needs everything to go right at every step"
  [crossley2025].
- The project should allow extension or simplification as needed, start at a
  level the student understands, and be able to produce valuable results in
  the time available; at undergraduate level reproducing published results is
  a legitimate deliverable [crossley2025].
- Expectations (goals, time commitment, likely problems) are written into a
  project plan at the outset and revisited at regular check-ins, so both sides
  know what success looks like [crossley2025].
- Regular scheduled meetings (weekly or fortnightly for full-time work) catch
  problems early; each meeting reviews progress, troubleshoots and clarifies
  the next steps before the student leaves [crossley2025].
- Scaffolding is heavier at the start (targets and assignments between
  meetings) and lighter toward the end; writing is scaffolded with dated
  intermediate goals such as an outline by week three and a methods draft by
  week six [crossley2025].
- Skill development is the primary outcome; a project that yields no
  publishable result but a student who can now do the work is a success
  [crossley2025].

### Briefing delegated work with clear boundaries

- In Anthropic's research system a lead agent analyzes the query, plans, and
  spawns subagents that work in parallel on different aspects, then
  synthesizes their results and decides whether more work is needed
  [anthropic-multi-agent-research].
- The post reports that each delegated subtask needs an objective, an output
  format, guidance on which tools and sources to use, and explicit task
  boundaries; short vague briefs led subagents to duplicate one another's
  work or leave gaps [anthropic-multi-agent-research].
- Effort is scaled to the complexity of the question with explicit rules
  (one worker and a few calls for a simple fact, several workers with divided
  responsibilities for a broad question), because agents left to themselves
  over- or under-invest [anthropic-multi-agent-research].
- Multi-agent decomposition pays off for breadth-first work with independent
  parts; tasks with many dependencies between parts or that need one shared
  context are a poor fit [anthropic-multi-agent-research].

### Project planning in the lab

- The HHMI/BWF guide's project-management chapter advises defining the goal of
  a project up front, breaking it into milestones with dates, laying the
  milestones on a timeline, and tracking progress against it in regular
  reviews (from knowledge of the source, not verified against the text)
  [hhmi-bwf-making-the-right-moves].

### Grove: leverage, indicators, maturity, one-on-ones

- Grove measures a manager by the output of the people they direct and
  influence, and says output must be tracked with a few indicators, each
  paired with a counter-indicator so speed is not bought with rework
  [grove-high-output-management].
- Delegation without monitoring is abdication; monitoring should happen at the
  stage where the least value has been added, so a plan or first result is
  reviewed early rather than a finished product late
  [grove-high-output-management].
- Task-relevant maturity: the amount of structure in a brief depends on the
  person's experience with this specific task, not on seniority; low maturity
  calls for what, when and how, high maturity for an objective and a check
  date [grove-high-output-management].
- The one-on-one is the subordinate's meeting: they set the agenda, the
  supervisor listens and coaches, both keep notes, and the frequency follows
  task-relevant maturity [grove-high-output-management].
- A decision is complete only when it is clear who decided, by when it is
  needed, and who must be informed [grove-high-output-management].

## Rules we adopt

1. Decompose a goal into work items that one person can finish in one working
   session (at most one day). If an item cannot be sized, split off a
   time-boxed spike first. Checked by the delegation skill. (from
   [scrum-guide2020], [invest-wake2003])
2. Write the acceptance criterion before work starts, as a check someone other
   than the owner can run (a test passes, a file exists with N rows, a figure
   shows X). An item without one is not ready. Checked by the delegation
   skill. (from [invest-wake2003], [scrum-guide2020])
3. Every work item has exactly one owner. Shared ownership is recorded as two
   items. Checked by the delegation skill and the meeting-scribe skill. (from
   [invest-wake2003], [grove-high-output-management])
4. List dependencies explicitly; the dependency graph must be acyclic, and
   each item must leave the shared state (repository, dataset, draft) working
   when it lands. Prefer independent items; stack dependent ones so review
   does not block work. Checked by the delegation skill. (from
   [google-small-cls], [invest-wake2003])
5. One item, one thing: refactoring, tests for existing behavior and new
   behavior are separate items, and a code change is at most about 100 lines
   unless the reviewer agreed otherwise in advance. Robert enforces in review.
   (from [google-small-cls])
6. Slice vertically: each item delivers something inspectable end to end (a
   result, a figure, a working command), not a finished layer with nothing on
   top. Checked by the delegation skill. (from [invest-wake2003],
   [google-small-cls])
7. Every bundle of items has a single stated goal, and scope inside the bundle
   may be renegotiated only in ways that keep that goal reachable. Checked by
   the delegation skill. (from [scrum-guide2020])
8. A brief to a delegate (student, colleague or agent) names the objective,
   the output format and location, the tools or data to use, what is out of
   scope, and the check date. Scale the level of detail to the delegate's
   experience with this specific task. Checked by the delegation skill.
   (from [anthropic-multi-agent-research], [grove-high-output-management])
9. Scope a short student project to one core deliverable that the student can
   reach with skills they have, then halve it; name a fallback deliverable
   (for example a reproduction of a published result) and optional extensions.
   Checked by the delegation skill. (from [crossley2025])
10. Write the project plan with dated milestones at the start and revisit it
    at every scheduled check-in; heavier scaffolding early, lighter later.
    Robert enforces. (from [crossley2025], [hhmi-bwf-making-the-right-moves])
11. Review early at the cheapest stage: the first milestone of any delegated
    item is a plan or a first partial result, due within a week. Checked by the
    delegation skill. (from [grove-high-output-management], [scrum-guide2020])
12. Every action item recorded from a meeting has an owner, a due date, and a
    one-line done condition; every recorded decision names who decided and who
    must be informed. An item missing any of these is flagged, not silently
    recorded. Checked by the meeting-scribe skill. (from [invest-wake2003],
    [grove-high-output-management])
13. At the end of each planning cycle hold a short review of what was
    delivered against the done conditions and a retrospective on how the
    process worked; carry at most two process changes into the next cycle.
    Robert enforces. (from [scrum-guide2020])
14. Track delivered items with two indicators, items closed and items
    reopened, so that speed is not bought with rework. Checked by the
    delegation skill. (from [grove-high-output-management])

## Where sources disagree

- Size of a work item: Wake accepts stories of a few person-weeks
  [invest-wake2003], Scrum plans work items of one day or less
  [scrum-guide2020], and Google measures changes in tens or hundreds of lines
  [google-small-cls]. These are different levels of the same hierarchy. We
  use "session-sized" (at most one day) for work items and one to two weeks
  for milestones, because research tasks have unknown outcomes and a shorter
  check cycle limits wasted work.
- How much to specify: Wake wants stories negotiable, with details settled in
  conversation [invest-wake2003]; Anthropic found that vague briefs to
  subagents cause duplicated work and gaps and requires detailed objectives
  and boundaries [anthropic-multi-agent-research]. Grove resolves this: the
  detail depends on task-relevant maturity [grove-high-output-management].
  We write the brief fully when the delegate is new to the task or cannot ask
  back (an agent, an absent collaborator), and keep it to essence plus a
  testable criterion when the delegate is experienced and reachable.
- Independence versus stacking: Wake asks for stories that can run in any
  order [invest-wake2003]; Google describes stacked dependent changes as a
  normal way to keep working while waiting for review [google-small-cls]. We
  allow dependencies when they are explicit and acyclic, and prefer
  independence when the split cost is low.
- Output versus skills: Crossley and Maini say skill development, not the
  deliverable, is the primary outcome of a student project [crossley2025];
  Grove and Scrum measure by output [grove-high-output-management,
  scrum-guide2020]. We scope student projects to a deliverable because a
  deliverable makes progress inspectable, but we record the fallback
  deliverable as a success and do not treat an unpublished result as failure.

## Not covered

- How to estimate research tasks whose outcome is unknown; the sources come
  from software or from short taught projects and assume the work is
  understood well enough to size.
- When to abandon a line of work rather than split it further; Scrum lets the
  Product Owner cancel a Sprint but gives no criterion for research.
- A research-specific Definition of Done (reproducible environment, data and
  code archived, figure regenerable from script); the sources leave the
  content of "done" to the team.
- Action items that have no natural owner or fall to someone absent from the
  meeting.
- The HHMI/BWF chapter was not fetched; its claims here are from memory and
  need checking against the text before a skill relies on them alone.
