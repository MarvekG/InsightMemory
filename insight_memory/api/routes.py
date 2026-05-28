from __future__ import annotations

from fastapi import APIRouter, Query

from insight_memory.api.schemas import (
    ClearUsageStatsResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    MemoryPreviewResponse,
    PromptEvalRequest,
    PromptEvalResponse,
    RecallAuditPreviewResponse,
    RecallRequest,
    RecallResponse,
    UsageStatsResponse,
)
from insight_memory.services.health_service import health_service
from insight_memory.services.ingest_service import ingest_service
from insight_memory.services.preview_service import preview_service
from insight_memory.services.prompt_eval_service import prompt_eval_service
from insight_memory.services.recall_audit_preview_service import recall_audit_preview_service
from insight_memory.services.recall_service import recall_service
from insight_memory.utils.logger import get_logger


router = APIRouter()
logger = get_logger(__name__)


async def _ingest_impl(request: IngestRequest) -> IngestResponse:
    logger.info(
        "http ingest received",
        extra={
            "memory_scope": request.memory_scope,
        },
    )
    result = await ingest_service.ingest(request)
    return IngestResponse(**result)


async def _recall_impl(request: RecallRequest) -> RecallResponse:
    logger.info(
        "http recall received",
        extra={
            "memory_scope": request.memory_scope,
            "query_preview": request.query[:120],
        },
    )
    result = await recall_service.recall(request)
    return RecallResponse(**result)


async def _health_impl() -> HealthResponse:
    return HealthResponse(**(await health_service.check()))


async def _usage_stats_impl(*, hours: int | None = None) -> UsageStatsResponse:
    return UsageStatsResponse(**(await health_service.usage_stats(hours=hours)))


async def _clear_usage_stats_impl() -> ClearUsageStatsResponse:
    return ClearUsageStatsResponse(**(await health_service.clear_usage_stats()))


async def _prompt_eval_impl(request: PromptEvalRequest) -> PromptEvalResponse:
    """调用 Memory prompt eval service 并包装 HTTP 响应。

    Args:
        request: Prompt eval 请求，包含 prompt key 和 worker payload。

    Returns:
        Prompt eval 调用结果。
    """

    logger.info(
        "http prompt eval received",
        extra={
            "prompt_key": request.prompt_key,
            "payload_keys": sorted(request.payload.keys()),
        },
    )
    result = await prompt_eval_service.run(prompt_key=request.prompt_key, payload=request.payload)
    return PromptEvalResponse(**result)


async def _memory_preview_impl(
    *,
    memory_scope: str | None,
    memory_scope_prefix: str | None,
    memory_scope_contains: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> MemoryPreviewResponse:
    result = await preview_service.preview(
        memory_scope=memory_scope,
        memory_scope_prefix=memory_scope_prefix,
        memory_scope_contains=memory_scope_contains,
        status=status,
        limit=limit,
        offset=offset,
    )
    return MemoryPreviewResponse(**result)


async def _recall_audit_preview_impl(
    *,
    memory_scope: str | None,
    memory_scope_prefix: str | None,
    memory_scope_contains: str | None,
    status: str | None,
    error_code: str | None,
    limit: int,
    offset: int,
) -> RecallAuditPreviewResponse:
    result = await recall_audit_preview_service.preview(
        memory_scope=memory_scope,
        memory_scope_prefix=memory_scope_prefix,
        memory_scope_contains=memory_scope_contains,
        status=status,
        error_code=error_code,
        limit=limit,
        offset=offset,
    )
    return RecallAuditPreviewResponse(**result)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    return await _ingest_impl(request)


@router.post("/memory/ingest", response_model=IngestResponse)
async def ingest_memory(request: IngestRequest) -> IngestResponse:
    return await _ingest_impl(request)


@router.post("/recall", response_model=RecallResponse)
async def recall(request: RecallRequest) -> RecallResponse:
    return await _recall_impl(request)


@router.post("/memory/recall", response_model=RecallResponse)
async def recall_memory(request: RecallRequest) -> RecallResponse:
    return await _recall_impl(request)


@router.post("/memory/prompt-evals/run", response_model=PromptEvalResponse)
async def run_prompt_eval_memory(request: PromptEvalRequest) -> PromptEvalResponse:
    """执行一次内部 Memory worker prompt 调用。

    Args:
        request: Prompt eval 请求，包含 prompt key 和 worker payload。

    Returns:
        LLM 调用输出和基础 usage 信息；不包含 case 比对结果。
    """

    return await _prompt_eval_impl(request)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return await _health_impl()


@router.get("/memory/health", response_model=HealthResponse)
async def health_memory() -> HealthResponse:
    return await _health_impl()


@router.get("/embedding/health", response_model=HealthResponse)
async def embedding_health() -> HealthResponse:
    return await _health_impl()


@router.get("/usage/stats", response_model=UsageStatsResponse)
async def usage_stats(hours: int | None = Query(default=None, ge=1, le=24 * 365)) -> UsageStatsResponse:
    return await _usage_stats_impl(hours=hours)


@router.get("/memory/usage/stats", response_model=UsageStatsResponse)
async def usage_stats_memory(hours: int | None = Query(default=None, ge=1, le=24 * 365)) -> UsageStatsResponse:
    return await _usage_stats_impl(hours=hours)


@router.delete("/usage/stats", response_model=ClearUsageStatsResponse)
async def clear_usage_stats() -> ClearUsageStatsResponse:
    return await _clear_usage_stats_impl()


@router.delete("/memory/usage/stats", response_model=ClearUsageStatsResponse)
async def clear_usage_stats_memory() -> ClearUsageStatsResponse:
    return await _clear_usage_stats_impl()


@router.get("/memory/admin/memories/preview", response_model=MemoryPreviewResponse)
async def preview_memories_memory(
    memory_scope: str | None = Query(default=None, max_length=255),
    memory_scope_prefix: str | None = Query(default=None, max_length=255),
    memory_scope_contains: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MemoryPreviewResponse:
    return await _memory_preview_impl(
        memory_scope=memory_scope,
        memory_scope_prefix=memory_scope_prefix,
        memory_scope_contains=memory_scope_contains,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/memory/admin/recall-audits/preview", response_model=RecallAuditPreviewResponse)
async def preview_recall_audits_memory(
    memory_scope: str | None = Query(default=None, max_length=255),
    memory_scope_prefix: str | None = Query(default=None, max_length=255),
    memory_scope_contains: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None, max_length=128),
    error_code: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RecallAuditPreviewResponse:
    return await _recall_audit_preview_impl(
        memory_scope=memory_scope,
        memory_scope_prefix=memory_scope_prefix,
        memory_scope_contains=memory_scope_contains,
        status=status,
        error_code=error_code,
        limit=limit,
        offset=offset,
    )
