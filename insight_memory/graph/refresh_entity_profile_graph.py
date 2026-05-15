from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.workers.runtime import MemoryWorkers


class RefreshEntityProfileState(TypedDict, total=False):
    memory_space: str
    entity_key: str
    entity: Any
    memories: list[Any]
    workers: MemoryWorkers
    profile: dict[str, Any]
    result: dict[str, Any]


class RefreshEntityProfileGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(self, *, memory_space: str, entity_key: str) -> dict[str, Any]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "entity_key": entity_key,
                "workers": MemoryWorkers(),
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(RefreshEntityProfileState)
        graph.add_node("load_entity_context", self._load_entity_context)
        graph.add_node("skip_missing_entity", self._skip_missing_entity)
        graph.add_node("write_profile", self._write_profile)
        graph.set_entry_point("load_entity_context")
        graph.add_conditional_edges(
            "load_entity_context",
            self._after_load_entity_context,
            {
                "skip_missing_entity": "skip_missing_entity",
                "write_profile": "write_profile",
            },
        )
        graph.add_edge("skip_missing_entity", END)
        graph.add_edge("write_profile", END)
        return graph.compile()

    async def _load_entity_context(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        async with MemoryRepository() as repository:
            entity = await repository.get_entity(memory_space=state["memory_space"], entity_key=state["entity_key"])
            if entity is None:
                return {"entity": None}
            memories = await repository.list_memories(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
                statuses=("active",),
                limit=10,
            )
        return {"entity": entity, "memories": memories}

    @staticmethod
    def _after_load_entity_context(state: RefreshEntityProfileState) -> str:
        return "write_profile" if state.get("entity") is not None else "skip_missing_entity"

    async def _skip_missing_entity(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        return {"result": {"refreshed": False}}

    async def _write_profile(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        entity = state["entity"]
        memories = state.get("memories") or []
        workers = state["workers"]
        profile_writer = await workers.run_profile_writer(
            memory_space=state["memory_space"],
            request_id=get_or_create_request_id(),
            payload={
                "current_identity_profile": entity.identity_profile,
                "current_display_name": entity.display_name,
                "recent_memory_summaries": [memory.summary for memory in memories[:4]],
            },
        )
        profile = profile_writer.model_dump()
        display_name = (profile.get("surface_forms") or [entity.display_name, profile.get("who") or entity.display_name])[0]
        async with MemoryRepository() as repository:
            current_entity = await repository.get_entity(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
            )
            if current_entity is None:
                return {"result": {"refreshed": False}}
            await repository.update_entity_profile(
                entity=current_entity,
                display_name=str(display_name),
                identity_profile=profile,
            )
            await retrieval_index.refresh_entities(entities=[current_entity])
        return {"profile": profile, "result": {"refreshed": True, "entity_key": state["entity_key"]}}


refresh_entity_profile_graph = RefreshEntityProfileGraph()
