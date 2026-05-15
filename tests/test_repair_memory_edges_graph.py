from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from insight_memory.graph import repair_memory_edges_graph as graph_module
from insight_memory.graph.repair_memory_edges_graph import RepairMemoryEdgesGraph


@pytest.mark.asyncio
async def test_cross_entity_judge_marks_task_stale_when_frontier_entity_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontier = _memory(memory_id="mem_frontier", entity_key="ent_merged")
    candidate = _memory(memory_id="mem_candidate", entity_key="ent_alive")

    monkeypatch.setattr(
        graph_module,
        "MemoryRepository",
        lambda: _Repository(entities=[_entity(entity_key="ent_alive")]),
    )

    result = await RepairMemoryEdgesGraph()._judge_cross_entity_graph(
        {
            "memory_space": "test_space",
            "entity_key": "ent_merged",
            "frontier_memories": [frontier],
            "cross_candidates": [candidate],
            "workers": _ExplodingWorkers(),
        }
    )

    assert result == {"stale_entity": True, "cross_judged": None, "cross_candidates": []}


def test_repair_routes_stale_entity_to_normal_task_exit() -> None:
    graph = RepairMemoryEdgesGraph()

    assert graph._after_retrieve_cross_entity_candidates({"stale_entity": True}) == "finish_stale_entity"
    assert graph._after_judge_cross_entity_graph({"stale_entity": True}) == "finish_stale_entity"


@pytest.mark.asyncio
async def test_finish_stale_entity_marks_task_complete_without_cross_edges() -> None:
    result = await RepairMemoryEdgesGraph()._finish_stale_entity(
        {
            "memory_space": "test_space",
            "entity_key": "ent_deleted",
            "local_created_edges": 2,
            "deleted_relation_edges": 3,
        }
    )

    assert result == {
        "result": {
            "created_edges": 2,
            "deleted_edges": 3,
            "cross_entity_created_edges": 0,
        }
    }


@pytest.mark.asyncio
async def test_cross_entity_judge_drops_stale_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    frontier = _memory(memory_id="mem_frontier", entity_key="ent_anchor")
    live_candidate = _memory(memory_id="mem_live_candidate", entity_key="ent_live")
    stale_candidate = _memory(memory_id="mem_stale_candidate", entity_key="ent_deleted")
    workers = _CapturingWorkers()

    monkeypatch.setattr(
        graph_module,
        "MemoryRepository",
        lambda: _Repository(
            entities=[
                _entity(entity_key="ent_anchor"),
                _entity(entity_key="ent_live"),
            ]
        ),
    )

    result = await RepairMemoryEdgesGraph()._judge_cross_entity_graph(
        {
            "memory_space": "test_space",
            "entity_key": "ent_anchor",
            "frontier_memories": [frontier],
            "cross_candidates": [live_candidate, stale_candidate],
            "workers": workers,
        }
    )

    assert result["cross_judged"].relations == []
    assert result["cross_candidates"] == [live_candidate]
    assert [item["memory_id"] for item in workers.payload["candidate_memories"]] == ["mem_live_candidate"]


class _Repository:
    def __init__(self, *, entities: list[Any]) -> None:
        self._entities = entities

    async def __aenter__(self) -> _Repository:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        return None

    async def get_entities_by_keys(self, *, memory_space: str, entity_keys: set[str]) -> list[Any]:
        return [entity for entity in self._entities if entity.entity_key in entity_keys]


class _ExplodingWorkers:
    async def run_edge_judge(self, **kwargs: Any) -> Any:
        raise AssertionError("edge judge should not run")


class _CapturingWorkers:
    def __init__(self) -> None:
        self.payload: dict[str, Any] = {}

    async def run_edge_judge(self, **kwargs: Any) -> Any:
        self.payload = dict(kwargs["payload"])
        return SimpleNamespace(relations=[])


def _memory(*, memory_id: str, entity_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        memory_id=memory_id,
        entity_key=entity_key,
        title=memory_id,
        summary=f"{memory_id} summary",
        content=f"{memory_id} content",
        status="active",
        metadata_json={},
    )


def _entity(*, entity_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        entity_key=entity_key,
        identity_profile={
            "who": entity_key,
            "surface_forms": [entity_key],
            "distinguishing_context": ["test"],
        },
    )
