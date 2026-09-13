# Contact policy

ADR-0009. The short version: borg-cube talks to Robert and to nobody else
until Robert records a grant for a specific person, channel and purpose.

## Default

No outbound contact to anyone. Any message, DM, email, GitHub comment, PR,
issue, social post, form submission, signature or website publish that would
reach a person other than Robert becomes a `kind:outbound` bead in the
approval queue. Robert either sends it himself or approves it; only then does
the system act, and the result (permalink, Message-ID, confirmation number)
is recorded as provenance.

## Grants

`contacts.yaml` in the repository, empty by default:

```yaml
grants:
  alex-example:
    mattermost_dm:
      granted: 2026-10-01
      granted_by: robert
      scope: [weekly-checkin, milestone-reminder]
      expires: 2027-01-31
      evidence: https://borg.bio2vec.net/borg/pl/<permalink to the student's agreement>
    email: null
  fin-fellow:
    mattermost_dm:
      granted: 2026-09-15
      granted_by: robert
      scope: [infra-alerts]
```

- Per person (roster slug), per channel (`mattermost_dm`, `mattermost_channel`,
  `email`, `github`, `web_form`), per action class (`weekly-checkin`,
  `milestone-reminder`, `infra-alerts`, `dossier_read`, ...).
- Each grant has a date, who granted it, the scope, an optional expiry and an
  evidence link to the person's agreement.
- `dossier_read` is a separate grant: read access to one's own milestone plan,
  check-in history and `visible:student` beads.

## The gate

`cube contact check <person> <channel> <action-class>` is the single check
used by every runner, by the approval flow and by the Hermes allowlist
generator. Outcomes: `granted` (act, log), `queue` (create the outbound bead
for Robert), never `send anyway`.

The advisor gateway's `MATTERMOST_ALLOWED_USERS` is rendered from grants
with channel `mattermost_dm`. No grant, empty list, the bot answers nobody.

## Granting and revoking

- `cube contact grant <person> <channel> <class> [--expires DATE] --evidence URL`
  and `cube contact revoke <person> [<channel>]` are Robert-only, run on ws,
  and append to `state/audit.jsonl`.
- Revocation is immediate: the advisor profile is re-rendered and its
  gateway restarted.
- Expired grants behave like revoked ones; the deadlines patrol warns 14 days
  before expiry.

## Roles

Every `roles/<role>.yaml` has `autonomous_actions: []` with respect to
outbound actions. `cube doctor` fails if any role lists an outbound action.
This stays true through the Phase 4 pilot; whether any action class becomes
autonomous for granted students is a decision taken at the pilot review, and
would be a new ADR.

## What a granted student never receives

Assessments, risk scores, rankings, Robert's notes, anything about another
student, or any fact the student did not state and that is not derivable from
artefacts Robert already has. The bot says when it will summarise for Robert.

## Audit

`git log contacts.yaml` plus `grep contact state/audit.jsonl` answers "who
has the system ever been allowed to talk to, since when, for what".
