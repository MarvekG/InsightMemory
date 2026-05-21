from __future__ import annotations

import asyncio
from time import perf_counter
from types import SimpleNamespace
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.config import settings
from insight_memory.graph.repair_memory_edges_graph import (
    _memory_payloads_with_identities,
    _normalize_relation_edges,
    _observation_payload,
    _sparsify_cross_entity_related_edges,
)
from insight_memory.index.retrieval_index import project_identity_profile, project_memory, retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.text import dedupe_preserve_order
from insight_memory.workers.runtime import MemoryWorkers


logger = get_logger(__name__)


class MainRecallState(TypedDict, total=False):
    memory_space: str
    query: str
    request_id: str
    started_at: float
    workers: MemoryWorkers
    planner: Any
    draft_payloads: list[dict[str, Any]]
    draft_runs: list[dict[str, Any]]
    resolution_trace: dict[str, Any]


class DraftRecallState(TypedDict, total=False):
    memory_space: str
    query: str
    original_query: str
    request_id: str
    workers: MemoryWorkers
    planner: Any
    draft_payload: dict[str, Any]
    scored_candidates: list[Any]
    linker: Any
    entity_key: str
    seed_memories: list[Any]
    expanded_memories: list[Any]
    evidence_observation_ids: list[str]
    graph_uncertainties: list[str]
    used_edges: list[dict[str, Any]]
    observations: list[Any]
    citations: list[dict[str, Any]]
    composer: Any
    id_ref_maps: dict[str, dict[str, str]]
    result: dict[str, Any]
    resolution_trace: dict[str, Any]


def _effective_time_intent(planner: Any) -> str:
    query_focus = getattr(planner, "query_focus", None)
    time_intent = str(getattr(query_focus, "time_intent", "") or "").strip().lower()
    if time_intent in {"current", "latest", "history", "unspecified"}:
        return time_intent
    if bool(getattr(query_focus, "include_history", False)):
        return "history"
    return "unspecified"


def _memory_evidence_role(*, memory_id: str, seed_ids: set[str], relation_types: list[str]) -> str:
    if memory_id in seed_ids:
        return "seed"
    relation_type_set = set(relation_types)
    if "contradicts" in relation_type_set:
        return "conflicting"
    if "updates" in relation_type_set:
        return "historical_or_updated"
    if "supports" in relation_type_set:
        return "supporting"
    if "related_to" in relation_type_set:
        return "background_only"
    return "expanded"


