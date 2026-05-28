from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import insight_memory.graph.refresh_entity_profile_graph as refresh_graph_module
from insight_memory.graph.refresh_entity_profile_graph import RefreshEntityProfileGraph
from insight_memory.workers.schemas import ProfileWriterOutput


class _FakeRepository:
    entity: SimpleNamespace | None = None
    memories: list[SimpleNamespace] = []
    updated_profiles: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def get_entity(self, *, memory_space: str, entity_key: str) -> SimpleNamespace | None:
        if self.entity is None:
            return None
        if self.entity.memory_space != memory_space or self.entity.entity_key != entity_key:
            return None
        return self.entity

    async def list_memories(self, **kwargs: Any) -> list[SimpleNamespace]:
        return list(self.memories)

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
                "display_name": display_name,
                "identity_profile": dict(identity_profile),
                "metadata": dict(metadata or {}),
            }
        )
        return entity


class _FakeRetrievalIndex:
    refresh_calls: list[list[str]] = []

    async def refresh_entities(self, *, entities: list[SimpleNamespace]) -> None:
        self.refresh_calls.append([entity.entity_key for entity in entities])


class _FakeWorkers:
    def __init__(self, output: ProfileWriterOutput) -> None:
        self.output = output
        self.profile_writer_calls: list[dict[str, Any]] = []

    async def run_profile_writer(self, **kwargs: Any) -> ProfileWriterOutput:
        self.profile_writer_calls.append(dict(kwargs))
        return self.output


def _entity() -> SimpleNamespace:
    return SimpleNamespace(
        entity_key="ent_1",
        memory_space="workspace:orion",
        display_name="Orion service",
        identity_profile={
            "schema_version": 2,
            "who": "Orion service",
            "entity_type": "system",
            "surface_forms": ["Orion service"],
            "stable_qualifiers": ["service"],
            "evidence": ["Original evidence."],
        },
        metadata_json={"profile_state": {"profile_revision": 1}},
    )


@pytest.mark.asyncio
async def test_refresh_entity_profile_applies_safe_additive_profile_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRepository.entity = _entity()
    _FakeRepository.memories = [SimpleNamespace(summary="Orion service 也叫 Orion API。")]
    _FakeRepository.updated_profiles = []
    retrieval_index = _FakeRetrievalIndex()
    retrieval_index.refresh_calls = []
    workers = _FakeWorkers(
        ProfileWriterOutput(
            schema_version=2,
            who="Orion service",
            entity_type="system",
            surface_forms=["Orion service", "Orion API"],
            stable_qualifiers=["service", "api service"],
            evidence=["Recent memory identifies Orion API as an alias."],
        )
    )

    monkeypatch.setattr(refresh_graph_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(refresh_graph_module, "retrieval_index", retrieval_index)

    result = await RefreshEntityProfileGraph()._write_profile(
        {
            "memory_space": "workspace:orion",
            "entity_key": "ent_1",
            "entity": _FakeRepository.entity,
            "memories": _FakeRepository.memories,
            "workers": workers,
        }
    )

    assert result["result"] == {"refreshed": True, "entity_key": "ent_1", "refresh_status": "applied"}
    assert _FakeRepository.entity.identity_profile["surface_forms"] == ["Orion service", "Orion API"]
    assert _FakeRepository.entity.identity_profile["stable_qualifiers"] == ["service", "api service"]
    assert _FakeRepository.entity.metadata_json["profile_state"]["profile_revision"] == 2
    assert _FakeRepository.entity.metadata_json["profile_state"]["last_refresh_status"] == "applied"
    assert _FakeRepository.entity.metadata_json["profile_history"][-1]["risk"] == "safe"
    assert retrieval_index.refresh_calls == [["ent_1"]]


@pytest.mark.asyncio
async def test_refresh_entity_profile_rejects_explicit_entity_type_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeRepository.entity = _entity()
    _FakeRepository.memories = [SimpleNamespace(summary="Orion service 的部署说明更新。")]
    _FakeRepository.updated_profiles = []
    retrieval_index = _FakeRetrievalIndex()
    retrieval_index.refresh_calls = []
    workers = _FakeWorkers(
        ProfileWriterOutput(
            schema_version=2,
            who="Orion service",
            entity_type="document",
            surface_forms=["Orion service"],
            stable_qualifiers=["runbook"],
            evidence=["The proposal looks like a document."],
        )
    )

    monkeypatch.setattr(refresh_graph_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(refresh_graph_module, "retrieval_index", retrieval_index)

    result = await RefreshEntityProfileGraph()._write_profile(
        {
            "memory_space": "workspace:orion",
            "entity_key": "ent_1",
            "entity": _FakeRepository.entity,
            "memories": _FakeRepository.memories,
            "workers": workers,
        }
    )

    assert result["result"] == {"refreshed": False, "entity_key": "ent_1", "refresh_status": "needs_identity_review"}
    assert _FakeRepository.entity.identity_profile["entity_type"] == "system"
    assert _FakeRepository.entity.metadata_json["profile_state"]["profile_revision"] == 1
    assert _FakeRepository.entity.metadata_json["profile_state"]["last_refresh_status"] == "needs_identity_review"
    assert _FakeRepository.entity.metadata_json["profile_history"][-1]["risk"] == "needs_identity_review"
    assert retrieval_index.refresh_calls == []
