"""Application settings for PersonaGraph."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


for candidate in (
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[2] / ".env",
    Path(__file__).resolve().parents[3] / ".env",
):
    if candidate.exists():
        load_dotenv(candidate, override=False)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "PersonaGraph API"
    env: str = "development"
    database_url: str = "sqlite:///./personagraph.db"
    data_dir: str = "./data"
    allowed_origins: list[str] = [
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        "http://localhost:3020",
        "http://127.0.0.1:3020",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
    ]
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3.5:9b"
    graph_backend: str = "graphiti"
    graphiti_base_url: str = "http://127.0.0.1:8182"
    graphiti_api_key: str = ""
    graphiti_timeout_seconds: float = 300.0
    simulation_backend: str = "native"
    report_backend: str = "native"
    graph_chunk_size: int = 1000
    graph_chunk_overlap: int = 100
    graph_batch_size: int = 1
    embed_workflow_runner: bool = True
    workflow_poll_interval_seconds: float = 0.25

    model_config = SettingsConfigDict(
        env_prefix="PERSONAGRAPH_",
        case_sensitive=False,
        env_file=(".env", "../.env", "../../.env"),
        extra="ignore",
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_allowed_origins(cls, value: object) -> list[str]:
        """Accept a comma-separated env var for allowed origins."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return value
        return [
            "http://localhost:3010",
            "http://127.0.0.1:3010",
            "http://localhost:3020",
            "http://127.0.0.1:3020",
            "http://localhost:3002",
            "http://127.0.0.1:3002",
            "http://localhost:5173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
            "http://localhost:4174",
            "http://127.0.0.1:4174",
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""
    legacy_overrides: dict[str, object] = {}

    if "PERSONAGRAPH_LLM_PROVIDER" not in os.environ:
        if os.environ.get("LLM_BASE_URL"):
            legacy_overrides["llm_provider"] = "openai-compatible"

    if "PERSONAGRAPH_LLM_BASE_URL" not in os.environ and os.environ.get("LLM_BASE_URL"):
        legacy_overrides["llm_base_url"] = os.environ["LLM_BASE_URL"]

    if "PERSONAGRAPH_LLM_API_KEY" not in os.environ and os.environ.get("LLM_API_KEY"):
        legacy_overrides["llm_api_key"] = os.environ["LLM_API_KEY"]

    if "PERSONAGRAPH_LLM_MODEL" not in os.environ and os.environ.get("LLM_MODEL_NAME"):
        legacy_overrides["llm_model"] = os.environ["LLM_MODEL_NAME"]

    if "PERSONAGRAPH_GRAPH_BACKEND" not in os.environ and os.environ.get("GRAPH_BACKEND"):
        legacy_overrides["graph_backend"] = os.environ["GRAPH_BACKEND"]

    if "PERSONAGRAPH_GRAPHITI_BASE_URL" not in os.environ and os.environ.get("GRAPHITI_BASE_URL"):
        legacy_overrides["graphiti_base_url"] = os.environ["GRAPHITI_BASE_URL"]

    if "PERSONAGRAPH_GRAPHITI_API_KEY" not in os.environ and os.environ.get("GRAPHITI_API_KEY"):
        legacy_overrides["graphiti_api_key"] = os.environ["GRAPHITI_API_KEY"]

    if "PERSONAGRAPH_GRAPHITI_TIMEOUT_SECONDS" not in os.environ and os.environ.get("GRAPHITI_TIMEOUT_SECONDS"):
        legacy_overrides["graphiti_timeout_seconds"] = os.environ["GRAPHITI_TIMEOUT_SECONDS"]

    return Settings(**legacy_overrides)
