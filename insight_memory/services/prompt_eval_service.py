from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from insight_memory.evals.prompt_registry import get_prompt_eval_target
from insight_memory.utils.logger import get_logger
from insight_memory.workers.llm_provider import llm_provider
from insight_memory.workers.prompts import get_worker_instructions


logger = get_logger(__name__)


class PromptEvalService:
    """执行单次后端提示词调用，并返回 LLM 输出。"""

    async def run(self, *, prompt_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用指定后端提示词并返回结构化 LLM 输出。

        Args:
            prompt_key: 后端允许评测的提示词 key。
            payload: 传给 worker prompt 的 JSON 对象。

        Returns:
            包含调用状态、模型、耗时、LLM 输出和 token usage 的结果字典。
        """

        target = get_prompt_eval_target(prompt_key)
        if target is None:
            return self._error(
                prompt_key=prompt_key,
                error_code="unsupported_prompt_key",
                error_message="Unsupported prompt key.",
            )
        if not llm_provider.enabled:
            return self._error(
                prompt_key=prompt_key,
                error_code="llm_provider_not_configured",
                error_message="Memory LLM provider is not configured.",
            )

        try:
            instructions = get_worker_instructions(target.instructions_key)
            call = await llm_provider.generate(
                worker_type=target.prompt_key,
                instructions=instructions,
                payload=payload,
                schema_type=target.schema_type,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "prompt eval output validation failed",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return self._error(
                prompt_key=prompt_key,
                error_code="schema_validation_failed",
                error_message="LLM output failed schema validation.",
            )
        except Exception as exc:
            logger.warning(
                "prompt eval llm call failed",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return self._error(
                prompt_key=prompt_key,
                error_code="llm_call_failed",
                error_message="LLM call failed.",
            )

        logger.info(
            "prompt eval completed",
            extra={
                "prompt_key": prompt_key,
                "model": call.model,
                "latency_ms": call.latency_ms,
            },
        )
        return {
            "status": "ok",
            "prompt_key": prompt_key,
            "model": call.model,
            "latency_ms": call.latency_ms,
            "output": call.output_json,
            "usage": {
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cached_tokens": call.cached_tokens,
                "cache_miss_tokens": call.cache_miss_tokens,
                "reasoning_tokens": call.reasoning_tokens,
            },
        }

    @staticmethod
    def _error(*, prompt_key: str, error_code: str, error_message: str) -> dict[str, Any]:
        """构造 Prompt Eval API 的标准错误响应。

        Args:
            prompt_key: 调用方传入的提示词 key。
            error_code: 机器可读错误码。
            error_message: 面向调用方的简短错误说明。

        Returns:
            标准错误响应字典。
        """

        return {
            "status": "error",
            "prompt_key": prompt_key,
            "error_code": error_code,
            "error_message": error_message,
        }


prompt_eval_service = PromptEvalService()
