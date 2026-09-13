---
topic: code-review-practice
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Code review practice

Sources
- google-code-review (CC-BY-3.0; short excerpts allowed)
- google-small-cls (CC-BY-3.0; short excerpts allowed)
- hunter-zinck2021 (CC-BY-4.0; short excerpts allowed)
- wilson2014 (CC-BY-4.0; short excerpts allowed)
- openssf-scorecard (Apache-2.0; short excerpts allowed)

This file grounds two things: how the code-audit skill writes findings, and
how the delegation skill gates work on review. Only the review, testing,
style, and continuous integration parts of the two PLOS papers are used, and
only the Code-Review and Branch-Protection checks of Scorecard.

## What the evidence says

### What review is and why it is done

- Google defines a code review as "a process where someone other than the
  author(s) of a piece of code examines that code", and uses it to maintain
  the quality of code and products [google-code-review].
- Research summarized by Wilson and colleagues finds code reviews to be the
  most cost-effective way of finding bugs; reviews also spread knowledge and
  good practice across a team [wilson2014].
- In groups with shifting membership, such as academic labs, reviews keep
  critical knowledge from leaving with a departing student or postdoc
  [wilson2014].
- Reviews that are not required in order to merge soon stop happening; the
  recommendation is pre-merge review (practice 8a) [wilson2014].
- Community code review is described as a cornerstone of modern software
  development, open source or proprietary, and clean, consistently styled
  code makes review protocols simpler [hunter-zinck2021].
- Scorecard's Code-Review check asks "Does the project practice code review
  before code is merged?" and rates the risk of its absence High; a
  protected default branch with required review satisfies it
  [openssf-scorecard].
- Scorecard's Branch-Protection check (High risk) inspects whether force
  pushes and deletion are disabled, how many reviewers are required, whether
  stale reviews are dismissed on new commits, whether status checks must
  pass, and whether administrators also need review [openssf-scorecard].

### What reviewers look for

- Google lists eight areas: design (is the code appropriate for the system),
  functionality (does it do what the author intended and is that good for
  users), complexity (could it be simpler; will the next developer
  understand it), tests (correct and well designed), naming, comments (clear
  and useful), style (follows the style guide), and documentation (updated
  with the change) [google-code-review].
- The linked "Standard of code review" page adds that reviewers should
  approve once a change definitely improves the overall health of the code,
  even if it is not perfect, because there is no perfect code, only better
  code; technical facts and data override opinions and preferences; the
  style guide is the authority on style; and reviewers should mark optional
  polish comments with a "Nit:" prefix so the author knows they may be
  deferred (from knowledge of the guide, not verified against the text)
  [google-code-review].
- The linked "What to look for in a code review" page adds: read every line
  you are asked to review, look at the change in context rather than only the
  diff, check edge cases and concurrency, watch for over-engineering, prefer
  comments that explain why over comments that explain what, and say
  something when the author did well (from knowledge of the guide, not
  verified against the text) [google-code-review].
- The linked guidance on review comments says every comment should be
  courteous, explain its reasoning, address the code rather than the
  developer, and balance pointing out problems with giving direction (from
  knowledge of the guide, not verified against the text) [google-code-review].
- Concrete items a reviewer can check in scientific code: one style guide
  applied throughout and enforced by a linter (Rule 1); functions that do one
  thing, with a suggested ceiling of about five arguments and about 40 lines
  (Rule 3); no commented-out or dead code (Rule 4); preconditions and
  postconditions on inputs and outputs (Rule 5) [hunter-zinck2021].
- Names should be consistent, distinctive, and meaningful (1b); style and
  formatting consistent (1c); code modularized rather than copied and pasted
  (4b); assertions used to check operation (5a); documentation describing
  interfaces and reasons rather than mechanics (7a); and when a piece of code
  needs a long explanation, the fix is to "refactor code in preference to
  explaining how it works" (7b) [wilson2014].

### Tests as part of review

- Tests are expected for all changes. A change that adds or alters logic
  carries new or updated tests; a pure refactoring is covered by tests that
  ideally already exist [google-small-cls].
- Each unit test should check one behavior, in isolation, and run fast;
  consistent naming and fixtures keep the suite readable [hunter-zinck2021].
- Write tests throughout development, not at the end; at minimum, every bug
  fix comes with a test that reproduces the bug [hunter-zinck2021].
- Turn bugs into test cases (5c) and use an off-the-shelf unit testing
  library (5b) [wilson2014].
- Aim for at least 60 percent line coverage as a rule of thumb, prefer branch
  coverage as the metric, and remember that tests also need maintenance, so
  keep only tests worth keeping [hunter-zinck2021].
- Linting and tests belong in continuous integration, triggered on push or
  on a schedule, so that they run every time and not only when someone
  remembers (Rule 10) [hunter-zinck2021].

### Small changes

- Small changes are "Reviewed more quickly", "Reviewed more thoroughly", and
  "Less likely to introduce bugs"; they also waste less work if rejected,
  merge more easily, are easier to design well, and roll back more simply
  [google-small-cls].
- The right size is one self-contained change with its tests, containing
  everything the reviewer needs. About 100 lines is usually reasonable and
  1000 usually too large; the same change spread across 50 files counts as
  larger than in one file [google-small-cls].
- Reviewers may reject a change for size alone and ask for a series of
  smaller ones; when in doubt, write a smaller change than you think you need
  [google-small-cls].
- Ways to split: stack dependent changes, split by file groups that need
  different reviewers, split horizontally across layers behind a shared
  interface, or split vertically into independent sub-features. Keep the
  build working after every step [google-small-cls].
- Refactorings go in a separate change from features and bug fixes; small
  local cleanups may ride along. Test-only changes that cover existing code
  may go first, so a later refactoring is checked against them
  [google-small-cls].
