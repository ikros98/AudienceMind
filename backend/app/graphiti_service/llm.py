from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
import typing
from typing import Any
from urllib.parse import urlparse

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.graphiti import Graphiti
from graphiti_core.llm_client.config import LLMConfig, ModelSize
from graphiti_core.llm_client.errors import RateLimitError
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.prompts.models import Message

from .config import Settings

logger = logging.getLogger(__name__)
_MAX_TOKENS_BAD_REQUEST_RE = re.compile(r"max_total_tokens=(\d+)", re.IGNORECASE)


def _is_runpod_openai_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname == "api.runpod.ai" or hostname.endswith(".api.runpod.ai")


def _should_disable_qwen_thinking_with_chat_template(
    base_url: str | None,
    model_name: str | None,
) -> bool:
    if not _is_runpod_openai_base_url(base_url):
        return False

    normalized = (model_name or "").lower()
    return "qwen3" in normalized or "qwq" in normalized


def _requires_reasoning_on_provider(exc: Exception) -> bool:
    if not isinstance(exc, openai.BadRequestError):
        return False
    message = str(exc).lower()
    return "reasoning is mandatory" in message and "cannot be disabled" in message


class OllamaAwareOpenAIGenericClient(OpenAIGenericClient):
    MAX_RETRIES = 2

    def __init__(
        self,
        config: LLMConfig,
        *,
        force_reasoning_off: bool,
        reasoning_effort: str | None,
        max_tokens: int,
        timeout_seconds: float,
        max_retries: int,
    ):
        super().__init__(
            config=config,
            cache=False,
            client=AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=timeout_seconds,
                max_retries=max_retries,
            ),
            max_tokens=max_tokens,
        )
        self.force_reasoning_off = force_reasoning_off
        self.reasoning_effort = reasoning_effort
        self.base_url = config.base_url
        self.model_name = config.model
        self.rate_limit_retries = max(0, max_retries)

    @staticmethod
    def _rate_limit_delay_seconds(exc: openai.RateLimitError, attempt: int) -> float:
        response = getattr(exc, "response", None)
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return max(1.0, float(retry_after))
                except ValueError:
                    pass
        return float(min(2 ** attempt, 12))

    def _extra_body(self) -> dict[str, Any]:
        if _should_disable_qwen_thinking_with_chat_template(self.base_url, self.model_name):
            return {"chat_template_kwargs": {"enable_thinking": False}}
        if self.force_reasoning_off:
            return {"reasoning": {"effort": "none"}}
        if self.reasoning_effort:
            return {"reasoning": {"effort": self.reasoning_effort}}
        return {}

    @staticmethod
    def _extract_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(getattr(item, "text", "") or getattr(item, "content", "")))
            return "".join(parts)
        return str(content or "")

    @staticmethod
    def _parse_json_payload(payload: str) -> Any:
        if not payload:
            raise ValueError("LLM returned an empty content payload")

        cleaned = payload.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        decoder = json.JSONDecoder()

        try:
            return decoder.decode(cleaned)
        except json.JSONDecodeError as exc:
            start_candidates = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1]
            for start in sorted(start_candidates):
                try:
                    parsed, _ = decoder.raw_decode(cleaned[start:])
                    return parsed
                except json.JSONDecodeError:
                    continue
            literal_candidates = [cleaned]
            literal_candidates.extend(cleaned[start:] for start in sorted(start_candidates))
            for candidate in literal_candidates:
                try:
                    return ast.literal_eval(candidate)
                except Exception:
                    continue
            raise exc

    @staticmethod
    def _extract_entity_type_map(messages: list[Message]) -> dict[str, int]:
        pattern = re.compile(r"<ENTITY TYPES>\s*(.*?)\s*</ENTITY TYPES>", re.DOTALL)
        for message in reversed(messages):
            content = message.content if isinstance(message.content, str) else str(message.content)
            match = pattern.search(content)
            if not match:
                continue

            raw_block = match.group(1).strip()
            parsed = None
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(raw_block)
                    break
                except Exception:
                    continue

            if isinstance(parsed, list):
                mapping: dict[str, int] = {}
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    type_name = item.get("entity_type_name")
                    type_id = item.get("entity_type_id")
                    if isinstance(type_name, str) and isinstance(type_id, int):
                        mapping[type_name] = type_id
                if mapping:
                    return mapping
        return {}

    @staticmethod
    def _normalize_item(
        item: Any,
        item_model: type[BaseModel] | None,
        entity_type_map: dict[str, int],
    ) -> Any:
        if not isinstance(item, dict):
            return item

        normalized = dict(item)
        aliases = {
            "text": "name",
            "entity": "name",
            "entity_name": "name",
            "source": "source_entity_name",
            "source_name": "source_entity_name",
            "target": "target_entity_name",
            "target_name": "target_entity_name",
            "relation": "relation_type",
            "relationship": "relation_type",
        }

        expected_fields = set(item_model.model_fields) if item_model is not None else set()
        for source_key, target_key in aliases.items():
            if source_key in normalized and target_key in expected_fields and target_key not in normalized:
                normalized[target_key] = normalized.pop(source_key)

        if (
            "entity_type_id" in expected_fields
            and "entity_type_id" not in normalized
            and isinstance(normalized.get("entity_type_name"), str)
        ):
            mapped_type_id = entity_type_map.get(normalized["entity_type_name"])
            if mapped_type_id is not None:
                normalized["entity_type_id"] = mapped_type_id

        if "fact" in expected_fields and not normalized.get("fact"):
            source_name = str(normalized.get("source_entity_name") or "").strip()
            relation_type = str(normalized.get("relation_type") or "").strip()
            target_name = str(normalized.get("target_entity_name") or "").strip()
            detail = str(
                normalized.get("description")
                or normalized.get("evidence")
                or normalized.get("context")
                or normalized.get("statement")
                or ""
            ).strip()
            if source_name and relation_type and target_name:
                normalized["fact"] = detail or f"{source_name} {relation_type} {target_name}."

        return normalized

    def _normalize_wrapped_value(
        self,
        wrapped_value: Any,
        inner_model: type[BaseModel] | None,
        entity_type_map: dict[str, int],
    ) -> Any:
        if inner_model is None:
            return wrapped_value

        if isinstance(wrapped_value, list):
            return [
                self._normalize_item(item, inner_model, entity_type_map)
                for item in wrapped_value
            ]

        if isinstance(wrapped_value, dict):
            inner_fields = set(inner_model.model_fields)
            if "name" in inner_fields:
                non_name_fields = [field for field in inner_fields if field != "name"]
                if len(non_name_fields) == 1:
                    value_field = non_name_fields[0]
                    normalized_items = []
                    for name, value in wrapped_value.items():
                        item: dict[str, Any] = {"name": name}
                        if isinstance(value, dict):
                            item.update(value)
                            item.setdefault(value_field, value.get(value_field))
                        else:
                            item[value_field] = value
                        normalized_items.append(
                            self._normalize_item(item, inner_model, entity_type_map)
                        )
                    return normalized_items

        return wrapped_value

    def _normalize_structured_payload(
        self,
        parsed: Any,
        response_model: type[BaseModel] | None,
        messages: list[Message],
    ) -> dict[str, Any]:
        if response_model is None:
            if not isinstance(parsed, dict):
                raise ValueError("LLM returned a non-dict payload without a response model")
            return parsed

        validation_error: Exception | None = None
        try:
            return response_model.model_validate(parsed).model_dump(mode="python")
        except Exception as exc:
            validation_error = exc

        model_fields = response_model.model_fields
        if len(model_fields) != 1:
            raise validation_error or ValueError("Structured payload validation failed")

        field_name, field_info = next(iter(model_fields.items()))
        wrapped_value = None
        if isinstance(parsed, list):
            wrapped_value = parsed
        elif isinstance(parsed, dict):
            if field_name in parsed:
                wrapped_value = parsed[field_name]
            else:
                for candidate_key in (
                    "entities",
                    "items",
                    "results",
                    "data",
                    "edges",
                    "nodes",
                    "summaries",
                    "duplicates",
                    "resolutions",
                ):
                    if candidate_key in parsed:
                        wrapped_value = parsed[candidate_key]
                        break
                if wrapped_value is None and len(parsed) == 1:
                    wrapped_value = next(iter(parsed.values()))
                if wrapped_value is None:
                    wrapped_value = parsed

        normalized_payload: Any = parsed
        if wrapped_value is not None:
            annotation = field_info.annotation
            inner_model: type[BaseModel] | None = None
            if typing.get_origin(annotation) is list:
                args = typing.get_args(annotation)
                if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    inner_model = args[0]

            entity_type_map = self._extract_entity_type_map(messages)
            wrapped_value = self._normalize_wrapped_value(
                wrapped_value,
                inner_model,
                entity_type_map,
            )
            normalized_payload = {field_name: wrapped_value}

        return response_model.model_validate(normalized_payload).model_dump(mode="python")

    @staticmethod
    def _empty_object_fallback_payload(
        response_model: type[BaseModel] | None,
    ) -> dict[str, Any] | None:
        if response_model is None:
            return None

        try:
            validated = response_model.model_validate({})
        except Exception:
            return None

        # For optional attribute-extraction models, dropping None values preserves
        # existing graph data instead of overwriting it with nulls.
        return validated.model_dump(mode="python", exclude_none=True)

    @staticmethod
    def _retryable_max_tokens(exc: Exception, attempted_max_tokens: int) -> int | None:
        if not isinstance(exc, openai.BadRequestError):
            return None

        message = str(exc)
        if "Please request fewer output tokens" not in message and "max_tokens" not in message:
            return None

        suggested_cap = 4096
        match = _MAX_TOKENS_BAD_REQUEST_RE.search(message)
        if match:
            try:
                max_total_tokens = int(match.group(1))
                # Keep a reasonable prompt budget instead of forcing a very low cap.
                suggested_cap = min(suggested_cap, max(512, max_total_tokens - 2048))
            except ValueError:
                pass

        if attempted_max_tokens <= suggested_cap:
            return None
        return suggested_cap

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 16384,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        openai_messages: list[ChatCompletionMessageParam] = []
        for message in messages:
            content = self._clean_input(message.content)
            if message.role in {"user", "system"}:
                openai_messages.append({"role": message.role, "content": content})

        response_format: dict[str, Any] = {"type": "json_object"}
        if response_model is not None:
            schema_name = getattr(response_model, "__name__", "structured_response")
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": response_model.model_json_schema(),
                },
            }

        if response_format["type"] in {"json_object", "json_schema"}:
            mentions_json = any("json" in str(message.get("content", "")).lower() for message in openai_messages)
            if not mentions_json:
                openai_messages.insert(0, {"role": "system", "content": "Return valid JSON only."})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        extra_body = self._extra_body()
        allow_reasoning_fallback = bool(extra_body)
        if extra_body:
            kwargs["extra_body"] = extra_body

        attempted_max_tokens = max_tokens
        rate_limit_attempt = 0
        while True:
            try:
                kwargs["max_tokens"] = attempted_max_tokens
                response = await self.client.chat.completions.create(**kwargs)
                content = self._extract_content(response.choices[0].message)
                parsed = self._parse_json_payload(content)
                return self._normalize_structured_payload(parsed, response_model, messages)
            except openai.RateLimitError as exc:
                if rate_limit_attempt < self.rate_limit_retries:
                    delay_seconds = self._rate_limit_delay_seconds(exc, rate_limit_attempt)
                    logger.warning(
                        "Retrying Graphiti LLM call after rate limit (attempt %s/%s) in %.1fs: %s",
                        rate_limit_attempt + 1,
                        self.rate_limit_retries + 1,
                        delay_seconds,
                        exc,
                    )
                    rate_limit_attempt += 1
                    await asyncio.sleep(delay_seconds)
                    continue
                raise RateLimitError from exc
            except Exception as exc:
                if allow_reasoning_fallback and _requires_reasoning_on_provider(exc):
                    logger.warning(
                        "Retrying Graphiti LLM call without reasoning override after provider rejection: %s",
                        exc,
                    )
                    kwargs.pop("extra_body", None)
                    allow_reasoning_fallback = False
                    continue
                retry_max_tokens = self._retryable_max_tokens(exc, attempted_max_tokens)
                if retry_max_tokens is not None:
                    logger.warning(
                        "Retrying Graphiti LLM call with max_tokens=%s after token limit error: %s",
                        retry_max_tokens,
                        exc,
                    )
                    attempted_max_tokens = retry_max_tokens
                    continue

                model_name = getattr(response_model, "__name__", "structured_response")
                if isinstance(exc, json.JSONDecodeError):
                    object_fallback = self._empty_object_fallback_payload(response_model)
                    if object_fallback is not None:
                        logger.warning(
                            "Falling back to empty object payload for %s after malformed JSON response: %s",
                            model_name,
                            exc,
                        )
                        return object_fallback
                logger.exception("Graphiti LLM response generation failed")
                raise


