# borg-cube task runner. Every recipe is safe to run repeatedly.

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# --- development -----------------------------------------------------------

sync:
    uv sync --all-extras

test:
    uv run pytest -q

lint:
    uv run ruff check cube tools tests
    uv run mypy cube

fmt:
    uv run ruff format cube tools tests
    uv run ruff check --fix cube tools tests

check: lint test skills-lint emacs-check emacs-contract

doctor *ARGS:
    uv run cube doctor {{ARGS}}

# --- knowledge -------------------------------------------------------------

seed *ARGS:
    uv run cube seed {{ARGS}}

brain-push *ARGS:
    uv run cube brain push {{ARGS}}

corpus-fetch *ARGS:
    uv run python tools/corpus_fetch.py {{ARGS}}

corpus-convert *ARGS:
    uv run python tools/corpus_convert.py {{ARGS}}

corpus-verify *ARGS:
    uv run python tools/corpus_verify.py {{ARGS}}

skills-lint *ARGS:
    uv run python tools/skills_lint.py {{ARGS}}

skills-sync *ARGS:
    uv run python tools/skills_sync.py {{ARGS}}

skills-test:
    uv run pytest -q tests/skills

pipeline-rehearsal:
    uv run python -m cube.cli pipeline rehearse

# --- deployment ------------------------------------------------------------

deploy-skills *ARGS:
    uv run python tools/deploy.py {{ARGS}}

hermes-render *ARGS:
    uv run cube hermes render {{ARGS}}

install-timers *ARGS:
    uv run cube systemd install {{ARGS}}

mirror-agents:
    cp CLAUDE.md AGENTS.md

# --- cockpit ---------------------------------------------------------------

emacs-check:
    make -C emacs check

emacs-contract:
    make -C emacs contract

# --- ledger ----------------------------------------------------------------

ready:
    bd ready

sync-beads *ARGS:
    uv run cube sync {{ARGS}}

# --- host --------------------------------------------------------------------

# Pull the pushed main on the orchestration host, sync the venv, run doctor and the tests there.
deploy-ws host="ws":
    ssh -o ConnectTimeout=10 {{host}} 'export PATH=$HOME/.local/bin:$HOME/.cargo/bin:$PATH; cd ~/Public/software/borg-cube && git pull --ff-only && uv sync --all-extras && uv run cube doctor && uv run pytest -q'
