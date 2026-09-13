# vLLM on unimatrix node005 (the `local` tier)

ADR-0011 records why. This page is the install and operations note.

## Access

- Head node: `ssh unimatrix01` (cluster login node; credentials live outside
  the repository, reference them by path only, never print).
- Compute nodes are reachable only through unimatrix01; Robert's ssh config
  has `ProxyJump`, so `ssh node005` works from the laptop and from ws.
- `/home` is NFS-shared cluster-wide; `/storage` is for environments and
  results, `/data` for databases. Slurm 23.11, partition `debug`.
- node005: 2x RTX 4090 (24 GB each), driver 580.159.03. Do not touch drivers
  on other nodes: node003 is Kepler and capped at 470; node006 has a dead
  second card. See `project_unimatrix_cluster` memory and
  `borg-infrastructure/unimatrix/KNOWN_ISSUES.md`.

## Install (once, on unimatrix01 or node005; paths are shared)

```
mkdir -p /storage/cube ~/cube-vllm
curl -LsSf https://astral.sh/uv/install.sh | sh          # if uv is missing; inspect the script first
uv venv /storage/cube/vllm-venv --python 3.12
source /storage/cube/vllm-venv/bin/activate
uv pip install vllm                                       # pin the version in this file once chosen
export HF_HOME=/storage/cube/hf
huggingface-cli download Qwen/Qwen3-32B-FP8               # verify the exact id on huggingface.co first
cp ~/Public/software/borg-cube/deploy/vllm-node005.sbatch ~/cube-vllm/   # or rsync from ws
```

Docker alternative: if Docker is available on node005 the vLLM image
(`vllm/vllm-openai`) with `--gpus all` works with the same flags; the sbatch
would then wrap `docker run`. Not the default.

## Start, stop, status

```
sbatch ~/cube-vllm/vllm-node005.sbatch                    # or: cube local start
squeue -u $USER -n cube-vllm                            # or: cube local status
scancel <jobid>                                           # or: cube local stop (asks first)
cat ~/cube-vllm/endpoint                                  # url=http://node005:8000/v1 ...
```

The job requeues on preemption (`--requeue`) and runs up to 14 days; extend
or resubmit as policy allows. When the job is not running the endpoint file is
absent and the router marks the local tier down; `privacy:local-only` beads
queue rather than leak.

## Health check

From ws (KAUST network, no tunnel):

```
curl -s http://node005:8000/v1/models | jq .
curl -s http://node005:8000/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"local","messages":[{"role":"user","content":"Say ok."}],"max_tokens":5}'
```

The infra-hygiene patrol runs the first call daily; the Sentinel marks
`local` available only when it answers. Tool calling is verified with a
request carrying a `tools` array (the `hermes` parser must return a
`tool_calls` object, not text).

## Model candidates

VRAM figures are estimates for weights plus a modest KV cache at 32k context
on 48 GB total; verify with `nvidia-smi` after loading. The exact HF model
ids must be checked before the first download; quantised variants move
between organisations.

| Model | Use | Estimated VRAM | Notes |
|---|---|---|---|
| Qwen3-32B FP8 or AWQ | default general model for `privacy:local-only` work | about 20 GB (estimate) | tensor parallel 2, hermes tool parser |
| Qwen2.5-Coder-32B (AWQ/FP8) | code tasks | about 20 GB (estimate) | swap in for implement-tier local runs |
| Qwen3-Coder-30B-A3B | code tasks, fast (MoE, 3B active) | about 18 GB (estimate) | check vLLM MoE support for the quant used |
| gpt-oss-20b | fast and cheap bulk model | about 14 GB (estimate) | can run alongside a second small model at TP 1 |
| Llama 3.3 70B AWQ | only if quality demands | about 40 GB (estimate) | little KV headroom; shorter `--max-model-len` |

One model per GPU pair at TP 2, or two smaller models at TP 1 each (two
sbatch jobs with `--gres=gpu:1` and different ports). Phase 1 chooses by
evaluation on the group's own tasks (progress-note drafting, org entry
drafting, code summaries).

## Consumers

- Hermes profiles on ws: `providers.local.base_url: http://node005:8000/v1`
  (rendered from `VLLM_BASE_URL` in `.env`).
- cube `bulk` and `local` runners: OpenAI-compatible calls to the same URL.
- `claude` and `codex` never use it.

## Ownership

The System Administrator role owns this service: restarts, vLLM upgrades,
GPU health, disk under `/storage/cube`. Any `scancel` is quoted back and
confirmed first.

## Status 2026-09-02

- node005 probed via ws -> unimatrix01 -> node005: Ubuntu 24.04.4, 48 cores, 251 GB
  RAM, NFS `/home` (1.1 TB free), Docker present, Python 3.12.3, `uv` 0.12.9 installed
  for the cluster user, `tmux` present.
- **Blocker: NVML driver/library mismatch.** Kernel module is 580.159.03
  (`/proc/driver/nvidia/version`), userspace library is 580.173.02
  (`libnvidia-ml.so.580.173.02`), so `nvidia-smi` fails with "Driver/library version
  mismatch". An unattended upgrade replaced the userspace packages. Fix is a reboot of
  node005 (or unload/reload of the nvidia modules) once no jobs run: a state-changing
  sysadmin action that needs Robert's explicit go-ahead. Until then the `local` tier
  queues.
- vLLM venv install started in tmux session `vllm-install` on node005
  (`~/vllm`, log `~/vllm-install.log`); the sbatch script expects `~/vllm/bin/vllm`.