class ResilientOpenAIEmbedder(OpenAIEmbedder):
    def __init__(
        self,
        config: OpenAIEmbedderConfig,
        *,
        client: AsyncOpenAI,
        max_retries: int,
        max_concurrency: int,
    ):
        super().__init__(config=config, client=client)
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _run_with_retry(self, operation):
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with self._semaphore:
                    return await operation()
            except (openai.APITimeoutError, openai.APIConnectionError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise
                delay = min(2 ** attempt, 8)
                logger.warning(
                    "Retrying embedding request after transient error (attempt %s/%s): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc

    async def create(
        self, input_data: str | list[str] | typing.Iterable[int] | typing.Iterable[typing.Iterable[int]]
    ) -> list[float]:
        async def operation():
            result = await self.client.embeddings.create(
                input=input_data,
                model=self.config.embedding_model,
                encoding_format="float",
            )
            return result.data[0].embedding[: self.config.embedding_dim]

        return await self._run_with_retry(operation)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        async def operation():
            result = await self.client.embeddings.create(
                input=input_data_list,
                model=self.config.embedding_model,
                encoding_format="float",
            )
            return [embedding.embedding[: self.config.embedding_dim] for embedding in result.data]

        return await self._run_with_retry(operation)


def create_graphiti(settings: Settings) -> Graphiti:
    llm_config = LLMConfig(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        small_model=settings.llm_small_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    llm_client = OllamaAwareOpenAIGenericClient(
        llm_config,
        force_reasoning_off=settings.force_reasoning_off,
        reasoning_effort=settings.reasoning_effort,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    embedder = ResilientOpenAIEmbedder(
        OpenAIEmbedderConfig(
            api_key=settings.embedder_api_key,
            base_url=settings.embedder_base_url,
            embedding_model=settings.embedding_model,
        ),
        client=AsyncOpenAI(
            api_key=settings.embedder_api_key,
            base_url=settings.embedder_base_url,
            timeout=settings.embedder_timeout_seconds,
            max_retries=settings.embedder_max_retries,
        ),
        max_retries=settings.embedder_max_retries,
        max_concurrency=settings.embedder_max_concurrency,
    )
    reranker = OpenAIRerankerClient(
        LLMConfig(
            api_key=settings.reranker_api_key,
            base_url=settings.reranker_base_url,
            model=settings.reranker_model,
            temperature=0,
        ),
        client=AsyncOpenAI(
            api_key=settings.reranker_api_key,
            base_url=settings.reranker_base_url,
        ),
    )
    return Graphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=reranker,
    )
