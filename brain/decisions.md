# Decisions

Agent-facing index of `adr/`. Read the ADR before arguing with a rule.

- ADR-0001 Beads is the work ledger, wrapped in `cube/beads.py`; beads hold work and provenance only; `xid` headers make sync idempotent. Accepted.
- ADR-0002 The group model (people, projects, papers, meetings) stays in `~/pa`, `~/org`, the research knowledge graph and the roster; borg-cube reads, never owns; conflicts become beads. Accepted.
- ADR-0003 One Hermes `advisor` profile and one bot `@borg-advisor` with per-DM sessions; allowlist generated from `contacts.yaml`; student context injected by a hook; the bot never assesses. Accepted.
- ADR-0004 Deterministic patrols run as systemd user timers on ws; Hermes cron only for judgments delivered through a bot identity; no scheduled Mattermost polling. Accepted.
- ADR-0005 Four router tiers with strict fallback: plan (Fable, Opus, refuse), implement (Codex ChatGPT profile, Sonnet, OpenRouter coder), bulk (OpenRouter cheap, local), local (vLLM or queue). Never downgrade planning or review. Accepted.
- ADR-0006 Claude Max only via Claude Code; Codex only via `codex exec -p cube-chatgpt`; Hermes never on Anthropic OAuth; daily plan-tier cap. Accepted.
- ADR-0007 Privacy classes public, internal, local-only; local-only only on node005; grades and HR never in beads. Accepted.
- ADR-0008 ws is the orchestration host; the laptop and any ssh-capable machine are thin cockpits; events flow through `state/events.jsonl`. Accepted.
- ADR-0009 Contact policy default-deny; per-person, per-channel, per-action-class grants in `contacts.yaml`; `cube contact check` is the single gate; `autonomous_actions` empty of outbound actions. Accepted.
- ADR-0010 Gas Town considered for the coding fleet only, decided after a one-week Phase 3 spike; research, advising, teaching, sysadmin stay in cube. Proposed.
- ADR-0011 vLLM on unimatrix node005 (2x RTX 4090) is the `local` tier; model chosen by Phase 1 evaluation; `claude` and `codex` never use it. Accepted.
- ADR-0012 The public profiles page is the roster of record; active members come from the site, while private program facts remain external. Accepted.
- ADR-0013 Research pipelines are deterministic Beads dependency graphs; the marshal dispatches and artifact gates control stage progress. Accepted.
- ADR-0014 The budget ledger separates billed and equivalent cost; binding ceilings fall through safely, and reversible controls choose only cheaper entries or lower tiers. Accepted.
- ADR-0015 Bulk work uses explicit free OpenRouter defaults; implement falls from Codex to free before paid models; free capacity backs off per model for ten minutes; doctor validates a daily patrol cache. Accepted.
- ADR-0016 Claude Code and Codex also run on OpenRouter GLM, identified by the runner token `claude@openrouter`; routing skips chat-only entries when the work needs tools; the OpenRouter key reaches the child environment only, under a separate Claude config dir; the budget ledger bills the price-table estimate. Accepted.
- ADR-0023 The cube runs itself: six plan slots and five minute ticks; Robert decides only security-critical (a change to a running system, spend over budget, contact) and privacy-critical matters, marked `critical`; other escalations go to the coordinator, one bead per subject; findings close on result without review; the coordinator reviews every four hours, distributes to quiet projects and chases stale beads; the sysadmin prepares one approval bead per host. Accepted.
- ADR-0024 Pending decisions are announced once into hermes-ws's inbox and reach Robert's Mattermost DM through the outbox cron; `cube decide --reply` parses his DM reply and answers the decision. Accepted.
- ADR-0027 Robert approves two things: a change to a running system in `decisions.systems` and a laptop read outside `hosts.laptop.readable`; everything else is answered by policy or settled by the coordinator (questions need `--critical` to reach him; routed beads are routed once more, then stand); the `liaison` role reads the readable directories on its own through path-bounded Read rules and `cube lookup`, with `~/pa`, `~/org` and credential stores closed; a finished goal becomes one report in his DM; runner errors name timeouts; the cube-worker profile bounds context and output. Accepted.
