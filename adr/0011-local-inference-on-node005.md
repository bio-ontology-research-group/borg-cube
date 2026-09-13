# ADR-0011: Local inference on unimatrix node005 as the `local` tier

Status: accepted
Date: 2026-09-02

## Context

`privacy:local-only` material (ADR-0007) needs a model that never leaves
KAUST. The laptop GPU is 8 GB and the laptop is often closed. The group's
Slurm cluster unimatrix has one real ML node: node005 with 2x RTX 4090 (24 GB
each, 48 GB total), driver 580.159.03, Slurm 23.11, partition `debug`,
reachable from ws over the KAUST network through the head node unimatrix01
(`ProxyJump` in Robert's ssh config). Hermes documents vLLM with
`--enable-auto-tool-choice --tool-call-parser hermes` for tool calling. The
node is shared with other group jobs.

## Decision

- vLLM serves the `local` tier on node005, started by a Slurm job
  (`deploy/vllm-node005.sbatch`: `--nodelist=node005 --gres=gpu:2`, long wall
  time, requeue on preemption) from a uv venv, or as a systemd unit if the
  node can be dedicated later.
- Flags: `--tensor-parallel-size 2 --enable-auto-tool-choice
  --tool-call-parser hermes --max-model-len 32768`, OpenAI-compatible API on
  port 8000.
- Model choice is decided by evaluation in Phase 1. Candidates, with VRAM
  estimates: Qwen3-32B FP8/AWQ (about 20 GB) as the default general model;
  Qwen2.5-Coder-32B or Qwen3-Coder-30B-A3B for code; gpt-oss-20b (about 14
  GB) as the fast bulk model; Llama 3.3 70B AWQ (about 40 GB) only if quality
  demands and KV headroom allows. One model at a time on the GPU pair, or two
  smaller models at `--tensor-parallel-size 1` each.
- Consumers: Hermes profiles on ws get a `providers.local` entry
  (`base_url: http://node005:8000/v1`); cube's `bulk` and `local` runners call
  the same endpoint. `claude` and `codex` never use it (they stay on their
  subscriptions).
- Availability: `cube local status|start|stop` wraps `sbatch`/`squeue`/
  `scancel`; the Sentinel checks `/v1/models`; the router marks `local`
  available only when it answers, otherwise local-only work queues.
- The laptop's ollama models are an optional offline fallback only, not part
  of the server design.

## Consequences

- Local-only work has a real home; privacy is enforced by routing, not by
  hoping.
- node005 is shared; a preempted or queued job means the local tier is down
  and local-only beads wait. This is acceptable and visible.
- Model files and the venv live on the cluster's shared `/home` or `/storage`
  as decided in `deploy/vllm-node005.md`; the HF model id must be verified
  before the first run.
- The System Administrator role owns this service (restart, upgrade, GPU
  health).

## Alternatives considered

- Cloud models with a data processing agreement: not available for personal
  student data on our terms, and slower to arrange than a local server.
- Ollama on node005: simpler install, weaker tool calling and batching than
  vLLM.
- The laptop GPU: 8 GB fits only small models and is not always on.
- A dedicated GPU box in the office: no budget line today; revisit if node005
  contention becomes a problem.
