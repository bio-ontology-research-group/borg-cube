#!/usr/bin/env bash
#SBATCH --job-name=cube-vllm
#SBATCH --partition=debug
#SBATCH --nodelist=node005
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=14-00:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@60
#SBATCH --output=%x-%j.out
# vLLM server for the borg-cube local tier (ADR-0011). Submit from unimatrix01:
#   sbatch ~/cube-vllm/vllm-node005.sbatch          (or: cube local start)
# Env overrides: VLLM_MODEL, VLLM_PORT, VLLM_VENV, VLLM_MAX_LEN, VLLM_ENDPOINT_FILE, HF_HOME.
# The default model id below MUST be verified on huggingface.co before the first run
# (an FP8 variant may be published under a different org or suffix); see vllm-node005.md.
set -euo pipefail

VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3-32B-FP8}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_VENV="${VLLM_VENV:-/storage/cube/vllm-venv}"
VLLM_MAX_LEN="${VLLM_MAX_LEN:-32768}"
VLLM_ENDPOINT_FILE="${VLLM_ENDPOINT_FILE:-$HOME/cube-vllm/endpoint}"
export HF_HOME="${HF_HOME:-/storage/cube/hf}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
export VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL:-INFO}"
# Conda-in-Slurm write-permission workaround from unimatrix KNOWN_ISSUES; harmless for uv venvs.
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib-$USER}"

mkdir -p "$(dirname "$VLLM_ENDPOINT_FILE")"
host="$(hostname -s)"
echo "$(date -Is) starting vLLM ${VLLM_MODEL} on ${host}:${VLLM_PORT} (job ${SLURM_JOB_ID})"

cleanup() {
  echo "$(date -Is) stopping (signal or exit)"
  rm -f "$VLLM_ENDPOINT_FILE"
  [ -n "${srv_pid:-}" ] && kill "$srv_pid" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

# shellcheck disable=SC1091
source "$VLLM_VENV/bin/activate"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

vllm serve "$VLLM_MODEL" \
  --host 0.0.0.0 --port "$VLLM_PORT" \
  --tensor-parallel-size 2 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len "$VLLM_MAX_LEN" \
  --gpu-memory-utilization 0.92 \
  --served-model-name local "$VLLM_MODEL" \
  --disable-log-requests &
srv_pid=$!

# Wait for /v1/models, then publish the endpoint for cube local status and the Sentinel.
for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
    printf 'url=http://%s:%s/v1\nmodel=%s\njob=%s\nstarted=%s\n' "$host" "$VLLM_PORT" "$VLLM_MODEL" "$SLURM_JOB_ID" "$(date -Is)" > "$VLLM_ENDPOINT_FILE"
    echo "$(date -Is) ready: http://${host}:${VLLM_PORT}/v1 (endpoint file ${VLLM_ENDPOINT_FILE})"
    break
  fi
  sleep 10
done
[ -f "$VLLM_ENDPOINT_FILE" ] || { echo "vLLM did not become ready in 20 min"; exit 1; }

wait "$srv_pid"
