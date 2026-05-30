from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable

from llama_index.core.schema import NodeRelationship, NodeWithScore, RelatedNodeInfo, TextNode
from llama_index.core.vector_stores.types import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
    VectorStoreQueryMode,
)
from llama_index.retrievers.bm25 import BM25Retriever

from insight_memory.config import settings
from insight_memory.index.llamaindex_pgvector import LlamaIndexPGVectorRetrievalStore
from insight_memory.storage.models import MemoryEntity, MemoryMemory
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.text import normalize_text


logger = get_logger(__name__)


def project_identity_profile(profile: dict[str, Any] | None) -> str:
    payload = dict(profile or {})
    who = normalize_text(payload.get("who"))
    definition = normalize_text(payload.get("definition"))
    surface_forms = [normalize_text(item) for item in payload.get("surface_forms") or []]
    stable_qualifiers = [normalize_text(item) for item in payload.get("stable_qualifiers") or []]
    parts = [
        f"who: {who}" if who else "",
        f"definition: {definition}" if definition else "",
        f"surface_forms: {' | '.join(item for item in surface_forms if item)}" if surface_forms else "",
        (
            f"stable_qualifiers: {' | '.join(item for item in stable_qualifiers if item)}"
            if stable_qualifiers
            else ""
        ),
    ]
    return "\n".join(part for part in parts if part).strip()


def project_memory(memory: MemoryMemory, *, entity: MemoryEntity | None = None) -> str:
    entity_identity = project_identity_profile(entity.identity_profile if entity is not None else {})
    return "\n".join(
        part
        for part in [entity_identity, memory.title, memory.summary, memory.content]
        if normalize_text(part)
    ).strip()


def entity_ref_doc_id(*, memory_space: str, entity_key: str) -> str:
    return f"entity:{memory_space}:{entity_key}"


def memory_ref_doc_id(*, memory_space: str, memory_id: str) -> str:
    return f"memory:{memory_space}:{memory_id}"


@dataclass(slots=True)
class ScoredEntity:
    entity: MemoryEntity
    score: float
    node_scores: list[NodeWithScore]


@dataclass(slots=True)
class ScoredMemory:
    memory: MemoryMemory
    score: float
    node_scores: list[NodeWithScore]


