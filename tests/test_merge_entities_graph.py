from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import insight_memory.graph.merge_entities_graph as merge_graph_module
from insight_memory.graph.merge_entities_graph import MergeEntitiesGraph


class _FakeRepository:
    entities: dict[str, SimpleNamespace] = {}
    memories: dict[str, list[SimpleNamespace]] = {}
    tasks: list[dict[str, Any]] = []
    updated_profiles: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def get_entity(self, *, memory_space: str, entity_key: str) -> SimpleNamespace | None:
        entity = self.entities.get(entity_key)
        if entity is None or entity.memory_space != memory_space:
            return None
        return entity

    async def list_memories(self, *, memory_space: str, entity_key: str, **kwargs: Any) -> list[SimpleNamespace]:
        return [memory for memory in self.memories.get(entity_key, []) if memory.memory_space == memory_space]

    async def merge_entities(
        self,
        *,
        memory_space: str,
        source_entity_key: str,
        target_entity_key: str,
        reason: str,
    ) -> None:
        for memory in self.memories.get(source_entity_key, []):
            memory.entity_key = target_entity_key
        self.memories.setdefault(target_entity_key, []).extend(self.memories.get(source_entity_key, []))
        self.memories[source_entity_key] = []
        self.entities.pop(source_entity_key, None)

    async def update_entity_profile(
        self,
        *,
        entity: SimpleNamespace,
        display_name: str,
        identity_profile: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        entity.display_name = display_name
        entity.identity_profile = dict(identity_profile)
        entity.metadata_json = dict(metadata or {})
        self.updated_profiles.append(
            {
                "entity_key": entity.entity_key,
                "identity_profile": dict(identity_profile),
                "metadata": dict(metadata or {}),
            }
        )
        return entity

    async def create_task(self, **kwargs: Any) -> SimpleNamespace:
        self.tasks.append(dict(kwargs))
        return SimpleNamespace(**kwargs)


class _FakeRetrievalIndex:
    deleted_entities: list[dict[str, Any]] = []
    refreshed_entities: list[list[str]] = []
    refreshed_memories: list[list[str]] = []

    async def delete_entities(self, **kwargs: Any) -> None:
        self.deleted_entities.append(dict(kwargs))

    async def refresh_entities(self, *, entities: list[SimpleNamespace]) -> None:
        self.refreshed_entities.append([entity.entity_key for entity in entities])

    async def refresh_memories(self, *, memories: list[SimpleNamespace], entities_by_key: dict[str, Any]) -> None:
        self.refreshed_memories.append([memory.memory_id for memory in memories])


def _entity(entity_key: str, *, entity_type: str, surface_forms: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        entity_key=entity_key,
        memory_space="workspace:orion",
        display_name=surface_forms[0],
        identity_profile={
            "schema_version": 2,
            "who": surface_forms[0],
            "entity_type": entity_type,
            "surface_forms": list(surface_forms),
            "stable_qualifiers": ["service"],
            "evidence": [f"{surface_forms[0]} evidence"],
        },
        metadata_json={"profile_state": {"profile_revision": 1}},
    )


def _memory(memory_id: str, entity_key: str) -> SimpleNamespace:
    return SimpleNamespace(memory_id=memory_id, entity_key=entity_key, memory_space="workspace:orion")


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> _FakeRetrievalIndex:
    retrieval_index = _FakeRetrievalIndex()
    retrieval_index.deleted_entities = []
    retrieval_index.refreshed_entities = []
    retrieval_index.refreshed_memories = []
    _FakeRepository.tasks = []
    _FakeRepository.updated_profiles = []
    monkeypatch.setattr(merge_graph_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(merge_graph_module, "retrieval_index", retrieval_index)
    return retrieval_index


@pytest.mark.asyncio
async def test_apply_merge_adds_source_profile_aliases_to_survivor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _entity("ent_source", entity_type="system", surface_forms=["Orion API"])
    target = _entity("ent_target", entity_type="system", surface_forms=["Orion service"])
    _FakeRepository.entities = {source.entity_key: source, target.entity_key: target}
    _FakeRepository.memories = {
        source.entity_key: [_memory("mem_source", source.entity_key)],
        target.entity_key: [_memory("mem_target", target.entity_key)],
    }
    retrieval_index = _install_fakes(monkeypatch)

    result = await MergeEntitiesGraph()._apply_merge(
        {
            "memory_space": "workspace:orion",
            "source_entity_key": source.entity_key,
            "target_entity_key": target.entity_key,
            "source": source,
            "target": target,
            "reason": "test",
            "judgment": SimpleNamespace(
                survivor_entity_key=target.entity_key,
                reason="same subject",
            ),
        }
    )

    assert result == {"result": {"merged": True}}
    assert target.identity_profile["surface_forms"] == ["Orion service", "Orion API"]
    assert target.metadata_json["profile_state"]["profile_revision"] == 2
    assert target.metadata_json["profile_history"][-1]["reason"] == "entity_merged:safe_additive_update"
    assert retrieval_index.deleted_entities[-1]["entity_keys"] == [source.entity_key]
    assert retrieval_index.refreshed_entities == [[target.entity_key]]
    assert retrieval_index.refreshed_memories == [["mem_target", "mem_source"]]


@pytest.mark.asyncio
async def test_apply_merge_keeps_survivor_profile_when_entity_type_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _entity("ent_source", entity_type="document", surface_forms=["Orion runbook"])
    target = _entity("ent_target", entity_type="system", surface_forms=["Orion service"])
    _FakeRepository.entities = {source.entity_key: source, target.entity_key: target}
    _FakeRepository.memories = {
        source.entity_key: [_memory("mem_source", source.entity_key)],
        target.entity_key: [_memory("mem_target", target.entity_key)],
    }
    _install_fakes(monkeypatch)

    await MergeEntitiesGraph()._apply_merge(
        {
            "memory_space": "workspace:orion",
            "source_entity_key": source.entity_key,
            "target_entity_key": target.entity_key,
            "source": source,
            "target": target,
            "reason": "test",
            "judgment": SimpleNamespace(
                survivor_entity_key=target.entity_key,
                reason="same subject",
            ),
        }
    )

    assert target.identity_profile["entity_type"] == "system"
    assert target.identity_profile["surface_forms"] == ["Orion service"]
    assert target.metadata_json["profile_state"]["profile_revision"] == 1
    assert target.metadata_json["profile_state"]["last_refresh_status"] == "needs_identity_review"
    assert target.metadata_json["profile_history"][-1]["reason"] == "entity_merged:entity_type_conflict"
