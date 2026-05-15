from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.config import settings
from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.index.version_state import mark_index_failed, mark_index_ready, mark_index_reindexing
from insight_memory.storage.models import MemoryEntity, MemoryMemory
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)


class RebuildRetrievalIndexState(TypedDict, total=False):
    result: dict[str, int]


class RebuildRetrievalIndexGraph:
    """Internal graph that rebuilds the pgvector retrieval index from truth tables."""

    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(self) -> dict[str, int]:
        """Run a full internal retrieval-index rebuild."""

        result = await self._graph.ainvoke({"result": {}})
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(RebuildRetrievalIndexState)
        graph.add_node("rebuild_index", self._rebuild_index)
        graph.set_entry_point("rebuild_index")
        graph.add_edge("rebuild_index", END)
        return graph.compile()

    async def _rebuild_index(self, _: RebuildRetrievalIndexState) -> dict[str, object]:
        entity_count = 0
        memory_count = 0
        batch_size = max(int(settings.MEMORY_EMBEDDING_BATCH_SIZE or 1), 1)
        try:
            await mark_index_reindexing()
            await retrieval_index.reset_storage()
            entity_count = await self._rebuild_entities(batch_size=batch_size)
            memory_count = await self._rebuild_memories(batch_size=batch_size)
            await mark_index_ready()
        except Exception as exc:
            await mark_index_failed(error=str(exc))
            logger.exception("retrieval index rebuild failed")
            raise
        logger.info(
            "retrieval index rebuild completed",
            extra={"refreshed_entities": entity_count, "refreshed_memories": memory_count},
        )
        return {"result": {"refreshed_entities": entity_count, "refreshed_memories": memory_count}}

    @staticmethod
    async def _rebuild_entities(*, batch_size: int) -> int:
        refreshed = 0
        offset = 0
        while True:
            async with MemoryRepository() as repository:
                entities = await repository.list_entities_for_rebuild(limit=batch_size, offset=offset)
            if not entities:
                break
            await retrieval_index.refresh_entities(entities=entities)
            refreshed += len(entities)
            offset += len(entities)
        return refreshed

    @staticmethod
    async def _rebuild_memories(*, batch_size: int) -> int:
        refreshed = 0
        offset = 0
        while True:
            async with MemoryRepository() as repository:
                memories = await repository.list_memories_for_rebuild(limit=batch_size, offset=offset)
                entities_by_key = await _load_entities_by_key(repository=repository, memories=memories)
            if not memories:
                break
            await retrieval_index.refresh_memories(memories=memories, entities_by_key=entities_by_key)
            refreshed += len(memories)
            offset += len(memories)
        return refreshed


async def _load_entities_by_key(
    *,
    repository: MemoryRepository,
    memories: list[MemoryMemory],
) -> dict[str, MemoryEntity]:
    by_space: dict[str, set[str]] = defaultdict(set)
    for memory in memories:
        by_space[memory.memory_space].add(memory.entity_key)

    entities_by_key: dict[str, MemoryEntity] = {}
    for memory_space, entity_keys in by_space.items():
        entities = await repository.get_entities_by_keys(memory_space=memory_space, entity_keys=entity_keys)
        for entity in entities:
            entities_by_key[entity.entity_key] = entity
    return entities_by_key


rebuild_retrieval_index_graph = RebuildRetrievalIndexGraph()
