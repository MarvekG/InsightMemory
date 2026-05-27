from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from insight_memory.api import routes as routes_module
from insight_memory.graph.recall_graph import RecallGraph
from insight_memory.main import app
from insight_memory.services.recall_service import recall_service
from tests.utils import run_async


def test_recall_returns_not_ready_while_continue_ingest_is_pending(monkeypatch) -> None:
    audit_calls: list[dict] = []

    async def _fake_has_pending_continuation(*, memory_space: str) -> bool:
        return memory_space == "workspace:apollo_not_ready"

    async def _fake_write_not_ready_audit(**kwargs) -> None:
        audit_calls.append(dict(kwargs))

    monkeypatch.setattr(recall_service, "_has_pending_continuation", _fake_has_pending_continuation)
    monkeypatch.setattr(recall_service, "_write_not_ready_audit", _fake_write_not_ready_audit)
    client = TestClient(app)

    response = client.post(
        "/recall",
        json={
            "memory_scope": "workspace:apollo_not_ready",
            "query": "Apollo API 当前主阻塞是什么？",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    item = payload["results"][0]
    assert item["status"] == "not_ready"
    assert item["answer"] == ""
    assert item["error_code"] == "memory_scope_not_ready"
    assert item["uncertainties"] == ["continue_ingest_pending"]
    assert set(item) == {"status", "answer", "citations", "uncertainties", "error_code"}
    assert item["citations"] == []
    assert len(audit_calls) == 1
    assert audit_calls[0]["memory_space"] == "workspace:apollo_not_ready"
    assert audit_calls[0]["query"] == "Apollo API 当前主阻塞是什么？"
    assert audit_calls[0]["result"]["results"][0]["status"] == "not_ready"


def test_build_audit_payload_keeps_single_draft_intact_and_multi_draft_unmerged() -> None:
    single_draft = {
        "query_identity_profile": {"who": "Atlas 发布项目"},
        "resolved_entity_key": "ent_project",
        "used_edges": [{"edge_type": "derived_from", "from_id": "mem_1", "to_id": "obs_1"}],
        "resolution_trace": {"linker_decision": {"decision": "link_existing"}},
        "result": {
            "status": "ok",
            "answer": "当前主阻塞是数据库迁移失败。",
            "citations": [
                {
                    "memory_id": "mem_1",
                    "observation_id": "obs_1",
                    "summary": "部署日志",
                    "excerpt": "数据库迁移失败",
                    "source_memory_ids": ["mem_1"],
                }
            ],
            "uncertainties": [],
            "error_code": None,
        },
    }
    single = RecallGraph._build_audit_payload([single_draft])

    assert single["resolved_entity_key"] == "ent_project"
    assert single["used_edges"] == single_draft["used_edges"]
    assert single["citations"] == single_draft["result"]["citations"]
    assert single["result"]["status"] == "ok"
    assert single["result"]["answer"] == "当前主阻塞是数据库迁移失败。"

    multi = RecallGraph._build_audit_payload(
        [
            single_draft,
            {
                "query_identity_profile": {"who": "Atlas 运行手册"},
                "resolved_entity_key": None,
                "used_edges": [{"edge_type": "derived_from", "from_id": "mem_2", "to_id": "obs_2"}],
                "resolution_trace": {"draft_error": "boom"},
                "result": {
                    "status": "rejected",
                    "answer": "",
                    "citations": [],
                    "uncertainties": ["draft_recall_failed"],
                    "error_code": "recall_draft_failed",
                },
            },
        ]
    )

    assert multi["resolved_entity_key"] is None
    assert multi["used_edges"] == []
    assert multi["citations"] == []
    assert multi["result"]["status"] == "partial"
    assert multi["result"]["answer"] == ""


def test_build_response_returns_each_draft_result_without_merging() -> None:
    response = RecallGraph._build_response(
        [
            {
                "result": {
                    "status": "ok",
                    "answer": "Atlas 发布项目 当前主阻塞是数据库迁移失败。",
                    "citations": [{"memory_id": "mem_project"}],
                    "uncertainties": [],
                    "error_code": None,
                }
            },
            {
                "result": {
                    "status": "ok",
                    "answer": "Atlas 文档 当前缺回滚说明。",
                    "citations": [{"memory_id": "mem_doc"}],
                    "uncertainties": [],
                    "error_code": None,
                }
            },
        ]
    )

    assert response == {
        "results": [
            {
                "status": "ok",
                "answer": "Atlas 发布项目 当前主阻塞是数据库迁移失败。",
                "citations": [{"memory_id": "mem_project"}],
                "uncertainties": [],
                "error_code": None,
            },
            {
                "status": "ok",
                "answer": "Atlas 文档 当前缺回滚说明。",
                "citations": [{"memory_id": "mem_doc"}],
                "uncertainties": [],
                "error_code": None,
            },
        ]
    }


def test_build_audit_payload_for_multi_draft_preserves_shared_rejection_code() -> None:
    payload = RecallGraph._build_audit_payload(
        [
            {
                "result": {
                    "status": "rejected",
                    "answer": "",
                    "citations": [],
                    "uncertainties": [],
                    "error_code": "cannot_resolve_query_identity",
                }
            },
            {
                "result": {
                    "status": "rejected",
                    "answer": "",
                    "citations": [],
                    "uncertainties": [],
                    "error_code": "cannot_resolve_query_identity",
                }
            },
        ]
    )

    assert payload["result"] == {
        "status": "rejected",
        "answer": "",
        "uncertainties": [],
        "error_code": "cannot_resolve_query_identity",
        "citations": [],
    }
    assert payload["resolved_entity_key"] is None
    assert payload["used_edges"] == []
    assert payload["citations"] == []


def test_build_audit_metadata_summarizes_recall_for_system_improvement() -> None:
    draft_runs = [
        {
            "result": {
                "status": "ok",
                "answer": "历史上证据冲突时，PM 维持仓位等待验证。",
                "citations": [
                    {
                        "memory_id": "mem_1",
                        "observation_id": "obs_1",
                        "summary": "PM 复盘",
                        "excerpt": "等待验证",
                        "source_memory_ids": ["mem_1", "mem_2"],
                    }
                ],
                "uncertainties": ["contradicting_memory:mem_3"],
                "error_code": None,
            },
            "used_edges": [
                {"edge_type": "supports", "from_id": "mem_2", "to_id": "mem_1"},
                {"edge_type": "contradicts", "from_id": "mem_3", "to_id": "mem_1"},
            ],
        },
        {
            "result": {
                "status": "rejected",
                "answer": "",
                "citations": [],
                "uncertainties": [],
                "error_code": "cannot_resolve_query_identity",
            },
            "used_edges": [],
        },
    ]

    query = "当前目标股票 PM决策经验：历史上盈利恶化但运价反弹时如何处理仓位？"
    answer = draft_runs[0]["result"]["answer"]
    metadata = RecallGraph._build_audit_metadata(
        query=query,
        draft_runs=draft_runs,
        result=draft_runs[0]["result"],
        used_edges=draft_runs[0]["used_edges"],
        citations=draft_runs[0]["result"]["citations"],
        latency_ms=37,
    )

    assert metadata["audit_schema_version"] == 1
    assert metadata["query_length"] == len(query)
    assert metadata["query_preview"] == query
    assert metadata["result_count"] == 2
    assert metadata["ok_result_count"] == 1
    assert metadata["rejected_result_count"] == 1
    assert metadata["latency_ms"] == 37
    assert metadata["answer_length"] == len(answer)
    assert metadata["citation_count"] == 1
    assert metadata["uncertainty_count"] == 1
    assert metadata["used_edge_count"] == 2
    assert metadata["used_edge_types"] == ["supports", "contradicts"]
    assert metadata["key_memory_ids"] == ["mem_1", "mem_2"]
    assert metadata["supporting_observation_ids"] == ["obs_1"]


def test_build_audit_metadata_includes_stage_and_draft_timings() -> None:
    metadata = RecallGraph._build_audit_metadata(
        query="Orion service 当前负责人是谁？",
        draft_runs=[
            {
                "result": {
                    "status": "ok",
                    "answer": "Orion service 当前负责人是 Mina。",
                    "citations": [],
                    "uncertainties": [],
                    "error_code": None,
                }
            }
        ],
        result={
            "status": "ok",
            "answer": "Orion service 当前负责人是 Mina。",
            "citations": [],
            "uncertainties": [],
            "error_code": None,
        },
        used_edges=[],
        citations=[],
        latency_ms=123,
        stage_timings_ms={"plan_query": 10, "run_draft_subgraphs": 90},
        draft_timings_ms=[
            {
                "draft_index": 0,
                "resolve_entity": 20,
                "memory_candidates": 5,
                "answer_composer": 40,
                "total": 70,
            }
        ],
    )

    assert metadata["stage_timings_ms"] == {"plan_query": 10, "run_draft_subgraphs": 90}
    assert metadata["draft_timings_ms"] == [
        {
            "draft_index": 0,
            "resolve_entity": 20,
            "memory_candidates": 5,
            "answer_composer": 40,
            "total": 70,
        }
    ]


def test_recall_audit_preview_route_exposes_improvement_metadata(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_preview(**kwargs):
        calls.append(dict(kwargs))
        return {
            "status": "success",
            "total": 1,
            "limit": 20,
            "offset": 0,
            "items": [
                {
                    "audit_id": "audit_1",
                    "memory_scope": "workspace:apollo",
                    "request_id": "req_1",
                    "query": "Apollo API 当前主阻塞是什么？",
                    "query_preview": "Apollo API 当前主阻塞是什么？",
                    "status": "ok",
                    "resolved_entity_key": "ent_1",
                    "error_code": None,
                    "answer_preview": "主阻塞是数据库迁移失败。",
                    "answer_length": 12,
                    "uncertainties": [],
                    "used_edge_count": 1,
                    "citation_count": 1,
                    "key_memory_ids": ["mem_1"],
                    "supporting_observation_ids": ["obs_1"],
                    "metadata": {"result_count": 1},
                    "created_at": 10.0,
                }
            ],
        }

    monkeypatch.setattr(routes_module.recall_audit_preview_service, "preview", fake_preview)
    client = TestClient(app)

    response = client.get(
        "/memory/admin/recall-audits/preview",
        params={
            "memory_scope": "workspace:apollo",
            "status": "ok",
            "limit": 20,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["items"][0]["key_memory_ids"] == ["mem_1"]
    assert payload["items"][0]["citation_count"] == 1
    assert calls == [
        {
            "memory_scope": "workspace:apollo",
            "memory_scope_prefix": None,
            "memory_scope_contains": None,
            "status": "ok",
            "error_code": None,
            "limit": 20,
            "offset": 0,
        }
    ]


def test_run_draft_subgraphs_uses_per_draft_query_text() -> None:
    graph = RecallGraph()
    calls: list[dict] = []

    class _StubDraftGraph:
        async def ainvoke(self, state):
            calls.append(dict(state))
            return {
                "entity_key": None,
                "stage_timings_ms": {"resolve_entity": 3, "answer_composer": 7, "total": 11},
                "used_edges": [],
                "resolution_trace": {},
                "result": {
                    "status": "ok",
                    "answer": state["query"],
                    "citations": [],
                    "uncertainties": [],
                    "error_code": None,
                },
            }

    graph._draft_graph = _StubDraftGraph()

    state = {
        "memory_space": "workspace:test",
        "query": "Atlas 发布项目 当前主阻塞是什么？Atlas 文档 当前缺什么？",
        "request_id": "req_test",
        "workers": object(),
        "planner": SimpleNamespace(query_identity_profile_drafts=[object(), object()], query_rewrites=[]),
        "draft_payloads": [
            {
                "who": "Atlas 发布项目",
                "surface_forms": ["Atlas 发布项目", "Atlas"],
                "distinguishing_context": ["发布项目"],
                "query_text": "Atlas 发布项目 当前主阻塞是什么？",
            },
            {
                "who": "Atlas 文档",
                "surface_forms": ["Atlas 文档", "Atlas"],
                "distinguishing_context": ["文档"],
                "query_text": "Atlas 文档 当前缺什么？",
            },
        ],
    }

    result = run_async(graph._run_draft_subgraphs(state))

    assert [item["query"] for item in calls] == [
        "Atlas 发布项目 当前主阻塞是什么？",
        "Atlas 文档 当前缺什么？",
    ]
    assert [item["original_query"] for item in calls] == [
        "Atlas 发布项目 当前主阻塞是什么？Atlas 文档 当前缺什么？",
        "Atlas 发布项目 当前主阻塞是什么？Atlas 文档 当前缺什么？",
    ]
    assert [item["result"]["answer"] for item in result["draft_runs"]] == [
        "Atlas 发布项目 当前主阻塞是什么？",
        "Atlas 文档 当前缺什么？",
    ]
    assert [item["stage_timings_ms"] for item in result["draft_runs"]] == [
        {"resolve_entity": 3, "answer_composer": 7, "total": 11},
        {"resolve_entity": 3, "answer_composer": 7, "total": 11},
    ]
