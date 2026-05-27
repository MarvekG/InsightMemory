from __future__ import annotations

from insight_memory.api.schemas import IngestRequest
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.text import normalize_text
from insight_memory.workers.runtime import MemoryWorkers


logger = get_logger(__name__)


class IngestService:
    """Handle the HTTP ingest hot path before background resolution continues."""

    async def ingest(self, request: IngestRequest) -> dict:
        """同步执行主体门禁，通过后创建 observation 并排队后台完整抽取。

        Args:
            request: 写入请求，包含记忆空间和原始上下文。

        Returns:
            与 Memory ingest API 对齐的同步 accepted/rejected 结果。
        """

        request_id = get_or_create_request_id()
        workers = MemoryWorkers()
        write_gate = await workers.run_write_gate(
            memory_space=request.memory_scope,
            context=request.context,
            request_id=request_id,
        )
        if write_gate.identity_gate_status != "passed":
            return {
                "status": "rejected",
                "observation_id": None,
                "affected_entity_keys": [],
                "affected_memory_ids": [],
                "error_code": write_gate.write_rejection_reason or "cannot_extract_identity_profile",
            }

        observation_id = await self._create_observation(
            memory_space=request.memory_scope,
            context=request.context,
            request_id=request_id,
        )
        await self._enqueue_continuation_task(
            memory_space=request.memory_scope,
            request_id=request_id,
            observation_id=observation_id,
            context=request.context,
        )
        logger.info(
            "ingest accepted for background continuation",
            extra={
                "memory_space": request.memory_scope,
                "request_id": request_id,
                "observation_id": observation_id,
            },
        )
        return {
            "status": "accepted",
            "observation_id": observation_id,
            "affected_entity_keys": [],
            "affected_memory_ids": [],
            "error_code": None,
        }

    async def _create_observation(self, *, memory_space: str, context: str, request_id: str) -> str:
        """创建待后台解析的原始 observation。

        Args:
            memory_space: 当前记忆空间。
            context: 原始写入内容。
            request_id: 当前请求 id。

        Returns:
            新建 observation 的 id。
        """

        async with MemoryRepository() as repository:
            observation = await repository.create_observation(
                memory_space=memory_space,
                content=context,
                summary=normalize_text(context)[:500],
                source_ref=request_id,
                metadata={"request_id": request_id},
            )
        logger.info(
            "ingest observation created",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "observation_id": observation.observation_id,
            },
        )
        return observation.observation_id

    async def _enqueue_continuation_task(
        self,
        *,
        memory_space: str,
        request_id: str,
        observation_id: str,
        context: str,
    ) -> None:
        """创建只携带原始上下文的后台继续写入任务。

        Args:
            memory_space: 当前记忆空间。
            request_id: 当前请求 id。
            observation_id: 已创建的 observation id。
            context: 原始写入内容，供后台完整 extractor 重新处理。
        """

        async with MemoryRepository() as repository:
            await repository.create_task(
                memory_space=memory_space,
                task_type="continue_ingest",
                dedupe_key=f"continue_ingest:{observation_id}",
                priority=16,
                payload={
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "observation_id": observation_id,
                    "context": context,
                },
            )


ingest_service = IngestService()
