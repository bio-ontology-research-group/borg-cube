# Privacy

What borg-cube stores, where, who sees it, and what it never does. Decisions:
ADR-0007 (classes), ADR-0009 (contact), ADR-0011 (local inference).

## Classes

| Class | Examples | Where processed | Where stored |
|---|---|---|---|
| public | research knowledge graph, public repositories, published papers | any tier | beads on ws, runs/ |
| internal | pa KG, papers.org, deadlines.md, meeting notes, org files, infra runbooks | Claude Max, Codex, OpenRouter under the subscription terms; never posted publicly | beads on ws, runs/, briefings/ |
| local-only | check-in transcripts, progress assessments, anything about a person's performance, contracts, visas, personnel, health | vLLM on node005 only; waits when it is down | ws and node005 only; never copied off the KAUST network |

Not stored at all: grades, HR records, passwords. `cube doctor` scans beads
and briefings for forbidden field patterns.

## Who sees what

- Robert: everything.
- Students: nothing, unless a `dossier_read` grant exists; then only their own
  milestone plan, their own check-in history, `visible:student` beads and the
  transparency note (`doc/student-guide.md`). Never Robert's notes, other
  students, or any assessment or risk score.
- The infrastructure postdoc: infrastructure alerts through the existing
  `hermes-ws` channel.
- Cloud providers: `public` and `internal` content sent to Claude (Anthropic),
  Codex (OpenAI) and OpenRouter models under the respective subscription and
  API terms; nothing `local-only`.
- Nobody else. Mattermost posts, emails, GitHub comments and PRs happen only
  through approved `kind:outbound` beads.

## Where data lives on ws

- `~/Public/software/borg-cube/state/`: leases, cursors, budget, audit log,
  events, KILL. Gitignored.
- `~/Public/software/borg-cube/runs/<date>/<run-id>/`: transcripts and
  artefacts of every run. Gitignored. Retention: 180 days, then deleted by
  the infra-hygiene patrol (local-only transcripts after 90 days).
- `briefings/students/`: Robert-only digests. Gitignored.
- Beads database (`.beads/`): work items and provenance, no personal
  assessments beyond a bead's own summary; nightly export backup on ws.
- `~/.hermes/profiles/<p>/transcripts/`: Hermes conversation logs; advisor
  transcripts are local-only.
- Data repositories (`~/org`, `~/pa`, KGs): their own privacy rules apply;
  borg-cube writes into them only through their scripts after approval.

## Credentials

Scoped, revocable tokens in `.env` files with mode 0600, never in the repo.
No passwords anywhere agent-readable; the KAUST SSO session for the secretary
is Robert's own browser session, reused, never the credentials. Password
files in `borg-infrastructure` are referenced by path only.

## Rights and controls

- Any student can ask Robert what is stored about them: `cube student export
  <slug>` produces the complete list of beads, briefings and transcripts.
- Opt-out is immediate: `cube contact revoke` removes grants, re-renders the
  advisor allowlist and restarts the gateway; existing local-only transcripts
  are deleted on request.
- Kill switch `state/KILL` stops all processing.
- Every access by a runner is a line in `state/audit.jsonl`.

## What the system never does

- Contact a person other than Robert without a recorded grant.
- Deliver an assessment, ranking or risk score to a student.
- Infer a fact about a person that the person did not state or that is not
  derivable from artefacts Robert already has access to.
- Send local-only material to a cloud model.
- Store grades, HR records or passwords.
