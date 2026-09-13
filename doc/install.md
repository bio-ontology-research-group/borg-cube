# Install

borg-cube runs on ws; the laptop is a cockpit (ADR-0008). The full ws
sequence is `deploy/ws-bootstrap.md`; this page is the short version plus the
laptop side.

## On ws

1. `uv`, `just`, `tmux`, `bd`, `skills-ref` installed; data repos cloned at
   the paths in `cube.yaml`.
2. `git clone leechuck/borg-cube ~/Public/software/borg-cube && cd $_ && uv sync --all-extras`.
3. `cp .env.example .env && chmod 600 .env`; fill scoped tokens only.
4. `claude login`; `codex login`; append `deploy/codex-profile.toml` to
   `~/.codex/config.toml`.
5. `bd init && bd setup claude && bd setup codex`.
6. `just hermes-render concierge` after creating its `.env`; `just install-timers`.
7. `just doctor` green; `just seed && just brain-push`.

## On the laptop

1. `git clone leechuck/borg-cube ~/Public/software/borg-cube` (for development
   and for the elisp).
2. Emacs: add `emacs/` to `load-path`, `(require 'borg-cube)`, `(cube-mode 1)`;
   `package-install eat`. `cube-remote-host` is `"ws"` by default.
3. `~/.codex/config.toml` gets the same `cube-chatgpt` profile (the default
   profile still bills OpenRouter; never run Codex for cube without `-p`).
4. Optional local mode for development: `uv sync`, `cube doctor`,
   `(setq cube-remote-host nil)`.

## Optional

- Local tier: `deploy/vllm-node005.md`.
- Advisor bot (Phase 4 only): create `@borg-advisor` on Mattermost, put its
  token in `~/.hermes/profiles/advisor/.env`, record the first grant with
  `cube contact grant`, which renders the profile and enables
  `cube-gateway-advisor.service`.

## Checks

`cube doctor` verifies: paths in `cube.yaml` exist; `.env` and Hermes `.env`
files are mode 0600; `bd`, `claude`, `codex` (with the profile), `hermes`,
`tmux` present; no `autonomous_actions` entry is outbound; `contacts.yaml`
parses; timers installed; `state/KILL` absent; no forbidden fields (grades,
HR) in beads.
