from __future__ import annotations

from typing import Any

from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)


async def record_worker_failure(
    *,
    memory_space: str,
    worker_kind: str,
    input_payload: dict[str, Any],
    error: Exception,
    structured_output: dict[str, Any] | None = None,
    write_set: dict[str, Any] | None = None,
    model_name: str,
    prompt_version: str,
    error_type: str | None = None,
) -> None:
    payload = dict(structured_output or {})
    if "error" not in payload:
        payload["error"] = str(error)
    logger.exception(
        "worker failure recorded",
        extra={
            "memory_space": memory_space,
            "worker_kind": worker_kind,
            "error_type": error_type or type(error).__name__,
            "write_set": write_set or {},
        },
        exc_info=error,
    )
    async with MemoryRepository() as repo:
        await repo.record_llm_run(
            memory_space=memory_space,
            worker_type=worker_kind,
            model=model_name,
            prompt_version=prompt_version,
            input_json=input_payload,
            output_json=payload,
            parse_status="error",
            request_id=None,
            latency_ms=None,
            input_tokens=None,
            output_tokens=None,
        )
