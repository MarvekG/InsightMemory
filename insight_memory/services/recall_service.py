from __future__ import annotations

from insight_memory.api.schemas import RecallRequest
from insight_memory.graph.recall_graph import recall_graph
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import get_or_create_request_id


logger = get_logger(__name__)


class RecallService:
    """Handle recall requests with async-ingest readiness gating."""

    async def recall(self, request: RecallRequest) -> dict:
        """Resolve one recall request against the durable memory state."""

        request_id = get_or_create_request_id()
        if await self._has_pending_continuation(memory_space=request.memory_scope):
            result = self._build_not_ready_result()
            await self._write_not_ready_audit(
                memory_space=request.memory_scope,
                request_id=request_id,
                query=request.query,
                result=result,
            )
            logger.info(
                "recall rejected as not ready",
                extra={
                    "memory_space": request.memory_scope,
                    "request_id": request_id,
                    "query_preview": request.query[:120],
                    "error_code": result["results"][0]["error_code"],
                },
            )
            return result

        return await recall_graph.run(
            memory_space=request.memory_scope,
            query=request.query,
            request_id=request_id,
        )

    @staticmethod
    async def _has_pending_continuation(*, memory_space: str) -> bool:
        """Return whether the target scope still has unresolved async ingest work."""

        async with MemoryRepository() as repository:
            tasks = await repository.list_tasks(
                memory_space=memory_space,
                statuses=("pending", "running"),
                task_types=("continue_ingest",),
                limit=1,
            )
        return bool(tasks)

    @staticmethod
    def _build_not_ready_result() -> dict:
        """Build the response returned while async ingest is still running."""

        return {
            "results": [
                {
                    "status": "not_ready",
                    "answer": "",
                    "citations": [],
                    "uncertainties": ["continue_ingest_pending"],
                    "error_code": "memory_scope_not_ready",
                }
            ],
        }

    @staticmethod
    async def _write_not_ready_audit(
        *,
        memory_space: str,
        request_id: str,
        query: str,
        result: dict,
    ) -> None:
        """Persist one recall audit row for a not-ready response."""

        async with MemoryRepository() as repository:
            await repository.create_recall_audit(
                memory_space=memory_space,
                request_id=request_id,
                query=query,
                status="not_ready",
                resolved_entity_key=None,
                answer="",
                error_code="memory_scope_not_ready",
                uncertainties=["continue_ingest_pending"],
                used_edges=[],
                resolution_trace={"planner_gate_status": "not_ready"},
                metadata={"draft_runs": []},
            )


recall_service = RecallService()
