# RunPod deployment

## Custom latest-vLLM load-balancer worker

The stock RunPod `worker-vllm` image was not sufficient for `Qwen/Qwen3.5-35B-A3B-FP8` because workers could be considered healthy before the OpenAI API was actually usable. The custom worker under [custom_vllm_lb_worker](./custom_vllm_lb_worker) fixes that by:

- starting vLLM inside the container
- exposing `/ping` from a wrapper FastAPI app
- returning `204` while the model is still loading or warming up
- returning `200` only after an internal warmup chat request succeeds

That is the correct shape for RunPod load balancing, which routes traffic based on `/ping`.

## Build and push

```bash
docker build --platform linux/amd64 \
  -t ghcr.io/YOUR_GH_USER/audiencemind-qwen35-vllm-lb:latest \
  -f deploy/runpod/custom_vllm_lb_worker/Dockerfile .

echo "$CR_PAT" | docker login ghcr.io -u YOUR_GH_USER --password-stdin
docker push ghcr.io/YOUR_GH_USER/audiencemind-qwen35-vllm-lb:latest
```

## Create the endpoint

```bash
RUNPOD_VLLM_IMAGE=ghcr.io/YOUR_GH_USER/audiencemind-qwen35-vllm-lb:latest \
uv run --with runpod-flash==1.10.0 python deploy/runpod/create_qwen35_vllm_lb.py
```

## Recommended env

```bash
RUNPOD_QWEN_MODEL=Qwen/Qwen3.5-35B-A3B-FP8
RUNPOD_VLLM_WORKERS_MIN=1
RUNPOD_VLLM_WORKERS_MAX=4
RUNPOD_VLLM_SCALER_VALUE=1
RUNPOD_VLLM_GPU_MEMORY_UTILIZATION=0.90
RUNPOD_VLLM_MAX_MODEL_LEN=8192
RUNPOD_VLLM_DEEP_GEMM_WARMUP=skip
RUNPOD_VLLM_TENSOR_PARALLEL_SIZE=1
```

## Notes

- Increase `TENSOR_PARALLEL_SIZE` only if you also increase `gpuCount` per worker.
- `VLLM_DEEP_GEMM_WARMUP=skip` is recommended for this load-balanced setup because the wrapper performs its own readiness-gated warmup request before marking the worker healthy.
- If DeepGEMM remains unstable on your target hardware, try `RUNPOD_VLLM_USE_DEEP_GEMM=0`.
