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


def _stable_json(value: Any) -> str:
    """生成适合 prompt cache 的稳定紧凑 JSON 字符串。

    Args:
        value: 需要序列化到 LLM 消息中的 JSON 兼容对象。

    Returns:
        key 顺序稳定且不包含无意义空白的 JSON 字符串。
    """

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _build_system_message(
    *,
    worker_type: str,
    instructions: str,
    schema_type: type[BaseModel],
) -> str:
    """构造 worker 的固定 system prompt。

    Args:
        worker_type: Memory worker 类型。
        instructions: 固定 worker 提示词。
        schema_type: 结构化输出 schema 类型。

    Returns:
        只包含固定 worker/schema/instructions 的 system message。
    """

    schema = schema_type.model_json_schema()
    if settings.MEMORY_SYSTEM_LANGUAGE == "zh":
        return (
            f"你是记忆系统的 {worker_type} worker。\n"
            "只返回一个 JSON 对象，不要返回其他内容。\n"
            "不要添加 markdown 代码块。\n"
            f"严格遵循以下输出 schema：\n{_stable_json(schema)}\n\n"
            f"Worker 指令：\n{instructions}"
        )
    return (
        f"You are the {worker_type} worker for a memory system.\n"
        "Return exactly one JSON object and nothing else.\n"
        "Do not add markdown fences.\n"
        f"Follow this output schema:\n{_stable_json(schema)}\n\n"
        f"Worker instructions:\n{instructions}"
    )


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
    cache_miss_tokens: int | None
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
    provider_cached_tokens = _usage_value(usage, "prompt_cache_hit_tokens")
    if provider_cached_tokens is not None:
        return provider_cached_tokens
    if isinstance(usage, Mapping):
        details = usage.get("prompt_tokens_details") or usage.get("input_token_details")
    else:
        details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_token_details", None)
    return _first_usage_value(details, ("cached_tokens", "cache_read"))


def _cache_miss_tokens(input_tokens: int | None, cached_tokens: int | None) -> int | None:
    if input_tokens is None:
        return None
    return max(input_tokens - int(cached_tokens or 0), 0)


def _cache_miss_tokens_from_usage(usage: Any) -> int | None:
    provider_miss_tokens = _first_usage_value(usage, ("prompt_cache_miss_tokens", "cache_miss_tokens"))
    if provider_miss_tokens is not None:
        return provider_miss_tokens
    if isinstance(usage, Mapping):
        details = usage.get("prompt_tokens_details") or usage.get("input_token_details")
    else:
        details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_token_details", None)
    return _first_usage_value(details, ("cache_miss", "cache_write"))


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

        system_message = _build_system_message(
            worker_type=worker_type,
            instructions=instructions,
            schema_type=schema_type,
        )
        user_message = _stable_json(payload)

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
        input_tokens = _usage_value(usage, "prompt_tokens")
        cached_tokens = _cached_tokens_from_usage(usage)
        explicit_cache_miss_tokens = _cache_miss_tokens_from_usage(usage)
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
            input_tokens=input_tokens,
            output_tokens=_usage_value(usage, "completion_tokens"),
            cached_tokens=cached_tokens,
            cache_miss_tokens=(
                explicit_cache_miss_tokens
                if explicit_cache_miss_tokens is not None
                else _cache_miss_tokens(input_tokens, cached_tokens)
            ),
            reasoning_tokens=_reasoning_tokens_from_usage(usage),
        )


llm_provider = StructuredLLMProvider()
