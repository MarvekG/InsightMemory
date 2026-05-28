from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

import insight_memory.graph.ingest_graph as ingest_graph_module
from insight_memory.graph.ingest_graph import IngestGraph
from insight_memory.workers.schemas import CandidateMemory, ExtractorOutput, IdentityProfileDraft, LinkerOutput


@dataclass(slots=True)
class _Entity:
    entity_key: str
    memory_space: str
    display_name: str
    identity_profile: dict[str, Any]
    updated_at: float = 1.0


class _FakeRetrievalIndex:
    def __init__(self, *, indexed_entities: list[_Entity] | None = None) -> None:
        self.indexed_entities = list(indexed_entities or [])
        self.entity_candidate_calls: list[dict[str, Any]] = []
        self.refresh_calls: list[list[str]] = []

    async def entity_candidates(self, *, memory_space: str, draft: dict[str, Any], limit: int = 10) -> list[Any]:
        self.entity_candidate_calls.append(
            {
                "memory_space": memory_space,
                "draft": draft,
                "indexed_entity_keys": [entity.entity_key for entity in self.indexed_entities],
                "limit": limit,
            }
        )
        return [
            SimpleNamespace(entity=entity, score=0.9)
            for entity in self.indexed_entities
            if entity.memory_space == memory_space
        ]

    async def refresh_entities(self, *, entities: list[_Entity]) -> None:
        self.refresh_calls.append([entity.entity_key for entity in entities])
        self.indexed_entities.extend(entities)


class _FakeWorkers:
    def __init__(self, *, link_result: LinkerOutput | None = None) -> None:
        self.link_result = link_result
        self.link_calls: list[dict[str, Any]] = []

    async def run_linker(self, **kwargs: Any) -> LinkerOutput:
        self.link_calls.append(kwargs)
        if self.link_result is None:
            raise AssertionError("linker should not run")
        return self.link_result


class _FakeRepository:
    entities_by_key: dict[str, _Entity] = {}
    created_entities: list[_Entity] = []

    async def __aenter__(self) -> _FakeRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def create_entity(
        self,
        *,
        memory_space: str,
        display_name: str,
        identity_profile: dict[str, Any],
        metadata: dict[str, Any],
    ) -> _Entity:
        entity = _Entity(
            entity_key=f"ent_{len(self.created_entities) + 1}",
            memory_space=memory_space,
            display_name=display_name,
            identity_profile=identity_profile,
        )
        self.created_entities.append(entity)
        self.entities_by_key[entity.entity_key] = entity
        return entity

    async def get_entity(self, *, memory_space: str, entity_key: str) -> _Entity | None:
        entity = self.entities_by_key.get(entity_key)
        if entity is not None and entity.memory_space == memory_space:
            return entity
        return None

    async def list_memories(
        self,
        *,
        memory_space: str,
        entity_key: str,
        statuses: tuple[str, ...],
        limit: int,
    ) -> list[Any]:
        return []


def _extractor(*drafts: IdentityProfileDraft) -> ExtractorOutput:
    return ExtractorOutput(
        identity_gate_status="passed",
        identity_profile_drafts=list(drafts),
        candidates=[
            CandidateMemory(
                candidate_id=f"c{index}",
                owner_draft_id=draft.draft_id,
                title=f"title {index}",
                summary=f"summary {index}",
                content=f"content {index}",
            )
            for index, draft in enumerate(drafts, start=1)
        ],
    )


def _profile(
    *,
    draft_id: str,
    who: str,
    entity_type: str,
    stable_qualifiers: list[str],
) -> IdentityProfileDraft:
    return IdentityProfileDraft(
        schema_version=2,
        draft_id=draft_id,
        who=who,
        entity_type=entity_type,
        surface_forms=[who],
        stable_qualifiers=stable_qualifiers,
        evidence=[f"The input names {who}."],
    )


