# Gas Town spike (Phase 3 opener, ADR-0010)

Goal: decide in one week whether the coding fleet (programmer, auditor, refinery)
runs on Gas Town or stays in `cube` only. Everything below runs on ws (tmux
present, always on). `gt` 1.2.1 installs with:

```
GOTOOLCHAIN=auto go install github.com/steveyegge/gastown/cmd/gt@latest
```

(the module path is `steveyegge/gastown`; the `gastownhall` alias fails to
build). `bd` 1.2.2 is already installed; Gas Town needs `bd` 0.57+.

## Protocol

1. `gt install ~/gt --shell --git` (HQ with its own town-level beads, prefix hq-).
2. `gt rig add borg-cube git@github.com:leechuck/borg-cube.git` (creates
   refinery/mayor clones, witness, polecats dir, seeds patrol molecules).
3. `gt crew add robert --rig borg-cube` for a human seat.
4. `gt up` (starts Mayor, Deacon, Witness, Refinery in tmux). Check `gt agents`,
   `gt feed`.
5. Create one small internal bead in the rig (`bd create` inside the rig, e.g.
   "add --version output test to cube") and dispatch it: `gt sling <id> borg-cube`
   with the Claude Code runtime, then a second one with the Codex runtime
   (`settings/config.json` runtime preset `codex`, must use `-p cube-chatgpt`).
6. Observe: polecat spawn, worktree hook, `gt done`, refinery merge into main,
   convoy status, witness behaviour on a deliberately stuck polecat (kill its
   tmux window), `gt escalate`, and how a cube-side process could read completion
   (beads state in the rig `.beads`).
7. Cost and noise: tokens per polecat run (`gt trail`), background patrol
   token use over 24 h with no work queued.

## Kill criteria (any one means cube-only)

- No way to run the dispatch headless from `cube run` (sling + poll) without a
  human in the Mayor session.
- Witness or Refinery restart loops or merge failures on the trivial bead.
- Idle patrol cost above what `cube worker` would spend doing nothing (target:
  zero tokens when idle).
- Codex runtime cannot be forced onto the `cube-chatgpt` profile.

## Adopt criteria

- Both beads land on main through the refinery with review comments intact.
- `cube` can create a rig bead, sling it, and read the closed state and merge
  commit from the rig beads within one polling loop.
- Formulas (TOML) express design -> implement -> review with the review step on
  a plan-tier runtime.

## Outcome

Record the decision in `adr/0010-gas-town-for-coding-rigs.md` (status accepted
or rejected) with the measurements from steps 6 and 7.
