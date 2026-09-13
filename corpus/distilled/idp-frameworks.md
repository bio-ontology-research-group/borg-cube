---
topic: idp-frameworks
reviewed_by: null   # pending review by Robert Hoehndorf
reviewed_on: null
---

# Individual development plans and competency frameworks

Sources
- vitae-rdf (CC-BY-NC-ND, UK licence; structure summarised, no quotes, never republished)
- myidp (proprietary web tool; not fetched, summarised from general knowledge)
- masters2017 (CC-BY-4.0; short excerpts allowed)
- quynn2026 (CC-BY-4.0; short excerpts allowed)
- nap2019-mentorship (proprietary, free to read; summary only)
- nap2018-graduate-stem (proprietary, free to read; summary only)
- marino2014 (CC-BY-4.0; short excerpts allowed)
- gu2007 (CC-BY-4.0; short excerpts allowed)
- hhmi-bwf-making-the-right-moves (proprietary; not fetched, summarised from general knowledge)
- handelsman2005 (book, proprietary; ideas from corpus/notes/handelsman2005.md)
- wisker-good-supervisor (book, proprietary; ideas from corpus/notes/wisker-good-supervisor.md)
- kaust-cemse-milestones (KAUST page; quote rules short, never republish)

## What the evidence says

### Where the IDP requirement comes from

- Masters and Kreeger record the funder history: in 2009 the NSF began
  requiring mentoring and development plans in proposals requesting support
  for postdoctoral fellows, and in 2014 the NIH announced that annual grant
  progress reports would have to describe whether and how individual
  development plans are used to manage the career development of predoctoral
  and postdoctoral trainees [masters2017].
- They also state the limit of the instrument: a development plan works on the
  mentee's long-term goals and does not address the day-to-day operation of
  the lab, so it cannot replace an expectations document [masters2017].
- The graduate education report asks institutions to make career development
  an explicit, planned part of a doctorate rather than a by-product of the
  research, and to broaden what counts as a successful outcome beyond the
  academic path [nap2018-graduate-stem].
- The mentorship report treats career and psychosocial development as two
  functions of the same relationship, which is why a plan that lists only
  technical skills misses half of what the relationship is for
  [nap2019-mentorship].

### myIDP: the four-step structure

- myIDP, published by Science Careers with AAAS and FASEB, is a web tool for
  science PhDs and postdocs built around four steps: assess yourself, explore
  career paths, set goals, and implement the plan with a mentor
  [myidp].
- The self-assessment covers three separate things that are often collapsed:
  skills (what you can do), interests (what you like doing), and values (what
  a job must provide). The tool scores these and maps them onto a set of
  scientific career paths so that the exploration step starts from data about
  the person rather than from a default assumption
  [myidp].
- The goal-setting step uses SMART goals across three tracks (project
  progress, career advancement, and skill development) with dates, and the
  plan is explicitly meant to be revisited with the mentor rather than filed
  [myidp].
- These entries are from general knowledge of the tool; the site was not
  fetched, and the exact wording of its categories should be checked before
  any of it is presented as a quotation [myidp].
- The HHMI and Burroughs Wellcome guide gives the same advice from the group
  leader's side: help each trainee write down where they are going and review
  it, rather than assuming the trainee wants the mentor's own career. This
  entry is also from general knowledge [hhmi-bwf-making-the-right-moves].

### Vitae RDF: a competency vocabulary

- The Vitae Researcher Development Framework was built from interviews with
  researchers to identify the characteristics of successful researchers, first
  published in 2010, and is used for planning and supporting the personal,
  professional and career development of researchers [vitae-rdf].
- The 2010 framework has four domains. A, knowledge and intellectual
  abilities, covers the knowledge base, cognitive abilities and creativity.
  B, personal effectiveness, covers personal qualities, self-management, and
  professional and career development. C, research governance and
  organisation, covers professional conduct, research management, and finance
  and resources. D, engagement, influence and impact, covers working with
  others, communication and dissemination, and engagement and impact
  [vitae-rdf].
- Each of the three sub-domains under a domain is broken into named
  descriptors. Domain A holds subject knowledge, research methods in theory
  and in practice, information seeking, information literacy and management,
  language and academic literacy; analysing, synthesising, critical thinking,
  evaluating and problem solving; and an inquiring mind, intellectual insight,
  innovation, argument construction and intellectual risk [vitae-rdf].
- The framework is explicitly designed for three audiences: researchers taking
  control of their own development, supervisors and managers supporting it,
  and developers planning provision [vitae-rdf].
- The 2025 refresh reorganises the same material, putting a Researcher domain
  at the centre and Research Communities around all domains, and gives each
  descriptor up to four phases representing stages of progression
  [vitae-rdf].
- Licence matters here: the RDF is licensed for UK use, quoting is restricted,
  and derivative works based on it need prior agreement. We use the domain
  labels as a vocabulary and do not reproduce the framework or its graphics
  [vitae-rdf].

### What makes a goal usable

- Marino and colleagues put a written plan with dates at the centre of
  finishing a doctorate, and treat the plan as something reviewed with the
  supervisor rather than held privately [marino2014].
- Gu and Bourne argue that the student should take ownership of the project
  and its direction early, which is the behaviour a development plan is meant
  to make visible [gu2007].
- Quynn and colleagues show what a usable goal looks like in the writing
  track: low-stakes items early (an outline, a README, a figure legend, a
  methods section), each one an occasion to practice and to receive feedback,
  with complexity rising over time [quynn2026].
- They also report that people consistently underestimate writing time, citing
  a study in which thesis writing took longer than students' worst-case
  projections, so a goal whose date assumes nothing goes wrong is not a plan
  [quynn2026].
