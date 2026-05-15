from __future__ import annotations

from typing import Any, Iterable

from insight_memory.storage.models import MEMORY_STATUSES
from insight_memory.storage.repository import MemoryRepository


class MemoryPreviewService:
    async def preview(
        self,
        *,
        memory_scope: str | None = None,
        memory_scope_prefix: str | None = None,
        memory_scope_contains: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        statuses = self._parse_statuses(status)
        async with MemoryRepository() as repository:
            total, memories = await repository.preview_memories(
                memory_space=self._normalize_filter(memory_scope),
                memory_space_prefix=self._normalize_filter(memory_scope_prefix),
                memory_space_contains=self._normalize_filter(memory_scope_contains),
                statuses=statuses,
                limit=limit,
                offset=offset,
            )
            return {
                "status": "success",
                "total": total,
                "limit": max(1, min(limit, 200)),
                "offset": max(0, offset),
                "items": [
                    {
                        "memory_id": memory.memory_id,
                        "memory_scope": memory.memory_space,
                        "entity_key": memory.entity_key,
                        "title": memory.title,
                        "summary": memory.summary,
                        "content": memory.content,
                        "status": memory.status,
                        "confidence": memory.confidence,
                        "salience": memory.salience,
                        "latest_source_observation_id": memory.latest_source_observation_id,
                        "metadata": dict(memory.metadata_json or {}),
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                    }
                    for memory in memories
                ],
            }

    @staticmethod
    def _normalize_filter(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _parse_statuses(status: str | None) -> Iterable[str] | None:
        normalized = str(status or "").strip()
        if not normalized:
            return None
        values = [item.strip() for item in normalized.split(",") if item.strip()]
        return [item for item in values if item in MEMORY_STATUSES] or None


preview_service = MemoryPreviewService()
