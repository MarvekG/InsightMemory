from __future__ import annotations

from typing import Any

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
        """Extract a subject, persist the observation, and enqueue background resolution."""
        request_id = get_or_create_request_id()
        workers = MemoryWorkers()
        extractor = await workers.run_extractor(
            memory_space=request.memory_scope,
            context=request.context,
            request_id=request_id,
        )
        if extractor.identity_gate_status != "passed":
            return {
                "status": "rejected",
                "observation_id": None,
                "affected_entity_keys": [],
                "affected_memory_ids": [],
                "error_code": extractor.write_rejection_reason or "cannot_extract_identity_profile",
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
            extractor_payload=extractor.model_dump(),
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
        extractor_payload: dict[str, Any],
    ) -> None:
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
                    "extractor": extractor_payload,
                },
            )


ingest_service = IngestService()
