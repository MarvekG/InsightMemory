from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.config import settings
from insight_memory.index.retrieval_index import project_identity_profile, retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.text import dedupe_preserve_order
from insight_memory.workers.runtime import MemoryWorkers


logger = get_logger(__name__)


class RepairMemoryEdgesState(TypedDict, total=False):
    memory_space: str
    memory_id: str | None
    entity_key: str | None
    memories: list[Any]
    observations: list[Any]
    entities_by_key: dict[str, Any]
    workers: MemoryWorkers
    local_judged: Any
    frontier_memories: list[Any]
    frontier_observations: list[Any]
    cross_query_texts: list[str]
    cross_candidates: list[Any]
    cross_judged: Any
    stale_entity: bool
    local_created_edges: int
    deleted_relation_edges: int
    result: dict[str, Any]


def _memory_payload(memory: Any, *, identity_profile: dict[str, Any]) -> dict[str, Any]:
    if not identity_profile:
        raise ValueError("identity_profile is required for edge judge memory payload")
    return {
        "memory_id": memory.memory_id,
        "entity_key": memory.entity_key,
        "identity_profile": identity_profile,
        "title": memory.title,
        "summary": memory.summary,
        "content": memory.content,
        "status": memory.status,
        "record_markers": (memory.metadata_json or {}).get("record_markers"),
    }


def _memory_payloads_with_identities(
    *,
    memories: list[Any],
    entities_by_key: dict[str, Any],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for memory in memories:
        entity = entities_by_key.get(memory.entity_key)
        if entity is None:
            raise RuntimeError(f"Missing entity identity for memory {memory.memory_id}: {memory.entity_key}")
        payloads.append(_memory_payload(memory, identity_profile=dict(entity.identity_profile or {})))
    return payloads


def _missing_entity_keys(*, memories: list[Any], entities_by_key: dict[str, Any]) -> list[str]:
    memory_entity_keys = {str(memory.entity_key) for memory in memories if str(memory.entity_key or "").strip()}
    return sorted(memory_entity_keys - set(entities_by_key))


def _observation_payload(observation: Any) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "summary": observation.summary,
        "content": observation.content[:1000],
    }