class RecallGraph:
    def __init__(self) -> None:
        self._draft_graph = self._build_draft_graph()
        self._graph = self._build_main_graph()

    async def run(self, *, memory_space: str, query: str, request_id: str) -> dict[str, Any]:
        workers = MemoryWorkers()
        final_state = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "query": query,
                "request_id": request_id,
                "started_at": perf_counter(),
                "workers": workers,
                "resolution_trace": {},
            }
        )
        return self._build_response(draft_runs=list(final_state.get("draft_runs") or []))

    def _build_main_graph(self):
        graph = StateGraph(MainRecallState)
        graph.add_node("plan_query", self._plan_query)
        graph.add_node("reject_query_gate", self._reject_query_gate)
        graph.add_node("run_draft_subgraphs", self._run_draft_subgraphs)
        graph.add_node("write_audit", self._write_audit_node)

        graph.set_entry_point("plan_query")
        graph.add_conditional_edges(
            "plan_query",
            self._after_plan_query,
            {
                "reject_query_gate": "reject_query_gate",
                "run_draft_subgraphs": "run_draft_subgraphs",
            },
        )
        graph.add_edge("reject_query_gate", "write_audit")
        graph.add_edge("run_draft_subgraphs", "write_audit")
        graph.add_edge("write_audit", END)
        return graph.compile()

    def _build_draft_graph(self):
        graph = StateGraph(DraftRecallState)
        graph.add_node("resolve_entity", self._resolve_entity)
        graph.add_node("reject_linker", self._reject_linker)
        graph.add_node("recall_memories", self._recall_memories)

        graph.set_entry_point("resolve_entity")
        graph.add_conditional_edges(
            "resolve_entity",
            self._after_resolve_entity,
            {
                "reject_linker": "reject_linker",
                "recall_memories": "recall_memories",
            },
        )
        graph.add_edge("reject_linker", END)
        graph.add_edge("recall_memories", END)
        return graph.compile()

    async def _plan_query(self, state: MainRecallState) -> dict[str, Any]:
        planner = await state["workers"].run_query_planner(
            memory_space=state["memory_space"],
            query=state["query"],
            request_id=state["request_id"],
        )
        resolution_trace = dict(state.get("resolution_trace") or {})
        resolution_trace.update(
            {
                "planner_gate_status": planner.query_gate_status,
                "planner_rejection_reason": planner.query_rejection_reason,
                "query_identity_profile_drafts": [item.model_dump() for item in planner.query_identity_profile_drafts],
                "query_focus": planner.query_focus.model_dump(),
            }
        )
        draft_payloads = [
            {
                "who": draft.who,
                "surface_forms": draft.surface_forms,
                "distinguishing_context": draft.distinguishing_context,
                "query_text": draft.query_text,
            }
            for draft in planner.query_identity_profile_drafts
        ]
        logger.info(
            "recall planner completed",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "gate_status": planner.query_gate_status,
                "draft_count": len(planner.query_identity_profile_drafts),
                "query_rewrite_count": len(planner.query_rewrites),
                "time_intent": getattr(planner.query_focus, "time_intent", None),
            },
        )
        return {
            "planner": planner,
            "draft_payloads": draft_payloads,
            "resolution_trace": resolution_trace,
        }

    @staticmethod
    def _after_plan_query(state: MainRecallState) -> str:
        planner = state["planner"]
        if planner.query_gate_status != "passed" or not state.get("draft_payloads"):
            return "reject_query_gate"
        return "run_draft_subgraphs"

    async def _reject_query_gate(self, state: MainRecallState) -> dict[str, Any]:
        planner = state["planner"]
        rejected_result = {
            "status": "rejected",
            "answer": "",
            "citations": [],
            "uncertainties": [],
            "error_code": planner.query_rejection_reason or "cannot_resolve_query_identity",
        }
        return {
            "draft_runs": [
                {
                    "query_identity_profile": None,
                    "resolved_entity_key": None,
                    "used_edges": [],
                    "resolution_trace": dict(state.get("resolution_trace") or {}),
                    "result": rejected_result,
                }
            ]
        }

    async def _run_draft_subgraphs(self, state: MainRecallState) -> dict[str, Any]:
        draft_payloads = list(state.get("draft_payloads") or [])
        planner = state["planner"]
        workers = state["workers"]
        draft_states = await asyncio.gather(
            *[
                self._draft_graph.ainvoke(
                    {
                        "memory_space": state["memory_space"],
                        "query": draft_payload["query_text"],
                        "original_query": state["query"],
                        "request_id": state["request_id"],
                        "workers": workers,
                        "planner": planner,
                        "draft_payload": draft_payload,
                        "resolution_trace": {
                            "query_identity_profile_draft": draft_payload,
                        },
                    }
                )
                for draft_payload in draft_payloads
            ],
            return_exceptions=True,
        )
        draft_runs: list[dict[str, Any]] = []
        for draft_index, (draft_payload, draft_state) in enumerate(zip(draft_payloads, draft_states, strict=True)):
            if isinstance(draft_state, Exception):
                logger.exception(
                    "recall draft subgraph failed",
                    extra={
                        "memory_space": state["memory_space"],
                        "request_id": state["request_id"],
                        "draft_index": draft_index,
                        "query_identity_profile": draft_payload,
                    },
                )
                failed_result = {
                    "status": "rejected",
                    "answer": "",
                    "citations": [],
                    "uncertainties": ["draft_recall_failed"],
                    "error_code": "recall_draft_failed",
                }
                draft_runs.append(
                    {
                        "query_identity_profile": dict(draft_payload),
                        "resolved_entity_key": None,
                        "used_edges": [],
                        "resolution_trace": {
                            "query_identity_profile_draft": draft_payload,
                            "draft_index": draft_index,
                            "draft_error": str(draft_state),
                        },
                        "result": failed_result,
                    }
                )
                continue
            draft_result = dict(draft_state.get("result") or {})
            resolution_trace = dict(draft_state.get("resolution_trace") or {})
            resolution_trace["draft_index"] = draft_index
            draft_runs.append(
                {
                    "query_identity_profile": dict(draft_payload),
                    "resolved_entity_key": draft_state.get("entity_key"),
                    "used_edges": list(draft_state.get("used_edges") or []),
                    "resolution_trace": resolution_trace,
                    "result": draft_result,
                }
            )
        return {
            "draft_runs": draft_runs,
        }

    async def _resolve_entity(self, state: DraftRecallState) -> dict[str, Any]:
        workers = state["workers"]
        draft_payload = state["draft_payload"]
        async with MemoryRepository() as repository:
            scored_candidates = await retrieval_index.entity_candidates(
                memory_space=state["memory_space"],
                draft=draft_payload,
                limit=10,
            )
            entity_candidates = [
                {
                    "entity_key": item.entity.entity_key,
                    "display_name": item.entity.display_name,
                    "identity_profile": item.entity.identity_profile,
                    "score": item.score,
                    "recent_memory_summaries": [
                        memory.summary
                        for memory in await repository.list_memories(
                            memory_space=state["memory_space"],
                            entity_key=item.entity.entity_key,
                            statuses=("active", "superseded", "stale"),
                            limit=5,
                        )
                    ],
                }
                for item in scored_candidates
            ]
        linker = await workers.run_linker(
            memory_space=state["memory_space"],
            request_id=state["request_id"],
            mode="query",
            identity_profile_draft=draft_payload,
            entity_candidates=entity_candidates,
        )
        logger.info(
            "recall entity linker completed",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "candidate_count": len(scored_candidates),
                "decision": linker.decision,
                "selected_entity_key": linker.selected_entity_key,
                "ambiguous_entity_keys": linker.ambiguous_entity_keys,
            },
        )
        resolution_trace = dict(state.get("resolution_trace") or {})
        resolution_trace.update(
            {
                "entity_candidate_keys": [item.entity.entity_key for item in scored_candidates],
                "linker_decision": linker.model_dump(),
            }
        )
        payload: dict[str, Any] = {
            "scored_candidates": scored_candidates,
            "linker": linker,
            "resolution_trace": resolution_trace,
        }
        if linker.decision == "link_existing" and linker.selected_entity_key:
            payload["entity_key"] = linker.selected_entity_key
        return payload

    @staticmethod
    def _after_resolve_entity(state: DraftRecallState) -> str:
        linker = state["linker"]
        if linker.decision == "link_existing" and linker.selected_entity_key:
            return "recall_memories"
        return "reject_linker"

    async def _reject_linker(self, state: DraftRecallState) -> dict[str, Any]:
        linker = state["linker"]
        if linker.decision == "ambiguous":
            return {
                "result": {
                    "status": "rejected",
                    "answer": "",
                    "uncertainties": [f"ambiguous_entity:{item}" for item in linker.ambiguous_entity_keys],
                    "error_code": "ambiguous_query_identity",
                }
            }
        return {
            "result": {
                "status": "rejected",
                "answer": "",
                "uncertainties": [],
                "error_code": "cannot_resolve_query_identity",
            }
        }

    async def _recall_memories(self, state: DraftRecallState) -> dict[str, Any]:
        workers = state["workers"]
        planner = state["planner"]
        entity_key = state["entity_key"]
        query = state["query"]
        async with MemoryRepository() as repository:
            memories = await repository.list_memories(
                memory_space=state["memory_space"],
                entity_key=entity_key,
                statuses=("active", "stale", "superseded"),
                limit=100,
            )
            entity = await repository.get_entity(memory_space=state["memory_space"], entity_key=entity_key)
        if entity is None:
            raise RuntimeError(f"Resolved entity disappeared before recall: {entity_key}")
        time_intent = _effective_time_intent(planner)
        query_texts = [query]
        if len(planner.query_identity_profile_drafts) <= 1:
            query_texts.extend(planner.query_rewrites)
        scored_seed = await retrieval_index.memory_candidates(
            query_texts=dedupe_preserve_order(query_texts, limit=4),
            memories=memories,
            limit=settings.MEMORY_MAX_RECALL_ITEMS,
            entities_by_key={entity.entity_key: entity},
        )
        seed_memories = [item.memory for item in scored_seed]
        if time_intent in {"current", "latest"}:
            active_seed_memories = [memory for memory in seed_memories if memory.status == "active"]
            if active_seed_memories:
                seed_memories = active_seed_memories
        expanded_memories, evidence_observation_ids, graph_uncertainties, used_edges = await self._expand_graph(
            memory_space=state["memory_space"],
            anchor_entity_key=entity_key,
            seed_memories=seed_memories,
            time_intent=time_intent,
        )
        if expanded_memories:
            (
                expanded_memories,
                evidence_observation_ids,
                graph_uncertainties,
                used_edges,
            ) = await self._supplement_cross_entity_graph(
                memory_space=state["memory_space"],
                anchor_entity_key=entity_key,
                original_query=str(state.get("original_query") or state.get("query") or ""),
                query_identity_profile={
                    "who": str(state["draft_payload"].get("who") or "").strip(),
                    "surface_forms": [str(item) for item in state["draft_payload"].get("surface_forms") or []],
                    "distinguishing_context": [
                        str(item) for item in state["draft_payload"].get("distinguishing_context") or []
                    ],
                },
                expanded_memories=expanded_memories,
                evidence_observation_ids=evidence_observation_ids,
                graph_uncertainties=graph_uncertainties,
                used_edges=used_edges,
                workers=workers,
            )
        logger.info(
            "recall graph expanded",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "entity_key": entity_key,
                "time_intent": time_intent,
                "seed_memory_ids": [item.memory_id for item in seed_memories],
                "expanded_memory_ids": [item.memory_id for item in expanded_memories],
                "evidence_observation_ids": evidence_observation_ids,
                "graph_uncertainty_count": len(graph_uncertainties),
                "used_edge_types": [edge["edge_type"] for edge in used_edges],
            },
        )
        resolution_trace = dict(state.get("resolution_trace") or {})
        resolution_trace.update(
            {
                "time_intent": time_intent,
                "seed_memory_ids": [item.memory_id for item in seed_memories],
                "expanded_memory_ids": [item.memory_id for item in expanded_memories],
                "graph_uncertainties": graph_uncertainties,
            }
        )
        if not expanded_memories:
            return {
                "used_edges": used_edges,
                "resolution_trace": resolution_trace,
                "result": {
                    "status": "ok",
                    "answer": "",
                    "citations": [],
                    "uncertainties": ["no_relevant_memory_found"],
                    "error_code": None,
                },
            }

        async with MemoryRepository() as repository:
            observations = await repository.get_observations_by_ids(
                memory_space=state["memory_space"],
                observation_ids=evidence_observation_ids,
            )
            entity = await repository.get_entity(memory_space=state["memory_space"], entity_key=entity_key)
        resolved_entity_profile = project_identity_profile(entity.identity_profile if entity is not None else {})
        memory_evidence = self._memory_evidence_payloads(
            memories=expanded_memories,
            seed_memories=seed_memories,
            used_edges=used_edges,
        )
        observation_evidence = self._observation_evidence_payloads(observations=observations)
        id_ref_maps = self._build_id_ref_maps(
            memory_ids=[
                *[str(memory.memory_id) for memory in expanded_memories],
                *[
                    str(edge.get("from_id") or "")
                    for edge in used_edges
                    if edge.get("from_id")
                ],
                *[
                    str(edge.get("to_id") or "")
                    for edge in used_edges
                    if edge.get("to_id") and str(edge.get("edge_type") or "") != "derived_from"
                ],
            ],
            observation_ids=[
                *[str(observation.observation_id) for observation in observations],
                *[
                    str(edge.get("to_id") or "")
                    for edge in used_edges
                    if edge.get("to_id") and str(edge.get("edge_type") or "") == "derived_from"
                ],
            ],
        )
        composer = await workers.run_answer_composer(
            memory_space=state["memory_space"],
            request_id=state["request_id"],
            payload={
                "query": query,
                "query_focus": planner.query_focus.model_dump(),
                "resolved_entity_key": entity_key,
                "resolved_entity_profile": resolved_entity_profile,
                "time_intent": time_intent,
                "graph_uncertainties": graph_uncertainties,
                "used_edges": self._shorten_llm_refs(used_edges, id_ref_maps=id_ref_maps),
                "memories": self._shorten_llm_refs(memory_evidence, id_ref_maps=id_ref_maps),
                "observations": self._shorten_llm_refs(observation_evidence, id_ref_maps=id_ref_maps),
            },
        )
        citations = self._normalize_composer_citations(
            composer_citations=list(composer.citations or []),
            expanded_memories=expanded_memories,
            observations=observations,
            used_edges=used_edges,
            id_ref_maps=id_ref_maps,
        )
        merged_uncertainties = self._merge_uncertainties(list(composer.uncertainties or []), graph_uncertainties)
        answer = str(composer.answer or "").strip()
        logger.info(
            "recall answer composed",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "entity_key": entity_key,
                "answer_length": len(answer),
                "candidate_memory_count": len(memory_evidence),
                "edge_count": len(used_edges),
                "citation_count": len(citations),
                "uncertainty_count": len(merged_uncertainties),
            },
        )
        return {
            "seed_memories": seed_memories,
            "expanded_memories": expanded_memories,
            "evidence_observation_ids": evidence_observation_ids,
            "graph_uncertainties": graph_uncertainties,
            "used_edges": used_edges,
            "observations": observations,
            "citations": citations,
            "composer": composer,
            "id_ref_maps": id_ref_maps,
            "resolution_trace": resolution_trace,
            "result": {
                "status": "ok",
                "answer": answer,
                "citations": citations,
                "uncertainties": merged_uncertainties,
                "error_code": None,
            },
        }

    async def _write_audit_node(self, state: MainRecallState) -> dict[str, Any]:
        draft_runs = list(state.get("draft_runs") or [])
        audit_payload = self._build_audit_payload(draft_runs=draft_runs)
        started_at = float(state.get("started_at") or perf_counter())
        latency_ms = max(0, round((perf_counter() - started_at) * 1000))
        audit_metadata = self._build_audit_metadata(
            query=state["query"],
            draft_runs=draft_runs,
            result=audit_payload["result"],
            used_edges=audit_payload["used_edges"],
            citations=audit_payload["citations"],
            latency_ms=latency_ms,
        )
        audit_metadata["draft_runs"] = draft_runs
        await self._write_recall_audit(
            memory_space=state["memory_space"],
            request_id=state["request_id"],
            query=state["query"],
            result=audit_payload["result"],
            resolved_entity_key=audit_payload["resolved_entity_key"],
            used_edges=audit_payload["used_edges"],
            resolution_trace=dict(state.get("resolution_trace") or {}),
            citations=audit_payload["citations"],
            metadata=audit_metadata,
        )
        logger.info(
            "recall audit written",
            extra={
             "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "result_count": len(draft_runs),
                "latency_ms": latency_ms,
                "status": audit_payload["result"].get("status"),
                "error_code": audit_payload["result"].get("error_code"),
                "resolved_entity_key": audit_payload["resolved_entity_key"],
            },
        )
        return {}

    @staticmethod
    def _build_response(draft_runs: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the public recall response from internal per-draft runs."""

        return {
            "results": [dict(item.get("result") or {}) for item in draft_runs],
        }

    @staticmethod
    def _build_audit_payload(draft_runs: list[dict[str, Any]]) -> dict[str, Any]:
        if len(draft_runs) == 1:
            only = draft_runs[0]
            result = dict(only.get("result") or {})
            return {
                "resolved_entity_key": only.get("resolved_entity_key"),
                "used_edges": list(only.get("used_edges") or []),
                "citations": list(result.get("citations") or []),
                "result": result,
            }

        result_items = [dict(item.get("result") or {}) for item in draft_runs]
        statuses = {str(item.get("status") or "rejected") for item in result_items}
        if statuses == {"ok"}:
            status = "ok"
        elif "ok" in statuses:
            status = "partial"
        elif statuses == {"not_ready"}:
            status = "not_ready"
        else:
            status = "rejected"
        rejected_codes = {
            str(item.get("error_code"))
            for item in result_items
            if item.get("error_code") and str(item.get("status") or "rejected") != "ok"
        }
        error_code = next(iter(rejected_codes)) if len(rejected_codes) == 1 else None
        return {
            "resolved_entity_key": None,
            "used_edges": [],
            "citations": [],
            "result": {
                "status": status,
                "answer": "",
                "uncertainties": [],
                "error_code": error_code,
                "citations": [],
            },
        }

    @staticmethod
    def _build_audit_metadata(
        *,
        query: str,
        draft_runs: list[dict[str, Any]],
        result: dict[str, Any],
        used_edges: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        latency_ms: int | None,
    ) -> dict[str, Any]:
        """Build recall audit metadata for debugging and retrieval-quality improvement."""

        query_text = str(query or "").replace("\n", " ").strip()
        result_items = [dict(item.get("result") or {}) for item in draft_runs]
        if not result_items:
            result_items = [dict(result or {})]
        statuses = [str(item.get("status") or "unknown") for item in result_items]
        answer = str(result.get("answer") or "")
        uncertainties = list(result.get("uncertainties") or [])
        key_memory_ids: list[str] = []
        supporting_observation_ids: list[str] = []
        for citation in citations:
            memory_id = str(citation.get("memory_id") or "").strip()
            if memory_id and memory_id not in key_memory_ids:
                key_memory_ids.append(memory_id)
            for source_memory_id in citation.get("source_memory_ids") or []:
                normalized_memory_id = str(source_memory_id or "").strip()
                if normalized_memory_id and normalized_memory_id not in key_memory_ids:
                    key_memory_ids.append(normalized_memory_id)
            observation_id = str(citation.get("observation_id") or "").strip()
            if observation_id and observation_id not in supporting_observation_ids:
                supporting_observation_ids.append(observation_id)
        used_edge_types = dedupe_preserve_order(
            str(edge.get("edge_type") or "").strip()
            for edge in used_edges
            if str(edge.get("edge_type") or "").strip()
        )
        return {
            "audit_schema_version": 1,
            "query_preview": query_text[:512],
            "query_length": len(query_text),
            "result_count": len(result_items),
            "ok_result_count": statuses.count("ok"),
            "partial_result_count": statuses.count("partial"),
            "rejected_result_count": statuses.count("rejected"),
            "not_ready_result_count": statuses.count("not_ready"),
            "status": str(result.get("status") or "unknown"),
            "error_code": result.get("error_code"),
            "latency_ms": latency_ms,
            "answer_preview": answer.replace("\n", " ").strip()[:512],
            "answer_length": len(answer),
            "citation_count": len(citations),
            "uncertainty_count": len(uncertainties),
            "used_edge_count": len(used_edges),
            "used_edge_types": used_edge_types,
            "key_memory_ids": key_memory_ids,
            "supporting_observation_ids": supporting_observation_ids,
        }

    async def _expand_graph(
        self,
        *,
        memory_space: str,
        anchor_entity_key: str,
        seed_memories: list[Any],
        time_intent: str,
    ) -> tuple[list[Any], list[str], list[str], list[dict[str, Any]]]:
        expanded_by_id = {memory.memory_id: memory for memory in seed_memories}
        evidence_observation_ids: list[str] = []
        uncertainties: list[str] = []
        used_edges: list[dict[str, Any]] = []
        if not seed_memories:
            return [], [], [], []

        def add_edge(edge) -> None:
            payload = {
                "edge_type": edge.edge_type,
                "from_id": edge.from_id,
                "to_id": edge.to_id,
                "reason": edge.reason,
                "weight": edge.weight,
            }
            if payload not in used_edges:
                used_edges.append(payload)

        def opposite_id(edge, current_ids: set[str]) -> str | None:
            if edge.from_id in current_ids and edge.to_kind == "memory":
                return edge.to_id
            if edge.to_id in current_ids and edge.to_kind == "memory":
                return edge.from_id
            return None

        async with MemoryRepository() as repository:

            async def classify_other_entity(memory_ids: list[str]) -> dict[str, str]:
                mapping: dict[str, str] = {}
                for memory in await repository.get_memories_by_ids(memory_space=memory_space, memory_ids=memory_ids):
                    mapping[memory.memory_id] = memory.entity_key
                return mapping

            async def collect_related_ids(*, current_ids: set[str], allow_cross_entity: bool) -> dict[str, list[str]]:
                related_ids_by_type: dict[str, list[str]] = {
                    "updates": [],
                    "supports": [],
                    "contradicts": [],
                    "related_to": [],
                }
                all_edges = await repository.list_edges_for_memory_ids(memory_space=memory_space, memory_ids=current_ids)
                candidate_other_ids = [
                    other_id
                    for edge in all_edges
                    for other_id in [opposite_id(edge, current_ids)]
                    if other_id is not None
                ]
                entity_by_memory_id = await classify_other_entity(candidate_other_ids)
                for edge in all_edges:
                    if edge.edge_type == "derived_from" and edge.to_kind == "observation":
                        if edge.to_id not in evidence_observation_ids:
                            evidence_observation_ids.append(edge.to_id)
                        add_edge(edge)
                        continue
                    other_id = opposite_id(edge, current_ids)
                    if other_id is None:
                        continue
                    other_entity_key = entity_by_memory_id.get(other_id)
                    is_cross_entity = bool(other_entity_key and other_entity_key != anchor_entity_key)
                    if is_cross_entity and not allow_cross_entity:
                        continue
                    if not is_cross_entity and allow_cross_entity:
                        continue
                    if edge.edge_type == "updates":
                        should_include = False
                        if time_intent == "history":
                            should_include = True
                        elif time_intent in {"current", "latest"}:
                            should_include = edge.to_id in current_ids and edge.from_id == other_id
                        else:
                            should_include = other_id not in expanded_by_id
                        if should_include:
                            related_ids_by_type["updates"].append(other_id)
                            add_edge(edge)
                    elif edge.edge_type == "supports":
                        related_ids_by_type["supports"].append(other_id)
                        add_edge(edge)
                    elif edge.edge_type == "contradicts":
                        related_ids_by_type["contradicts"].append(other_id)
                        uncertainties.append(f"contradicting_memory:{other_id}")
                        add_edge(edge)
                    elif edge.edge_type == "related_to":
                        related_ids_by_type["related_to"].append(other_id)
                        add_edge(edge)
                return related_ids_by_type

            async def add_related_memories(*, related_ids_by_type: dict[str, list[str]]) -> list[str]:
                ordered_ids: list[str] = []
                ordered_ids.extend(self._bounded_unique(related_ids_by_type["updates"], settings.MEMORY_GRAPH_UPDATES_BUDGET))
                ordered_ids.extend(self._bounded_unique(related_ids_by_type["supports"], settings.MEMORY_GRAPH_SUPPORTS_BUDGET))
                ordered_ids.extend(
                    self._bounded_unique(related_ids_by_type["contradicts"], settings.MEMORY_GRAPH_CONTRADICTS_BUDGET)
                )
                ordered_ids.extend(
                    self._bounded_unique(related_ids_by_type["related_to"], settings.MEMORY_GRAPH_RELATED_TO_BUDGET)
                )
                remaining_budget = max(settings.MEMORY_GRAPH_TOTAL_MEMORY_BUDGET - len(expanded_by_id), 0)
                related_memories = await repository.get_memories_by_ids(
                    memory_space=memory_space,
                    memory_ids=ordered_ids[:remaining_budget],
                )
                for memory in related_memories:
                    expanded_by_id.setdefault(memory.memory_id, memory)
                return [memory.memory_id for memory in related_memories]

            local_related_ids = await collect_related_ids(current_ids=set(expanded_by_id.keys()), allow_cross_entity=False)
            frontier_memory_ids = await add_related_memories(related_ids_by_type=local_related_ids)

            current_frontier_ids = list(dict.fromkeys([*expanded_by_id.keys(), *frontier_memory_ids]))
            seen_frontier_ids = set(current_frontier_ids)
            for _ in range(3):
                cross_related_ids = await collect_related_ids(
                    current_ids=set(current_frontier_ids),
                    allow_cross_entity=True,
                )
                added_memory_ids = await add_related_memories(related_ids_by_type=cross_related_ids)
                next_frontier_ids = [memory_id for memory_id in added_memory_ids if memory_id not in seen_frontier_ids]
                if not next_frontier_ids:
                    break
                seen_frontier_ids.update(next_frontier_ids)
                current_frontier_ids = next_frontier_ids

            if expanded_by_id:
                derived_edges = await repository.list_edges_for_memory_ids(
                    memory_space=memory_space,
                    memory_ids=list(expanded_by_id.keys()),
                )
                for edge in derived_edges:
                    if edge.edge_type != "derived_from" or edge.to_kind != "observation":
                        continue
                    if edge.to_id not in evidence_observation_ids:
                        evidence_observation_ids.append(edge.to_id)
                    add_edge(edge)

        return (
            list(expanded_by_id.values())[: settings.MEMORY_GRAPH_TOTAL_MEMORY_BUDGET],
            evidence_observation_ids,
            self._bounded_unique(uncertainties, 8),
            used_edges,
        )

    async def _supplement_cross_entity_graph(
        self,
        *,
        memory_space: str,
        anchor_entity_key: str,
        original_query: str,
        query_identity_profile: dict[str, Any],
        expanded_memories: list[Any],
        evidence_observation_ids: list[str],
        graph_uncertainties: list[str],
        used_edges: list[dict[str, Any]],
        workers: MemoryWorkers,
    ) -> tuple[list[Any], list[str], list[str], list[dict[str, Any]]]:
        expanded_by_id = {memory.memory_id: memory for memory in expanded_memories}
        current_evidence_observation_ids = list(evidence_observation_ids)
        current_uncertainties = list(graph_uncertainties)
        current_used_edges = list(used_edges)
        frontier_ids = list(expanded_by_id.keys())
        seen_frontier_ids = set(frontier_ids)
        for _ in range(2):
            if not frontier_ids:
                break
            added_ids = await self._dynamic_cross_entity_step(
                memory_space=memory_space,
                anchor_entity_key=anchor_entity_key,
                original_query=original_query,
                query_identity_profile=query_identity_profile,
                frontier_ids=frontier_ids,
                expanded_by_id=expanded_by_id,
                evidence_observation_ids=current_evidence_observation_ids,
                uncertainties=current_uncertainties,
                used_edges=current_used_edges,
                workers=workers,
            )
            next_frontier_ids = [memory_id for memory_id in added_ids if memory_id not in seen_frontier_ids]
            if not next_frontier_ids:
                break
            seen_frontier_ids.update(next_frontier_ids)
            frontier_ids = next_frontier_ids
        return (
            list(expanded_by_id.values())[: settings.MEMORY_GRAPH_TOTAL_MEMORY_BUDGET],
            current_evidence_observation_ids,
            self._bounded_unique(current_uncertainties, 8),
            current_used_edges,
        )

    async def _dynamic_cross_entity_step(
        self,
        *,
        memory_space: str,
        anchor_entity_key: str,
        original_query: str,
        query_identity_profile: dict[str, Any],
        frontier_ids: list[str],
        expanded_by_id: dict[str, Any],
        evidence_observation_ids: list[str],
        uncertainties: list[str],
        used_edges: list[dict[str, Any]],
        workers: MemoryWorkers,
    ) -> list[str]:
        remaining_budget = max(settings.MEMORY_GRAPH_TOTAL_MEMORY_BUDGET - len(expanded_by_id), 0)
        if remaining_budget <= 0:
            return []
        async with MemoryRepository() as repository:
            frontier_memories = await repository.get_memories_by_ids(memory_space=memory_space, memory_ids=frontier_ids)
            if not frontier_memories:
                return []
            anchor_entity = await repository.get_entity(memory_space=memory_space, entity_key=anchor_entity_key)
            frontier_entities = await repository.get_entities_by_keys(
                memory_space=memory_space,
                entity_keys={memory.entity_key for memory in frontier_memories},
            )
            frontier_edges = await repository.list_edges_for_memory_ids(memory_space=memory_space, memory_ids=frontier_ids)
            frontier_observation_ids = [
                edge.to_id
                for edge in frontier_edges
                if edge.edge_type == "derived_from" and edge.to_kind == "observation" and edge.to_id
            ]
            frontier_observations = await repository.get_observations_by_ids(
                memory_space=memory_space,
                observation_ids=frontier_observation_ids,
            )
            candidate_pool = [
                memory
                for memory in await repository.list_all_memories(memory_space=memory_space)
                if memory.memory_id not in expanded_by_id and memory.status in {"active", "stale", "superseded"}
            ]
        if not candidate_pool:
            return []
        cross_query_ref_maps = self._build_id_ref_maps(
            memory_ids=[str(memory.memory_id) for memory in frontier_memories],
            observation_ids=[str(observation.observation_id) for observation in frontier_observations],
        )
        cross_query_plan = await workers.run_cross_entity_query_builder(
            memory_space=memory_space,
            request_id=get_or_create_request_id(),
            payload={
                "anchor_entity_key": anchor_entity_key,
                "anchor_identity_profile": (
                    project_identity_profile(anchor_entity.identity_profile)
                    if anchor_entity is not None
                    else ""
                ),
                "frontier_memories": self._shorten_llm_refs(
                    _memory_payloads_with_identities(
                        memories=frontier_memories,
                        entities_by_key={entity.entity_key: entity for entity in frontier_entities},
                    ),
                    id_ref_maps=cross_query_ref_maps,
                ),
                "frontier_observations": self._shorten_llm_refs(
                    [_observation_payload(observation) for observation in frontier_observations],
                    id_ref_maps=cross_query_ref_maps,
                ),
            },
        )
        query_texts = dedupe_preserve_order(
            [
                *(cross_query_plan.query_texts or []),
                *[memory.summary or memory.content for memory in frontier_memories if memory.summary or memory.content],
                *[
                    observation.summary or observation.content
                    for observation in frontier_observations
                    if observation.summary or observation.content
                ],
            ],
            limit=8,
        )
        if not query_texts:
            return []
        async with MemoryRepository() as repository:
            candidate_entities = await repository.get_entities_by_keys(
                memory_space=memory_space,
                entity_keys={memory.entity_key for memory in candidate_pool},
            )
        entities_by_key = {entity.entity_key: entity for entity in candidate_entities}
        scored = await retrieval_index.memory_candidates(
            query_texts=query_texts,
            memories=candidate_pool,
            limit=max(8, settings.MEMORY_GRAPH_RELATED_TO_BUDGET + settings.MEMORY_GRAPH_SUPPORTS_BUDGET),
            entities_by_key=entities_by_key,
        )
        candidate_memories = [item.memory for item in scored][:remaining_budget]
        if not candidate_memories:
            return []
        edge_judge_ref_maps = self._build_id_ref_maps(
            memory_ids=[
                *[str(memory.memory_id) for memory in frontier_memories],
                *[str(memory.memory_id) for memory in candidate_memories],
            ],
            observation_ids=[],
        )
        judged = await workers.run_edge_judge(
            memory_space=memory_space,
            request_id=get_or_create_request_id(),
            payload={
                "mode": "cross_entity_graph",
                "original_query": str(original_query or "").strip(),
                "query_identity_profile": dict(query_identity_profile or {}),
                "anchor_entity_key": anchor_entity_key,
                "frontier_memories": self._shorten_llm_refs(
                    _memory_payloads_with_identities(
                        memories=frontier_memories,
                        entities_by_key={entity.entity_key: entity for entity in frontier_entities},
                    ),
                    id_ref_maps=edge_judge_ref_maps,
                ),
                "candidate_memories": self._shorten_llm_refs(
                    _memory_payloads_with_identities(
                        memories=candidate_memories,
                        entities_by_key={entity.entity_key: entity for entity in candidate_entities},
                    ),
                    id_ref_maps=edge_judge_ref_maps,
                ),
            },
        )
        valid_memory_ids = {memory.memory_id for memory in frontier_memories}
        valid_memory_ids.update(memory.memory_id for memory in candidate_memories)
        restored_relations = self._restore_edge_judge_relations(
            relations=list(judged.relations or []),
            id_ref_maps=edge_judge_ref_maps,
            memory_space=memory_space,
        )
        normalized_edges = _normalize_relation_edges(
            relations=restored_relations,
            valid_memory_ids=valid_memory_ids,
        )
        candidate_rank = {memory.memory_id: index for index, memory in enumerate(candidate_memories)}
        normalized_edges = _sparsify_cross_entity_related_edges(
            edges=normalized_edges,
            frontier_ids={memory.memory_id for memory in frontier_memories},
            candidate_rank=candidate_rank,
        )
        candidate_by_id = {memory.memory_id: memory for memory in candidate_memories}
        frontier_id_set = {memory.memory_id for memory in frontier_memories}
        candidate_id_set = set(candidate_by_id.keys())
        normalized_edges = [
            edge
            for edge in normalized_edges
            if (
                (edge["from_id"] in frontier_id_set and edge["to_id"] in candidate_id_set)
                or (edge["to_id"] in frontier_id_set and edge["from_id"] in candidate_id_set)
            )
        ]
        added_ids: list[str] = []
        for edge in normalized_edges:
            payload = {
                "edge_type": edge["edge_type"],
                "from_id": edge["from_id"],
                "to_id": edge["to_id"],
                "reason": edge["reason"],
                "weight": edge["weight"],
            }
            if payload not in used_edges:
                used_edges.append(payload)
            if edge["edge_type"] == "contradicts":
                for memory_id in (edge["from_id"], edge["to_id"]):
                    if memory_id not in frontier_ids:
                        uncertainties.append(f"contradicting_memory:{memory_id}")
            for memory_id in (edge["from_id"], edge["to_id"]):
                if memory_id in candidate_by_id and memory_id not in expanded_by_id and len(added_ids) < remaining_budget:
                    expanded_by_id[memory_id] = candidate_by_id[memory_id]
                    added_ids.append(memory_id)
        if added_ids:
            async with MemoryRepository() as repository:
                derived_edges = await repository.list_edges_for_memory_ids(memory_space=memory_space, memory_ids=added_ids)
            for edge in derived_edges:
                if edge.edge_type != "derived_from" or edge.to_kind != "observation":
                    continue
                if edge.to_id not in evidence_observation_ids:
                    evidence_observation_ids.append(edge.to_id)
                payload = {
                    "edge_type": edge.edge_type,
                    "from_id": edge.from_id,
                    "to_id": edge.to_id,
                    "reason": edge.reason,
                    "weight": edge.weight,
                }
                if payload not in used_edges:
                    used_edges.append(payload)
        logger.info(
            "recall dynamic cross entity step completed",
            extra={
                "memory_space": memory_space,
                "anchor_entity_key": anchor_entity_key,
                "frontier_ids": frontier_ids,
                "query_texts": query_texts,
                "candidate_count": len(candidate_memories),
                "created_edge_count": len(normalized_edges),
                "added_memory_ids": added_ids,
            },
        )
        return added_ids

    @staticmethod
    def _bounded_unique(values: list[str], limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value)
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _build_id_ref_maps(
        *,
        memory_ids: list[str],
        observation_ids: list[str],
    ) -> dict[str, dict[str, str]]:
        """
        为 LLM 构造短引用映射。

        Args:
            memory_ids: 本次 payload 中允许 LLM 引用的真实 memory_id。
            observation_ids: 本次 payload 中允许 LLM 引用的真实 observation_id。

        Returns:
            同时包含长 ID 到短 ID、短 ID 到长 ID 的映射表。
        """
        memory_ids = dedupe_preserve_order(memory_ids)
        observation_ids = dedupe_preserve_order(observation_ids)
        memory_long_to_short = {memory_id: f"m{index}" for index, memory_id in enumerate(memory_ids, start=1)}
        observation_long_to_short = {
            observation_id: f"o{index}"
            for index, observation_id in enumerate(observation_ids, start=1)
        }
        return {
            "memory_long_to_short": memory_long_to_short,
            "memory_short_to_long": {short_id: long_id for long_id, short_id in memory_long_to_short.items()},
            "observation_long_to_short": observation_long_to_short,
            "observation_short_to_long": {
                short_id: long_id
                for long_id, short_id in observation_long_to_short.items()
            },
        }

    @staticmethod
    def _short_ref_for_llm(
        *,
        ref_id: str,
        ref_kind: str,
        id_ref_maps: dict[str, dict[str, str]],
    ) -> str:
        ref_id = str(ref_id or "").strip()
        if not ref_id:
            return ""
        return id_ref_maps[f"{ref_kind}_long_to_short"].get(ref_id, "")

    @staticmethod
    def _id_from_llm_ref(*, ref_id: str, ref_kind: str, id_ref_maps: dict[str, dict[str, str]]) -> str:
        ref_id = str(ref_id or "").strip()
        if not ref_id:
            return ""
        return id_ref_maps[f"{ref_kind}_short_to_long"].get(ref_id, "")

    @staticmethod
    def _shorten_llm_refs(value: Any, *, id_ref_maps: dict[str, dict[str, str]]) -> Any:
        if isinstance(value, list):
            return [RecallGraph._shorten_llm_refs(item, id_ref_maps=id_ref_maps) for item in value]
        if not isinstance(value, dict):
            return value
        payload: dict[str, Any] = {}
        for key, item in value.items():
            if key == "memory_id" or key == "from_id":
                payload[key] = RecallGraph._short_ref_for_llm(
                    ref_id=str(item or ""),
                    ref_kind="memory",
                    id_ref_maps=id_ref_maps,
                )
            elif key == "to_id":
                ref_kind = "observation" if str(value.get("edge_type") or "") == "derived_from" else "memory"
                payload[key] = RecallGraph._short_ref_for_llm(
                    ref_id=str(item or ""),
                    ref_kind=ref_kind,
                    id_ref_maps=id_ref_maps,
                )
            elif key == "observation_id":
                payload[key] = RecallGraph._short_ref_for_llm(
                    ref_id=str(item or ""),
                    ref_kind="observation",
                    id_ref_maps=id_ref_maps,
                )
            else:
                payload[key] = RecallGraph._shorten_llm_refs(item, id_ref_maps=id_ref_maps)
        return payload

    @staticmethod
    def _restore_edge_judge_relations(
        *,
        relations: list[Any],
        id_ref_maps: dict[str, dict[str, str]],
        memory_space: str,
    ) -> list[Any]:
        """
        把 edge judge 输出的短 memory 引用还原成真实 memory_id。

        Args:
            relations: edge judge 输出的关系对象。
            id_ref_maps: `_build_id_ref_maps` 生成的映射表。
            memory_space: 当前记忆空间，用于日志定位。

        Returns:
            可继续交给 `_normalize_relation_edges` 的关系对象列表。
        """
        restored: list[Any] = []
        for relation in relations:
            from_ref = str(getattr(relation, "from_memory_id", "") or "").strip()
            to_ref = str(getattr(relation, "to_memory_id", "") or "").strip()
            from_memory_id = RecallGraph._id_from_llm_ref(
                ref_id=from_ref,
                ref_kind="memory",
                id_ref_maps=id_ref_maps,
            )
            to_memory_id = RecallGraph._id_from_llm_ref(
                ref_id=to_ref,
                ref_kind="memory",
                id_ref_maps=id_ref_maps,
            )
            if not from_memory_id or not to_memory_id:
                logger.warning(
                    "recall edge judge returned unknown short memory ref",
                    extra={
                        "memory_space": memory_space,
                        "from_ref": from_ref,
                        "to_ref": to_ref,
                    },
                )
                continue
            restored.append(
                SimpleNamespace(
                    from_memory_id=from_memory_id,
                    to_memory_id=to_memory_id,
                    edge_type=relation.edge_type,
                    reason=relation.reason,
                    weight=relation.weight,
                )
            )
        return restored

    @staticmethod
    def _memory_evidence_payloads(
        *,
        memories: list[Any],
        seed_memories: list[Any],
        used_edges: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        memories_by_id = {str(memory.memory_id): memory for memory in memories}
        seed_ids = {str(memory.memory_id) for memory in seed_memories}
        relation_edges_by_memory_id: dict[str, list[dict[str, Any]]] = {memory_id: [] for memory_id in memories_by_id}
        for edge in used_edges:
            edge_type = str(edge.get("edge_type") or "")
            if edge_type == "derived_from":
                continue
            payload = {
                "edge_type": edge_type,
                "from_id": edge.get("from_id"),
                "to_id": edge.get("to_id"),
                "reason": edge.get("reason"),
                "weight": edge.get("weight"),
            }
            for key in ("from_id", "to_id"):
                memory_id = str(edge.get(key) or "")
                if memory_id in relation_edges_by_memory_id and payload not in relation_edges_by_memory_id[memory_id]:
                    relation_edges_by_memory_id[memory_id].append(payload)

        payloads: list[dict[str, Any]] = []
        for memory in memories:
            memory_id = str(memory.memory_id)
            relation_edges = relation_edges_by_memory_id.get(memory_id, [])
            relation_types = dedupe_preserve_order(
                [str(edge.get("edge_type") or "") for edge in relation_edges if edge.get("edge_type")]
            )
            payloads.append(
                {
                    "memory_id": memory.memory_id,
                    "status": memory.status,
                    "evidence_role": _memory_evidence_role(
                        memory_id=memory_id,
                        seed_ids=seed_ids,
                        relation_types=relation_types,
                    ),
                    "relation_types": relation_types,
                    "relation_edges": relation_edges,
                    "text": project_memory(memory),
                    "title": memory.title,
                    "summary": memory.summary,
                    "content": memory.content,
                }
            )
        return payloads

    @staticmethod
    def _observation_evidence_payloads(*, observations: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "observation_id": observation.observation_id,
                "summary": observation.summary,
                "content": observation.content,
                "created_at": observation.created_at,
            }
            for observation in observations
        ]

    @staticmethod
    def _citation_value(citation: Any, key: str) -> str:
        if isinstance(citation, dict):
            return str(citation.get(key) or "").strip()
        return str(getattr(citation, key, "") or "").strip()

    @staticmethod
    def _normalize_composer_citations(
        *,
        composer_citations: list[Any],
        expanded_memories: list[Any],
        observations: list[Any],
        used_edges: list[dict[str, Any]],
        id_ref_maps: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        memories_by_id = {str(memory.memory_id): memory for memory in expanded_memories}
        observations_by_id = {str(observation.observation_id): observation for observation in observations}
        source_memory_ids_by_observation: dict[str, list[str]] = {}
        for edge in used_edges:
            if str(edge.get("edge_type") or "") != "derived_from":
                continue
            observation_id = str(edge.get("to_id") or "")
            memory_id = str(edge.get("from_id") or "")
            if observation_id not in observations_by_id or memory_id not in memories_by_id:
                continue
            bucket = source_memory_ids_by_observation.setdefault(observation_id, [])
            if memory_id not in bucket:
                bucket.append(memory_id)

        citations: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None, str]] = set()
        for citation in composer_citations:
            memory_id = RecallGraph._id_from_llm_ref(
                ref_id=RecallGraph._citation_value(citation, "memory_id"),
                ref_kind="memory",
                id_ref_maps=id_ref_maps,
            )
            observation_id = RecallGraph._id_from_llm_ref(
                ref_id=RecallGraph._citation_value(citation, "observation_id"),
                ref_kind="observation",
                id_ref_maps=id_ref_maps,
            )
            memory_id = memory_id if memory_id in memories_by_id else ""
            observation_id = observation_id if observation_id in observations_by_id else ""
            source_memory_ids: list[str] = []
            if memory_id:
                source_memory_ids.append(memory_id)
            if observation_id:
                for source_memory_id in source_memory_ids_by_observation.get(observation_id, []):
                    if source_memory_id not in source_memory_ids:
                        source_memory_ids.append(source_memory_id)
            if not memory_id and source_memory_ids:
                memory_id = source_memory_ids[0]
            if not memory_id and not observation_id:
                continue

            memory = memories_by_id.get(memory_id)
            observation = observations_by_id.get(observation_id)
            summary = RecallGraph._citation_value(citation, "summary")
            excerpt = RecallGraph._citation_value(citation, "excerpt")
            if not summary and observation is not None:
                summary = str(observation.summary or "").strip()
            if not summary and memory is not None:
                summary = str(memory.summary or memory.title or "").strip()
            if not excerpt and observation is not None:
                excerpt = str(observation.summary or observation.content or "").strip()
            if not excerpt and memory is not None:
                excerpt = str(memory.summary or memory.content or "").strip()
            dedupe_key = (memory_id or None, observation_id or None, excerpt)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            citations.append(
                {
                    "memory_id": memory_id or None,
                    "observation_id": observation_id or None,
                    "summary": summary,
                    "excerpt": excerpt,
                    "source_memory_ids": source_memory_ids,
                }
            )
        return citations

    @staticmethod
    def _merge_uncertainties(primary: list[str], secondary: list[str]) -> list[str]:
        result: list[str] = []
        for group in (primary, secondary):
            for item in group:
                if item not in result:
                    result.append(item)
        return result

    @staticmethod
    async def _write_recall_audit(
        *,
        memory_space: str,
        request_id: str,
        query: str,
        result: dict[str, Any],
        resolved_entity_key: str | None = None,
        used_edges: list[dict[str, Any]] | None = None,
        resolution_trace: dict[str, Any] | None = None,
        citations: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with MemoryRepository() as repository:
            metadata_payload = dict(metadata or {})
            metadata_payload.setdefault("citations", list(citations or result.get("citations") or []))
            await repository.create_recall_audit(
                memory_space=memory_space,
                request_id=request_id,
                query=query,
                status=str(result.get("status") or "unknown"),
                resolved_entity_key=resolved_entity_key,
                answer=str(result.get("answer") or ""),
                error_code=result.get("error_code"),
                uncertainties=list(result.get("uncertainties") or []),
                used_edges=list(used_edges or []),
                resolution_trace=resolution_trace or {},
                metadata=metadata_payload,
            )

recall_graph = RecallGraph()