- Wisker's stuck places and conceptual thresholds explain why a skill rating
  can stay flat for months while real progress happens: the student is
  crossing a threshold in how they understand the work, and the visible output
  lags [wisker-good-supervisor].
- Entering Mentoring asks the mentor to define, with the mentee, what success
  on the project looks like, which is the same act as writing the artefact
  that shows a goal is done [handelsman2005].
- Programme deadlines are not development goals and cannot be negotiated in an
  IDP: at KAUST the milestone dates and degree deadlines come from the
  division and the registrar [kaust-cemse-milestones].

### The annual review

- The mentorship report frames the review as a conversation about the
  relationship and the direction, not an assessment of the person, and warns
  that the mentee's ability to raise problems is limited by the power
  difference [nap2019-mentorship].
- Masters and Kreeger recommend a fixed annual slot for revisiting the written
  documents, either in a group meeting or as part of the evaluation process,
  so that the review does not depend on something having gone wrong
  [masters2017].
- The graduate education report expects career conversations to happen
  repeatedly across the degree, not once at the end
  [nap2018-graduate-stem].

## Rules we adopt

1. The IDP belongs to the student. borg-cube never edits an IDP and never
   writes into one; `idp_diff.py` reads two versions the student shared and
   nothing else. Checked by the mentoring-compact skill. (from [myidp],
   [nap2019-mentorship])
2. Pre-fill only facts (programme, year, next milestone and its date, the
   skill rows the project needs). Ratings, career interests, values and goals
   are the student's and are never pre-filled or suggested by the system.
   Checked by the mentoring-compact skill. (from [myidp], [masters2017])
3. Keep the three self-assessment axes separate: skills, interests and values.
   A plan that records only skills cannot support a career conversation.
   (from [myidp], [nap2019-mentorship])
4. Tag every skill row with a Vitae domain letter (A to D) so the plan can be
   checked for a domain with no entry, and use the domain labels as vocabulary
   only. Never reproduce the framework text or graphics. (from [vitae-rdf])
5. Every goal has a date in parentheses at the end of the line and names the
   artefact that shows it is done. A goal without a date is not tracked, and a
   goal without an artefact is not checkable. Checked by `idp_diff.py`.
   (from [marino2014], [handelsman2005], [quynn2026])
6. Cover three tracks in the goals: research progress, skills, and career or
   network. Add a wellbeing and boundaries item when the compact has anything
   outstanding. (from [myidp], [nap2018-graduate-stem])
7. Start the skills track with low-stakes, short items and raise the stakes
   over the year, rather than setting one large goal per skill.
   (from [quynn2026])
8. Never place a programme milestone in the IDP as a negotiable goal. The
   milestone dates come from `phd-milestones`; the IDP holds the preparation
   goals that lead to them. Checked by the mentoring-compact skill.
   (from [kaust-cemse-milestones], [marino2014])
9. Record the mentoring network in the plan: at least one person other than
   Robert for method help and one for a career path he does not represent.
   (from [nap2019-mentorship])
10. Fix the review date in advance, once every twelve months, and hold it even
    when the year went well. Record the review in the plan's review log and in
    the person's org file. (from [masters2017], [nap2018-graduate-stem])
11. Build the review agenda in this order: goals completed, then overdue and
    dropped goals asked about as questions rather than judged, then rating
    changes, then next year's goals. A flat or falling self-rating is a
    prompt to ask what changed, never a finding.
    (from [nap2019-mentorship], [wisker-good-supervisor])
12. Career interests, values and wellbeing entries are `privacy:local-only`:
    they stay out of beads and briefings, and any model call over them uses
    the local tier. (from [nap2019-mentorship])

## Where sources disagree

- Who the plan is for: the funder requirement treats the IDP as a management
  and reporting instrument the mentor uses [masters2017], while myIDP is built
  as a self-assessment the trainee owns and shares selectively [myidp]. We
  follow the myIDP position, because a plan the supervisor writes about the
  student is an assessment under another name, and assessments live in
  progress-review reports.
- Competency lists versus career interests: the Vitae framework is a
  competency vocabulary with no career-path model [vitae-rdf], while myIDP is
  organised around matching a person to career paths [myidp]. We use Vitae for
  the skills table and myIDP's three axes for the career section, and accept
  that the two do not map onto each other cleanly.
- Progression phases: the 2025 Vitae refresh assigns each descriptor up to
  four phases [vitae-rdf], while our template uses a 1 to 5 self-rating from
  novice to could-teach-it. We keep the 1 to 5 scale because it is what the
  template and `idp_diff.py` already track, and record it as a house choice
  rather than a Vitae rating.
- How ambitious a goal should be: Marino and colleagues push for dated,
  finishing-oriented plans [marino2014], while Quynn and colleagues show that
  writing time is systematically underestimated [quynn2026]. We ask for dated
  goals and treat a rescheduled goal as normal information for the review, not
  as a failure.

## Not covered

- Whether IDPs change outcomes. The funder requirements and the reports assume
  benefit; none of the fetched sources reports a controlled comparison.
- Career paths and their entry requirements in Saudi Arabia and the wider
  region. The myIDP career set is built around the US market.
- How to rate a competency reliably. Self-ratings are known to move with
  confidence rather than skill, and no source here gives a calibration method.
- The Vitae 2025 descriptor phases in detail; only the structure was on the
  fetched page, and the framework itself is licensed for UK use.
- The myIDP and HHMI/BWF entries were not fetched and rest on general
  knowledge; check them against the sources before quoting.
