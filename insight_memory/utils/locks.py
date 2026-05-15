from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

_resolution_locks: dict[tuple[str, str | None], asyncio.Lock] = {}
_resolution_locks_guard = asyncio.Lock()


async def _get_resolution_lock(*, memory_space: str, entity_key: str | None = None) -> asyncio.Lock:
    key = (str(memory_space).strip(), str(entity_key).strip() or None)
    async with _resolution_locks_guard:
        lock = _resolution_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _resolution_locks[key] = lock
        return lock


@asynccontextmanager
async def entity_resolution_lock(*, memory_space: str):
    lock = await _get_resolution_lock(memory_space=memory_space)
    async with lock:
        yield


@asynccontextmanager
async def entity_memory_resolution_lock(*, memory_space: str, entity_key: str):
    lock = await _get_resolution_lock(
        memory_space=memory_space,
        entity_key=entity_key,
    )
    async with lock:
        yield
