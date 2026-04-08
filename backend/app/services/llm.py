"""OpenAI-compatible LLM adapter with safe fallbacks."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings


class LLMGenerationError(RuntimeError):
    """Raised when the configured LLM call fails."""


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible client for local and remote providers."""

    def __init__(self, settings: Settings):
        self.name = settings.llm_provider
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self._timeout = httpx.Timeout(20.0, connect=5.0)

    def describe(self) -> str:
        """Return a readable provider description."""
        return f"{self.name} at {self.base_url}"

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> str:
        """Call an OpenAI-compatible chat completions endpoint."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = self._extract_openai_content(data)
                if content:
                    return content

                if "/v1" in self.base_url:
                    native_response = client.post(
                        self.base_url.rsplit("/v1", 1)[0] + "/api/chat",
                        headers={"Content-Type": "application/json"},
                        json={
                            "model": self.model,
                            "stream": False,
                            "think": False,
                            "messages": payload["messages"],
                            "options": {
                                "temperature": temperature,
                            },
                        },
                    )
                    native_response.raise_for_status()
                    native_data = native_response.json()
                    native_content = self._extract_native_content(native_data)
                    if native_content:
                        return native_content
        except Exception as exc:  # noqa: BLE001
            raise LLMGenerationError(str(exc)) from exc
        raise LLMGenerationError("The provider returned an empty message.")

    @staticmethod
    def _extract_openai_content(data: dict[str, Any]) -> str:
        """Extract assistant content from an OpenAI-compatible response."""
        choices = data.get("choices") or []
        if not choices:
            raise LLMGenerationError("No completion choices returned by the provider.")

        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            content = "".join(text_parts)

        if isinstance(content, str) and content.strip():
            return content.strip()
        return ""

    @staticmethod
    def _extract_native_content(data: dict[str, Any]) -> str:
        """Extract assistant content from an Ollama native chat response."""
        message = data.get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
        return ""
