from __future__ import annotations

from typing import Any

from insight_memory.config import settings
from insight_memory.index.constants import MEMORY_PROJECTION_VERSION
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)

VECTOR_INDEX_STATE_KEY = "memory_vector_index_version"
REBUILD_RETRIEVAL_INDEX_TASK = "rebuild_retrieval_index"
REBUILD_RETRIEVAL_INDEX_DEDUPE_KEY = "rebuild_retrieval_index:global"

INDEX_STATUS_READY = "ready"
INDEX_STATUS_STALE = "stale"
INDEX_STATUS_REINDEXING = "reindexing"
INDEX_STATUS_FAILED = "failed"


def current_index_config() -> dict[str, Any]:
    """返回当前运行配置对应的索引版本字段。"""

    return {
        "embedding_provider": settings.MEMORY_EMBEDDING_PROVIDER,
        "embedding_model": settings.MEMORY_EMBEDDING_MODEL,
        "embedding_dim": int(settings.MEMORY_EMBEDDING_DIM),
        "projection_version": MEMORY_PROJECTION_VERSION,
    }


def build_index_state(
    *,
    status: str,
    indexed_at: float | None = None,
    last_error: str = "",
) -> dict[str, Any]:
    """构造写入系统状态表的 vector index 状态。"""

    state = current_index_config()
    state.update(
        {
            "status": status,
            "indexed_at": float(indexed_at or 0),
            "last_error": str(last_error or ""),
        }
    )
    return state


def index_config_matches(state_json: dict[str, Any] | None) -> bool:
    """判断已记录索引版本是否与当前运行配置一致。"""

    state = dict(state_json or {})
    current = current_index_config()
    return all(state.get(key) == value for key, value in current.items())


async def ensure_rebuild_task_if_needed() -> dict[str, Any]:
    """启动时检查索引版本，必要时创建内部重建任务。"""

    async with MemoryRepository() as repository:
        state = await repository.get_system_state(state_key=VECTOR_INDEX_STATE_KEY)
        state_json = dict(state.state_json or {}) if state is not None else {}
        status = str(state_json.get("status") or "")
        if state is not None and index_config_matches(state_json) and status == INDEX_STATUS_READY:
            logger.info("vector index version ready", extra={"index_status": status})
            return {"status": INDEX_STATUS_READY, "task_created": False}

        stale_state = build_index_state(
            status=INDEX_STATUS_STALE,
            indexed_at=float(state_json.get("indexed_at") or 0),
            last_error=str(state_json.get("last_error") or ""),
        )
        await repository.upsert_system_state(state_key=VECTOR_INDEX_STATE_KEY, state_json=stale_state)
        task = await repository.create_task(
            memory_space="global",
            task_type=REBUILD_RETRIEVAL_INDEX_TASK,
            payload={},
            dedupe_key=REBUILD_RETRIEVAL_INDEX_DEDUPE_KEY,
            priority=1000,
            available_at=repository.timestamp_now() + 1.0,
        )
        logger.info(
            "vector index rebuild task ensured",
            extra={"task_id": task.task_id, "previous_status": status or "missing"},
        )
        return {"status": INDEX_STATUS_STALE, "task_created": True, "task_id": task.task_id}


async def mark_index_reindexing() -> None:
    """标记 vector index 正在内部重建。"""

    async with MemoryRepository() as repository:
        await repository.upsert_system_state(
            state_key=VECTOR_INDEX_STATE_KEY,
            state_json=build_index_state(status=INDEX_STATUS_REINDEXING),
        )


async def mark_index_ready() -> None:
    """标记 vector index 已经按当前配置重建完成。"""

    async with MemoryRepository() as repository:
        await repository.upsert_system_state(
            state_key=VECTOR_INDEX_STATE_KEY,
            state_json=build_index_state(status=INDEX_STATUS_READY, indexed_at=repository.timestamp_now()),
        )


async def mark_index_failed(*, error: str) -> None:
    """标记 vector index 内部重建失败。"""

    async with MemoryRepository() as repository:
        await repository.upsert_system_state(
            state_key=VECTOR_INDEX_STATE_KEY,
            state_json=build_index_state(status=INDEX_STATUS_FAILED, last_error=error),
        )


async def load_index_health() -> dict[str, Any]:
    """读取健康检查需要暴露的索引版本状态。"""

    async with MemoryRepository() as repository:
        state = await repository.get_system_state(state_key=VECTOR_INDEX_STATE_KEY)
    state_json = dict(state.state_json or {}) if state is not None else {}
    status = str(state_json.get("status") or INDEX_STATUS_STALE)
    if not state_json or not index_config_matches(state_json):
        status = INDEX_STATUS_STALE
    current = current_index_config()
    return {
        "index_status": status,
        **current,
    }
