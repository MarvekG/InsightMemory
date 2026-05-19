from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, TypeVar

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel

from insight_memory.config import settings
from insight_memory.utils.logger import get_logger


SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = get_logger(__name__)


@dataclass(slots=True)
class LLMCallResult(Generic[SchemaT]):
    parsed: SchemaT
    output_json: dict[str, Any]
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None


def _usage_value(value: Any, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        raw_value = value.get(key)
    else:
        raw_value = getattr(value, key, None)
    if raw_value is None:
        return None
    return int(raw_value)


def _cached_tokens_from_usage(usage: Any) -> int | None:
    deepseek_cached_tokens = _usage_value(usage, "prompt_cache_hit_tokens")
    if deepseek_cached_tokens is not None:
        return deepseek_cached_tokens
    if isinstance(usage, Mapping):
        details = usage.get("prompt_tokens_details") or usage.get("input_token_details")
    else:
        details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_token_details", None)
    return _first_usage_value(details, ("cached_tokens", "cache_read"))


def _reasoning_tokens_from_usage(usage: Any) -> int | None:
    if isinstance(usage, Mapping):
        details = usage.get("completion_tokens_details") or usage.get("output_token_details")
    else:
        details = getattr(usage, "completion_tokens_details", None) or getattr(usage, "output_token_details", None)
    return _usage_value(details, "reasoning_tokens")


def _first_usage_value(value: Any, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        usage_value = _usage_value(value, key)
        if usage_value is not None:
            return usage_value
    return None


class StructuredLLMProvider:
    def __init__(self) -> None:
        self.provider = settings.MEMORY_LLM_PROVIDER
        self.model_name = settings.MEMORY_LLM_MODEL
        self.prompt_version = settings.MEMORY_LLM_PROMPT_VERSION
        self._api_key = settings.MEMORY_LLM_API_KEY
        self._base_url = settings.MEMORY_LLM_BASE_URL
        self._client: AsyncOpenAI | None = None
        if self.enabled:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url or None,
                http_client=httpx.AsyncClient(timeout=settings.MEMORY_LLM_TIMEOUT_SECONDS),
            )

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.model_name and self._api_key)

    async def generate(
        self,
        *,
        worker_type: str,
        instructions: str,
        payload: dict[str, Any],
        schema_type: type[SchemaT],
    ) -> LLMCallResult[SchemaT]:
        if not self.enabled or self._client is None:
            raise RuntimeError("memory llm provider is not configured")

        schema = schema_type.model_json_schema()
        system_message = (
            f"You are the {worker_type} worker for a memory system.\n"
            "Return exactly one JSON object and nothing else.\n"
            "Do not add markdown fences.\n"
            f"Follow this output schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Worker instructions:\n{instructions}"
        )
        user_message = json.dumps(payload, ensure_ascii=False)

        started_at = perf_counter()
        response = await self._client.chat.completions.create(
            model=self.model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
        )
        latency_ms = int(round((perf_counter() - started_at) * 1000))
        content = response.choices[0].message.content or "{}"
        output_json = json.loads(content)
        parsed = schema_type.model_validate(output_json)
        usage = getattr(response, "usage", None)
        logger.info(
            "llm worker completed",
            extra={
                "worker_type": worker_type,
                "model_name": self.model_name,
                "latency_ms": latency_ms,
            },
        )
        return LLMCallResult(
            parsed=parsed,
            output_json=output_json,
            model=self.model_name,
            prompt_version=self.prompt_version,
            latency_ms=latency_ms,
            input_tokens=_usage_value(usage, "prompt_tokens"),
            output_tokens=_usage_value(usage, "completion_tokens"),
            cached_tokens=_cached_tokens_from_usage(usage),
            reasoning_tokens=_reasoning_tokens_from_usage(usage),
        )


llm_provider = StructuredLLMProvider()
