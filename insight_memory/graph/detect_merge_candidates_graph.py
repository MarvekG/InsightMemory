from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.identity_profile import identity_profile_refresh_risk


class DetectMergeCandidatesState(TypedDict, total=False):
    memory_space: str
    entity_key: str
    entities: list[object]
    target: object
    result: dict[str, int]


class DetectMergeCandidatesGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(self, *, memory_space: str, entity_key: str) -> dict[str, int]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "entity_key": entity_key,
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(DetectMergeCandidatesState)
        graph.add_node("load_entities", self._load_entities)
        graph.add_node("skip_missing_target", self._skip_missing_target)
        graph.add_node("queue_merge_tasks", self._queue_merge_tasks)
        graph.set_entry_point("load_entities")
        graph.add_conditional_edges(
            "load_entities",
            self._after_load_entities,
            {
                "skip_missing_target": "skip_missing_target",
                "queue_merge_tasks": "queue_merge_tasks",
            },
        )
        graph.add_edge("skip_missing_target", END)
        graph.add_edge("queue_merge_tasks", END)
        return graph.compile()

    async def _load_entities(self, state: DetectMergeCandidatesState) -> dict[str, object]:
        async with MemoryRepository() as repository:
            target = await repository.get_entity(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
            )
        return {"target": target}

    @staticmethod
    def _after_load_entities(state: DetectMergeCandidatesState) -> str:
        return "queue_merge_tasks" if state.get("target") is not None else "skip_missing_target"

    async def _skip_missing_target(self, state: DetectMergeCandidatesState) -> dict[str, object]:
        return {"result": {"queued": 0}}

    async def _queue_merge_tasks(self, state: DetectMergeCandidatesState) -> dict[str, object]:
        target = state["target"]
        retrieved = await retrieval_index.entity_candidates(
            memory_space=state["memory_space"],
            draft=target.identity_profile or {},
            limit=8,
        )
        queued = 0
        async with MemoryRepository() as repository:
            for item in retrieved:
                other = item.entity
                if other.entity_key == target.entity_key:
                    continue
                risk, _reason = identity_profile_refresh_risk(
                    current_profile=dict(target.identity_profile or {}),
                    proposed_profile=dict(other.identity_profile or {}),
                )
                if risk != "safe":
                    continue
                smaller, larger = sorted([target.entity_key, other.entity_key])
                await repository.create_task(
                    memory_space=state["memory_space"],
                    task_type="merge_entities",
                    dedupe_key=f"merge:{smaller}:{larger}",
                    priority=2,
                    payload={
                        "memory_space": state["memory_space"],
                        "source_entity_key": other.entity_key,
                        "target_entity_key": target.entity_key,
                        "reason": "retrieval_candidate",
                    },
                )
                queued += 1
        return {"result": {"queued": queued}}


detect_merge_candidates_graph = DetectMergeCandidatesGraph()
