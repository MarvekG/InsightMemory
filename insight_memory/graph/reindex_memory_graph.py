from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository


class ReindexMemoryState(TypedDict, total=False):
    memory_space: str
    entity_key: str | None
    memory_ids: list[str]
    result: dict[str, int]


class ReindexMemoryGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(
        self,
        *,
        memory_space: str,
        entity_key: str | None,
        memory_ids: list[str],
    ) -> dict[str, int]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "entity_key": entity_key,
                "memory_ids": memory_ids,
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(ReindexMemoryState)
        graph.add_node("refresh_retrieval_docs", self._refresh_retrieval_docs)
        graph.set_entry_point("refresh_retrieval_docs")
        graph.add_edge("refresh_retrieval_docs", END)
        return graph.compile()

    async def _refresh_retrieval_docs(self, state: ReindexMemoryState) -> dict[str, object]:
        memory_space = state["memory_space"]
        entity_key = state.get("entity_key")
        memory_ids = list(state.get("memory_ids") or [])
        refreshed_entities = 0
        refreshed_memories = 0
        async with MemoryRepository() as repository:
            if entity_key:
                entity = await repository.get_entity(memory_space=memory_space, entity_key=str(entity_key))
                if entity is not None:
                    await retrieval_index.refresh_entities(entities=[entity])
                    refreshed_entities += 1
                    memories = await repository.list_memories(
                        memory_space=memory_space,
                        entity_key=str(entity_key),
                        limit=200,
                    )
                    await retrieval_index.refresh_memories(memories=memories, entities_by_key={entity.entity_key: entity})
                    refreshed_memories += len(memories)
            if memory_ids:
                memories = await repository.get_memories_by_ids(memory_space=memory_space, memory_ids=memory_ids)
                entities_by_key = {
                    entity.entity_key: entity
                    for entity in await repository.get_entities_by_keys(
                        memory_space=memory_space,
                        entity_keys={memory.entity_key for memory in memories},
                    )
                }
                await retrieval_index.refresh_memories(memories=memories, entities_by_key=entities_by_key)
                refreshed_memories += len(memories)
        return {"result": {"refreshed_entities": refreshed_entities, "refreshed_memories": refreshed_memories}}


reindex_memory_graph = ReindexMemoryGraph()
