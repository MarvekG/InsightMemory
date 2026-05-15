from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository


class ForgetMemoryState(TypedDict, total=False):
    memory_space: str
    memory_ids: list[str]
    trigger_observation_id: str | None
    reason: str
    purge_delay_seconds: int
    result: dict[str, object]


class PurgeMemoryState(TypedDict, total=False):
    memory_space: str
    memory_ids: list[str]
    result: dict[str, int]


class ForgetMemoryGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(
        self,
        *,
        memory_space: str,
        memory_ids: list[str],
        trigger_observation_id: str | None,
        reason: str,
        purge_delay_seconds: int,
    ) -> dict[str, object]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "memory_ids": memory_ids,
                "trigger_observation_id": trigger_observation_id,
                "reason": reason,
                "purge_delay_seconds": purge_delay_seconds,
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(ForgetMemoryState)
        graph.add_node("archive_memories", self._archive_memories)
        graph.set_entry_point("archive_memories")
        graph.add_edge("archive_memories", END)
        return graph.compile()

    async def _archive_memories(self, state: ForgetMemoryState) -> dict[str, object]:
        async with MemoryRepository() as repository:
            archived = await repository.archive_memories(
                memory_space=state["memory_space"],
                memory_ids=list(state.get("memory_ids") or []),
                trigger_observation_id=state.get("trigger_observation_id"),
                reason=state.get("reason") or "forget_memory",
            )
            if archived:
                available_at = repository.timestamp_now() + max(int(state.get("purge_delay_seconds") or 0), 0)
                await repository.create_task(
                    memory_space=state["memory_space"],
                    task_type="purge_memory",
                    dedupe_key=(
                        f"purge_memory:{state['memory_space']}:{','.join(sorted(memory.memory_id for memory in archived))}"
                    ),
                    priority=2,
                    available_at=available_at,
                    payload={
                        "memory_space": state["memory_space"],
                        "memory_ids": [memory.memory_id for memory in archived],
                        "reason": "scheduled_after_forget",
                    },
                )
        return {"result": {"archived": len(archived), "purge_task_created": bool(archived)}}


class PurgeMemoryGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(self, *, memory_space: str, memory_ids: list[str]) -> dict[str, int]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "memory_ids": memory_ids,
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(PurgeMemoryState)
        graph.add_node("delete_archived_bundle", self._delete_archived_bundle)
        graph.set_entry_point("delete_archived_bundle")
        graph.add_edge("delete_archived_bundle", END)
        return graph.compile()

    async def _delete_archived_bundle(self, state: PurgeMemoryState) -> dict[str, object]:
        async with MemoryRepository() as repository:
            deleted = await repository.purge_memories(
                memory_space=state["memory_space"],
                memory_ids=list(state.get("memory_ids") or []),
            )
        await retrieval_index.delete_memories(
            memory_space=state["memory_space"],
            memory_ids=list(state.get("memory_ids") or []),
        )
        return {"result": deleted}


forget_memory_graph = ForgetMemoryGraph()
purge_memory_graph = PurgeMemoryGraph()
