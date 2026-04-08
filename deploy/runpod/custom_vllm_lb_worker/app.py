#!/usr/bin/env python3
"""RunPod load-balancer worker that gates readiness until vLLM is actually usable."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask


LOG_LEVEL = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("custom_vllm_lb_worker")


def getenv_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def getenv_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


@dataclass
class WorkerState:
    ready: bool = False
    error: str | None = None
    process: subprocess.Popen[str] | None = None
    started_at: float = field(default_factory=time.time)
    warmup_started_at: float | None = None
    ready_at: float | None = None


LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = getenv_int("PORT", 80)
INTERNAL_HOST = os.getenv("VLLM_INTERNAL_HOST", "127.0.0.1")
INTERNAL_PORT = getenv_int("VLLM_INTERNAL_PORT", 8000)
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-35B-A3B-FP8")
SERVED_MODEL_NAME = os.getenv("SERVED_MODEL_NAME", MODEL_NAME)
WARMUP_TIMEOUT_SECONDS = getenv_int("WORKER_WARMUP_TIMEOUT_SECONDS", 1800)
WARMUP_PROMPT = os.getenv("WORKER_WARMUP_PROMPT", "Reply with the single word ok.")
VLLM_BASE_URL = f"http://{INTERNAL_HOST}:{INTERNAL_PORT}"
HTTP_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=float(os.getenv("WORKER_PROXY_READ_TIMEOUT_SECONDS", "330")),
    write=30.0,
    pool=None,
)

state = WorkerState()
state_lock = threading.Lock()
startup_thread: threading.Thread | None = None
app = FastAPI(title="PersonaGraph custom vLLM LB worker", docs_url=None, redoc_url=None)


def build_vllm_command() -> list[str]:
    command = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--host",
        INTERNAL_HOST,
        "--port",
        str(INTERNAL_PORT),
        "--model",
        MODEL_NAME,
        "--served-model-name",
        SERVED_MODEL_NAME,
        "--dtype",
        os.getenv("VLLM_DTYPE", "auto"),
        "--gpu-memory-utilization",
        str(getenv_float("VLLM_GPU_MEMORY_UTILIZATION", 0.90)),
        "--max-model-len",
        str(getenv_int("VLLM_MAX_MODEL_LEN", 8192)),
        "--tensor-parallel-size",
        str(getenv_int("TENSOR_PARALLEL_SIZE", 1)),
    ]

    reasoning_parser = os.getenv("VLLM_REASONING_PARSER", "qwen3").strip()
    if reasoning_parser:
        command.extend(["--reasoning-parser", reasoning_parser])

    if getenv_bool("VLLM_LANGUAGE_MODEL_ONLY", True):
        command.append("--language-model-only")
    if getenv_bool("VLLM_TRUST_REMOTE_CODE", False):
        command.append("--trust-remote-code")
    if getenv_bool("VLLM_ENFORCE_EAGER", False):
        command.append("--enforce-eager")
    # vLLM uses --enable-log-requests / --no-enable-log-requests.
    # Default is already "disabled", so we only need to pass the positive flag.
    if getenv_bool("VLLM_ENABLE_LOG_REQUESTS", False):
        command.append("--enable-log-requests")

    extra_args = os.getenv("VLLM_EXTRA_ARGS", "").strip()
    if extra_args:
        command.extend(shlex.split(extra_args))

    return command


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("VLLM_DEEP_GEMM_WARMUP", os.getenv("VLLM_DEEP_GEMM_WARMUP", "skip"))
    return env


def process_alive() -> bool:
    with state_lock:
        process = state.process
    return bool(process and process.poll() is None)


def set_error(message: str) -> None:
    logger.error("%s", message)
    with state_lock:
        state.error = message
        state.ready = False


def wait_for_vllm_process() -> subprocess.Popen[str]:
    command = build_vllm_command()
    logger.info("Starting vLLM: %s", " ".join(shlex.quote(part) for part in command))
    process = subprocess.Popen(
        command,
        env=child_env(),
        text=True,
    )
    with state_lock:
        state.process = process
    return process


def wait_for_internal_http(process: subprocess.Popen[str]) -> None:
    deadline = time.time() + WARMUP_TIMEOUT_SECONDS
    models_url = f"{VLLM_BASE_URL}/v1/models"
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited early with code {process.returncode}")
        try:
            response = httpx.get(models_url, timeout=10.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise TimeoutError("Timed out waiting for the internal vLLM API server")


def run_internal_warmup(process: subprocess.Popen[str]) -> None:
    deadline = time.time() + WARMUP_TIMEOUT_SECONDS
    payload = {
        "model": SERVED_MODEL_NAME,
        "messages": [{"role": "user", "content": WARMUP_PROMPT}],
        "max_tokens": 8,
        "temperature": 0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = f"{VLLM_BASE_URL}/v1/chat/completions"

    with state_lock:
        state.warmup_started_at = time.time()

    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"vLLM exited during warmup with code {process.returncode}")
        try:
            response = httpx.post(url, json=payload, timeout=180.0)
            if response.status_code == 200:
                logger.info("Internal warmup chat request completed successfully")
                return
            logger.warning(
                "Warmup request returned status %s: %s",
                response.status_code,
                response.text[:500],
            )
        except httpx.HTTPError as exc:
            logger.info("Warmup request still pending: %s", exc)
        time.sleep(3)

    raise TimeoutError("Timed out during internal vLLM warmup request")


def bootstrap_vllm() -> None:
    try:
        process = wait_for_vllm_process()
        wait_for_internal_http(process)
        run_internal_warmup(process)
        with state_lock:
            state.ready = True
            state.error = None
            state.ready_at = time.time()
        logger.info("Worker ready: vLLM is serving OpenAI-compatible requests")
    except Exception as exc:  # noqa: BLE001
        set_error(str(exc))


def sanitize_request_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    blocked = {
        "authorization",
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
    return {key: value for key, value in headers if key.lower() not in blocked}


def sanitize_response_headers(headers: httpx.Headers) -> dict[str, str]:
    blocked = {"content-length", "connection", "transfer-encoding", "content-encoding"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


async def proxy_request(upstream_path: str, request: Request) -> Response:
    if not process_alive():
        detail = state.error or "vLLM worker process is not running"
        return JSONResponse({"error": detail}, status_code=503)
    if not state.ready:
        return Response(status_code=204)

    body = await request.body()
    headers = sanitize_request_headers(request.headers.items())
    upstream_url = f"{VLLM_BASE_URL}{upstream_path}"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            headers=headers,
            content=body,
            params=request.query_params,
        )
        upstream_response = await client.send(
            upstream_request,
            stream=bool("text/event-stream" in request.headers.get("accept", "")),
        )

        if request.headers.get("accept", "").find("text/event-stream") != -1:
            return StreamingResponse(
                upstream_response.aiter_raw(),
                status_code=upstream_response.status_code,
                headers=sanitize_response_headers(upstream_response.headers),
                background=BackgroundTask(upstream_response.aclose),
            )

        content = await upstream_response.aread()
        return Response(
            content=content,
            status_code=upstream_response.status_code,
            headers=sanitize_response_headers(upstream_response.headers),
            media_type=upstream_response.headers.get("content-type"),
        )


@app.on_event("startup")
async def startup() -> None:
    global startup_thread
    startup_thread = threading.Thread(target=bootstrap_vllm, daemon=True, name="vllm-bootstrap")
    startup_thread.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    with state_lock:
        process = state.process
    if not process or process.poll() is not None:
        return

    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


@app.get("/ping")
async def ping() -> Response:
    if state.ready and process_alive():
        return Response(status_code=200)
    if state.error or not process_alive():
        return JSONResponse({"status": "error", "error": state.error or "worker exited"}, status_code=503)
    return Response(status_code=204)


@app.get("/")
async def root() -> JSONResponse:
    with state_lock:
        body = {
            "service": "personagraph-custom-vllm-lb-worker",
            "model": MODEL_NAME,
            "served_model_name": SERVED_MODEL_NAME,
            "ready": state.ready,
            "error": state.error,
            "started_at": state.started_at,
            "warmup_started_at": state.warmup_started_at,
            "ready_at": state.ready_at,
            "internal_base_url": VLLM_BASE_URL,
        }
    return JSONResponse(body)


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def openai_proxy(path: str, request: Request) -> Response:
    return await proxy_request(f"/v1/{path}", request)


@app.api_route("/openai/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def openai_prefixed_proxy(path: str, request: Request) -> Response:
    return await proxy_request(f"/v1/{path}", request)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level=LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
