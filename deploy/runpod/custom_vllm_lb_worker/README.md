# Custom RunPod vLLM LB Worker

This worker wraps `vllm/vllm-openai:v0.18.0` with a small FastAPI process that exposes:

- `/ping` for RunPod load-balancer health checks
- `/v1/*` and `/openai/v1/*` as OpenAI-compatible proxy routes

The important behavior is readiness gating:

- `/ping` returns `204` while vLLM is still loading or warming up
- `/ping` returns `200` only after:
  - the internal vLLM server answers `/v1/models`
  - one internal `/v1/chat/completions` warmup request succeeds

That prevents RunPod from routing real traffic to a worker that still looks "up" but is not yet capable of serving requests.

## Build

```bash
docker build --platform linux/amd64 \
  -t ghcr.io/YOUR_GH_USER/audiencemind-qwen35-vllm-lb:latest \
  -f deploy/runpod/custom_vllm_lb_worker/Dockerfile .
```

## Push

```bash
echo "$CR_PAT" | docker login ghcr.io -u YOUR_GH_USER --password-stdin
docker push ghcr.io/YOUR_GH_USER/audiencemind-qwen35-vllm-lb:latest
```

## Runtime env

Required:

- `MODEL_NAME=Qwen/Qwen3.5-35B-A3B-FP8`
- `SERVED_MODEL_NAME=Qwen/Qwen3.5-35B-A3B-FP8`

Recommended:

- `VLLM_DEEP_GEMM_WARMUP=skip`
- `VLLM_GPU_MEMORY_UTILIZATION=0.90`
- `VLLM_MAX_MODEL_LEN=8192`
- `VLLM_REASONING_PARSER=qwen3`
- `VLLM_LANGUAGE_MODEL_ONLY=true`
- `WORKER_WARMUP_TIMEOUT_SECONDS=1800`

Optional:

- `TENSOR_PARALLEL_SIZE=1`
- `VLLM_EXTRA_ARGS=...`
- `VLLM_USE_DEEP_GEMM=0`

Use `VLLM_USE_DEEP_GEMM=0` only if DeepGEMM remains unstable on your chosen hardware. It is a fallback, not the preferred default.