- Large changes are acceptable for whole-file deletions and for output of a
  trusted automatic refactoring tool; otherwise, get the reviewer's consent
  in advance and expect a long review [google-small-cls].
- Programmers are most productive in small steps with frequent feedback and
  course correction (3a), with steps of about an hour and iterations of
  about a week [wilson2014].
- Refactor incrementally, running the tests before and after each step so
  a step that breaks something can be rolled back [hunter-zinck2021].

### Who reviews, pairing, and the record

- The best reviewer is the person able to give the most thorough and correct
  review, usually the owner of the code; if that person is unavailable, copy
  them on the change [google-code-review].
- Code pair-programmed with someone qualified to review it counts as
  reviewed; in-person review is also allowed [google-code-review].
- Pair programming improves productivity in several studies but many find it
  intrusive; use it when bringing someone new up to speed and for tricky
  problems (8b) [wilson2014].
- Use a version control system (3b), put everything created by hand under it
  (3c), and use an issue tracker so that review requests and tasks are not
  dropped as the team grows (8c) [wilson2014].

## Rules we adopt

1. The reviewer is not the author. Code written in a pair with someone
   qualified to review it counts as reviewed, and the merge record names the
   partner (from [google-code-review], [wilson2014]).
2. Review happens before merge. The default branch of every group repository
   requires at least one approving review, dismisses stale approvals on new
   commits, and rejects force pushes; the code-audit skill checks these
   settings (from [wilson2014], [openssf-scorecard]).
3. Every finding names the file and line, states the problem, gives a
   severity, and proposes a concrete fix or the test that would expose the
   problem. A finding without a fix is written as a question and labelled
   so (from [google-code-review]).
4. Findings use four labels and are grouped by label, blockers first:
   blocker (wrong behavior, missing test for changed behavior, or a high
   security finding; must be fixed before merge), should (fix before merge
   unless author and reviewer agree to a follow-up issue), nit (style,
   naming, wording; the author may defer), and question. Nits are never
   mixed into the blocker list (from [google-code-review]).
5. Every comment addresses the code, not the person, and says why; the
   reviewer offers a direction, not only a complaint (from
   [google-code-review]).
6. Approve when the change improves overall code health even if it is not
   perfect. Remaining nits become follow-up issues, not a second review round
   (from [google-code-review]).
7. The reviewer checks that a test exists for every changed behavior and
   that a bug fix includes a test that fails without the fix. A change
   without such tests is a blocker (from [google-small-cls], [wilson2014],
   [hunter-zinck2021]).
8. A change is small enough to review in one sitting: about 100 changed
   lines is the target and 1000 the ceiling, except whole-file deletions and
   trusted mechanical refactors. Above the ceiling the reviewer asks for a
   split before reading (from [google-small-cls]).
9. Refactorings are separate changes from behavior changes, and a test-only
   change covering existing code may precede a refactoring (from
   [google-small-cls], [hunter-zinck2021]).
10. The reviewer walks the eight areas in order (design, functionality,
    complexity, tests, naming, comments, style, documentation) and reads
    every line of the diff in the context of the surrounding code (from
    [google-code-review]).
11. Style is settled by the repository's declared style guide and linter,
    which run in continuous integration. A reviewer does not raise style
    findings the linter accepts; a missing linter or CI is itself a should
    finding (from [hunter-zinck2021], [wilson2014]).
12. Reviews are mentoring in both directions: a senior reviewer explains the
    reason behind each finding, and a student reviewing a senior's change
    has findings weighed on their merits alone (from [wilson2014],
    [google-code-review]).
13. The author picks the reviewer who knows the code best and can respond
    within one working day, and copies the ideal reviewer when unavailable
    (from [google-code-review]).
14. The author answers every finding, either with a fix or a reason; the
    reviewer, not the author, marks it resolved (from [google-code-review]).

## Where sources disagree

- Pair programming as review: Google treats a pairing session with a
  qualified partner as a full substitute for review; Wilson and colleagues
  recommend pairing only for onboarding and hard problems because many find
  it intrusive. We accept pairing as review when the partner is qualified,
  but the default is asynchronous pre-merge review, because it leaves a
  written record the audit can read [google-code-review, wilson2014].
- Size: Google gives reviewers discretion to reject a change outright for
  being too large; neither PLOS paper discusses size. We adopt the size
  guidance but phrase it as a request to split with suggested seams, not a
  bare rejection, since most authors here are students [google-small-cls,
  wilson2014, hunter-zinck2021].
- Coverage: Hunter-Zinck and colleagues suggest 60 percent coverage as a
  floor; Google expects tests with every change regardless of a number. We
  apply both at different scales: per change, every behavior change has a
  test; per repository, coverage is tracked and 60 percent is a floor, not a
  target [hunter-zinck2021, google-small-cls].
- What counts as review: Scorecard measures presence (an approval before
  merge); Google measures quality (does the change improve code health).
  Presence is necessary and the audit checks it, but a rubber-stamp approval
  does not satisfy rules 3 to 10 [openssf-scorecard, google-code-review].

## Not covered

- Reviewing notebooks, data pipelines, and analysis results, where the
  question is scientific correctness rather than code health.
- Reviewing code generated by an agent, where the "author" cannot answer
  questions and the delegating person carries the author's duties.
- Response time: Google has a page on speed of review that was not fetched;
  the one-working-day figure in rule 13 is our own.
- Resolving standoffs between author and reviewer; Google's CL author guide
  covers this but was not fetched.
- Repositories with one or two active developers, where "someone other than
  the author" may not exist inside the group.
- Tooling: pull request templates, CODEOWNERS files, and review bots.
