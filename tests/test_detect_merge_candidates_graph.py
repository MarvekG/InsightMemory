from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import insight_memory.graph.detect_merge_candidates_graph as detect_graph_module
from insight_memory.graph.detect_merge_candidates_graph import DetectMergeCandidatesGraph


class _FakeRepository:
    target: SimpleNamespace | None = None
    tasks: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def get_entity(self, *, memory_space: str, entity_key: str) -> SimpleNamespace | None:
        if self.target is None:
            return None
        if self.target.memory_space != memory_space or self.target.entity_key != entity_key:
            return None
        return self.target

    async def create_task(self, **kwargs: Any) -> SimpleNamespace:
        self.tasks.append(dict(kwargs))
        return SimpleNamespace(**kwargs)


class _FakeRetrievalIndex:
    candidates: list[SimpleNamespace] = []

    async def entity_candidates(self, **kwargs: Any) -> list[SimpleNamespace]:
        return list(self.candidates)


def _entity(entity_key: str, *, entity_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        entity_key=entity_key,
        memory_space="workspace:orion",
        identity_profile={
            "schema_version": 2,
            "who": "Orion",
            "entity_type": entity_type,
            "surface_forms": ["Orion"],
            "stable_qualifiers": ["service"],
            "evidence": ["identity evidence"],
        },
    )


@pytest.mark.asyncio
async def test_detect_merge_candidates_skips_entity_type_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _entity("ent_target", entity_type="system")
    same_type = _entity("ent_same_type", entity_type="system")
    type_conflict = _entity("ent_type_conflict", entity_type="document")
    _FakeRepository.target = target
    _FakeRepository.tasks = []
    retrieval_index = _FakeRetrievalIndex()
    retrieval_index.candidates = [
        SimpleNamespace(entity=target),
        SimpleNamespace(entity=same_type),
        SimpleNamespace(entity=type_conflict),
    ]
    monkeypatch.setattr(detect_graph_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(detect_graph_module, "retrieval_index", retrieval_index)

    result = await DetectMergeCandidatesGraph()._queue_merge_tasks(
        {
            "memory_space": "workspace:orion",
            "entity_key": target.entity_key,
            "target": target,
        }
    )

    assert result == {"result": {"queued": 1}}
    assert _FakeRepository.tasks[0]["payload"]["source_entity_key"] == same_type.entity_key
