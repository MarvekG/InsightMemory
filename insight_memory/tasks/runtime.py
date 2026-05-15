from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from insight_memory.config import settings
from insight_memory.graph.detect_merge_candidates_graph import detect_merge_candidates_graph
from insight_memory.graph.ingest_graph import ingest_graph
from insight_memory.graph.lifecycle_graph import forget_memory_graph, purge_memory_graph
from insight_memory.graph.merge_entities_graph import merge_entities_graph
from insight_memory.graph.rebuild_retrieval_index_graph import rebuild_retrieval_index_graph
from insight_memory.graph.refresh_entity_profile_graph import refresh_entity_profile_graph
from insight_memory.graph.reindex_memory_graph import reindex_memory_graph
from insight_memory.graph.repair_memory_edges_graph import repair_memory_edges_graph
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import clear_request_id
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.request_context import set_request_id


logger = get_logger(__name__)


COALESCABLE_TASK_TYPES = {
    "refresh_entity_profile",
    "reindex_memory",
    "repair_memory_edges",
    "detect_merge_candidates",
}


class TaskRuntime:
    def run_due_tasks_once(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return asyncio.run(self.run_due_tasks_once_async(limit=limit))

    async def run_due_tasks_once_async(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        claim_limit = self._effective_claim_limit(limit=limit)
        async with MemoryRepository() as repository:
            await repository.recover_abandoned_tasks()
            await repository.retry_failed_tasks()
            claimed_tasks = await repository.claim_due_tasks(
                limit=claim_limit,
                lease_owner="local_runner",
                lease_seconds=settings.MEMORY_TASK_LEASE_SECONDS,
            )
        if not claimed_tasks:
            return results

        leaders, followers = self._coalesce_tasks(tasks=claimed_tasks)
        if followers:
            async with MemoryRepository() as repository:
                for task in followers:
                    current = await repository.get_task(task_id=task.task_id)
                    if current is not None:
                        await repository.mark_task_succeeded(task=current)
                    results.append(
                        {
                            "task_id": task.task_id,
                            "status": "coalesced",
                            "task_type": task.task_type,
                        }
                    )

        semaphore = asyncio.Semaphore(settings.MEMORY_BACKGROUND_MAX_CONCURRENCY)
        space_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(settings.MEMORY_BACKGROUND_MAX_PER_SPACE)
        )
        resource_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        async def _run_leader(task: Any) -> dict[str, Any]:
            async with semaphore:
                async with space_semaphores[str(task.memory_space)]:
                    async with self._task_lock_scope(task=task, resource_locks=resource_locks):
                        return await self._run_claimed_task(task=task)

        concurrent_leaders = [task for task in leaders if not self._is_exclusive_task(task=task)]
        exclusive_leaders = [task for task in leaders if self._is_exclusive_task(task=task)]

        leader_results: list[dict[str, Any]] = []
        if concurrent_leaders:
            leader_results.extend(await asyncio.gather(*[_run_leader(task) for task in concurrent_leaders]))
        for task in exclusive_leaders:
            leader_results.append(await _run_leader(task))
        results.extend(leader_results)
        return results

    def run_due_tasks_until_idle(
        self,
        *,
        max_batches: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run due background tasks until the queue is idle or the batch budget is exhausted."""
        return asyncio.run(self.run_due_tasks_until_idle_async(max_batches=max_batches, limit=limit))

    async def run_due_tasks_until_idle_async(
        self,
        *,
        max_batches: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Drain due-task batches while continuously refilling free concurrency slots."""
        batch_budget = self._effective_batch_budget(max_batches=max_batches)
        results: list[dict[str, Any]] = []
        batches_claimed = 0
        active_tasks: set[asyncio.Task[dict[str, Any]]] = set()
        max_concurrency = settings.MEMORY_BACKGROUND_MAX_CONCURRENCY
        poll_seconds = settings.MEMORY_BACKGROUND_POLL_SECONDS
        claim_limit = self._effective_claim_limit(limit=limit)

        semaphore = asyncio.Semaphore(max_concurrency)
        space_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(settings.MEMORY_BACKGROUND_MAX_PER_SPACE)
        )
        resource_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        async def _run_leader(task: Any) -> dict[str, Any]:
            async with semaphore:
                async with space_semaphores[str(task.memory_space)]:
                    async with self._task_lock_scope(task=task, resource_locks=resource_locks):
                        return await self._run_claimed_task(task=task)

        def _collect_done(done: set[asyncio.Task[dict[str, Any]]]) -> None:
            for task in done:
                results.append(task.result())

        try:
            while batches_claimed < batch_budget:
                claimed_count = await self._start_due_task_batch(
                    active_tasks=active_tasks,
                    max_concurrency=max_concurrency,
                    claim_limit=claim_limit,
                    run_leader=_run_leader,
                    results=results,
                )
                if claimed_count > 0:
                    batches_claimed += 1
                    if len(active_tasks) < max_concurrency:
                        continue

                if not active_tasks:
                    break

                done, active_tasks = await asyncio.wait(
                    active_tasks,
                    timeout=poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                _collect_done(done)

            if active_tasks:
                done, _ = await asyncio.wait(active_tasks)
                _collect_done(done)
        except asyncio.CancelledError:
            for active_task in active_tasks:
                active_task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            raise
        return results

    async def _start_due_task_batch(
        self,
        *,
        active_tasks: set[asyncio.Task[dict[str, Any]]],
        max_concurrency: int,
        claim_limit: int,
        run_leader: Any,
        results: list[dict[str, Any]],
    ) -> int:
        free_slots = max_concurrency - len(active_tasks)
        if free_slots <= 0:
            return 0

        async with MemoryRepository() as repository:
            await repository.recover_abandoned_tasks()
            await repository.retry_failed_tasks()
            claimed_tasks = await repository.claim_due_tasks(
                limit=min(claim_limit, free_slots),
                lease_owner="local_runner",
                lease_seconds=settings.MEMORY_TASK_LEASE_SECONDS,
            )
        if not claimed_tasks:
            return 0

        leaders, followers = self._coalesce_tasks(tasks=claimed_tasks)
        await self._mark_coalesced_followers(followers=followers, results=results)
        active_tasks.update(asyncio.create_task(run_leader(task)) for task in leaders)
        return len(claimed_tasks)

    @staticmethod
    async def _mark_coalesced_followers(*, followers: list[Any], results: list[dict[str, Any]]) -> None:
        if not followers:
            return
        async with MemoryRepository() as repository:
            for task in followers:
                current = await repository.get_task(task_id=task.task_id)
                if current is not None:
                    await repository.mark_task_succeeded(task=current)
                results.append(
                    {
                        "task_id": task.task_id,
                        "status": "coalesced",
                        "task_type": task.task_type,
                    }
                )

    def run_task(self, *, task_id: str) -> dict[str, Any]:
        return asyncio.run(self.run_task_async(task_id=task_id))

    async def run_task_async(self, *, task_id: str) -> dict[str, Any]:
        async with MemoryRepository() as repository:
            task = await repository.claim_task(
                task_id=task_id,
                lease_owner="local_runner",
                lease_seconds=settings.MEMORY_TASK_LEASE_SECONDS,
            )
        if task is None:
            return {"task_id": task_id, "status": "skipped"}
        return await self._run_claimed_task(task=task)

    async def _run_claimed_task(self, *, task: Any) -> dict[str, Any]:
        task_type = str(task.task_type)
        task_payload = dict(task.payload or {})
        request_id = get_or_create_request_id(task_payload.get("request_id"))
        task_record_id = str(task.task_id)

        token = set_request_id(request_id)
        try:
            result = await self._dispatch_async(task_type=task_type, payload=task_payload)
            async with MemoryRepository() as repository:
                current = await repository.get_task(task_id=task_record_id)
                if current is not None:
                    await repository.mark_task_succeeded(task=current)
            return {"task_id": task_record_id, "status": "succeeded", "result": result}
        except asyncio.CancelledError:
            async with MemoryRepository() as repository:
                current = await repository.get_task(task_id=task_record_id)
                if current is not None:
                    await repository.release_running_task(task=current)
            logger.warning("task cancelled and released", extra={"task_id": task_record_id, "task_type": task_type})
            raise
        except Exception as exc:
            async with MemoryRepository() as repository:
                current = await repository.get_task(task_id=task_record_id)
                if current is not None:
                    await repository.mark_task_failed(
                        task=current,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                    )
            logger.exception("task failed", extra={"task_id": task_record_id, "task_type": task_type})
            return {"task_id": task_record_id, "status": "failed", "error": str(exc)}
        finally:
            clear_request_id(token)

    def _coalesce_tasks(self, *, tasks: list[Any]) -> tuple[list[Any], list[Any]]:
        leaders_by_key: dict[tuple[str, str, str], Any] = {}
        followers: list[Any] = []
        for task in tasks:
            coalesce_key = self._task_coalesce_key(task=task)
            if coalesce_key is None:
                leaders_by_key[(task.task_type, task.memory_space, task.task_id)] = task
                continue
            leader = leaders_by_key.get(coalesce_key)
            if leader is None:
                leaders_by_key[coalesce_key] = task
                continue
            merged_payload = self._merge_task_payloads(
                task_type=str(task.task_type),
                leader_payload=dict(leader.payload or {}),
                follower_payload=dict(task.payload or {}),
            )
            leader.payload = merged_payload
            followers.append(task)
        return list(leaders_by_key.values()), followers

    @staticmethod
    def _task_coalesce_key(*, task: Any) -> tuple[str, str, str] | None:
        task_type = str(task.task_type)
        if task_type not in COALESCABLE_TASK_TYPES:
            return None
        payload = dict(task.payload or {})
        entity_key = str(payload.get("entity_key") or "").strip()
        if not entity_key:
            return None
        return task_type, str(task.memory_space), entity_key

    @staticmethod
    def _merge_task_payloads(
        *,
        task_type: str,
        leader_payload: dict[str, Any],
        follower_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if task_type != "reindex_memory":
            return leader_payload
        leader_memory_ids = [str(item) for item in leader_payload.get("memory_ids") or [] if str(item).strip()]
        follower_memory_ids = [str(item) for item in follower_payload.get("memory_ids") or [] if str(item).strip()]
        merged_memory_ids: list[str] = []
        for memory_id in [*leader_memory_ids, *follower_memory_ids]:
            if memory_id not in merged_memory_ids:
                merged_memory_ids.append(memory_id)
        merged = dict(leader_payload)
        if merged_memory_ids:
            merged["memory_ids"] = merged_memory_ids
        return merged

    @staticmethod
    def _is_exclusive_task(*, task: Any) -> bool:
        return str(task.task_type) == "rebuild_retrieval_index"

    @staticmethod
    def _effective_claim_limit(*, limit: int | None) -> int:
        if limit is not None:
            return max(1, int(limit))
        if settings.MEMORY_BACKGROUND_CLAIM_LIMIT > 0:
            return settings.MEMORY_BACKGROUND_CLAIM_LIMIT
        return max(1, settings.MEMORY_BACKGROUND_MAX_CONCURRENCY * 2)

    @staticmethod
    def _effective_batch_budget(*, max_batches: int | None) -> int:
        if max_batches is not None:
            return max(1, int(max_batches))
        return settings.MEMORY_BACKGROUND_DRAIN_BATCHES_PER_TICK

    @asynccontextmanager
    async def _task_lock_scope(
        self,
        *,
        task: Any,
        resource_locks: dict[str, asyncio.Lock],
    ) -> Any:
        lock_keys = self._task_lock_keys(task=task)
        if not lock_keys:
            yield
            return
        async with AsyncExitStack() as stack:
            for lock_key in lock_keys:
                await stack.enter_async_context(self._lock(resource_locks[lock_key]))
            yield

    @staticmethod
    @asynccontextmanager
    async def _lock(lock: asyncio.Lock) -> Any:
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _task_lock_keys(*, task: Any) -> list[str]:
        task_type = str(task.task_type)
        memory_space = str(task.memory_space)
        payload = dict(task.payload or {})
        if task_type == "rebuild_retrieval_index":
            return ["global:retrieval_index_maintenance"]
        if task_type in {"refresh_entity_profile", "repair_memory_edges", "detect_merge_candidates"}:
            entity_key = str(payload.get("entity_key") or "").strip()
            if not entity_key:
                return []
            return [f"entity:{memory_space}:{entity_key}:{task_type}"]
        if task_type == "merge_entities":
            entity_keys = sorted(
                {
                    str(payload.get("source_entity_key") or "").strip(),
                    str(payload.get("target_entity_key") or "").strip(),
                }
                - {""}
            )
            return [f"merge:{memory_space}:{entity_key}" for entity_key in entity_keys]
        if task_type in {"forget_memory", "purge_memory"}:
            memory_ids = sorted(
                {
                    str(memory_id).strip()
                    for memory_id in payload.get("memory_ids") or []
                    if str(memory_id).strip()
                }
            )
            return [f"lifecycle:{memory_space}:{memory_id}" for memory_id in memory_ids]
        return []

    async def _dispatch_async(self, *, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task_type == "continue_ingest":
            return await self._continue_ingest(payload=payload)
        if task_type == "refresh_entity_profile":
            return await self._refresh_entity_profile(payload=payload)
        if task_type == "reindex_memory":
            return await self._reindex_memory(payload=payload)
        if task_type == "repair_memory_edges":
            return await self._repair_memory_edges(payload=payload)
        if task_type == "detect_merge_candidates":
            return await self._detect_merge_candidates(payload=payload)
        if task_type == "merge_entities":
            return await self._merge_entities(payload=payload)
        if task_type == "rebuild_retrieval_index":
            return await self._rebuild_retrieval_index()
        if task_type == "forget_memory":
            return await self._forget_memory(payload=payload)
        if task_type == "purge_memory":
            return await self._purge_memory(payload=payload)
        return {"task_type": task_type, "status": "ignored"}

    async def _continue_ingest(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await ingest_graph.run(
            memory_space=str(payload["memory_space"]),
            request_id=str(payload["request_id"]),
            observation_id=str(payload["observation_id"]),
            extractor_payload=dict(payload.get("extractor") or {}),
        )

    async def _refresh_entity_profile(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await refresh_entity_profile_graph.run(
            memory_space=str(payload["memory_space"]),
            entity_key=str(payload["entity_key"]),
        )

    async def _reindex_memory(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await reindex_memory_graph.run(
            memory_space=str(payload["memory_space"]),
            entity_key=str(payload.get("entity_key")) if payload.get("entity_key") else None,
            memory_ids=list(payload.get("memory_ids") or []),
        )

    async def _repair_memory_edges(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await repair_memory_edges_graph.run(
            memory_space=str(payload["memory_space"]),
            memory_id=str(payload["memory_id"]) if payload.get("memory_id") else None,
            entity_key=str(payload["entity_key"]) if payload.get("entity_key") else None,
        )

    async def _detect_merge_candidates(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await detect_merge_candidates_graph.run(
            memory_space=str(payload["memory_space"]),
            entity_key=str(payload.get("entity_key") or ""),
        )

    async def _merge_entities(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await merge_entities_graph.run(
            memory_space=str(payload["memory_space"]),
            source_entity_key=str(payload["source_entity_key"]),
            target_entity_key=str(payload["target_entity_key"]),
            reason=str(payload.get("reason") or "merge"),
        )

    async def _rebuild_retrieval_index(self) -> dict[str, Any]:
        return await rebuild_retrieval_index_graph.run()

    async def _forget_memory(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        memory_ids = [str(item) for item in payload.get("memory_ids") or [] if str(item).strip()]
        if not memory_ids:
            return {"archived": 0, "purge_task_created": False}
        return await forget_memory_graph.run(
            memory_space=str(payload["memory_space"]),
            memory_ids=memory_ids,
            trigger_observation_id=payload.get("trigger_observation_id"),
            reason=str(payload.get("reason") or "forget_memory"),
            purge_delay_seconds=int(payload.get("purge_delay_seconds") or 0),
        )

    async def _purge_memory(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        memory_ids = [str(item) for item in payload.get("memory_ids") or [] if str(item).strip()]
        if not memory_ids:
            return {"deleted_memories": 0, "deleted_versions": 0, "deleted_edges": 0}
        return await purge_memory_graph.run(
            memory_space=str(payload["memory_space"]),
            memory_ids=memory_ids,
        )


task_runtime = TaskRuntime()
