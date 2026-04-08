from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    service_name: str
    host: str
    port: int
    log_level: str
    bearer_token: str
    data_dir: Path
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_small_model: str
    llm_temperature: float
    llm_max_tokens: int
    llm_timeout_seconds: float
    llm_max_retries: int
    reasoning_effort: str | None
    force_reasoning_off: bool
    embedder_base_url: str
    embedder_api_key: str
    embedding_model: str
    embedder_timeout_seconds: float
    embedder_max_retries: int
    embedder_max_concurrency: int
    reranker_base_url: str
    reranker_api_key: str
    reranker_model: str
    search_reranker: str
    max_page_size: int

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"


def load_settings() -> Settings:
    data_dir = Path(_env("GRAPHITI_SERVICE_DATA_DIR", "./deploy/graphiti/data")).expanduser()
    llm_base_url = _env("GRAPHITI_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    llm_api_key = _env("GRAPHITI_LLM_API_KEY", "graphiti-local")
    embedder_base_url = _env("GRAPHITI_EMBEDDER_BASE_URL", llm_base_url)
    embedder_api_key = _env("GRAPHITI_EMBEDDER_API_KEY", llm_api_key)
    reranker_base_url = _env("GRAPHITI_RERANKER_BASE_URL", llm_base_url)
    reranker_api_key = _env("GRAPHITI_RERANKER_API_KEY", llm_api_key)
    reasoning_effort = os.getenv("GRAPHITI_LLM_REASONING_EFFORT", "").strip() or None

    return Settings(
        service_name=_env("GRAPHITI_SERVICE_NAME", "personagraph-graphiti"),
        host=_env("GRAPHITI_SERVICE_HOST", "127.0.0.1"),
        port=_int_env("GRAPHITI_SERVICE_PORT", 8182),
        log_level=_env("GRAPHITI_SERVICE_LOG_LEVEL", "INFO"),
        bearer_token=_env("GRAPHITI_SERVICE_BEARER_TOKEN", required=True),
        data_dir=data_dir,
        neo4j_uri=_env("NEO4J_URI", required=True),
        neo4j_user=_env("NEO4J_USER", required=True),
        neo4j_password=_env("NEO4J_PASSWORD", required=True),
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=_env("GRAPHITI_LLM_MODEL", "qwen3.5:35b-a3b"),
        llm_small_model=_env("GRAPHITI_LLM_SMALL_MODEL", "qwen3.5:9b"),
        llm_temperature=float(_env("GRAPHITI_LLM_TEMPERATURE", "0")),
        llm_max_tokens=_int_env("GRAPHITI_LLM_MAX_TOKENS", 4096),
        llm_timeout_seconds=float(_env("GRAPHITI_LLM_TIMEOUT_SECONDS", "300")),
        llm_max_retries=_int_env("GRAPHITI_LLM_MAX_RETRIES", 1),
        reasoning_effort=reasoning_effort,
        force_reasoning_off=_bool_env("GRAPHITI_LLM_FORCE_REASONING_OFF", True),
        embedder_base_url=embedder_base_url,
        embedder_api_key=embedder_api_key,
        embedding_model=_env("GRAPHITI_EMBEDDING_MODEL", "bge-large-en-v1.5"),
        embedder_timeout_seconds=float(_env("GRAPHITI_EMBEDDER_TIMEOUT_SECONDS", "120")),
        embedder_max_retries=_int_env("GRAPHITI_EMBEDDER_MAX_RETRIES", 3),
        embedder_max_concurrency=_int_env("GRAPHITI_EMBEDDER_MAX_CONCURRENCY", 2),
        reranker_base_url=reranker_base_url,
        reranker_api_key=reranker_api_key,
        reranker_model=_env("GRAPHITI_RERANKER_MODEL", "qwen3.5:9b"),
        search_reranker=_env("GRAPHITI_SEARCH_RERANKER", "rrf").lower(),
        max_page_size=_int_env("GRAPHITI_MAX_PAGE_SIZE", 500),
    )
