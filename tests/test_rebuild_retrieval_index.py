from __future__ import annotations

from insight_memory.graph import rebuild_retrieval_index_graph as graph_module
from tests.utils import run_async


def test_rebuild_graph_run_uses_valid_initial_state(monkeypatch) -> None:
    calls: list[str] = []
    graph = graph_module.RebuildRetrievalIndexGraph()

    async def fake_mark_index_reindexing() -> None:
        calls.append("reindexing")

    async def fake_mark_index_ready() -> None:
        calls.append("ready")

    async def fake_rebuild_entities(*, batch_size: int) -> int:
        calls.append(f"entities:{batch_size}")
        return 2

    async def fake_rebuild_memories(*, batch_size: int) -> int:
        calls.append(f"memories:{batch_size}")
        return 3

    class _RetrievalIndex:
        async def reset_storage(self) -> None:
            calls.append("reset")

    monkeypatch.setattr(graph_module, "mark_index_reindexing", fake_mark_index_reindexing)
    monkeypatch.setattr(graph_module, "mark_index_ready", fake_mark_index_ready)
    monkeypatch.setattr(graph_module, "retrieval_index", _RetrievalIndex())
    monkeypatch.setattr(graph, "_rebuild_entities", fake_rebuild_entities)
    monkeypatch.setattr(graph, "_rebuild_memories", fake_rebuild_memories)

    result = run_async(graph.run())

    assert result == {"refreshed_entities": 2, "refreshed_memories": 3}
    assert calls == ["reindexing", "reset", "entities:32", "memories:32", "ready"]
