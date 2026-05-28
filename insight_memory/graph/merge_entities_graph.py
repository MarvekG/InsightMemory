from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.identity_profile import (
    identity_profile_refresh_risk,
    next_profile_metadata,
)
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.workers.runtime import MemoryWorkers


class MergeEntitiesState(TypedDict, total=False):
    memory_space: str
    source_entity_key: str
    target_entity_key: str
    reason: str
    source: Any
    target: Any
    workers: MemoryWorkers
    judgment: Any
    result: dict[str, Any]


class MergeEntitiesGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(
        self,
        *,
        memory_space: str,
        source_entity_key: str,
        target_entity_key: str,
        reason: str,
    ) -> dict[str, Any]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "source_entity_key": source_entity_key,
                "target_entity_key": target_entity_key,
                "reason": reason,
                "workers": MemoryWorkers(),
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(MergeEntitiesState)
        graph.add_node("load_merge_context", self._load_merge_context)
        graph.add_node("skip_missing_entities", self._skip_missing_entities)
        graph.add_node("judge_merge", self._judge_merge)
        graph.add_node("apply_merge", self._apply_merge)
        graph.set_entry_point("load_merge_context")
        graph.add_conditional_edges(
            "load_merge_context",
            self._after_load_merge_context,
            {
                "skip_missing_entities": "skip_missing_entities",
                "judge_merge": "judge_merge",
            },
        )
        graph.add_edge("skip_missing_entities", END)
        graph.add_conditional_edges(
            "judge_merge",
            self._after_judge_merge,
            {
                "skip_missing_entities": "skip_missing_entities",
                "apply_merge": "apply_merge",
            },
        )
        graph.add_edge("apply_merge", END)
        return graph.compile()

    async def _load_merge_context(self, state: MergeEntitiesState) -> dict[str, Any]:
        async with MemoryRepository() as repository:
            source = await repository.get_entity(memory_space=state["memory_space"], entity_key=state["source_entity_key"])
            target = await repository.get_entity(memory_space=state["memory_space"], entity_key=state["target_entity_key"])
        return {"source": source, "target": target}

    @staticmethod
    def _after_load_merge_context(state: MergeEntitiesState) -> str:
        if state.get("source") is None or state.get("target") is None:
            return "skip_missing_entities"
        return "judge_merge"

    async def _skip_missing_entities(self, state: MergeEntitiesState) -> dict[str, Any]:
        return {"result": {"merged": False}}

    async def _judge_merge(self, state: MergeEntitiesState) -> dict[str, Any]:
        source = state["source"]
        target = state["target"]
        workers = state["workers"]
        async with MemoryRepository() as repository:
            source_summaries = [
                memory.summary
                for memory in await repository.list_memories(
                    memory_space=state["memory_space"],
                    entity_key=source.entity_key,
                    statuses=("active",),
                    limit=5,
                )
            ]
            target_summaries = [
                memory.summary
                for memory in await repository.list_memories(
                    memory_space=state["memory_space"],
                    entity_key=target.entity_key,
                    statuses=("active",),
                    limit=5,
                )
            ]
        judgment = await workers.run_merge_judge(
            memory_space=state["memory_space"],
            request_id=get_or_create_request_id(),
            payload={
                "source_entity": {
                    "entity_key": source.entity_key,
                    "display_name": source.display_name,
                    "identity_profile": source.identity_profile,
                    "active_memory_summaries": source_summaries,
                },
                "target_entity": {
                    "entity_key": target.entity_key,
                    "display_name": target.display_name,
                    "identity_profile": target.identity_profile,
                    "active_memory_summaries": target_summaries,
                },
            },
        )
        return {"judgment": judgment}

    @staticmethod
    def _after_judge_merge(state: MergeEntitiesState) -> str:
        judgment = state["judgment"]
        return "apply_merge" if judgment.decision == "merge" else "skip_missing_entities"

    async def _apply_merge(self, state: MergeEntitiesState) -> dict[str, Any]:
        judgment = state["judgment"]
        request_id = get_or_create_request_id()
        survivor_entity_key = judgment.survivor_entity_key or state["target_entity_key"]
        merged_entity_key = (
            state["source_entity_key"]
            if survivor_entity_key == state["target_entity_key"]
            else state["target_entity_key"]
        )
        source = state["source"]
        target = state["target"]
        merged_entity = source if merged_entity_key == source.entity_key else target
        async with MemoryRepository() as repository:
            await repository.merge_entities(
                memory_space=state["memory_space"],
                source_entity_key=merged_entity_key,
                target_entity_key=survivor_entity_key,
                reason=judgment.reason or state["reason"],
            )
            survivor = await repository.get_entity(memory_space=state["memory_space"], entity_key=survivor_entity_key)
            survivor_memories = (
                await repository.list_memories(
                    memory_space=state["memory_space"],
                    entity_key=survivor_entity_key,
                    limit=500,
                )
                if survivor is not None
                else []
            )
            if survivor is not None:
                survivor_profile = dict(survivor.identity_profile or {})
                proposed_profile = (
                    judgment.merged_identity_profile.model_dump()
                    if judgment.merged_identity_profile is not None
                    else {}
                )
                if proposed_profile:
                    risk, risk_reason = identity_profile_refresh_risk(
                        current_profile=survivor_profile,
                        proposed_profile=proposed_profile,
                    )
                else:
                    risk, risk_reason = "needs_identity_review", "missing_merged_identity_profile"
                applied_profile = proposed_profile if risk == "safe" else survivor_profile
                metadata = next_profile_metadata(
                    current_metadata=dict(survivor.metadata_json or {}),
                    previous_profile=survivor_profile,
                    proposed_profile=proposed_profile,
                    applied_profile=applied_profile,
                    risk=risk,
                    reason=f"entity_merged:{risk_reason}",
                    request_id=request_id,
                    applied=risk == "safe",
                )
                await repository.update_entity_profile(
                    entity=survivor,
                    display_name=str(applied_profile.get("who") or survivor.display_name),
                    identity_profile=applied_profile,
                    metadata=metadata,
                )
                await repository.create_task(
                    memory_space=state["memory_space"],
                    task_type="repair_memory_edges",
                    dedupe_key=f"repair_memory_edges:{survivor_entity_key}",
                    priority=11,
                    payload={
                        "memory_space": state["memory_space"],
                        "entity_key": survivor_entity_key,
                        "reason": "entity_merged",
                    },
                    dedupe_statuses=("pending",),
                )
        await retrieval_index.delete_entities(memory_space=state["memory_space"], entity_keys=[merged_entity_key])
        if survivor is not None:
            await retrieval_index.refresh_entities(entities=[survivor])
            await retrieval_index.refresh_memories(
                memories=survivor_memories,
                entities_by_key={survivor.entity_key: survivor},
            )
        return {"result": {"merged": True}}


merge_entities_graph = MergeEntitiesGraph()
