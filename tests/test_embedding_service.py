from __future__ import annotations

import asyncio
import time

import pytest

from insight_memory.config import settings
from insight_memory.services.embedding_service import EmbeddingService
from tests.utils import run_async


def test_embed_texts_honors_max_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_DIM", 3)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_BATCH_SIZE", 1)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_MAX_CONCURRENCY", 2)

    service = EmbeddingService()
    state = {"active": 0, "peak": 0}

    async def fake_embed_batch(texts: list[str]) -> list[list[float]]:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return [[1.0, 2.0, 3.0] for _ in texts]

    monkeypatch.setattr(service, "_embed_batch", fake_embed_batch)

    vectors = run_async(service.embed_texts(["a", "b", "c", "d"]))

    assert len(vectors) == 4
    assert state["peak"] == 2


def test_local_embedding_encode_uses_local_concurrency_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_DIM", 3)
    monkeypatch.setattr(settings, "MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY", 2)

    service = EmbeddingService()
    state = {"active": 0, "peak": 0}

    class FakeModel:
        def encode(self, texts: list[str], **_: object) -> list[list[float]]:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.02)
            state["active"] -= 1
            return [[1.0, 2.0, 3.0] for _ in texts]

    async def fake_load_local_model() -> FakeModel:
        return FakeModel()

    monkeypatch.setattr(service, "_load_local_model", fake_load_local_model)

    async def run_batches() -> list[list[list[float]]]:
        return await asyncio.gather(
            service._embed_local_batch(["a"]),
            service._embed_local_batch(["b"]),
            service._embed_local_batch(["c"]),
        )

    vectors = run_async(run_batches())

    assert vectors == [[[1.0, 2.0, 3.0]], [[1.0, 2.0, 3.0]], [[1.0, 2.0, 3.0]]]
    assert state["peak"] == 2


def test_prewarm_health_reports_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_ON_STARTUP", True)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_DIM", 3)

    service = EmbeddingService()

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[1.0, 2.0, 3.0] for _ in texts]

    monkeypatch.setattr(service, "embed_texts", fake_embed_texts)

    run_async(service.prewarm())

    assert service.prewarm_health() == {
        "embedding_prewarm_status": "ready",
        "embedding_prewarm_error": None,
        "embedding_prewarm_attempt": 0,
        "embedding_prewarm_max_attempts": 5,
    }


def test_prewarm_health_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_ON_STARTUP", True)

    service = EmbeddingService()

    async def fake_embed_texts(_: list[str]) -> list[list[float]]:
        raise RuntimeError("download failed")

    monkeypatch.setattr(service, "embed_texts", fake_embed_texts)

    with pytest.raises(RuntimeError, match="download failed"):
        run_async(service.prewarm())

    assert service.prewarm_health() == {
        "embedding_prewarm_status": "failed",
        "embedding_prewarm_error": "download failed",
        "embedding_prewarm_attempt": 0,
        "embedding_prewarm_max_attempts": 5,
    }


def test_background_prewarm_retries_until_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_ON_STARTUP", True)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_RETRY_SECONDS", 0.0)

    service = EmbeddingService()
    attempts = {"count": 0}

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("download failed")
        return [[1.0, 2.0, 3.0] for _ in texts]

    monkeypatch.setattr(service, "embed_texts", fake_embed_texts)

    run_async(service._run_prewarm_background())

    assert attempts["count"] == 3
    assert service.prewarm_health() == {
        "embedding_prewarm_status": "ready",
        "embedding_prewarm_error": None,
        "embedding_prewarm_attempt": 3,
        "embedding_prewarm_max_attempts": 5,
    }


def test_background_prewarm_stops_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_ON_STARTUP", True)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "MEMORY_EMBEDDING_PREWARM_RETRY_SECONDS", 0.0)

    service = EmbeddingService()
    attempts = {"count": 0}

    async def fake_embed_texts(_: list[str]) -> list[list[float]]:
        attempts["count"] += 1
        raise RuntimeError("download failed")

    monkeypatch.setattr(service, "embed_texts", fake_embed_texts)

    run_async(service._run_prewarm_background())

    assert attempts["count"] == 5
    assert service.prewarm_health() == {
        "embedding_prewarm_status": "failed",
        "embedding_prewarm_error": "download failed",
        "embedding_prewarm_attempt": 5,
        "embedding_prewarm_max_attempts": 5,
    }