async def _resolve_entities(
    *,
    monkeypatch: pytest.MonkeyPatch,
    extractor: ExtractorOutput,
    retrieval_index: _FakeRetrievalIndex,
    workers: _FakeWorkers,
) -> dict[str, Any]:
    _FakeRepository.entities_by_key = {
        entity.entity_key: entity
        for entity in retrieval_index.indexed_entities
    }
    _FakeRepository.created_entities = []
    monkeypatch.setattr(ingest_graph_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(ingest_graph_module, "retrieval_index", retrieval_index)
    return await IngestGraph()._resolve_entities(
        {
            "memory_space": "space",
            "request_id": "request",
            "observation_id": "obs",
            "workers": workers,
            "extractor": extractor,
            "draft_to_entity": {},
            "affected_entity_keys": [],
        }
    )


@pytest.mark.asyncio
async def test_resolve_entities_delays_new_entity_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    """New entities from the same observation must not become linker candidates."""

    retrieval_index = _FakeRetrievalIndex()
    workers = _FakeWorkers()

    result = await _resolve_entities(
        monkeypatch=monkeypatch,
        retrieval_index=retrieval_index,
        workers=workers,
        extractor=_extractor(
            _profile(draft_id="d1", who="Alpha service", entity_type="system", stable_qualifiers=["service"]),
            _profile(draft_id="d2", who="Beta checklist", entity_type="document", stable_qualifiers=["checklist"]),
            _profile(draft_id="d3", who="Gamma review", entity_type="event", stable_qualifiers=["review"]),
        ),
    )

    assert workers.link_calls == []
    assert result["draft_to_entity"] == {"d1": "ent_1", "d2": "ent_2", "d3": "ent_3"}
    assert retrieval_index.refresh_calls == [["ent_1", "ent_2", "ent_3"]]
    assert [call["indexed_entity_keys"] for call in retrieval_index.entity_candidate_calls] == [[], [], []]


@pytest.mark.asyncio
async def test_resolve_entities_reuses_exact_local_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact duplicate identity drafts in one observation reuse the same provisional entity."""

    retrieval_index = _FakeRetrievalIndex()
    workers = _FakeWorkers()

    result = await _resolve_entities(
        monkeypatch=monkeypatch,
        retrieval_index=retrieval_index,
        workers=workers,
        extractor=_extractor(
            _profile(draft_id="d1", who="Alpha service", entity_type="system", stable_qualifiers=["service"]),
            _profile(draft_id="d2", who="Alpha service", entity_type="system", stable_qualifiers=["service"]),
        ),
    )

    assert workers.link_calls == []
    assert result["draft_to_entity"] == {"d1": "ent_1", "d2": "ent_1"}
    assert retrieval_index.refresh_calls == [["ent_1"]]
    assert len(retrieval_index.entity_candidate_calls) == 1


@pytest.mark.asyncio
async def test_resolve_entities_still_links_against_historical_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical indexed entities remain visible and still go through linker."""

    historical = _Entity(
        entity_key="ent_old",
        memory_space="space",
        display_name="Alpha service",
        identity_profile={
            "schema_version": 2,
            "who": "Alpha service",
            "entity_type": "system",
            "surface_forms": ["Alpha service"],
            "stable_qualifiers": ["service"],
            "evidence": ["The input names Alpha service."],
        },
    )
    retrieval_index = _FakeRetrievalIndex(indexed_entities=[historical])
    workers = _FakeWorkers(
        link_result=LinkerOutput(
            decision="link_existing",
            selected_entity_key="ent_old",
            confidence=0.9,
            reason="historical match",
        )
    )

    result = await _resolve_entities(
        monkeypatch=monkeypatch,
        retrieval_index=retrieval_index,
        workers=workers,
        extractor=_extractor(
            _profile(draft_id="d1", who="Alpha service", entity_type="system", stable_qualifiers=["service"]),
        ),
    )

    assert len(workers.link_calls) == 1
    assert result["draft_to_entity"] == {"d1": "ent_old"}
    assert retrieval_index.refresh_calls == []
    assert _FakeRepository.created_entities == []