def _normalize_relation_edges(*, relations: list[Any], valid_memory_ids: set[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        score = float(relation.weight or 0.0)
        from_id = str(relation.from_memory_id or "").strip()
        to_id = str(relation.to_memory_id or "").strip()
        if score < 0.2 or not from_id or not to_id or from_id == to_id:
            continue
        if from_id not in valid_memory_ids or to_id not in valid_memory_ids:
            continue
        if relation.edge_type in {"contradicts", "related_to"}:
            left_id = min(from_id, to_id)
            right_id = max(from_id, to_id)
            edge_key = (left_id, right_id, relation.edge_type)
            payload = {
                "from_id": left_id,
                "to_kind": "memory",
                "to_id": right_id,
                "edge_type": relation.edge_type,
                "weight": score,
                "reason": relation.reason,
            }
        else:
            edge_key = (from_id, to_id, relation.edge_type)
            payload = {
                "from_id": from_id,
                "to_kind": "memory",
                "to_id": to_id,
                "edge_type": relation.edge_type,
                "weight": score,
                "reason": relation.reason,
            }
        if edge_key in seen:
            continue
        seen.add(edge_key)
        normalized.append(payload)
    return normalized


def _sparsify_cross_entity_related_edges(
    *,
    edges: list[dict[str, Any]],
    frontier_ids: set[str],
    candidate_rank: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for edge in edges:
        if edge["edge_type"] != "related_to":
            passthrough.append(edge)
            continue
        frontier_id = None
        if edge["from_id"] in frontier_ids:
            frontier_id = edge["from_id"]
        elif edge["to_id"] in frontier_ids:
            frontier_id = edge["to_id"]
        if frontier_id is None:
            passthrough.append(edge)
            continue
        grouped.setdefault(frontier_id, []).append(edge)
    pruned = list(passthrough)
    for frontier_id, related_edges in grouped.items():
        def _rank_key(edge: dict[str, Any]) -> tuple[float, int]:
            other_id = edge["to_id"] if edge["from_id"] == frontier_id else edge["from_id"]
            rank = (candidate_rank or {}).get(other_id, 10**9)
            return (float(edge.get("weight") or 0.0), -rank)

        kept = [max(related_edges, key=_rank_key)]
        logger.info(
            "repair cross entity related edges sparsified",
            extra={
                "frontier_id": frontier_id,
                "input_count": len(related_edges),
                "kept_count": len(kept),
                "kept_other_ids": [
                    edge["to_id"] if edge["from_id"] == frontier_id else edge["from_id"]
                    for edge in kept
                ],
            },
        )
        pruned.extend(kept)
    return pruned


def _prune_weak_related_to_components(
    *,
    edges: list[dict[str, Any]],
    weight_margin: float = 0.15,
) -> list[dict[str, Any]]:
    related_edges = [edge for edge in edges if edge["edge_type"] == "related_to"]
    passthrough = [edge for edge in edges if edge["edge_type"] != "related_to"]
    if len(related_edges) <= 1:
        return list(edges)
    adjacency: dict[str, set[str]] = {}
    edge_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in related_edges:
        left = str(edge["from_id"])
        right = str(edge["to_id"])
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
        edge_by_pair[(min(left, right), max(left, right))] = edge
    visited: set[str] = set()
    kept_related: list[dict[str, Any]] = []
    for start in adjacency:
        if start in visited:
            continue
        stack = [start]
        component_nodes: set[str] = set()
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            component_nodes.add(node)
            stack.extend(neighbor for neighbor in adjacency.get(node, set()) if neighbor not in visited)
        component_edges = [
            edge
            for (left, right), edge in edge_by_pair.items()
            if left in component_nodes and right in component_nodes
        ]
        if len(component_edges) <= 1:
            kept_related.extend(component_edges)
            continue
        max_weight = max(float(edge.get("weight") or 0.0) for edge in component_edges)
        keep_threshold = max_weight - weight_margin
        component_kept = [
            edge
            for edge in component_edges
            if float(edge.get("weight") or 0.0) >= keep_threshold
        ]
        logger.info(
            "repair related_to component pruned",
            extra={
                "component_nodes": sorted(component_nodes),
                "input_count": len(component_edges),
                "kept_count": len(component_kept),
                "max_weight": max_weight,
                "keep_threshold": keep_threshold,
            },
        )
        kept_related.extend(component_kept)
    return passthrough + kept_related


def _has_record_markers(memory: Any | None) -> bool:
    if memory is None:
        return False
    markers = dict((memory.metadata_json or {}).get("record_markers") or {})
    return any(str(value or "").strip() for value in markers.values())


def _prune_cross_entity_historical_contradicts(
    *,
    edges: list[dict[str, Any]],
    memories_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    pruned: list[dict[str, Any]] = []
    for edge in edges:
        if edge["edge_type"] != "contradicts":
            pruned.append(edge)
            continue
        from_memory = memories_by_id.get(str(edge["from_id"]))
        to_memory = memories_by_id.get(str(edge["to_id"]))
        if _has_record_markers(from_memory) != _has_record_markers(to_memory):
            logger.info(
                "repair cross entity historical contradict pruned",
                extra={
                    "from_id": edge["from_id"],
                    "to_id": edge["to_id"],
                    "reason": edge.get("reason"),
                },
            )
            continue
        pruned.append(edge)
    return pruned


class RepairMemoryEdgesGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(
        self,
        *,
        memory_space: str,
        memory_id: str | None = None,
        entity_key: str | None = None,
    ) -> dict[str, Any]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "memory_id": memory_id,
                "entity_key": entity_key,
                "workers": MemoryWorkers(),
                "local_created_edges": 0,
                "deleted_relation_edges": 0,
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(RepairMemoryEdgesState)
        graph.add_node("load_graph_context", self._load_graph_context)
        graph.add_node("skip_missing_entity", self._skip_missing_entity)
        graph.add_node("finish_stale_entity", self._finish_stale_entity)
        graph.add_node("judge_local_graph", self._judge_local_graph)
        graph.add_node("write_local_graph", self._write_local_graph)
        graph.add_node("select_frontier_memories", self._select_frontier_memories)
        graph.add_node("retrieve_cross_entity_candidates", self._retrieve_cross_entity_candidates)
        graph.add_node("skip_cross_entity_graph", self._skip_cross_entity_graph)
        graph.add_node("judge_cross_entity_graph", self._judge_cross_entity_graph)
        graph.add_node("write_cross_entity_graph", self._write_cross_entity_graph)

        graph.set_entry_point("load_graph_context")
        graph.add_conditional_edges(
            "load_graph_context",
            self._after_load_graph_context,
            {
                "skip_missing_entity": "skip_missing_entity",
                "judge_local_graph": "judge_local_graph",
                "write_local_graph": "write_local_graph",
            },
        )
        graph.add_edge("skip_missing_entity", END)
        graph.add_edge("judge_local_graph", "write_local_graph")
        graph.add_edge("write_local_graph", "select_frontier_memories")
        graph.add_edge("select_frontier_memories", "retrieve_cross_entity_candidates")
        graph.add_conditional_edges(
            "retrieve_cross_entity_candidates",
            self._after_retrieve_cross_entity_candidates,
            {
                "finish_stale_entity": "finish_stale_entity",
                "skip_cross_entity_graph": "skip_cross_entity_graph",
                "judge_cross_entity_graph": "judge_cross_entity_graph",
            },
        )
        graph.add_edge("skip_cross_entity_graph", END)
        graph.add_conditional_edges(
            "judge_cross_entity_graph",
            self._after_judge_cross_entity_graph,
            {
                "finish_stale_entity": "finish_stale_entity",
                "write_cross_entity_graph": "write_cross_entity_graph",
            },
        )
        graph.add_edge("finish_stale_entity", END)
        graph.add_edge("write_cross_entity_graph", END)
        return graph.compile()

    async def _load_graph_context(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        entity_key = str(state.get("entity_key") or "").strip() or None
        memory_id = str(state.get("memory_id") or "").strip() or None
        async with MemoryRepository() as repository:
            if entity_key is None and memory_id is not None:
                source = await repository.get_memory(memory_space=state["memory_space"], memory_id=memory_id)
                if source is None:
                    return {"entity_key": None}
                entity_key = source.entity_key
            if entity_key is None:
                return {"entity_key": None}
            entity = await repository.get_entity(memory_space=state["memory_space"], entity_key=entity_key)
            if entity is None:
                return {"entity_key": None}
            memories = await repository.list_memories(
                memory_space=state["memory_space"],
                entity_key=entity_key,
                statuses=("active", "stale", "superseded"),
                limit=50,
            )
            observation_ids = list(
                dict.fromkeys(
                    memory.latest_source_observation_id
                    for memory in memories
                    if str(memory.latest_source_observation_id or "").strip()
                )
            )
            observations = await repository.get_observations_by_ids(
                memory_space=state["memory_space"],
                observation_ids=observation_ids,
            )
        return {
            "entity_key": entity_key,
            "entities_by_key": {entity.entity_key: entity},
            "memories": memories,
            "observations": observations,
        }

    @staticmethod
    def _after_load_graph_context(state: RepairMemoryEdgesState) -> str:
        if not state.get("entity_key") or not state.get("memories"):
            return "skip_missing_entity"
        if len(state.get("memories") or []) < 2:
            return "write_local_graph"
        return "judge_local_graph"

    async def _skip_missing_entity(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        logger.info(
            "repair memory edges skipped",
            extra={
                "memory_space": state["memory_space"],
                "memory_id": state.get("memory_id"),
                "entity_key": state.get("entity_key"),
            },
        )
        return {"result": {"created_edges": 0, "deleted_edges": 0}}

    async def _finish_stale_entity(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        logger.info(
            "repair memory edges finished stale entity task",
            extra={
                "memory_space": state["memory_space"],
                "memory_id": state.get("memory_id"),
                "entity_key": state.get("entity_key"),
            },
        )
        return {
            "result": {
                "created_edges": int(state.get("local_created_edges") or 0),
                "deleted_edges": int(state.get("deleted_relation_edges") or 0),
                "cross_entity_created_edges": 0,
            }
        }

    async def _judge_local_graph(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        logger.info(
            "repair local graph judging",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "memory_count": len(state.get("memories") or []),
                "observation_count": len(state.get("observations") or []),
            },
        )
        judged = await state["workers"].run_edge_judge(
            memory_space=state["memory_space"],
            request_id=get_or_create_request_id(),
            payload={
                "mode": "local_graph",
                "entity_key": state["entity_key"],
                "memories": _memory_payloads_with_identities(
                    memories=list(state.get("memories") or []),
                    entities_by_key=state.get("entities_by_key") or {},
                ),
                "observations": [
                    {
                        "observation_id": observation.observation_id,
                        "summary": observation.summary,
                    }
                    for observation in state.get("observations") or []
                ],
            },
        )
        logger.info(
            "repair local graph judged",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "relation_count": len(judged.relations),
            },
        )
        return {"local_judged": judged}

    async def _write_local_graph(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        memories = list(state.get("memories") or [])
        memory_ids = [memory.memory_id for memory in memories]
        local_edges = _normalize_relation_edges(
            relations=list((state.get("local_judged").relations if state.get("local_judged") is not None else [])),
            valid_memory_ids=set(memory_ids),
        )
        async with MemoryRepository() as repository:
            deleted_relation_edges = await repository.delete_relation_edges_for_memory_ids(
                memory_space=state["memory_space"],
                memory_ids=memory_ids,
            )
            created = await repository.create_edges(memory_space=state["memory_space"], edges=local_edges)
        logger.info(
            "repair local graph written",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "deleted_relation_edges": deleted_relation_edges,
                "created_edges": len(created),
                "edge_types": [edge["edge_type"] for edge in local_edges],
            },
        )
        return {
            "deleted_relation_edges": deleted_relation_edges,
            "local_created_edges": len(created),
        }

    async def _select_frontier_memories(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        memories = list(state.get("memories") or [])
        observations = {item.observation_id: item for item in state.get("observations") or []}
        active_memories = [memory for memory in memories if memory.status == "active"]
        ordered = active_memories or memories
        frontier = ordered[: min(len(ordered), settings.MEMORY_GRAPH_SUPPORTS_BUDGET)]
        frontier_observation_ids = list(
            dict.fromkeys(
                str(memory.latest_source_observation_id or "").strip()
                for memory in frontier
                if str(memory.latest_source_observation_id or "").strip()
            )
        )
        frontier_observations = [
            observations[observation_id]
            for observation_id in frontier_observation_ids
            if observation_id in observations
        ]
        logger.info(
            "repair frontier selected",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "frontier_memory_ids": [memory.memory_id for memory in frontier],
                "frontier_observation_ids": [item.observation_id for item in frontier_observations],
            },
        )
        return {"frontier_memories": frontier, "frontier_observations": frontier_observations}

    async def _retrieve_cross_entity_candidates(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        frontier_memories = list(state.get("frontier_memories") or [])
        if not frontier_memories:
            return {"cross_candidates": []}
        async with MemoryRepository() as repository:
            anchor_entity = await repository.get_entity(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
            )
            if anchor_entity is None:
                logger.info(
                    "repair cross entity candidates skipped stale anchor entity",
                    extra={
                        "memory_space": state["memory_space"],
                        "entity_key": state["entity_key"],
                        "frontier_memory_ids": [memory.memory_id for memory in frontier_memories],
                    },
                )
                return {"stale_entity": True, "cross_candidates": [], "cross_query_texts": []}
            all_memories = [
                memory
                for memory in await repository.list_all_memories(memory_space=state["memory_space"])
                if memory.entity_key != state["entity_key"] and memory.status in {"active", "stale", "superseded"}
            ]
            entities_by_key = {
                entity.entity_key: entity
                for entity in await repository.get_entities_by_keys(
                    memory_space=state["memory_space"],
                    entity_keys={memory.entity_key for memory in all_memories},
                )
            }
        if not all_memories:
            return {"cross_candidates": [], "cross_query_texts": []}
        frontier_observations = list(state.get("frontier_observations") or [])
        cross_query_plan = await state["workers"].run_cross_entity_query_builder(
            memory_space=state["memory_space"],
            request_id=get_or_create_request_id(),
            payload={
                "anchor_entity_key": state["entity_key"],
                "anchor_identity_profile": project_identity_profile(anchor_entity.identity_profile),
                "frontier_memories": _memory_payloads_with_identities(
                    memories=frontier_memories,
                    entities_by_key={anchor_entity.entity_key: anchor_entity},
                ),
                "frontier_observations": [_observation_payload(observation) for observation in frontier_observations],
            },
        )
        if not cross_query_plan.query_texts:
            logger.info(
                "repair cross entity candidates skipped by query builder",
                extra={
                    "memory_space": state["memory_space"],
                    "entity_key": state["entity_key"],
                    "frontier_memory_ids": [memory.memory_id for memory in frontier_memories],
                },
            )
            return {"cross_candidates": [], "cross_query_texts": []}
        base_query_texts = [
            memory.summary or memory.content
            for memory in frontier_memories
            if (memory.summary or memory.content)
        ]
        base_query_texts.extend(
            observation.summary or observation.content
            for observation in frontier_observations
            if (observation.summary or observation.content)
        )
        query_texts = dedupe_preserve_order(
            [*cross_query_plan.query_texts, *base_query_texts],
            limit=8,
        )
        if not query_texts:
            return {"cross_candidates": []}
        scored = await retrieval_index.memory_candidates(
            query_texts=query_texts,
            memories=all_memories,
            limit=max(8, settings.MEMORY_GRAPH_RELATED_TO_BUDGET + settings.MEMORY_GRAPH_SUPPORTS_BUDGET),
            entities_by_key=entities_by_key,
        )
        cross_candidates = [item.memory for item in scored]
        logger.info(
            "repair cross entity candidates retrieved",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "frontier_memory_ids": [memory.memory_id for memory in frontier_memories],
                "query_texts": query_texts,
                "candidate_count": len(cross_candidates),
                "candidate_entity_keys": [memory.entity_key for memory in cross_candidates],
            },
        )
        return {"cross_candidates": cross_candidates, "cross_query_texts": query_texts}

    @staticmethod
    def _after_retrieve_cross_entity_candidates(state: RepairMemoryEdgesState) -> str:
        if state.get("stale_entity"):
            return "finish_stale_entity"
        return "judge_cross_entity_graph" if state.get("cross_candidates") else "skip_cross_entity_graph"

    async def _skip_cross_entity_graph(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        logger.info(
            "repair cross entity graph skipped",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
            },
        )
        return {
            "result": {
                "created_edges": int(state.get("local_created_edges") or 0),
                "deleted_edges": int(state.get("deleted_relation_edges") or 0),
                "cross_entity_created_edges": 0,
            }
        }

    async def _judge_cross_entity_graph(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        frontier_memories = list(state.get("frontier_memories") or [])
        cross_candidates = list(state.get("cross_candidates") or [])
        async with MemoryRepository() as repository:
            entities = await repository.get_entities_by_keys(
                memory_space=state["memory_space"],
                entity_keys={memory.entity_key for memory in [*frontier_memories, *cross_candidates]},
            )
        entities_by_key = {entity.entity_key: entity for entity in entities}
        missing_frontier_entity_keys = _missing_entity_keys(
            memories=frontier_memories,
            entities_by_key=entities_by_key,
        )
        if missing_frontier_entity_keys:
            logger.info(
                "repair cross entity graph skipped stale frontier entity",
                extra={
                    "memory_space": state["memory_space"],
                    "entity_key": state["entity_key"],
                    "missing_entity_keys": missing_frontier_entity_keys,
                    "frontier_memory_ids": [memory.memory_id for memory in frontier_memories],
                },
            )
            return {"stale_entity": True, "cross_judged": None, "cross_candidates": []}
        missing_candidate_entity_keys = _missing_entity_keys(
            memories=cross_candidates,
            entities_by_key=entities_by_key,
        )
        if missing_candidate_entity_keys:
            cross_candidates = [memory for memory in cross_candidates if memory.entity_key in entities_by_key]
            logger.info(
                "repair cross entity graph dropped stale candidates",
                extra={
                    "memory_space": state["memory_space"],
                    "entity_key": state["entity_key"],
                    "missing_entity_keys": missing_candidate_entity_keys,
                    "remaining_candidate_count": len(cross_candidates),
                },
            )
            if not cross_candidates:
                return {"cross_judged": None, "cross_candidates": []}
        logger.info(
            "repair cross entity graph judging",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "frontier_count": len(frontier_memories),
                "candidate_count": len(cross_candidates),
            },
        )
        judged = await state["workers"].run_edge_judge(
            memory_space=state["memory_space"],
            request_id=get_or_create_request_id(),
            payload={
                "mode": "cross_entity_graph",
                "anchor_entity_key": state["entity_key"],
                "frontier_memories": _memory_payloads_with_identities(
                    memories=frontier_memories,
                    entities_by_key=entities_by_key,
                ),
                "candidate_memories": _memory_payloads_with_identities(
                    memories=cross_candidates,
                    entities_by_key=entities_by_key,
                ),
            },
        )
        logger.info(
            "repair cross entity graph judged",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "relation_count": len(judged.relations),
            },
        )
        return {"cross_judged": judged, "cross_candidates": cross_candidates}

    @staticmethod
    def _after_judge_cross_entity_graph(state: RepairMemoryEdgesState) -> str:
        if state.get("stale_entity"):
            return "finish_stale_entity"
        return "write_cross_entity_graph"

    async def _write_cross_entity_graph(self, state: RepairMemoryEdgesState) -> dict[str, Any]:
        frontier_ids = {memory.memory_id for memory in state.get("frontier_memories") or []}
        candidate_ids = {memory.memory_id for memory in state.get("cross_candidates") or []}
        candidate_rank = {
            memory.memory_id: idx
            for idx, memory in enumerate(state.get("cross_candidates") or [])
        }
        valid_memory_ids = frontier_ids | candidate_ids
        cross_edges = []
        for edge in _normalize_relation_edges(
            relations=list((state.get("cross_judged").relations if state.get("cross_judged") is not None else [])),
            valid_memory_ids=valid_memory_ids,
        ):
            if edge["from_id"] not in frontier_ids and edge["to_id"] not in frontier_ids:
                continue
            if edge["from_id"] not in candidate_ids and edge["to_id"] not in candidate_ids:
                continue
            cross_edges.append(edge)
        cross_edges = _sparsify_cross_entity_related_edges(
            edges=cross_edges,
            frontier_ids=frontier_ids,
            candidate_rank=candidate_rank,
        )
        memories_by_id = {
            memory.memory_id: memory
            for memory in [*list(state.get("frontier_memories") or []), *list(state.get("cross_candidates") or [])]
        }
        cross_edges = _prune_cross_entity_historical_contradicts(
            edges=cross_edges,
            memories_by_id=memories_by_id,
        )
        cross_edges = _prune_weak_related_to_components(edges=cross_edges)
        async with MemoryRepository() as repository:
            created = await repository.create_edges(memory_space=state["memory_space"], edges=cross_edges)
        logger.info(
            "repair cross entity graph written",
            extra={
                "memory_space": state["memory_space"],
                "entity_key": state["entity_key"],
                "created_edges": len(created),
                "edge_types": [edge["edge_type"] for edge in cross_edges],
            },
        )
        return {
            "result": {
                "created_edges": int(state.get("local_created_edges") or 0) + len(created),
                "deleted_edges": int(state.get("deleted_relation_edges") or 0),
                "cross_entity_created_edges": len(created),
            }
        }


repair_memory_edges_graph = RepairMemoryEdgesGraph()
