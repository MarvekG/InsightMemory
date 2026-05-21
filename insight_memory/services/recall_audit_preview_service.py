from __future__ import annotations

from typing import Any, Iterable

from insight_memory.storage.repository import MemoryRepository


class RecallAuditPreviewService:
    async def preview(
        self,
        *,
        memory_scope: str | None = None,
        memory_scope_prefix: str | None = None,
        memory_scope_contains: str | None = None,
        status: str | None = None,
        error_code: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return recall audit rows for retrieval-quality inspection."""

        statuses = self._parse_csv(status)
        async with MemoryRepository() as repository:
            total, audits = await repository.preview_recall_audits(
                memory_space=self._normalize_filter(memory_scope),
                memory_space_prefix=self._normalize_filter(memory_scope_prefix),
                memory_space_contains=self._normalize_filter(memory_scope_contains),
                statuses=statuses,
                error_code=self._normalize_filter(error_code),
                limit=limit,
                offset=offset,
            )
        return {
            "status": "success",
            "total": total,
            "limit": max(1, min(limit, 200)),
            "offset": max(0, offset),
            "items": [self._serialize_audit(audit) for audit in audits],
        }

    @staticmethod
    def _normalize_filter(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @classmethod
    def _parse_csv(cls, value: str | None) -> Iterable[str] | None:
        normalized = cls._normalize_filter(value)
        if not normalized:
            return None
        return [item.strip() for item in normalized.split(",") if item.strip()] or None

    @classmethod
    def _serialize_audit(cls, audit: Any) -> dict[str, Any]:
        metadata = dict(getattr(audit, "metadata_json", None) or {})
        query = str(getattr(audit, "query", "") or "")
        answer = str(getattr(audit, "answer", "") or "")
        return {
            "audit_id": audit.audit_id,
            "memory_scope": audit.memory_space,
            "request_id": audit.request_id,
            "query": query,
            "query_preview": str(metadata.get("query_preview") or query.replace("\n", " ").strip()[:240]),
            "status": audit.status,
            "resolved_entity_key": audit.resolved_entity_key,
            "error_code": audit.error_code,
            "answer_preview": str(metadata.get("answer_preview") or answer.replace("\n", " ").strip()[:240]),
            "answer_length": cls._metadata_int(metadata, "answer_length", len(answer)),
            "uncertainties": list(audit.uncertainties or []),
            "used_edge_count": cls._metadata_int(metadata, "used_edge_count", len(audit.used_edges or [])),
            "citation_count": cls._metadata_int(metadata, "citation_count", len(metadata.get("citations") or [])),
            "key_memory_ids": list(metadata.get("key_memory_ids") or []),
            "supporting_observation_ids": list(metadata.get("supporting_observation_ids") or []),
            "metadata": metadata,
            "created_at": audit.created_at,
        }

    @staticmethod
    def _metadata_int(metadata: dict[str, Any], key: str, default: int) -> int:
        value = metadata.get(key)
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return default


recall_audit_preview_service = RecallAuditPreviewService()
