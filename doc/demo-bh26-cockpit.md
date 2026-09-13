# BH26 demo from the cockpit: one task, the whole chain

Source: Robert's demo plan, 2026-09-13. Design: ADR-0036. Five to seven
minutes, nothing outbound. The auditor audits the KM Protégé plugin
(`bio-ontology-research-group/kobayashi-marust`: public, Robert's, small,
read-only).

## Before the talk

- VPN on. `Host ws` in `~/.ssh/config` already has `IPQoS none` (hotel path
  MTU under 1000 bytes stalls the key exchange). Fallback: the alternative ssh
  route documented in the infrastructure repository.
- Hide the sections with real names: in Emacs
  `(setq cube-dashboard-sections '(goals decisions work pipelines fleet projects ready literature repos))`
  (drops `students`, `attention`, `papers`).
- On ws: `cube doctor` green (topics error fixed 2026-09-11), `state/KILL`
  absent, plan tier available, the `cube/km-codex` tmux session may stay.
- Rehearse once the evening before with `--apply`; if the live run stalls,
  `S` in the watch buffer resumes the stored session.
- In Emacs: `M-x cube-server-watch-events` runs when the dashboard opens; the
  watch buffer starts it too.

## The seven minutes

1. **Backlog and roles.** `C-c b d` dashboard (ready beads, work rows);
   `C-c b l` fleet; roles: `M-x cube-run-role` completion shows the 18 roles,
   or `cube roles --json` in the second terminal.
2. **Create the task.** `C-c b F` (`cube-watch-new`). Title "Audit the Protégé
   plugin for release readiness", kind `audit`, role `auditor`, project
   `kobayashi-marust`, privacy `public`, acceptance "audit.md with file:line
   findings, severity and fix; proposed fix beads; no outbound action",
   provenance "BH26 demo", extra label
   `repo:bio-ontology-research-group/kobayashi-marust`. The plan buffer shows
   the dry-run `bd` commands; confirm; the watch buffer opens on the new bead.
   Point: provenance, privacy and acceptance are mandatory; dry-run is the
   default; the label is validated.
3. **Show the prompt.** `p`: runner and model chosen by the plan tier
   (`claude@openrouter` GLM 5.3 Flash first, local Qwen or Claude as
   fallback), `needs_tools`, the exact command with read-only tools, and the
   assembled prompt with the code-audit skill (two passes).
4. **Run and watch.** `s`: dry-run plan, confirm, the run starts attached in
   tmux `cube/run-auditor-<bead>`; the rolodex shows the session. Stay in the
   watch buffer: the Trail fills with `▶ start`, then one `·` line per tool
   call (`Read README.md`, `Grep secret`, `Bash python3 audit_collect.py`),
   then `■ stop` and `✓ finished`. Second terminal, optional:
   `ssh ws cube tail -f --bead <bead>`.
5. **Result and gates.** The Result section shows the summary; `O` opens
   `runs/<run>/audit.md`, `o` the run directory. `l` shows the bead with the
   review label; `C-c b d` ready list shows the proposed fix beads; `r`
   previews `cube review <bead> --dry-run` (senior must review; the auditor
   cannot close); `A` opens approvals: empty, nothing outbound.

## If something stalls

- No trail after start: the run is on Hermes (no tool hooks) or the event
  tail dropped; `g` reloads the backlog from `cube tail --bead`.
- Run past its time: `a` attaches the tmux session; `S` resumes; the engine
  releases the claim on error and the bead returns to ready.
- ssh stalls at key exchange: `IPQoS none` is set; use `wst`.
