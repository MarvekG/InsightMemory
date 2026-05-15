from __future__ import annotations

import pytest
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.core.vector_stores.utils import node_to_metadata_dict

from insight_memory.config import settings
from insight_memory.index.llamaindex_pgvector import _validate_embedding_dimensions


def test_validate_embedding_dimensions_rejects_mismatch() -> None:
    with pytest.raises(RuntimeError, match="Embedding dimension mismatch"):
        _validate_embedding_dimensions([[0.0] * (settings.MEMORY_EMBEDDING_DIM + 1)])


def test_llamaindex_standard_source_relationship_writes_ref_doc_id() -> None:
    node = TextNode(
        id_="memory:scope:mem_1",
        text="content",
        metadata={"kind": "memory"},
        relationships={NodeRelationship.SOURCE: RelatedNodeInfo(node_id="memory:scope:mem_1")},
    )

    metadata = node_to_metadata_dict(node, remove_text=True, flat_metadata=False)

    assert metadata["ref_doc_id"] == "memory:scope:mem_1"
