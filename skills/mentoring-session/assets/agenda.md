# 1:1 agenda, {student}, {date}

Prepared for Robert. Not sent to the student. Privacy: local-only.

## Since the last meeting

| Evidence | Locator | What it shows |
| --- | --- | --- |
| {commits} | {repo, range} | {one line} |
| {draft} | {path, words, date} | {one line} |
| {previous entry} | {org file, entry date} | {open items} |

Open action items carried over:

- [ ] {item} ({owner}) {due}

## Agenda, in order

1. Student's own items first, whatever they bring.
2. {point} (evidence: {locator})
3. {point} (evidence: {locator})
4. Next steps and dates.

Each point names its evidence. A point without evidence is dropped.

## Questions

Four to six, at least three different cognitive processes, at least one
metacognitive and, when a result exists, one evaluate or create question.

- {question} (understand, conceptual) about {artefact}
- {question} (apply, procedural) about {artefact}
- {question} (evaluate, metacognitive) about {artefact}
- What are you stuck on right now? (metacognitive)

## Feedback to give

- Worked well: {specific thing, by name}
- Argument level: {comment with locator}
- Next action: {fits before the next meeting}
- Turnaround promised: {what Robert will return, by when}

## Flags for Robert

Observation plus evidence, no diagnosis, no label, nothing about health,
grades, contracts or visas.

- {observation} ({evidence locator})

## After the meeting

Fill `assets/session.yaml.example` and run
`python3 scripts/org_meeting_entry.py --input runs/{student}/{date}.yaml`,
then rerun with `--apply` once the printed entry is right.
