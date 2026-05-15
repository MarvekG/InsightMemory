from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.vector_stores import VectorStoreQuery
from llama_index.core.vector_stores.types import MetadataFilters, VectorStoreQueryMode
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import bindparam, text
from sqlalchemy.engine import make_url

from insight_memory.config import settings
from insight_memory.index.constants import MEMORY_VECTOR_TABLE
from insight_memory.services.embedding_service import embedding_service
from insight_memory.storage import database as database_module
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)


class LlamaIndexPGVectorRetrievalStore:
    """LlamaIndex PGVectorStore adapter used by the memory retrieval index."""

    def __init__(self) -> None:
        self._store: PGVectorStore | None = None
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def clear(self) -> None:
        """Delete all vector index rows."""

        await self.initialize()
        logger.info("pgvector clear started", extra={"table_name": MEMORY_VECTOR_TABLE})
        await self._vector_store().aclear()
        logger.info("pgvector clear completed", extra={"table_name": MEMORY_VECTOR_TABLE})

    async def reset_table(self) -> None:
        """Clear the vector index through PGVectorStore before a full rebuild."""

        logger.info(
            "pgvector table reset started",
            extra={"schema_name": database_module.schema_name(), "table_name": MEMORY_VECTOR_TABLE},
        )
        await self.initialize()
        await self._vector_store().aclear()
        logger.info(
            "pgvector table reset completed",
            extra={"schema_name": database_module.schema_name(), "table_name": MEMORY_VECTOR_TABLE},
        )

    async def initialize(self) -> None:
        """
        Initialize pgvector schema, extension and table.
        """

        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            backend_name = make_url(settings.MEMORY_DATABASE_URL).get_backend_name()
            if backend_name != "postgresql":
                raise RuntimeError(
                    "MEMORY_DATABASE_URL must point to PostgreSQL with pgvector enabled; "
                    f"got backend '{backend_name}'."
                )
            store = self._vector_store()
            logger.info(
                "pgvector initialization started",
                extra={
                    "database_url": make_url(settings.MEMORY_DATABASE_URL).render_as_string(hide_password=True),
                    "schema_name": database_module.schema_name(),
                    "table_name": MEMORY_VECTOR_TABLE,
                },
            )
            try:
                await self._setup_backend(store=store)
                await store.aget_nodes(node_ids=["__memory_startup_probe__"])
            except Exception as exc:
                logger.exception(
                    "pgvector initialization failed",
                    extra={
                        "schema_name": database_module.schema_name(),
                        "table_name": MEMORY_VECTOR_TABLE,
                    },
                )
                raise RuntimeError(
                    "Failed to initialize pgvector retrieval backend. "
                    "Check PostgreSQL connectivity, pgvector extension, and table permissions."
                ) from exc
            self._initialized = True
            logger.info(
                "pgvector initialization completed",
                extra={"schema_name": database_module.schema_name(), "table_name": MEMORY_VECTOR_TABLE},
            )

    async def _setup_backend(self, *, store: PGVectorStore) -> None:
        """Ensure pgvector extension, schema, and table exist using the async engine only."""

        schema = database_module.schema_name()
        async with database_module.async_engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            if schema:
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
            await conn.run_sync(store._base.metadata.create_all)

    async def upsert_nodes(self, nodes: list[TextNode]) -> None:
        """
        Delete and add nodes by ref_doc_id.

        Args:
            nodes: Nodes with text and metadata ready for indexing.
        """

        await self.initialize()
        ref_doc_ids = [str(node.metadata["ref_doc_id"]) for node in nodes]
        logger.info(
            "pgvector upsert started",
            extra={
                "node_count": len(nodes),
                "ref_doc_count": len(_dedupe_non_empty(ref_doc_ids)),
            },
        )
        indexed_nodes = [node for node in nodes if node.text.strip()]
        if not indexed_nodes:
            logger.info("pgvector upsert skipped empty nodes", extra={"node_count": len(nodes)})
            await self.delete_ref_doc_ids(ref_doc_ids)
            return
        texts = [node.text for node in indexed_nodes]
        embeddings = await embedding_service.embed_texts(texts)
        _validate_embedding_dimensions(embeddings)
        for node, embedding in zip(indexed_nodes, embeddings, strict=True):
            node.embedding = embedding
        await self.delete_ref_doc_ids(ref_doc_ids)
        await self._vector_store().async_add(indexed_nodes)
        logger.info(
            "pgvector upsert completed",
            extra={
                "indexed_node_count": len(indexed_nodes),
                "vector_count": len(embeddings),
            },
        )

    async def delete_ref_doc_ids(self, ref_doc_ids: Iterable[str]) -> None:
        """
        Delete indexed documents by ref_doc_id.

        Args:
            ref_doc_ids: Stable retrieval document ids.
        """

        await self.initialize()
        deduped_ref_doc_ids = _dedupe_non_empty(ref_doc_ids)
        if not deduped_ref_doc_ids:
            return
        logger.info("pgvector delete started", extra={"ref_doc_count": len(deduped_ref_doc_ids)})
        for ref_doc_id in deduped_ref_doc_ids:
            await self._vector_store().adelete(ref_doc_id)
        logger.info("pgvector delete completed", extra={"ref_doc_count": len(deduped_ref_doc_ids)})

    async def get_nodes_by_ref_doc_ids(self, ref_doc_ids: list[str]) -> list[TextNode]:
        """
        Load indexed nodes from PGVectorStore by ref_doc_id.

        Args:
            ref_doc_ids: Stable retrieval document ids.

        Returns:
            Text nodes in vector-store order.
        """

        await self.initialize()
        ids = _dedupe_non_empty(ref_doc_ids)
        if not ids:
            return []
        logger.info("pgvector load nodes started", extra={"ref_doc_count": len(ids)})
        nodes = await self._vector_store().aget_nodes(node_ids=ids)
        text_nodes = [node for node in nodes if isinstance(node, TextNode)]
        logger.info(
            "pgvector load nodes completed",
            extra={"ref_doc_count": len(ids), "node_count": len(text_nodes)},
        )
        return text_nodes

    async def query_nodes(
        self,
        *,
        query_text: str,
        similarity_top_k: int,
        ref_doc_ids: list[str] | None = None,
        filters: MetadataFilters | None = None,
        mode: VectorStoreQueryMode = VectorStoreQueryMode.DEFAULT,
    ) -> list[NodeWithScore]:
        """
        Run retrieval against PGVectorStore.

        Args:
            query_text: Recall query.
            similarity_top_k: Max result count.
            ref_doc_ids: Optional retrieval document ids used as an extra filter.
            filters: Optional metadata filters.
            mode: Retrieval mode.

        Returns:
            Scored nodes returned by the vector store.
        """

        await self.initialize()
        ids = _dedupe_non_empty(ref_doc_ids or [])
        if not query_text.strip():
            return []
        if not ids and filters is None:
            return []
        logger.info(
            "pgvector query started",
            extra={
                "query_length": len(query_text),
                "ref_doc_count": len(ids),
                "has_filters": filters is not None,
                "mode": mode.value,
                "similarity_top_k": max(int(similarity_top_k), 1),
            },
        )
        query_embedding: list[float] | None = None
        if mode in {VectorStoreQueryMode.DEFAULT, VectorStoreQueryMode.HYBRID, VectorStoreQueryMode.MMR}:
            query_embedding = await embedding_service.embed_text(query_text)
            _validate_embedding_dimensions([query_embedding])
        result = await self._vector_store().aquery(
            VectorStoreQuery(
                query_embedding=query_embedding,
                query_str=query_text,
                similarity_top_k=max(int(similarity_top_k), 1),
                mode=mode,
                filters=filters,
            ),
            ref_doc_ids=ids or None,
        )
        nodes = list(result.nodes or [])
        similarities = list(result.similarities or [])
        scored: list[NodeWithScore] = []
        for index, node in enumerate(nodes):
            score = similarities[index] if index < len(similarities) else None
            scored.append(NodeWithScore(node=node, score=score))
        logger.info(
            "pgvector query completed",
            extra={
                "query_length": len(query_text),
                "ref_doc_count": len(ids),
                "has_filters": filters is not None,
                "mode": mode.value,
                "result_count": len(scored),
            },
        )
        return scored

    def _vector_store(self) -> PGVectorStore:
        if self._store is None:
            logger.info(
                "creating pgvector store",
                extra={
                    "schema_name": database_module.schema_name(),
                    "table_name": MEMORY_VECTOR_TABLE,
                    "embedding_dim": settings.MEMORY_EMBEDDING_DIM,
                },
            )
            async_database_url = database_module.async_database_url(settings.MEMORY_DATABASE_URL)
            self._store = PGVectorStore(
                connection_string=settings.MEMORY_DATABASE_URL,
                async_connection_string=async_database_url,
                table_name=MEMORY_VECTOR_TABLE,
                schema_name=database_module.schema_name(),
                embed_dim=settings.MEMORY_EMBEDDING_DIM,
                perform_setup=False,
                use_jsonb=True,
                initialization_fail_on_error=True,
                create_engine_kwargs={"pool_pre_ping": True},
                customize_query_fn=_customize_query_with_ref_doc_ids,
                indexed_metadata_keys={
                    ("ref_doc_id", "text"),
                    ("kind", "text"),
                    ("memory_space", "text"),
                    ("entity_key", "text"),
                    ("memory_id", "text"),
                    ("status", "text"),
                },
            )
        return self._store


def _dedupe_non_empty(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _validate_embedding_dimensions(embeddings: list[list[float]]) -> None:
    """Validate embedding dimensions before mutating pgvector rows."""

    expected_dim = int(settings.MEMORY_EMBEDDING_DIM)
    for index, embedding in enumerate(embeddings):
        actual_dim = len(embedding)
        if actual_dim != expected_dim:
            raise RuntimeError(
                f"Embedding dimension mismatch at index {index}: expected {expected_dim}, got {actual_dim}."
            )


def _customize_query_with_ref_doc_ids(stmt: Any, table_class: Any, **kwargs: Any) -> Any:
    """Apply a parameterized ref_doc_id filter inside LlamaIndex PGVectorStore queries."""

    ref_doc_ids = _dedupe_non_empty(kwargs.get("ref_doc_ids") or [])
    if not ref_doc_ids:
        return stmt
    ref_doc_id_filter = table_class.metadata_["ref_doc_id"].astext.in_(
        bindparam("ref_doc_ids", value=ref_doc_ids, expanding=True)
    )
    return stmt.where(ref_doc_id_filter)
