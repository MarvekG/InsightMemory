from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import insight_memory.services.ingest_service as ingest_service_module
import insight_memory.graph.ingest_graph as ingest_graph_module
import insight_memory.tasks.runtime as task_runtime_module
from insight_memory.api.schemas import IngestRequest
from insight_memory.graph.ingest_graph import IngestGraph
from insight_memory.services.ingest_service import IngestService
from insight_memory.tasks.runtime import TaskRuntime
from insight_memory.workers.runtime import MemoryWorkers
from insight_memory.workers.schemas import ExtractorOutput, IdentityProfileDraft, WriteGateOutput
from tests.utils import run_async


class _FakeIngestRepository:
    observations: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeIngestRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def create_observation(
        self,
        *,
        memory_space: str,
        content: str,
        summary: str,
        source_ref: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        observation = {
            "observation_id": f"obs_{len(self.observations) + 1}",
            "memory_space": memory_space,
            "content": content,
            "summary": summary,
            "source_ref": source_ref,
            "metadata": dict(metadata or {}),
        }
        self.observations.append(observation)
        return SimpleNamespace(observation_id=observation["observation_id"])

    async def create_task(self, **kwargs: Any) -> SimpleNamespace:
        self.tasks.append(dict(kwargs))
        return SimpleNamespace(task_id=f"task_{len(self.tasks)}")


class _FakeGateWorkers:
    def __init__(self, *, gate_status: str = "passed") -> None:
        self.gate_status = gate_status
        self.gate_calls: list[dict[str, Any]] = []
        self.extractor_calls: list[dict[str, Any]] = []

    async def run_write_gate(self, **kwargs: Any) -> SimpleNamespace:
        self.gate_calls.append(dict(kwargs))
        return SimpleNamespace(
            identity_gate_status=self.gate_status,
            identity_profile_drafts=[
                IdentityProfileDraft(draft_id="d1", who="Atlas review", surface_forms=["Atlas review"])
            ]
            if self.gate_status == "passed"
            else [],
            write_rejection_reason=None if self.gate_status == "passed" else "cannot_extract_identity_profile",
        )

    async def run_extractor(self, **kwargs: Any) -> ExtractorOutput:
        self.extractor_calls.append(dict(kwargs))
        raise AssertionError("run_extractor must not run in the synchronous ingest path")


def test_ingest_uses_write_gate_and_enqueues_context_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeIngestRepository.observations = []
    _FakeIngestRepository.tasks = []
    workers = _FakeGateWorkers(gate_status="passed")
    monkeypatch.setattr(ingest_service_module, "MemoryRepository", _FakeIngestRepository)
    monkeypatch.setattr(ingest_service_module, "MemoryWorkers", lambda: workers)

    result = run_async(
        IngestService().ingest(
            IngestRequest(
                memory_scope="workspace:atlas",
                context="Atlas review 当前主阻塞是 rollback note 缺失。",
            )
        )
    )

    assert result["status"] == "accepted"
    assert result["observation_id"] == "obs_1"
    assert len(workers.gate_calls) == 1
    assert workers.extractor_calls == []
    assert len(_FakeIngestRepository.observations) == 1
    assert len(_FakeIngestRepository.tasks) == 1
    task = _FakeIngestRepository.tasks[0]
    assert task["task_type"] == "continue_ingest"
    assert task["payload"]["memory_space"] == "workspace:atlas"
    assert task["payload"]["observation_id"] == "obs_1"
    assert task["payload"]["context"] == "Atlas review 当前主阻塞是 rollback note 缺失。"
    assert "extractor" not in task["payload"]
    assert "write_gate" not in task["payload"]


def test_ingest_write_gate_rejection_does_not_create_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeIngestRepository.observations = []
    _FakeIngestRepository.tasks = []
    workers = _FakeGateWorkers(gate_status="rejected_no_identity_profile")
    monkeypatch.setattr(ingest_service_module, "MemoryRepository", _FakeIngestRepository)
    monkeypatch.setattr(ingest_service_module, "MemoryWorkers", lambda: workers)

    result = run_async(
        IngestService().ingest(
            IngestRequest(
                memory_scope="workspace:atlas",
                context="今天只是随便聊了几句，没有稳定主体。",
            )
        )
    )

    assert result == {
        "status": "rejected",
        "observation_id": None,
        "affected_entity_keys": [],
        "affected_memory_ids": [],
        "error_code": "cannot_extract_identity_profile",
    }
    assert len(workers.gate_calls) == 1
    assert workers.extractor_calls == []
    assert _FakeIngestRepository.observations == []
    assert _FakeIngestRepository.tasks == []


def test_run_write_gate_normalizes_drafts_and_rejects_empty_surface_forms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_run(self, **kwargs: Any) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return SimpleNamespace(
            parsed=WriteGateOutput(
                identity_gate_status="passed",
                identity_profile_drafts=[
                    IdentityProfileDraft(
                        draft_id="d1",
                        who="  Atlas review  ",
                        surface_forms=["Atlas review", "Atlas review"],
                        distinguishing_context=[" review ", "review"],
                    ),
                    IdentityProfileDraft(
                        draft_id="d2",
                        who="No surface",
                        surface_forms=[],
                        distinguishing_context=[],
                    ),
                ],
            )
        )

    monkeypatch.setattr(MemoryWorkers, "_run", _fake_run)

    result = run_async(
        MemoryWorkers().run_write_gate(
            memory_space="workspace:atlas",
            context="Atlas review 当前主阻塞是 rollback note 缺失。",
            request_id="req-1",
        )
    )

    assert calls[0]["provider_worker_type"] == "write_gate"
    assert calls[0]["payload"] == {
        "memory_space": "workspace:atlas",
        "context": "Atlas review 当前主阻塞是 rollback note 缺失。",
    }
    assert result.identity_gate_status == "passed"
    assert [draft.model_dump() for draft in result.identity_profile_drafts] == [
        {
            "draft_id": "d1",
            "who": "Atlas review",
            "surface_forms": ["Atlas review"],
            "distinguishing_context": ["review"],
        }
    ]


class _FakeRuntimeWorkers:
    def __init__(self, extractor: ExtractorOutput) -> None:
        self.extractor = extractor
        self.extractor_calls: list[dict[str, Any]] = []

    async def run_extractor(self, **kwargs: Any) -> ExtractorOutput:
        self.extractor_calls.append(dict(kwargs))
        return self.extractor


class _FakeRuntimeGraph:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.continue_calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {"status": "accepted"}

    async def continue_ingest(self, **kwargs: Any) -> dict[str, Any]:
        self.continue_calls.append(dict(kwargs))
        return {"status": "accepted"}


class _FakeRuntimeRepository:
    resolved_observations: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeRuntimeRepository:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    async def mark_observation_resolved(self, **kwargs: Any) -> None:
        self.resolved_observations.append(dict(kwargs))


def test_task_runtime_continue_ingest_delegates_context_to_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _FakeRuntimeGraph()
    monkeypatch.setattr(task_runtime_module, "ingest_graph", graph)

    result = run_async(
        TaskRuntime()._continue_ingest(
            payload={
                "memory_space": "workspace:atlas",
                "request_id": "req-1",
                "observation_id": "obs-1",
                "context": "Atlas review 当前主阻塞是 rollback note 缺失。",
            }
        )
    )

    assert result == {"status": "accepted"}
    assert graph.calls == []
    assert graph.continue_calls == [
        {
            "memory_space": "workspace:atlas",
            "request_id": "req-1",
            "observation_id": "obs-1",
            "context": "Atlas review 当前主阻塞是 rollback note 缺失。",
        }
    ]


def test_ingest_graph_continue_ingest_runs_full_extractor_from_context(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = ExtractorOutput(
        identity_gate_status="passed",
        identity_profile_drafts=[
            IdentityProfileDraft(draft_id="d1", who="Atlas review", surface_forms=["Atlas review"])
        ],
        candidates=[],
    )
    workers = _FakeRuntimeWorkers(extractor=extractor)
    resolve_calls: list[dict[str, Any]] = []

    async def _fake_resolve_entities(self, state: dict[str, Any]) -> dict[str, Any]:
        resolve_calls.append(
            {
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "observation_id": state["observation_id"],
                "extractor": state["extractor"],
            }
        )
        return {"draft_to_entity": {}, "affected_entity_keys": []}

    async def _fake_resolve_candidates(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"affected_memory_ids": []}

    async def _fake_finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"result": {"status": "accepted"}}

    monkeypatch.setattr(ingest_graph_module, "MemoryWorkers", lambda: workers)
    monkeypatch.setattr(IngestGraph, "_resolve_entities", _fake_resolve_entities)
    monkeypatch.setattr(IngestGraph, "_resolve_candidates", _fake_resolve_candidates)
    monkeypatch.setattr(IngestGraph, "_finalize", _fake_finalize)

    result = run_async(
        IngestGraph().continue_ingest(
            memory_space="workspace:atlas",
            request_id="req-1",
            observation_id="obs-1",
            context="Atlas review 当前主阻塞是 rollback note 缺失。",
        )
    )

    assert result == {"status": "accepted"}
    assert workers.extractor_calls == [
        {
            "memory_space": "workspace:atlas",
            "request_id": "req-1",
            "context": "Atlas review 当前主阻塞是 rollback note 缺失。",
        }
    ]
    assert resolve_calls == [
        {
            "memory_space": "workspace:atlas",
            "request_id": "req-1",
            "observation_id": "obs-1",
            "extractor": extractor,
        }
    ]


def test_continue_ingest_marks_unresolved_when_background_extractor_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = ExtractorOutput(
        identity_gate_status="rejected_no_identity_profile",
        identity_profile_drafts=[],
        candidates=[],
        write_rejection_reason="cannot_extract_identity_profile",
    )
    workers = _FakeRuntimeWorkers(extractor=extractor)
    _FakeRuntimeRepository.resolved_observations = []
    monkeypatch.setattr(ingest_graph_module, "MemoryWorkers", lambda: workers)
    monkeypatch.setattr(ingest_graph_module, "MemoryRepository", _FakeRuntimeRepository)

    result = run_async(
        IngestGraph().continue_ingest(
            memory_space="workspace:atlas",
            request_id="req-1",
            observation_id="obs-1",
            context="今天只是随便聊了几句，没有稳定主体。",
        )
    )

    assert result == {
        "status": "rejected",
        "observation_id": "obs-1",
        "affected_entity_keys": [],
        "affected_memory_ids": [],
        "error_code": "cannot_extract_identity_profile",
    }
    assert _FakeRuntimeRepository.resolved_observations == [
        {
            "memory_space": "workspace:atlas",
            "observation_id": "obs-1",
            "status": "unresolved",
            "metadata": {
                "extractor_status": "rejected_no_identity_profile",
                "extractor_rejection_reason": "cannot_extract_identity_profile",
            },
        }
    ]
