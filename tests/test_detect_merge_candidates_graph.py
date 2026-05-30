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


def _entity(entity_key: str, *, who: str = "Orion", surfaces: list[str] | None = None) -> SimpleNamespace:
    surface_forms = surfaces or [who]
    return SimpleNamespace(
        entity_key=entity_key,
        memory_space="workspace:orion",
        identity_profile={
            "schema_version": 2,
            "who": who,
            "surface_forms": surface_forms,
            "stable_qualifiers": ["service"],
            "definition": "Named service.",
        },
    )


@pytest.mark.asyncio
async def test_detect_merge_candidates_skips_identity_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _entity("ent_target")
    same_subject = _entity("ent_same_subject")
    risky_subject = _entity("ent_risky_subject", who="Orion runbook", surfaces=["Orion runbook"])
    _FakeRepository.target = target
    _FakeRepository.tasks = []
    retrieval_index = _FakeRetrievalIndex()
    retrieval_index.candidates = [
        SimpleNamespace(entity=target),
        SimpleNamespace(entity=same_subject),
        SimpleNamespace(entity=risky_subject),
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
    assert _FakeRepository.tasks[0]["payload"]["source_entity_key"] == same_subject.entity_key