class RetrievalIndex:
    _BM25_TOKEN_PATTERN = r"[A-Za-z0-9_]+|[\u4e00-\u9fff]"

    def __init__(self) -> None:
        self._pgvector_store = LlamaIndexPGVectorRetrievalStore()
        self._lock = asyncio.Lock()

    async def clear(self) -> None:
        async with self._lock:
            await self._pgvector_store.initialize()
            await self._pgvector_store.clear()

    async def reset_storage(self) -> None:
        """重建底层 pgvector 表，用于 embedding 或投影版本变化后的内部全量重建。"""

        async with self._lock:
            await self._pgvector_store.reset_table()

    async def refresh_entities(self, *, entities: Iterable[MemoryEntity]) -> None:
        async with self._lock:
            await self._pgvector_store.initialize()
            await self._refresh_entities_locked(entities=list(entities))

    async def refresh_memories(
        self,
        *,
        memories: Iterable[MemoryMemory],
        entities_by_key: dict[str, MemoryEntity] | None = None,
    ) -> None:
        async with self._lock:
            await self._pgvector_store.initialize()
            await self._refresh_memories_locked(memories=list(memories), entities_by_key=entities_by_key)

    async def delete_entities(self, *, memory_space: str, entity_keys: Iterable[str]) -> None:
        async with self._lock:
            await self._pgvector_store.initialize()
            await self._pgvector_store.delete_ref_doc_ids(
                entity_ref_doc_id(memory_space=memory_space, entity_key=entity_key)
                for entity_key in entity_keys
            )

    async def delete_memories(self, *, memory_space: str, memory_ids: Iterable[str]) -> None:
        async with self._lock:
            await self._pgvector_store.initialize()
            await self._pgvector_store.delete_ref_doc_ids(
                memory_ref_doc_id(memory_space=memory_space, memory_id=memory_id)
                for memory_id in memory_ids
            )

    async def entity_candidates(
        self,
        *,
        memory_space: str,
        draft: dict[str, Any],
        limit: int = 10,
    ) -> list[ScoredEntity]:
        draft_text = project_identity_profile(draft)
        if not draft_text:
            return []
        filters = _metadata_filters(kind="entity", memory_space=memory_space)
        retrieval_top_k = self._requested_top_k(limit=limit)
        vector_nodes = await self._vector_retrieve(
            query_text=draft_text,
            similarity_top_k=retrieval_top_k,
            filters=filters,
        )
        if not vector_nodes:
            return []
        fused_nodes = self._rrf_fuse(
            ranked_lists=[vector_nodes],
            similarity_top_k=retrieval_top_k,
        )
        score_by_ref_doc = self._aggregate_ref_doc_scores(fused_nodes)
        nodes_by_ref_doc = self._group_ref_doc_node_scores(fused_nodes)
        entity_keys = [
            _entity_key_from_ref_doc_id(ref_doc_id)
            for ref_doc_id in score_by_ref_doc
            if _entity_key_from_ref_doc_id(ref_doc_id)
        ]
        async with MemoryRepository() as repository:
            entities = await repository.get_entities_by_keys(memory_space=memory_space, entity_keys=entity_keys)
        entities_by_key = {entity.entity_key: entity for entity in entities}
        scored: list[ScoredEntity] = []
        for entity_key in entity_keys:
            entity = entities_by_key.get(entity_key)
            if entity is None:
                continue
            doc_id = entity_ref_doc_id(memory_space=entity.memory_space, entity_key=entity.entity_key)
            score = score_by_ref_doc.get(doc_id, 0.0)
            if score <= 0:
                continue
            node_scores = nodes_by_ref_doc.get(doc_id, [])
            scored.append(ScoredEntity(entity=entity, score=score, node_scores=node_scores))
        scored.sort(key=lambda item: (item.score, item.entity.updated_at), reverse=True)
        return scored[:limit]

    async def memory_candidates(
        self,
        *,
        query_texts: list[str],
        memories: list[MemoryMemory],
        limit: int,
        entities_by_key: dict[str, MemoryEntity] | None = None,
    ) -> list[ScoredMemory]:
        await self._ensure_memories_indexed(memories=memories, entities_by_key=entities_by_key)
        query_corpus = "\n".join(normalize_text(item) for item in query_texts if normalize_text(item))
        ref_doc_ids = [
            memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id)
            for memory in memories
        ]
        retrieval_top_k = await self._effective_top_k(
            ref_doc_ids=ref_doc_ids,
            requested=self._requested_top_k(limit=limit),
        )
        bm25_nodes, vector_nodes = await asyncio.gather(
            self._bm25_retrieve(query_text=query_corpus, ref_doc_ids=ref_doc_ids, similarity_top_k=retrieval_top_k),
            self._vector_retrieve(
                query_text=query_corpus,
                ref_doc_ids=ref_doc_ids,
                similarity_top_k=retrieval_top_k,
            ),
        )
        if not bm25_nodes and not vector_nodes:
            return []
        fused_nodes = self._rrf_fuse(
            ranked_lists=[bm25_nodes, vector_nodes],
            similarity_top_k=retrieval_top_k,
        )
        score_by_ref_doc = self._aggregate_ref_doc_scores(fused_nodes)
        nodes_by_ref_doc = self._group_ref_doc_node_scores(fused_nodes)
        scored: list[ScoredMemory] = []
        for memory in memories:
            doc_id = memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id)
            score = score_by_ref_doc.get(doc_id, 0.0)
            if score <= 0:
                continue
            node_scores = nodes_by_ref_doc.get(doc_id, [])
            scored.append(ScoredMemory(memory=memory, score=score, node_scores=node_scores))
        scored.sort(
            key=lambda item: (
                item.score,
                1 if item.memory.status == "active" else 0,
                item.memory.salience,
                item.memory.confidence,
                item.memory.updated_at,
            ),
            reverse=True,
        )
        return scored[:limit]

    async def health(self) -> dict[str, str | int]:
        await self._pgvector_store.initialize()
        return {"status": "ok", "backend": "pgvector"}

    async def _get_ref_doc_nodes(self, ref_doc_ids: list[str]) -> list[TextNode]:
        return await self._pgvector_store.get_nodes_by_ref_doc_ids(ref_doc_ids)

    async def _build_bm25_retriever(self, *, ref_doc_ids: list[str], similarity_top_k: int) -> BM25Retriever | None:
        nodes = await self._get_ref_doc_nodes(ref_doc_ids)
        if not nodes:
            return None
        effective_top_k = min(max(int(similarity_top_k), 1), len(nodes))
        return await asyncio.to_thread(
            BM25Retriever.from_defaults,
            nodes=nodes,
            similarity_top_k=effective_top_k,
            skip_stemming=True,
            token_pattern=self._BM25_TOKEN_PATTERN,
        )

    async def _bm25_retrieve(
        self,
        *,
        query_text: str,
        ref_doc_ids: list[str],
        similarity_top_k: int,
    ) -> list[NodeWithScore]:
        bm25_retriever = await self._build_bm25_retriever(
            ref_doc_ids=ref_doc_ids,
            similarity_top_k=similarity_top_k,
        )
        if bm25_retriever is None:
            return []
        nodes = await asyncio.to_thread(bm25_retriever.retrieve, query_text)
        return [node for node in nodes if float(node.score or 0.0) > 0]

    async def _effective_top_k(self, *, ref_doc_ids: list[str], requested: int) -> int:
        node_count = len(await self._get_ref_doc_nodes(ref_doc_ids))
        if node_count <= 0:
            return 1
        return min(max(int(requested), 1), node_count)

    @staticmethod
    def _requested_top_k(*, limit: int) -> int:
        return max(int(limit), int(settings.MEMORY_VECTOR_RECALL_OVERSAMPLE))

    async def _ensure_entities_indexed(self, *, entities: list[MemoryEntity]) -> None:
        """只刷新缺失或落后于数据库行的 entity 候选索引。

        候选召回需要看到刚写入的 entity，即使后台 reindex 任务还没执行。
        每个向量节点都会保存来源行的 updated_at，因此这里可以用当前 DB
        行和已索引节点做版本比较，只 upsert 过期候选，避免每次查询都重建
        整个候选集合。初次检查不占全局写锁，只有发现缺失或过期节点时才
        进入锁内二次确认并写入，减少并发 recall 之间的串行等待。
        """

        if not entities:
            return
        expected_updated_at = {
            entity_ref_doc_id(memory_space=entity.memory_space, entity_key=entity.entity_key): _updated_at_timestamp(
                entity.updated_at
            )
            for entity in entities
        }
        stale_ref_doc_ids = await self._stale_ref_doc_ids(expected_updated_at=expected_updated_at)
        if not stale_ref_doc_ids:
            return
        stale_entities = [
            entity
            for entity in entities
            if entity_ref_doc_id(memory_space=entity.memory_space, entity_key=entity.entity_key) in stale_ref_doc_ids
        ]
        async with self._lock:
            remaining_stale_ref_doc_ids = await self._stale_ref_doc_ids(expected_updated_at=expected_updated_at)
            if not remaining_stale_ref_doc_ids:
                return
            await self._refresh_entities_locked(
                entities=[
                    entity
                    for entity in stale_entities
                    if entity_ref_doc_id(memory_space=entity.memory_space, entity_key=entity.entity_key)
                    in remaining_stale_ref_doc_ids
                ]
            )

    async def _ensure_memories_indexed(
        self,
        *,
        memories: list[MemoryMemory],
        entities_by_key: dict[str, MemoryEntity] | None = None,
    ) -> None:
        """只刷新缺失或落后于数据库行的 memory 候选索引。

        recall 可能早于 debounce 后的 reindex 任务执行。为避免漏掉新写入的
        memory，这里检查每个候选是否存在向量节点，以及节点 metadata.updated_at
        是否等于当前 DB 行的 updated_at。只有缺失或过期的候选会重新 embedding
        并 upsert，从而保证读路径正确，同时避免每次候选查询都全量重建索引。
        初次检查不占全局写锁，只有需要写入时才进入锁内二次确认，避免大量
        并发 recall 因纯读取索引状态而串行。
        """

        if not memories:
            return
        expected_updated_at = {
            memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id): _updated_at_timestamp(
                memory.updated_at
            )
            for memory in memories
        }
        stale_ref_doc_ids = await self._stale_ref_doc_ids(expected_updated_at=expected_updated_at)
        if not stale_ref_doc_ids:
            return
        stale_memories = [
            memory
            for memory in memories
            if memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id) in stale_ref_doc_ids
        ]
        async with self._lock:
            remaining_stale_ref_doc_ids = await self._stale_ref_doc_ids(expected_updated_at=expected_updated_at)
            if not remaining_stale_ref_doc_ids:
                return
            await self._refresh_memories_locked(
                memories=[
                    memory
                    for memory in stale_memories
                    if memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id)
                    in remaining_stale_ref_doc_ids
                ],
                entities_by_key=entities_by_key,
            )

    async def _stale_ref_doc_ids(self, *, expected_updated_at: dict[str, float]) -> set[str]:
        """返回索引中缺失或 updated_at 标记过期的 ref_doc_id。"""

        await self._pgvector_store.initialize()
        nodes = await self._pgvector_store.get_nodes_by_ref_doc_ids(list(expected_updated_at))
        indexed_updated_at = {
            str(node.metadata.get("ref_doc_id") or ""): _metadata_timestamp(node.metadata.get("updated_at"))
            for node in nodes
        }
        return {
            ref_doc_id
            for ref_doc_id, updated_at in expected_updated_at.items()
            if indexed_updated_at.get(ref_doc_id) != updated_at
        }

    async def _refresh_entities_locked(self, *, entities: list[MemoryEntity]) -> None:
        nodes: list[TextNode] = []
        for entity in entities:
            doc_id = entity_ref_doc_id(memory_space=entity.memory_space, entity_key=entity.entity_key)
            nodes.append(
                TextNode(
                    id_=doc_id,
                    text=project_identity_profile(entity.identity_profile),
                    metadata={
                        "kind": "entity",
                        "ref_doc_id": doc_id,
                        "memory_space": entity.memory_space,
                        "entity_key": entity.entity_key,
                        "display_name": entity.display_name,
                        "updated_at": _updated_at_timestamp(entity.updated_at),
                    },
                    relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=doc_id)},
                )
            )
        await self._pgvector_store.upsert_nodes(nodes)

    async def _refresh_memories_locked(
        self,
        *,
        memories: list[MemoryMemory],
        entities_by_key: dict[str, MemoryEntity] | None = None,
    ) -> None:
        nodes: list[TextNode] = []
        for memory in memories:
            doc_id = memory_ref_doc_id(memory_space=memory.memory_space, memory_id=memory.memory_id)
            entity = entities_by_key.get(memory.entity_key) if entities_by_key is not None else None
            nodes.append(
                TextNode(
                    id_=doc_id,
                    text=project_memory(memory, entity=entity),
                    metadata={
                        "kind": "memory",
                        "ref_doc_id": doc_id,
                        "memory_space": memory.memory_space,
                        "memory_id": memory.memory_id,
                        "entity_key": memory.entity_key,
                        "status": memory.status,
                        "updated_at": _updated_at_timestamp(memory.updated_at),
                    },
                    relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id=doc_id)},
                )
            )
        await self._pgvector_store.upsert_nodes(nodes)

    async def _vector_retrieve(
        self,
        *,
        query_text: str,
        similarity_top_k: int,
        ref_doc_ids: list[str] | None = None,
        filters: MetadataFilters | None = None,
    ) -> list[NodeWithScore]:
        try:
            nodes = await self._pgvector_store.query_nodes(
                query_text=query_text,
                similarity_top_k=similarity_top_k,
                ref_doc_ids=ref_doc_ids,
                filters=filters,
                mode=VectorStoreQueryMode.DEFAULT,
            )
            min_score = float(settings.MEMORY_VECTOR_DENSE_MIN_SCORE)
            return [node for node in nodes if float(node.score or 0.0) >= min_score]
        except Exception:
            logger.exception("vector retrieval failed")
            raise

    async def _text_retrieve(
        self,
        *,
        query_text: str,
        similarity_top_k: int,
        ref_doc_ids: list[str] | None = None,
        filters: MetadataFilters | None = None,
    ) -> list[NodeWithScore]:
        try:
            nodes = await self._pgvector_store.query_nodes(
                query_text=query_text,
                similarity_top_k=similarity_top_k,
                ref_doc_ids=ref_doc_ids,
                filters=filters,
                mode=VectorStoreQueryMode.TEXT_SEARCH,
            )
            min_score = float(settings.MEMORY_VECTOR_LEXICAL_MIN_SCORE)
            return [node for node in nodes if float(node.score or 0.0) >= min_score]
        except Exception:
            logger.exception("text retrieval failed")
            raise

    @staticmethod
    def _rrf_fuse(*, ranked_lists: list[list[NodeWithScore]], similarity_top_k: int) -> list[NodeWithScore]:
        scores_by_node_id: dict[str, float] = {}
        nodes_by_node_id: dict[str, Any] = {}
        rrf_k = float(settings.MEMORY_VECTOR_RRF_K)
        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                node_id = str(item.node.node_id)
                nodes_by_node_id.setdefault(node_id, item.node)
                scores_by_node_id[node_id] = scores_by_node_id.get(node_id, 0.0) + (1.0 / (rrf_k + rank))
        fused = [
            NodeWithScore(node=nodes_by_node_id[node_id], score=score)
            for node_id, score in scores_by_node_id.items()
            if score >= float(settings.MEMORY_SIMILARITY_MIN_SCORE)
        ]
        fused.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return fused[: max(int(similarity_top_k), 1)]

    @staticmethod
    def _aggregate_ref_doc_scores(nodes: list[NodeWithScore]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for item in nodes:
            ref_doc_id = str(item.node.metadata.get("ref_doc_id") or "")
            if not ref_doc_id:
                continue
            score = float(item.score or 0.0)
            if score > scores.get(ref_doc_id, 0.0):
                scores[ref_doc_id] = score
        return scores

    @staticmethod
    def _group_ref_doc_node_scores(nodes: list[NodeWithScore]) -> dict[str, list[NodeWithScore]]:
        grouped: dict[str, list[NodeWithScore]] = {}
        for item in nodes:
            ref_doc_id = str(item.node.metadata.get("ref_doc_id") or "")
            if not ref_doc_id:
                continue
            grouped.setdefault(ref_doc_id, []).append(item)
        for items in grouped.values():
            items.sort(key=lambda item: float(item.score or 0.0), reverse=True)
        return grouped


retrieval_index = RetrievalIndex()


def _metadata_filters(*, kind: str, memory_space: str) -> MetadataFilters:
    return MetadataFilters(
        filters=[
            MetadataFilter(key="kind", value=kind, operator=FilterOperator.EQ),
            MetadataFilter(key="memory_space", value=memory_space, operator=FilterOperator.EQ),
        ],
        condition=FilterCondition.AND,
    )


def _entity_key_from_ref_doc_id(ref_doc_id: str) -> str | None:
    normalized = str(ref_doc_id or "").strip()
    if not normalized.startswith("entity:"):
        return None
    remainder = normalized[len("entity:") :]
    _, _, entity_key = remainder.rpartition(":")
    return entity_key or None


def _updated_at_timestamp(value: Any) -> float:
    """把模型 updated_at 转成写入索引 metadata 的秒级时间戳。"""

    return float(value.timestamp()) if hasattr(value, "timestamp") else float(value or 0)


def _metadata_timestamp(value: Any) -> float:
    """把索引 metadata 中的 updated_at 转成可比较的秒级时间戳。"""

    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
