FROM vllm/vllm-openai:v0.18.0

WORKDIR /app

COPY deploy/runpod/custom_vllm_lb_worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY deploy/runpod/custom_vllm_lb_worker/app.py /app/app.py

ENV PORT=80 \
    PORT_HEALTH=80 \
    VLLM_INTERNAL_HOST=127.0.0.1 \
    VLLM_INTERNAL_PORT=8000 \
    VLLM_DEEP_GEMM_WARMUP=skip \
    VLLM_LANGUAGE_MODEL_ONLY=true \
    VLLM_REASONING_PARSER=qwen3 \
    WORKER_LOG_LEVEL=INFO

EXPOSE 80 8000

ENTRYPOINT []
CMD ["python3", "/app/app.py"]
