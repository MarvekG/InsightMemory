from __future__ import annotations

import asyncio

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from insight_memory.config import settings
from insight_memory.index.retrieval_index import RetrievalIndex
from insight_memory.storage.models import MemoryMemory
from tests.utils import run_async


def test_requested_top_k_uses_oversample(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_VECTOR_RECALL_OVERSAMPLE", 24)

    assert RetrievalIndex._requested_top_k(limit=10) == 24
    assert RetrievalIndex._requested_top_k(limit=30) == 30


def test_rrf_filters_low_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_VECTOR_RRF_K", 50)
    monkeypatch.setattr(settings, "MEMORY_SIMILARITY_MIN_SCORE", 0.5)
    node = TextNode(id_="node_1", text="content", metadata={"ref_doc_id": "memory:scope:mem_1"})

    fused = RetrievalIndex._rrf_fuse(
        ranked_lists=[[NodeWithScore(node=node, score=1.0)]],
        similarity_top_k=10,
    )

    assert fused == []


def test_vector_retrieve_filters_low_dense_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_VECTOR_DENSE_MIN_SCORE", 0.5)
    index = RetrievalIndex()
    low = TextNode(id_="low", text="low", metadata={"ref_doc_id": "memory:scope:low"})
    high = TextNode(id_="high", text="high", metadata={"ref_doc_id": "memory:scope:high"})

    class _Store:
        async def query_nodes(self, **kwargs):
            del kwargs
            return [
                NodeWithScore(node=low, score=0.49),
                NodeWithScore(node=high, score=0.5),
            ]

    index._pgvector_store = _Store()

    result = run_async(index._vector_retrieve(query_text="query", ref_doc_ids=["a", "b"], similarity_top_k=2))

    assert [item.node.node_id for item in result] == ["high"]


def test_memory_candidates_runs_bm25_and_vector_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_VECTOR_DENSE_MIN_SCORE", 0.0)
    monkeypatch.setattr(settings, "MEMORY_SIMILARITY_MIN_SCORE", 0.0)
    index = RetrievalIndex()
    memory = MemoryMemory(
        memory_id="mem_parallel",
        memory_space="workspace:parallel",
        entity_key="ent_parallel",
        title="Parallel recall",
        summary="Parallel recall summary",
        content="Parallel recall content",
        confidence=0.9,
        salience=0.9,
        status="active",
        updated_at=1.0,
    )
    bm25_node = TextNode(
        id_="memory:workspace:parallel:mem_parallel",
        text="bm25",
        metadata={"ref_doc_id": "memory:workspace:parallel:mem_parallel"},
    )
    vector_node = TextNode(
        id_="memory:workspace:parallel:mem_parallel",
        text="vector",
        metadata={"ref_doc_id": "memory:workspace:parallel:mem_parallel"},
    )
    active = {"count": 0, "peak": 0}

    async def fake_ensure_memories_indexed(**kwargs) -> None:
        del kwargs

    async def fake_effective_top_k(**kwargs) -> int:
        del kwargs
        return 10

    async def fake_bm25_retrieve(**kwargs):
        del kwargs
        active["count"] += 1
        active["peak"] = max(active["peak"], active["count"])
        await asyncio.sleep(0.01)
        active["count"] -= 1
        return [NodeWithScore(node=bm25_node, score=1.0)]

    async def fake_vector_retrieve(**kwargs):
        del kwargs
        active["count"] += 1
        active["peak"] = max(active["peak"], active["count"])
        await asyncio.sleep(0.01)
        active["count"] -= 1
        return [NodeWithScore(node=vector_node, score=1.0)]

    monkeypatch.setattr(index, "_ensure_memories_indexed", fake_ensure_memories_indexed)
    monkeypatch.setattr(index, "_effective_top_k", fake_effective_top_k)
    monkeypatch.setattr(index, "_bm25_retrieve", fake_bm25_retrieve)
    monkeypatch.setattr(index, "_vector_retrieve", fake_vector_retrieve)

    scored = run_async(index.memory_candidates(query_texts=["query"], memories=[memory], limit=1))

    assert scored[0].memory.memory_id == "mem_parallel"
    assert active["peak"] == 2
