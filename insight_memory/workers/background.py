from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import date

from insight_memory.config import settings
from insight_memory.storage.repository import MemoryRepository
from insight_memory.tasks.runtime import task_runtime
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)
LLM_USAGE_RETENTION_DAYS = 7


class BackgroundWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_llm_usage_cleanup_date: object | None = None

    async def recover_pending_tasks(self) -> dict[str, int]:
        async with MemoryRepository() as repository:
            recovered = await repository.recover_abandoned_tasks()
            retried = await repository.retry_failed_tasks()
        return {"recovered": recovered, "retried": retried}

    async def run_due_tasks_once(self, *, force_observation_gc: bool = False) -> list[dict]:
        del force_observation_gc
        return await task_runtime.run_due_tasks_once_async()

    async def run_llm_usage_cleanup_once(
        self,
        *,
        retention_days: int = LLM_USAGE_RETENTION_DAYS,
    ) -> dict[str, int | str]:
        """Delete memory LLM usage rows older than the retention window at most once per day."""

        today = date.today()
        if self._last_llm_usage_cleanup_date == today:
            return {
                "deleted": 0,
                "retention_days": retention_days,
                "skipped": "already_ran_today",
            }

        async with MemoryRepository() as repository:
            deleted = await repository.delete_old_llm_runs(retention_days=retention_days)
        self._last_llm_usage_cleanup_date = today
        if deleted:
            logger.info("Deleted %s old memory LLM usage run(s)", deleted)
        return {"deleted": deleted, "retention_days": retention_days}

    async def start(self) -> None:
        if self._running or settings.MEMORY_BACKGROUND_POLL_SECONDS <= 0:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def shutdown(self, *, cancel: bool = True) -> list[str]:
        messages: list[str] = []
        self._running = False
        if self._task is not None and cancel:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                messages.append("cancelled")
        self._task = None
        return messages

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.run_llm_usage_cleanup_once()
                    await task_runtime.run_due_tasks_until_idle_async()
                except Exception:
                    logger.exception("background task drain failed")
                await asyncio.sleep(settings.MEMORY_BACKGROUND_POLL_SECONDS)
        except asyncio.CancelledError:
            raise


background_worker = BackgroundWorker()
