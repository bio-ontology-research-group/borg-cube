# ADR-0025: The laptop liaison channel is the ledger, and its model runs on OpenRouter

Status: accepted
Date: 2026-09-07
Extends: ADR-0017 (ledger sync on every worker tick), ADR-0021 (local endpoint first), ADR-0023 (what Robert decides)

## Context

On 2026-09-07 Robert asked hermes-ws on Mattermost for a read-only validation
of two directories that exist only on the laptop. hermes-ws tried ssh to
`lc-dell` (a stale DNS entry, then a home address) and asked Robert for the
laptop's IP. There is no such route by design: `cube.yaml` records the laptop
with `ssh: null`, and ws never reaches into the laptop. Robert, 2026-09-07:
the cube cannot get data from the laptop; the liaison must provide it.

The channel already existed in part. ADR-0017 syncs the Beads ledger through
the git remote on every worker tick on both hosts, so a `kind:request` bead
filed on ws reaches the laptop and an answer written on the laptop reaches
ws. What was missing was the laptop side for anything but mail: the liaison
workday answered mail requests deterministically and treated every other
request as an error. `cube-p91d` (a deadlines audit) sat all day with
`missing Question field`; no liaison model run ever happened on the laptop
(`runs/` there held none). The laptop also cannot reach the group's own
endpoint on unimatrix01, so the plan tier's first entries never answer there.

## Decision

1. The channel is the ledger, both ways. A request for the laptop is a bead
   filed with `cube request liaison "<question>" --apply` on ws (labels
   `kind:request agent:liaison host:laptop`). The answer is written on the
   same bead on the laptop and the bead is closed there. Nothing else crosses:
   no ssh into the laptop, no file copy, no chat bot on the laptop. Robert
   talks to the cube through hermes-ws on Mattermost; hermes-ws files the
   request and reports the answer when the bead comes back.
2. The laptop workday answers what it can deterministically (mail requests,
   `cube/agents/liaison.py`) and defers everything else to one model step per
   request, with the reason the deterministic path gave. The step prompt
   (`LIAISON_REQUEST_PROMPT`) names the whole protocol: read only the named
   local sources, never contact anyone, never change a file, answer with an
   `answer:` comment of source-backed lines, close the bead, and for
   personal-category material write nothing and label `needs:robert`.
3. An agent may pin its harness and model (`runner`, `model` in
   `agents/<name>.yaml`; the harness must equal the agent's runtime). The
   liaison pins `claude@openrouter` on `z-ai/glm-5.3-flash`: Claude Code with
   its per-command allowlist and the senior role's read-only permission mode,
   talking to OpenRouter with `provider.data_collection=deny` (ADR-0018).
   Robert chose this on 2026-09-07 knowing the request text and the extracted
   facts leave the laptop for OpenRouter; the privacy classes still hold:
   a `privacy:local-only` bead is refused by the router on any non-local
   runner, so it stays on the laptop and shows up as a blocked step.
4. Timing is the sync cadence: a request reaches the laptop within one laptop
   tick (five minutes) after ws pushes; the answer reaches ws within one laptop
   push plus one ws pull (up to thirty-five minutes).

## Consequences

- hermes-ws and the coordinator never probe the laptop. "Laptop unreachable"
  in `cube status` is informational; the request path does not depend on it.
- Every liaison request must carry a `Question:` line or a plain ask after the
  header; either way it is answered, by code or by the model step.
- Artifacts larger than a bead (a drafted report, a data table) still have no
  channel beyond a pointer to `state/agents/liaison/answers/` on the laptop.
  When one is needed, the options are a git-tracked answers directory pushed
  with the sync tick or an upload to Robert's Mattermost DM by hermes-ws; that
  is a separate decision.
- Without the pin the router picks `claude@local` on the laptop, because the
  static availability check only asks whether `VLLM_BASE_URL` is set, and the
  run hangs on the unreachable endpoint until the role timeout (observed on
  2026-09-07 19:15 UTC, run `r-20260907-1915-ca` for `cube-iclb`, which held
  the liaison workday lock meanwhile). The pin sidesteps that; a reachability
  probe in the availability check is a separate improvement.
- The liaison reads the laptop only. A request about data that lives on ws
  (a checkout under `~/Public/software` there) is work for a ws agent, not a
  request to the laptop; the coordinator must not route it to the liaison.
- The laptop needs `OPENROUTER_API_KEY` in its `.env`; a missing key surfaces
  as a refused run on the workday result, never as a silent skip.
