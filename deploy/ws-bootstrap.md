# ws bootstrap

Steps to make the office workstation `ws` the orchestration host (ADR-0008).
Run as `leechuck` on ws (`ssh ws`). Everything is idempotent; re-run any
step. Nothing here touches `~/.hermes/config.yaml`, `~/.hermes/AGENTS.md` or
the `hermes-ws` gateway.

1. Tools present: `git`, `python3` (3.12+), `tmux` (`sudo apt install tmux`
   if missing; needed for persistent sessions and for a later Gas Town spike),
   `jq`, `curl`, `rsync`, `gh`.
2. uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (read the script
   first), then `uv --version`.
3. just: `uv tool install rust-just` or the distro package; `just --version`.
4. Beads: install `bd` with the project's curl script from the Beads README
   (inspect before running), pin the version in `cube.yaml` `beads.version`
   once known; `bd --version`. Nightly `bd export` backup is set up by
   `cube systemd install`.
5. skills-ref: `uv tool install skills-ref` (provides `agentskills validate`
   for `just skills-lint`).
6. Data repo clones at the paths in `cube.yaml`:
   `git clone <org> ~/org`, `git clone leechuck/pa ~/Public/software/pa && ln -s ~/Public/software/pa ~/pa`,
   `git clone <rkg> ~/Public/software/website/research-knowledge-graph`,
   `git clone <borg-website> ~/Public/software/website/borg-website`.
   The hourly `data-pull` patrol keeps them fresh afterwards.
7. borg-cube: `git clone leechuck/borg-cube ~/Public/software/borg-cube && cd ~/Public/software/borg-cube && uv sync --all-extras`.
8. `.env`: `cp .env.example .env && chmod 600 .env`, fill the scoped tokens
   (OpenRouter key, GitHub fine-grained read token; Mattermost bot tokens
   later). Never a password.
9. Claude Code: `claude login` (device flow on ws is Claude Code itself,
   within terms, ADR-0006). Check `claude -p 'say ok' --output-format json`.
10. Codex: `codex login` (device flow) or copy `~/.codex/auth.json` from the
    laptop with mode 0600. Then add the profile from `deploy/codex-profile.toml`
    to `~/.codex/config.toml` (append; leave the default profile untouched).
    Check `codex exec -p cube-chatgpt --sandbox read-only 'say ok'` and confirm
    in the output that the provider is ChatGPT, not OpenRouter.
11. Beads init in the repo: `bd init`, `bd setup claude`, `bd setup codex`
    (installs the `bd prime` hooks for both runtimes).
12. Hermes profiles: `mkdir -p ~/.hermes/profiles/{advisor,concierge,scribe}`,
    create `~/.hermes/profiles/concierge/.env` (mode 0600) from
    `hermes/profiles/advisor/env.example` with the concierge token,
    `just hermes-render concierge`, `hermes -p concierge config validate`.
    The advisor profile waits for Phase 4.
13. Timers and worker: `just install-timers`, then
    `systemctl --user list-timers 'cube-*'`; `loginctl show-user leechuck | grep Linger`
    must say yes.
14. `just doctor` (`cube doctor`) must be green: paths, tokens' file modes,
    `bd`, `claude`, `codex` profile, Hermes binary, tmux, no outbound
    `autonomous_actions`, `contacts.yaml` empty.
15. Seed: `just seed` then `just brain-push` (`bd remember` facts from
    `brain/facts/`), `just seed -- --diff` shows drift later.
16. Emacs thin client on the laptop: `cube-remote-host` defaults to `"ws"`;
    test `ssh ws ~/Public/software/borg-cube/.venv/bin/cube status --json`
    and `ssh -t ws tmux new -A -s cube/test`.

Optional later: `deploy/vllm-node005.md` for the local tier; Gas Town spike
(Go 1.26 via `GOTOOLCHAIN=auto`) in Phase 3.

## Mattermost bot accounts (manual, Robert)

borg-cube needs two bot accounts on https://borg.bio2vec.net (System Console ->
Integrations -> Bot Accounts, or `POST /api/v4/bots` with a system-admin token):

| bot | purpose | token goes to |
|---|---|---|
| `borg-concierge` | Robert-only DM remote control (Hermes profile `concierge`) | `ws:~/Public/software/borg-cube/.env` as `MATTERMOST_CONCIERGE_TOKEN` |
| `borg-advisor` | student-facing advisor, allowlist generated from `contacts.yaml` grants only | `MATTERMOST_TOKEN` |

Record each bot's user id as `MATTERMOST_CONCIERGE_BOT_ID` / `MATTERMOST_ADVISOR_BOT_ID`
in the same `.env`. Existing bots on the server (`hermes-ws`, `hermes-home`) stay untouched.
Then `cube hermes deploy concierge --apply` renders the profile; `hermes -p concierge gateway`
starts it. Nothing posts to anyone until a grant exists (`cube contact grant`).
