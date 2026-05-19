from __future__ import annotations

from collections.abc import Iterable
import time
from typing import Any

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from insight_memory.storage import database as database_module
from insight_memory.storage.models import (
    MemoryEdge,
    MemoryEntity,
    MemoryEntityMergeLog,
    MemoryLLMRun,
    MemoryMemory,
    MemoryMemoryVersion,
    MemoryObservation,
    MemoryRecallAudit,
    MemorySystemState,
    MemoryTask,
)
from insight_memory.utils.ids import new_prefixed_id
from insight_memory.utils.request_context import get_request_id


def _cache_hit_rate(cached_tokens: int, input_tokens: int) -> float:
    if input_tokens <= 0:
        return 0.0
    return cached_tokens / input_tokens


class MemoryRepository:
    """Async repository used by the FastAPI application runtime."""

    def __init__(self) -> None:
        self.db: AsyncSession = database_module.AsyncSessionLocal()

    async def __aenter__(self) -> MemoryRepository:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        try:
            if exc_type is None:
                await self.db.commit()
            else:
                await self.db.rollback()
        finally:
            try:
                await self.db.close()
            except Exception:
                pass

    @staticmethod
    def timestamp_now() -> float:
        """返回当前 Unix 时间戳，单位为秒。"""

        return time.time()

    async def list_entities(self, *, memory_space: str, limit: int = 200) -> list[MemoryEntity]:
        stmt = (
            select(MemoryEntity)
            .where(MemoryEntity.memory_space == memory_space)
            .order_by(MemoryEntity.updated_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_entity(self, *, memory_space: str, entity_key: str) -> MemoryEntity | None:
        stmt = select(MemoryEntity).where(
            MemoryEntity.memory_space == memory_space,
            MemoryEntity.entity_key == entity_key,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_entities_by_keys(self, *, memory_space: str, entity_keys: Iterable[str]) -> list[MemoryEntity]:
        keys = [str(item) for item in entity_keys if str(item).strip()]
        if not keys:
            return []
        stmt = select(MemoryEntity).where(
            MemoryEntity.memory_space == memory_space,
            MemoryEntity.entity_key.in_(keys),
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        order = {entity_key: index for index, entity_key in enumerate(keys)}
        rows.sort(key=lambda item: order.get(item.entity_key, len(order)))
        return rows

    async def create_entity(
        self,
        *,
        memory_space: str,
        display_name: str,
        identity_profile: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntity:
        entity = MemoryEntity(
            entity_key=new_prefixed_id("ent"),
            memory_space=memory_space,
            display_name=display_name,
            identity_profile=dict(identity_profile),
            metadata_json=dict(metadata or {}),
        )
        self.db.add(entity)
        await self.db.flush()
        return entity

    async def update_entity_profile(
        self,
        *,
        entity: MemoryEntity,
        display_name: str,
        identity_profile: dict[str, Any],
    ) -> MemoryEntity:
        entity.display_name = display_name
        entity.identity_profile = dict(identity_profile)
        entity.updated_at = self.timestamp_now()
        await self.db.flush()
        return entity

    async def create_observation(
        self,
        *,
        memory_space: str,
        content: str,
        summary: str,
        source_ref: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryObservation:
        observation = MemoryObservation(
            observation_id=new_prefixed_id("obs"),
            memory_space=memory_space,
            source_ref=source_ref,
            content=content,
            summary=summary,
            entity_resolution_status="pending",
            metadata_json=dict(metadata or {}),
        )
        self.db.add(observation)
        await self.db.flush()
        return observation

    async def mark_observation_resolved(
        self,
        *,
        memory_space: str,
        observation_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        result = await self.db.execute(
            select(MemoryObservation.metadata_json).where(
                MemoryObservation.memory_space == memory_space,
                MemoryObservation.observation_id == observation_id,
            )
        )
        existing = result.scalar_one()
        merged_metadata = dict(existing or {})
        if metadata:
            merged_metadata.update(metadata)
        stmt = (
            update(MemoryObservation)
            .where(
                MemoryObservation.memory_space == memory_space,
                MemoryObservation.observation_id == observation_id,
            )
            .values(
                entity_resolution_status=status,
                metadata_json=merged_metadata,
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def list_observations(self, *, memory_space: str, limit: int = 1000) -> list[MemoryObservation]:
        stmt = (
            select(MemoryObservation)
            .where(MemoryObservation.memory_space == memory_space)
            .order_by(MemoryObservation.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_memories(
        self,
        *,
        memory_space: str,
        entity_key: str,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[MemoryMemory]:
        stmt = select(MemoryMemory).where(
            MemoryMemory.memory_space == memory_space,
            MemoryMemory.entity_key == entity_key,
        )
        if statuses:
            stmt = stmt.where(MemoryMemory.status.in_(list(statuses)))
        stmt = stmt.order_by(MemoryMemory.updated_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_memory(self, *, memory_space: str, memory_id: str) -> MemoryMemory | None:
        stmt = select(MemoryMemory).where(
            MemoryMemory.memory_space == memory_space,
            MemoryMemory.memory_id == memory_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_memories_by_ids(self, *, memory_space: str, memory_ids: Iterable[str]) -> list[MemoryMemory]:
        ids = [str(item) for item in memory_ids if str(item).strip()]
        if not ids:
            return []
        stmt = select(MemoryMemory).where(
            MemoryMemory.memory_space == memory_space,
            MemoryMemory.memory_id.in_(ids),
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        order = {memory_id: index for index, memory_id in enumerate(ids)}
        rows.sort(key=lambda item: order.get(item.memory_id, len(order)))
        return rows

    async def create_memory(
        self,
        *,
        memory_space: str,
        entity_key: str,
        title: str,
        summary: str,
        content: str,
        confidence: float,
        salience: float,
        status: str,
        latest_source_observation_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryMemory:
        memory = MemoryMemory(
            memory_id=new_prefixed_id("mem"),
            memory_space=memory_space,
            entity_key=entity_key,
            title=title,
            summary=summary,
            content=content,
            confidence=confidence,
            salience=salience,
            status=status,
            latest_source_observation_id=latest_source_observation_id,
            metadata_json=dict(metadata or {}),
        )
        self.db.add(memory)
        await self.db.flush()
        return memory

    async def update_memory(
        self,
        *,
        memory: MemoryMemory,
        title: str | None = None,
        summary: str | None = None,
        content: str | None = None,
        confidence: float | None = None,
        salience: float | None = None,
        status: str | None = None,
        latest_source_observation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryMemory:
        if title is not None:
            memory.title = title
        if summary is not None:
            memory.summary = summary
        if content is not None:
            memory.content = content
        if confidence is not None:
            memory.confidence = confidence
        if salience is not None:
            memory.salience = salience
        if status is not None:
            memory.status = status
        if latest_source_observation_id is not None:
            memory.latest_source_observation_id = latest_source_observation_id
        if metadata:
            merged = dict(memory.metadata_json or {})
            merged.update(metadata)
            memory.metadata_json = merged
        memory.updated_at = self.timestamp_now()
        await self.db.flush()
        return memory

    async def next_memory_version(self, *, memory_space: str, memory_id: str) -> int:
        stmt = select(func.max(MemoryMemoryVersion.version)).where(
            MemoryMemoryVersion.memory_space == memory_space,
            MemoryMemoryVersion.memory_id == memory_id,
        )
        result = await self.db.execute(stmt)
        current = result.scalar_one_or_none() or 0
        return int(current) + 1

    async def create_memory_version(
        self,
        *,
        memory_space: str,
        memory: MemoryMemory,
        action: str,
        trigger_observation_id: str | None,
        resolver_output: dict[str, Any],
        change_reason: str,
    ) -> MemoryMemoryVersion:
        version = MemoryMemoryVersion(
            version_id=new_prefixed_id("ver"),
            memory_space=memory_space,
            memory_id=memory.memory_id,
            version=await self.next_memory_version(memory_space=memory_space, memory_id=memory.memory_id),
            action=action,
            title=memory.title,
            summary=memory.summary,
            content=memory.content,
            confidence=memory.confidence,
            salience=memory.salience,
            status=memory.status,
            trigger_observation_id=trigger_observation_id,
            resolver_output=dict(resolver_output),
            change_reason=change_reason,
        )
        self.db.add(version)
        await self.db.flush()
        return version

    async def create_edges(self, *, memory_space: str, edges: list[dict[str, Any]]) -> list[MemoryEdge]:
        created: list[MemoryEdge] = []
        seen_relation_pairs: set[tuple[str, str, str]] = set()
        for edge in edges:
            from_id = str(edge["from_id"])
            to_id = str(edge["to_id"])
            to_kind = str(edge["to_kind"])
            edge_type = str(edge["edge_type"])
            existing_stmt = select(MemoryEdge).where(
                MemoryEdge.memory_space == memory_space,
                MemoryEdge.from_id == from_id,
                MemoryEdge.to_id == to_id,
                MemoryEdge.edge_type == edge_type,
            )
            existing_result = await self.db.execute(existing_stmt)
            if existing_result.scalar_one_or_none() is not None:
                continue
            relation_pair_key: tuple[str, str, str] | None = None
            if to_kind == "memory" and edge_type in {"supports", "contradicts", "related_to"}:
                left_id, right_id = sorted((from_id, to_id))
                relation_pair_key = (left_id, right_id, edge_type)
                if relation_pair_key in seen_relation_pairs:
                    continue
                reverse_stmt = select(MemoryEdge).where(
                    MemoryEdge.memory_space == memory_space,
                    MemoryEdge.from_id == to_id,
                    MemoryEdge.to_id == from_id,
                    MemoryEdge.edge_type == edge_type,
                )
                reverse_result = await self.db.execute(reverse_stmt)
                if reverse_result.scalar_one_or_none() is not None:
                    continue
            row = MemoryEdge(
                edge_id=new_prefixed_id("edge"),
                memory_space=memory_space,
                from_kind="memory",
                from_id=from_id,
                to_kind=to_kind,
                to_id=to_id,
                edge_type=edge_type,
                weight=edge.get("weight"),
                reason=edge.get("reason"),
                metadata_json=dict(edge.get("metadata") or {}),
            )
            self.db.add(row)
            created.append(row)
            if relation_pair_key is not None:
                seen_relation_pairs.add(relation_pair_key)
        await self.db.flush()
        return created

    async def list_edges_for_memory_ids(self, *, memory_space: str, memory_ids: Iterable[str]) -> list[MemoryEdge]:
        ids = [str(item) for item in memory_ids if str(item).strip()]
        if not ids:
            return []
        stmt = select(MemoryEdge).where(
            MemoryEdge.memory_space == memory_space,
            or_(
                MemoryEdge.from_id.in_(ids),
                MemoryEdge.to_id.in_(ids),
            ),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_edges(
        self,
        *,
        memory_space: str,
        edge_types: Iterable[str] | None = None,
        limit: int = 5000,
    ) -> list[MemoryEdge]:
        stmt = select(MemoryEdge).where(MemoryEdge.memory_space == memory_space)
        if edge_types:
            stmt = stmt.where(MemoryEdge.edge_type.in_(list(edge_types)))
        stmt = stmt.order_by(MemoryEdge.created_at.asc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_relation_edges_for_memory_ids(self, *, memory_space: str, memory_ids: Iterable[str]) -> int:
        ids = [str(item) for item in memory_ids if str(item).strip()]
        if not ids:
            return 0
        stmt = delete(MemoryEdge).where(
            MemoryEdge.memory_space == memory_space,
            MemoryEdge.edge_type.in_(("supports", "contradicts", "related_to")),
            or_(
                MemoryEdge.from_id.in_(ids),
                MemoryEdge.to_id.in_(ids),
            ),
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return int(result.rowcount or 0)

    async def get_observations_by_ids(self, *, memory_space: str, observation_ids: Iterable[str]) -> list[MemoryObservation]:
        ids = [str(item) for item in observation_ids if str(item).strip()]
        if not ids:
            return []
        stmt = select(MemoryObservation).where(
            MemoryObservation.memory_space == memory_space,
            MemoryObservation.observation_id.in_(ids),
        )
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())
        order = {observation_id: index for index, observation_id in enumerate(ids)}
        rows.sort(key=lambda item: order.get(item.observation_id, len(order)))
        return rows

    async def record_llm_run(
        self,
        *,
        memory_space: str,
        worker_type: str,
        model: str,
        prompt_version: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any] | None,
        parse_status: str,
        request_id: str | None,
        latency_ms: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int | None = None,
        cache_miss_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        task_id: str | None = None,
    ) -> MemoryLLMRun:
        row = MemoryLLMRun(
            run_id=new_prefixed_id("run"),
            memory_space=memory_space,
            task_id=task_id,
            worker_type=worker_type,
            model=model,
            prompt_version=prompt_version,
            input_json=dict(input_json),
            output_json=None if output_json is None else dict(output_json),
            parse_status=parse_status,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_miss_tokens=cache_miss_tokens,
            reasoning_tokens=reasoning_tokens,
            request_id=request_id,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def count_stats(self, *, memory_space: str | None = None) -> dict[str, int]:
        return {
            "entities": await self._count(MemoryEntity, memory_space=memory_space),
            "memories": await self._count(MemoryMemory, memory_space=memory_space),
            "observations": await self._count(MemoryObservation, memory_space=memory_space),
            "llm_runs": await self._count(MemoryLLMRun, memory_space=memory_space),
            "recall_audits": await self._count(MemoryRecallAudit, memory_space=memory_space),
            "tasks": await self._count(MemoryTask, memory_space=memory_space),
        }

    async def llm_usage_stats(self, *, hours: int | None = None) -> dict[str, Any]:
        filters = []
        if hours is not None and hours > 0:
            filters.append(MemoryLLMRun.created_at >= self.timestamp_now() - hours * 3600)

        input_tokens = func.coalesce(MemoryLLMRun.input_tokens, 0)
        output_tokens = func.coalesce(MemoryLLMRun.output_tokens, 0)
        cached_tokens = func.coalesce(MemoryLLMRun.cached_tokens, 0)
        cache_miss_tokens = func.coalesce(MemoryLLMRun.cache_miss_tokens, 0)
        reasoning_tokens = func.coalesce(MemoryLLMRun.reasoning_tokens, 0)
        total_tokens = input_tokens + output_tokens

        total_stmt = select(
            func.count(MemoryLLMRun.run_id),
            func.coalesce(func.sum(input_tokens), 0),
            func.coalesce(func.sum(output_tokens), 0),
            func.coalesce(func.sum(total_tokens), 0),
            func.coalesce(func.sum(cached_tokens), 0),
            func.coalesce(func.sum(cache_miss_tokens), 0),
            func.coalesce(func.sum(reasoning_tokens), 0),
        ).select_from(MemoryLLMRun)
        by_operation_stmt = (
            select(
                MemoryLLMRun.worker_type,
                func.count(MemoryLLMRun.run_id),
                func.coalesce(func.sum(input_tokens), 0),
                func.coalesce(func.sum(output_tokens), 0),
                func.coalesce(func.sum(total_tokens), 0),
                func.coalesce(func.sum(cached_tokens), 0),
                func.coalesce(func.sum(cache_miss_tokens), 0),
                func.coalesce(func.sum(reasoning_tokens), 0),
            )
            .select_from(MemoryLLMRun)
            .group_by(MemoryLLMRun.worker_type)
            .order_by(MemoryLLMRun.worker_type.asc())
        )
        for condition in filters:
            total_stmt = total_stmt.where(condition)
            by_operation_stmt = by_operation_stmt.where(condition)

        total_result = await self.db.execute(total_stmt)
        (
            total_calls,
            total_input_tokens,
            total_output_tokens,
            summed_tokens,
            total_cached_tokens,
            total_cache_miss_tokens,
            total_reasoning_tokens,
        ) = total_result.one()
        by_operation_result = await self.db.execute(by_operation_stmt)
        by_operation = {
            str(worker_type): {
                "calls": int(calls or 0),
                "input_tokens": int(operation_input_tokens or 0),
                "output_tokens": int(operation_output_tokens or 0),
                "total_tokens": int(operation_total_tokens or 0),
                "cached_tokens": int(operation_cached_tokens or 0),
                "cache_miss_tokens": int(operation_cache_miss_tokens or 0),
                "reasoning_tokens": int(operation_reasoning_tokens or 0),
                "cache_hit_rate": _cache_hit_rate(
                    int(operation_cached_tokens or 0),
                    int(operation_input_tokens or 0),
                ),
            }
            for (
                worker_type,
                calls,
                operation_input_tokens,
                operation_output_tokens,
                operation_total_tokens,
                operation_cached_tokens,
                operation_cache_miss_tokens,
                operation_reasoning_tokens,
            ) in by_operation_result.all()
        }
        input_token_count = int(total_input_tokens or 0)
        cached_token_count = int(total_cached_tokens or 0)
        return {
            "total_calls": int(total_calls or 0),
            "input_tokens": input_token_count,
            "output_tokens": int(total_output_tokens or 0),
            "total_tokens": int(summed_tokens or 0),
            "cached_tokens": cached_token_count,
            "cache_miss_tokens": int(total_cache_miss_tokens or 0),
            "reasoning_tokens": int(total_reasoning_tokens or 0),
            "cache_hit_rate": _cache_hit_rate(cached_token_count, input_token_count),
            "by_operation": by_operation,
        }

    async def delete_old_llm_runs(self, *, retention_days: int, now: float | None = None) -> int:
        """Delete LLM run audit rows older than the retention window."""

        cutoff = (self.timestamp_now() if now is None else now) - retention_days * 24 * 60 * 60
        result = await self.db.execute(delete(MemoryLLMRun).where(MemoryLLMRun.created_at < cutoff))
        return int(result.rowcount or 0)

    async def clear_llm_runs(self) -> int:
        """Delete all LLM run audit rows."""

        result = await self.db.execute(delete(MemoryLLMRun))
        return int(result.rowcount or 0)

    async def create_task(
        self,
        *,
        memory_space: str,
        task_type: str,
        payload: dict[str, Any],
        dedupe_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        available_at: float | None = None,
        dedupe_statuses: Iterable[str] = ("pending", "running"),
    ) -> MemoryTask:
        if dedupe_key:
            stmt = select(MemoryTask).where(
                MemoryTask.memory_space == memory_space,
                MemoryTask.dedupe_key == dedupe_key,
                MemoryTask.status.in_(tuple(dedupe_statuses)),
            )
            result = await self.db.execute(stmt)
            existing_tasks = result.scalars().all()
            if existing_tasks:
                return existing_tasks[0]
        task_payload = dict(payload)
        current_request_id = get_request_id()
        if current_request_id and not str(task_payload.get("request_id") or "").strip():
            task_payload["request_id"] = current_request_id
        task = MemoryTask(
            task_id=new_prefixed_id("task"),
            memory_space=memory_space,
            task_type=task_type,
            status="pending",
            priority=priority,
            dedupe_key=dedupe_key,
            payload=task_payload,
            available_at=available_at or self.timestamp_now(),
            max_attempts=max_attempts,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def list_tasks(
        self,
        *,
        memory_space: str,
        statuses: Iterable[str] | None = None,
        task_types: Iterable[str] | None = None,
        limit: int = 1000,
    ) -> list[MemoryTask]:
        stmt = select(MemoryTask).where(MemoryTask.memory_space == memory_space)
        if statuses:
            stmt = stmt.where(MemoryTask.status.in_(list(statuses)))
        if task_types:
            stmt = stmt.where(MemoryTask.task_type.in_(list(task_types)))
        stmt = stmt.order_by(MemoryTask.created_at.asc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_due_tasks(self, *, limit: int = 50) -> list[MemoryTask]:
        stmt = (
            select(MemoryTask)
            .where(
                MemoryTask.status == "pending",
                MemoryTask.available_at <= self.timestamp_now(),
            )
            .order_by(MemoryTask.priority.desc(), MemoryTask.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def claim_due_tasks(
        self,
        *,
        limit: int,
        lease_owner: str,
        lease_seconds: int,
    ) -> list[MemoryTask]:
        stmt = (
            select(MemoryTask)
            .where(
                MemoryTask.status == "pending",
                MemoryTask.available_at <= self.timestamp_now(),
            )
            .order_by(MemoryTask.priority.desc(), MemoryTask.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.db.execute(stmt)
        tasks = list(result.scalars().all())
        for task in tasks:
            await self.mark_task_running(task=task, lease_owner=lease_owner, lease_seconds=lease_seconds)
        await self.db.flush()
        return tasks

    async def claim_task(
        self,
        *,
        task_id: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> MemoryTask | None:
        stmt = (
            select(MemoryTask)
            .where(
                MemoryTask.task_id == task_id,
                MemoryTask.status == "pending",
                MemoryTask.available_at <= self.timestamp_now(),
            )
            .with_for_update(skip_locked=True)
        )
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        if task is None:
            return None
        await self.mark_task_running(task=task, lease_owner=lease_owner, lease_seconds=lease_seconds)
        await self.db.flush()
        return task

    async def get_task(self, *, task_id: str) -> MemoryTask | None:
        stmt = select(MemoryTask).where(MemoryTask.task_id == task_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_task_running(self, *, task: MemoryTask, lease_owner: str, lease_seconds: int) -> MemoryTask:
        task.status = "running"
        task.lease_owner = lease_owner
        task.lease_expires_at = self.timestamp_now() + max(lease_seconds, 1)
        task.attempt_count += 1
        await self.db.flush()
        return task

    async def mark_task_succeeded(self, *, task: MemoryTask) -> None:
        task.status = "succeeded"
        task.lease_owner = None
        task.lease_expires_at = None
        task.last_error_code = None
        task.last_error_message = None
        await self.db.flush()

    async def mark_task_failed(self, *, task: MemoryTask, error_code: str, error_message: str) -> None:
        task.last_error_code = error_code
        task.last_error_message = error_message
        task.lease_owner = None
        task.lease_expires_at = None
        task.status = "dead_letter" if task.attempt_count >= task.max_attempts else "failed"
        await self.db.flush()

    async def release_running_task(self, *, task: MemoryTask) -> None:
        """Release a claimed task back to the pending queue after cooperative cancellation."""

        task.status = "pending"
        task.lease_owner = None
        task.lease_expires_at = None
        task.available_at = self.timestamp_now()
        await self.db.flush()

    async def retry_failed_tasks(self) -> int:
        stmt = select(MemoryTask).where(
            MemoryTask.status == "failed",
            MemoryTask.attempt_count < MemoryTask.max_attempts,
        )
        result = await self.db.execute(stmt)
        tasks = list(result.scalars().all())
        for task in tasks:
            task.status = "pending"
            task.available_at = self.timestamp_now()
        await self.db.flush()
        return len(tasks)

    async def recover_abandoned_tasks(self) -> int:
        now = self.timestamp_now()
        stmt = select(MemoryTask).where(
            MemoryTask.status == "running",
            MemoryTask.lease_expires_at.is_not(None),
            MemoryTask.lease_expires_at <= now,
        )
        result = await self.db.execute(stmt)
        tasks = list(result.scalars().all())
        for task in tasks:
            task.status = "pending"
            task.lease_owner = None
            task.lease_expires_at = None
            task.available_at = now
        await self.db.flush()
        return len(tasks)

    async def get_system_state(self, *, state_key: str) -> MemorySystemState | None:
        """读取一条服务级状态记录。"""

        stmt = select(MemorySystemState).where(MemorySystemState.state_key == state_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_system_state(self, *, state_key: str, state_json: dict[str, Any]) -> MemorySystemState:
        """创建或更新一条服务级状态记录。"""

        state = await self.get_system_state(state_key=state_key)
        if state is None:
            state = MemorySystemState(state_key=state_key, state_json=dict(state_json))
            self.db.add(state)
        else:
            state.state_json = dict(state_json)
            state.updated_at = self.timestamp_now()
        await self.db.flush()
        return state

    async def list_all_entities(self, *, memory_space: str | None = None) -> list[MemoryEntity]:
        stmt = select(MemoryEntity)
        if memory_space:
            stmt = stmt.where(MemoryEntity.memory_space == memory_space)
        stmt = stmt.order_by(MemoryEntity.created_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_all_memories(self, *, memory_space: str | None = None) -> list[MemoryMemory]:
        stmt = select(MemoryMemory)
        if memory_space:
            stmt = stmt.where(MemoryMemory.memory_space == memory_space)
        stmt = stmt.order_by(MemoryMemory.created_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_entities_for_rebuild(self, *, limit: int, offset: int = 0) -> list[MemoryEntity]:
        """按稳定顺序分批读取需要重建索引的 entity。"""

        stmt = select(MemoryEntity).order_by(MemoryEntity.created_at.asc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_memories_for_rebuild(self, *, limit: int, offset: int = 0) -> list[MemoryMemory]:
        """按稳定顺序分批读取需要重建索引的 memory。"""

        stmt = select(MemoryMemory).order_by(MemoryMemory.created_at.asc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def preview_memories(
        self,
        *,
        memory_space: str | None = None,
        memory_space_prefix: str | None = None,
        memory_space_contains: str | None = None,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[MemoryMemory]]:
        stmt = select(MemoryMemory)
        count_stmt = select(func.count()).select_from(MemoryMemory)
        conditions = []
        if memory_space:
            conditions.append(MemoryMemory.memory_space == memory_space)
        if memory_space_prefix:
            conditions.append(MemoryMemory.memory_space.like(f"{memory_space_prefix}%"))
        if memory_space_contains:
            conditions.append(MemoryMemory.memory_space.like(f"%{memory_space_contains}%"))
        if statuses:
            conditions.append(MemoryMemory.status.in_(list(statuses)))
        for condition in conditions:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar_one())
        rows_result = await self.db.execute(
            stmt.order_by(MemoryMemory.updated_at.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
        )
        return total, list(rows_result.scalars().all())

    async def merge_entities(
        self,
        *,
        memory_space: str,
        source_entity_key: str,
        target_entity_key: str,
        reason: str,
    ) -> None:
        if source_entity_key == target_entity_key:
            return
        source = await self.get_entity(memory_space=memory_space, entity_key=source_entity_key)
        target = await self.get_entity(memory_space=memory_space, entity_key=target_entity_key)
        if source is None or target is None:
            return
        source_memories = await self.list_memories(memory_space=memory_space, entity_key=source_entity_key, limit=1000)
        for memory in source_memories:
            memory.entity_key = target_entity_key
        await self.create_merge_log(
            memory_space=memory_space,
            source_entity_key=source_entity_key,
            target_entity_key=target_entity_key,
            reason=reason,
        )
        await self.db.delete(source)
        await self.db.flush()

    async def create_merge_log(
        self,
        *,
        memory_space: str,
        source_entity_key: str,
        target_entity_key: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntityMergeLog:
        row = MemoryEntityMergeLog(
            merge_id=new_prefixed_id("merge"),
            memory_space=memory_space,
            source_entity_key=source_entity_key,
            target_entity_key=target_entity_key,
            reason=reason,
            metadata_json=dict(metadata or {}),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def archive_memories(
        self,
        *,
        memory_space: str,
        memory_ids: Iterable[str],
        trigger_observation_id: str | None = None,
        reason: str = "archive",
    ) -> list[MemoryMemory]:
        memories = await self.get_memories_by_ids(memory_space=memory_space, memory_ids=memory_ids)
        archived: list[MemoryMemory] = []
        for memory in memories:
            if memory.status == "archived":
                continue
            await self.update_memory(memory=memory, status="archived")
            await self.create_memory_version(
                memory_space=memory_space,
                memory=memory,
                action="archive",
                trigger_observation_id=trigger_observation_id,
                resolver_output={"action": "archive"},
                change_reason=reason,
            )
            archived.append(memory)
        return archived

    async def purge_memories(
        self,
        *,
        memory_space: str,
        memory_ids: Iterable[str],
    ) -> dict[str, int]:
        ids = [str(item) for item in memory_ids if str(item).strip()]
        if not ids:
            return {"deleted_memories": 0, "deleted_versions": 0, "deleted_edges": 0}
        edge_stmt = delete(MemoryEdge).where(
            MemoryEdge.memory_space == memory_space,
            or_(MemoryEdge.from_id.in_(ids), MemoryEdge.to_id.in_(ids)),
        )
        version_stmt = delete(MemoryMemoryVersion).where(
            MemoryMemoryVersion.memory_space == memory_space,
            MemoryMemoryVersion.memory_id.in_(ids),
        )
        memory_stmt = delete(MemoryMemory).where(
            MemoryMemory.memory_space == memory_space,
            MemoryMemory.memory_id.in_(ids),
        )
        deleted_edges = (await self.db.execute(edge_stmt)).rowcount or 0
        deleted_versions = (await self.db.execute(version_stmt)).rowcount or 0
        deleted_memories = (await self.db.execute(memory_stmt)).rowcount or 0
        await self.db.flush()
        return {
            "deleted_memories": int(deleted_memories),
            "deleted_versions": int(deleted_versions),
            "deleted_edges": int(deleted_edges),
        }

    async def all_ref_doc_ids(self) -> set[str]:
        entity_ids = {
            f"entity:{row.memory_space}:{row.entity_key}"
            for row in await self.list_all_entities()
        }
        stmt = select(MemoryMemory.memory_space, MemoryMemory.memory_id)
        result = await self.db.execute(stmt)
        memory_ids = {
            f"memory:{memory_space}:{memory_id}"
            for memory_space, memory_id in result.all()
        }
        return entity_ids | memory_ids

    async def create_recall_audit(
        self,
        *,
        memory_space: str,
        request_id: str,
        query: str,
        status: str,
        resolved_entity_key: str | None,
        answer: str,
        error_code: str | None,
        uncertainties: list[str],
        used_edges: list[dict[str, Any]],
        resolution_trace: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecallAudit:
        row = MemoryRecallAudit(
            audit_id=new_prefixed_id("audit"),
            memory_space=memory_space,
            request_id=request_id,
            query=query,
            status=status,
            resolved_entity_key=resolved_entity_key,
            answer=answer,
            error_code=error_code,
            uncertainties=list(uncertainties),
            used_edges=list(used_edges),
            resolution_trace=dict(resolution_trace or {}),
            metadata_json=dict(metadata or {}),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_recall_audits(
        self,
        *,
        memory_space: str,
        query: str | None = None,
        limit: int = 1000,
    ) -> list[MemoryRecallAudit]:
        stmt = select(MemoryRecallAudit).where(MemoryRecallAudit.memory_space == memory_space)
        if query is not None:
            stmt = stmt.where(MemoryRecallAudit.query == query)
        stmt = stmt.order_by(MemoryRecallAudit.created_at.asc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _count(self, model, *, memory_space: str | None = None) -> int:
        stmt = select(func.count()).select_from(model)
        if memory_space and hasattr(model, "memory_space"):
            stmt = stmt.where(model.memory_space == memory_space)
        result = await self.db.execute(stmt)
        return int(result.scalar_one())
