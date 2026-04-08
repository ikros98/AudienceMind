#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${RUNPOD_VLLM_IMAGE:-}"

if [[ -z "${IMAGE_NAME}" ]]; then
  echo "Set RUNPOD_VLLM_IMAGE, for example:"
  echo "  RUNPOD_VLLM_IMAGE=ghcr.io/YOUR_GH_USER/personagraph-qwen35-vllm-lb:latest"
  exit 1
fi

echo "Building ${IMAGE_NAME}"
docker build --platform linux/amd64 \
  -t "${IMAGE_NAME}" \
  -f deploy/runpod/custom_vllm_lb_worker/Dockerfile .

echo "Pushing ${IMAGE_NAME}"
docker push "${IMAGE_NAME}"
