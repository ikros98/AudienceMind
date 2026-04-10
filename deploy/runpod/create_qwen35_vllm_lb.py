#!/usr/bin/env python3
"""Provision a custom load-balanced RunPod endpoint for Qwen 3.5 on latest vLLM."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from runpod_flash.core.resources.gpu import GpuType
from runpod_flash.core.resources.load_balancer_sls_resource import LoadBalancerSlsResource
from runpod_flash.core.resources.serverless import ServerlessScalerType
from runpod_flash.core.resources.template import PodTemplate
from runpod_flash.core.utils.user_agent import get_user_agent


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "Qwen/Qwen3.5-35B-A3B-FP8"
DEFAULT_NAME = "AudienceMind Qwen35 latest vLLM"


def load_root_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def get_api_key() -> str:
    load_root_env()
    api_key = (
        os.getenv("RUNPOD_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("GRAPHITI_LLM_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Missing RUNPOD_API_KEY / LLM_API_KEY")
    return api_key


def http_json(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    timeout: int = 30,
) -> tuple[int, object]:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "identity",
        "User-Agent": get_user_agent(),
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            decoded = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            decoded = payload
        return exc.code, decoded


async def deploy_endpoint() -> LoadBalancerSlsResource:
    model = os.getenv("RUNPOD_QWEN_MODEL", DEFAULT_MODEL)
    image = os.getenv("RUNPOD_VLLM_IMAGE", "").strip()
    name = os.getenv("RUNPOD_QWEN_ENDPOINT_NAME", DEFAULT_NAME)
    if not image:
        raise RuntimeError("Missing RUNPOD_VLLM_IMAGE. Push the custom worker image first.")

    template = PodTemplate(
        name=f"{name} template",
        imageName=image,
        containerDiskInGb=int(os.getenv("RUNPOD_VLLM_CONTAINER_DISK_GB", "150")),
        ports=os.getenv("RUNPOD_VLLM_EXPOSED_PORTS", "80/http"),
    )

    resource = LoadBalancerSlsResource(
        name=name,
        imageName=image,
        template=template,
        env={},
        gpus=[
            GpuType.NVIDIA_H100_80GB_HBM3,
            GpuType.NVIDIA_A100_SXM4_80GB,
        ],
        gpuCount=1,
        workersMin=int(os.getenv("RUNPOD_VLLM_WORKERS_MIN", "1")),
        workersMax=int(os.getenv("RUNPOD_VLLM_WORKERS_MAX", "4")),
        idleTimeout=int(os.getenv("RUNPOD_VLLM_IDLE_TIMEOUT", "5")),
        scalerType=ServerlessScalerType.REQUEST_COUNT,
        scalerValue=int(os.getenv("RUNPOD_VLLM_SCALER_VALUE", "1")),
        flashboot=os.getenv("RUNPOD_VLLM_FLASHBOOT", "true").lower() in {"1", "true", "yes"},
        executionTimeoutMs=0,
    )

    resource.env["FLASH_ENDPOINT_TYPE"] = "lb"
    resource.env["PORT"] = os.getenv("RUNPOD_VLLM_PORT", "80")
    resource.env["PORT_HEALTH"] = os.getenv("RUNPOD_VLLM_PORT_HEALTH", resource.env["PORT"])
    resource.env["MODEL_NAME"] = model
    resource.env["SERVED_MODEL_NAME"] = os.getenv("RUNPOD_SERVED_MODEL_NAME", model)
    resource.env["VLLM_GPU_MEMORY_UTILIZATION"] = os.getenv("RUNPOD_VLLM_GPU_MEMORY_UTILIZATION", "0.90")
    resource.env["VLLM_MAX_MODEL_LEN"] = os.getenv("RUNPOD_VLLM_MAX_MODEL_LEN", "8192")
    resource.env["VLLM_REASONING_PARSER"] = os.getenv("RUNPOD_VLLM_REASONING_PARSER", "qwen3")
    resource.env["VLLM_LANGUAGE_MODEL_ONLY"] = os.getenv("RUNPOD_VLLM_LANGUAGE_MODEL_ONLY", "true")
    resource.env["VLLM_DEEP_GEMM_WARMUP"] = os.getenv("RUNPOD_VLLM_DEEP_GEMM_WARMUP", "skip")
    resource.env["WORKER_WARMUP_TIMEOUT_SECONDS"] = os.getenv("RUNPOD_VLLM_READY_TIMEOUT_SECONDS", "1800")
    resource.env["TENSOR_PARALLEL_SIZE"] = os.getenv("RUNPOD_VLLM_TENSOR_PARALLEL_SIZE", "1")

    optional_env = {
        "VLLM_EXTRA_ARGS": os.getenv("RUNPOD_VLLM_EXTRA_ARGS"),
        "VLLM_USE_DEEP_GEMM": os.getenv("RUNPOD_VLLM_USE_DEEP_GEMM"),
        "VLLM_ENFORCE_EAGER": os.getenv("RUNPOD_VLLM_ENFORCE_EAGER"),
        "VLLM_TRUST_REMOTE_CODE": os.getenv("RUNPOD_VLLM_TRUST_REMOTE_CODE"),
    }
    for key, value in optional_env.items():
        if value:
            resource.env[key] = value

    payload = resource.model_dump(
        exclude=resource._payload_exclude(),
        exclude_none=True,
        mode="json",
    )
    resource._inject_multi_volume_payload(payload)

    mutation = """
    mutation saveEndpoint($input: EndpointInput!) {
        saveEndpoint(input: $input) {
            id
            name
            templateId
            workersMax
            workersMin
            scalerType
            scalerValue
            idleTimeout
            gpuCount
            executionTimeoutMs
            type
        }
    }
    """

    status, response = http_json(
        "POST",
        "https://api.runpod.io/graphql",
        token=get_api_key(),
        body={"query": mutation, "variables": {"input": payload}},
        timeout=120,
    )
    if status >= 400:
        raise RuntimeError(f"RunPod GraphQL saveEndpoint failed: {status} {response}")
    if not isinstance(response, dict) or "errors" in response:
        raise RuntimeError(f"RunPod GraphQL returned errors: {response}")

    endpoint_data = response.get("data", {}).get("saveEndpoint")
    if not endpoint_data:
        raise RuntimeError(f"RunPod GraphQL returned no endpoint data: {response}")

    resource.id = endpoint_data["id"]
    resource.templateId = endpoint_data.get("templateId")
    return resource


def wait_until_ready(endpoint_id: str, endpoint_url: str, token: str) -> None:
    deadline = time.time() + int(os.getenv("RUNPOD_VLLM_READY_TIMEOUT_SECONDS", "1800"))
    last_health: object = {}

    while time.time() < deadline:
        health_status, health = http_json(
            "GET",
            f"https://api.runpod.ai/v2/{endpoint_id}/health",
            token=token,
            timeout=30,
        )
        last_health = health

        models_status, models = http_json(
            "GET",
            f"{endpoint_url}/v1/models",
            token=token,
            timeout=30,
        )

        print(
            json.dumps(
                {
                    "health_status": health_status,
                    "health": health,
                    "models_status": models_status,
                    "models": models,
                },
                indent=2,
            )
        )

        if models_status == 200:
            return

        time.sleep(20)

    raise TimeoutError(f"Endpoint did not become ready in time: {last_health}")


async def main() -> int:
    token = get_api_key()
    os.environ.setdefault("RUNPOD_API_KEY", token)

    resource = await deploy_endpoint()
    endpoint_id = resource.id
    endpoint_url = resource.endpoint_url

    if not endpoint_id:
        raise RuntimeError("Deployment returned no endpoint id")

    print(f"endpoint_id={endpoint_id}")
    print(f"endpoint_url={endpoint_url}")

    wait_until_ready(endpoint_id, endpoint_url, token)
    print("ready=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
