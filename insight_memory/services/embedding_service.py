from __future__ import annotations

import asyncio
import os
from typing import Any

from insight_memory.config import settings
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)


class EmbeddingService:
    """Generate embeddings through a local model or OpenAI-compatible API."""

    def __init__(self) -> None:
        self._provider = settings.MEMORY_EMBEDDING_PROVIDER.strip().lower()
        self._batch_size = int(settings.MEMORY_EMBEDDING_BATCH_SIZE or 1)
        self._semaphore = asyncio.Semaphore(int(settings.MEMORY_EMBEDDING_MAX_CONCURRENCY or 1))
        self._model_lock = asyncio.Lock()
        self._prewarm_task: asyncio.Task[None] | None = None
        self._prewarm_status = "not_started"
        self._prewarm_error: str | None = None
        self._prewarm_attempt = 0
        self._local_model: Any | None = None
        self._openai_client: Any | None = None

    @property
    def provider(self) -> str:
        """Return the configured embedding provider."""

        return self._provider

    @property
    def batch_size(self) -> int:
        """Return the configured embedding batch size."""

        return self._batch_size

    def start_prewarm_background(self) -> None:
        """Schedule embedding prewarm without blocking application startup."""

        if self._prewarm_task is not None and not self._prewarm_task.done():
            logger.info(
                "embedding prewarm already running",
                extra={"provider": self._provider, "model": settings.MEMORY_EMBEDDING_MODEL},
            )
            return
        self._prewarm_task = asyncio.create_task(self._run_prewarm_background())

    def prewarm_health(self) -> dict[str, int | str | None]:
        """Return the latest embedding prewarm state for health responses."""

        return {
            "embedding_prewarm_status": self._prewarm_status,
            "embedding_prewarm_error": self._prewarm_error,
            "embedding_prewarm_attempt": self._prewarm_attempt,
            "embedding_prewarm_max_attempts": int(settings.MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS),
        }

    async def shutdown(self) -> None:
        """Cancel an in-flight background prewarm task during service shutdown."""

        if self._prewarm_task is None or self._prewarm_task.done():
            return
        self._prewarm_task.cancel()
        try:
            await self._prewarm_task
        except asyncio.CancelledError:
            logger.info(
                "embedding prewarm cancelled",
                extra={"provider": self._provider, "model": settings.MEMORY_EMBEDDING_MODEL},
            )

    async def prewarm(self) -> None:
        """Run a small embedding request to validate provider availability and dimensions."""

        if not settings.MEMORY_EMBEDDING_PREWARM_ON_STARTUP:
            self._prewarm_status = "skipped"
            self._prewarm_error = None
            self._prewarm_attempt = 0
            logger.info("embedding prewarm skipped", extra={"provider": self._provider})
            return
        self._prewarm_status = "running"
        self._prewarm_error = None
        logger.info(
            "embedding prewarm started",
            extra={"provider": self._provider, "model": settings.MEMORY_EMBEDDING_MODEL},
        )
        try:
            await self.embed_texts(["memory embedding prewarm"])
        except Exception as error:
            self._prewarm_status = "failed"
            self._prewarm_error = str(error)
            raise
        self._prewarm_status = "ready"
        logger.info(
            "embedding prewarm completed",
            extra={"provider": self._provider, "model": settings.MEMORY_EMBEDDING_MODEL},
        )

    async def _run_prewarm_background(self) -> None:
        max_attempts = int(settings.MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS)
        retry_seconds = float(settings.MEMORY_EMBEDDING_PREWARM_RETRY_SECONDS)
        for attempt in range(1, max_attempts + 1):
            self._prewarm_attempt = attempt
            try:
                await self.prewarm()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "embedding prewarm attempt failed",
                    extra={
                        "provider": self._provider,
                        "model": settings.MEMORY_EMBEDDING_MODEL,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
            if attempt < max_attempts:
                self._prewarm_status = "retrying"
                await asyncio.sleep(retry_seconds)
        logger.error(
            "embedding prewarm failed after retries",
            extra={
                "provider": self._provider,
                "model": settings.MEMORY_EMBEDDING_MODEL,
                "attempts": max_attempts,
            },
        )

    async def embed_text(self, text: str) -> list[float]:
        """
        Embed one text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """

        vectors = await self.embed_texts([text])
        return vectors[0] if vectors else []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts using configured batching and concurrency limits.

        Args:
            texts: Texts to embed.

        Returns:
            Embedding vectors in the same order as input texts.
        """

        normalized = [str(text or "") for text in texts]
        if not normalized:
            return []

        logger.info(
            "embedding request started",
            extra={
                "provider": self._provider,
                "model": settings.MEMORY_EMBEDDING_MODEL,
                "text_count": len(normalized),
                "batch_size": self._batch_size,
                "max_concurrency": int(settings.MEMORY_EMBEDDING_MAX_CONCURRENCY or 1),
            },
        )
        batch_jobs = [
            (start, normalized[start : start + self._batch_size])
            for start in range(0, len(normalized), self._batch_size)
        ]
        results = await asyncio.gather(
            *(self._embed_batch_job(start=start, texts=batch) for start, batch in batch_jobs)
        )
        results.sort(key=lambda item: item[0])
        vectors = [vector for _, batch_vectors in results for vector in batch_vectors]
        logger.info(
            "embedding request completed",
            extra={
                "provider": self._provider,
                "model": settings.MEMORY_EMBEDDING_MODEL,
                "text_count": len(normalized),
                "vector_count": len(vectors),
            },
        )
        return vectors

    async def _embed_batch_job(self, *, start: int, texts: list[str]) -> tuple[int, list[list[float]]]:
        logger.info(
            "embedding batch started",
            extra={
                "provider": self._provider,
                "model": settings.MEMORY_EMBEDDING_MODEL,
                "batch_start": start,
                "batch_size": len(texts),
            },
        )
        async with self._semaphore:
            batch_vectors = await self._embed_batch(texts)
        for vector in batch_vectors:
            self._validate_dimension(vector)
        logger.info(
            "embedding batch completed",
            extra={
                "provider": self._provider,
                "model": settings.MEMORY_EMBEDDING_MODEL,
                "batch_start": start,
                "batch_size": len(texts),
                "vector_count": len(batch_vectors),
            },
        )
        return start, batch_vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._provider == "local":
            return await self._embed_local_batch(texts)
        if self._provider == "openai_compatible":
            return await self._embed_openai_compatible_batch(texts)
        raise ValueError(f"Unsupported MEMORY_EMBEDDING_PROVIDER: {self._provider}")

    async def _embed_local_batch(self, texts: list[str]) -> list[list[float]]:
        model = await self._load_local_model()
        vectors = await asyncio.to_thread(
            model.encode,
            texts,
            batch_size=len(texts),
            normalize_embeddings=True,
            convert_to_numpy=False,
            show_progress_bar=False,
        )
        return [self._coerce_vector(vector) for vector in vectors]

    async def _embed_openai_compatible_batch(self, texts: list[str]) -> list[list[float]]:
        client = await self._load_openai_client()
        response = await client.embeddings.create(
            model=settings.MEMORY_EMBEDDING_MODEL,
            input=texts,
            timeout=settings.MEMORY_EMBEDDING_TIMEOUT_SECONDS,
        )
        ordered = sorted(response.data, key=lambda item: int(item.index))
        return [self._coerce_vector(item.embedding) for item in ordered]

    async def _load_local_model(self) -> Any:
        if self._local_model is not None:
            return self._local_model
        async with self._model_lock:
            if self._local_model is not None:
                return self._local_model
            if settings.MEMORY_HF_ENDPOINT:
                os.environ.setdefault("HF_ENDPOINT", settings.MEMORY_HF_ENDPOINT)
            from sentence_transformers import SentenceTransformer

            logger.info(
                "loading local embedding model",
                extra={
                    "model": settings.MEMORY_EMBEDDING_MODEL,
                    "cache_dir": settings.MEMORY_EMBEDDING_CACHE_DIR,
                    "local_files_only": settings.MEMORY_EMBEDDING_LOCAL_FILES_ONLY,
                },
            )
            self._local_model = await asyncio.to_thread(
                SentenceTransformer,
                settings.MEMORY_EMBEDDING_MODEL,
                cache_folder=settings.MEMORY_EMBEDDING_CACHE_DIR,
                local_files_only=settings.MEMORY_EMBEDDING_LOCAL_FILES_ONLY,
            )
            return self._local_model

    async def _load_openai_client(self) -> Any:
        if self._openai_client is not None:
            return self._openai_client
        async with self._model_lock:
            if self._openai_client is not None:
                return self._openai_client
            if not settings.MEMORY_EMBEDDING_API_KEY:
                raise ValueError("MEMORY_EMBEDDING_API_KEY is required for openai_compatible embedding provider")
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {
                "api_key": settings.MEMORY_EMBEDDING_API_KEY,
                "timeout": settings.MEMORY_EMBEDDING_TIMEOUT_SECONDS,
            }
            if settings.MEMORY_EMBEDDING_BASE_URL:
                kwargs["base_url"] = settings.MEMORY_EMBEDDING_BASE_URL
            logger.info(
                "creating openai-compatible embedding client",
                extra={
                    "model": settings.MEMORY_EMBEDDING_MODEL,
                    "base_url": settings.MEMORY_EMBEDDING_BASE_URL or "",
                    "timeout_seconds": settings.MEMORY_EMBEDDING_TIMEOUT_SECONDS,
                },
            )
            self._openai_client = AsyncOpenAI(**kwargs)
            return self._openai_client

    @staticmethod
    def _coerce_vector(vector: Any) -> list[float]:
        return [float(item) for item in vector]

    @staticmethod
    def _validate_dimension(vector: list[float]) -> None:
        expected = int(settings.MEMORY_EMBEDDING_DIM)
        actual = len(vector)
        if actual != expected:
            raise ValueError(
                f"Embedding dimension mismatch: expected {expected}, got {actual}. "
                "Check MEMORY_EMBEDDING_MODEL and MEMORY_EMBEDDING_DIM."
            )


embedding_service = EmbeddingService()
