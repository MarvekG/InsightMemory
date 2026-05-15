from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from typing import Any, Protocol


class MemoryApiLike(Protocol):
    """Minimal async memory API protocol for timing wrappers."""

    async def health(self) -> dict[str, Any]:
        """Return service health information."""

    async def ingest(self, *, memory_scope: str, context: str) -> dict[str, Any]:
        """Send an ingest request."""

    async def recall(self, *, memory_scope: str, query: str) -> dict[str, Any]:
        """Send a recall request."""

    async def aclose(self) -> None:
        """Close the underlying client."""


class TimedMemoryApiClient:
    """Wrap a memory API client and collect per-endpoint latency statistics."""

    def __init__(self, *, inner: MemoryApiLike) -> None:
        self._inner = inner
        self._latencies_ms: dict[str, list[float]] = defaultdict(list)

    async def health(self) -> dict[str, Any]:
        """Call the health endpoint and record latency."""

        return await self._measure("health", self._inner.health)

    async def ingest(self, *, memory_scope: str, context: str) -> dict[str, Any]:
        """Call ingest and record latency."""

        return await self._measure(
            "ingest",
            self._inner.ingest,
            memory_scope=memory_scope,
            context=context,
        )

    async def recall(self, *, memory_scope: str, query: str) -> dict[str, Any]:
        """Call recall and record latency."""

        return await self._measure(
            "recall",
            self._inner.recall,
            memory_scope=memory_scope,
            query=query,
        )

    async def aclose(self) -> None:
        """Close the wrapped client."""

        await self._inner.aclose()

    async def _measure(self, endpoint: str, func, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            return await func(**kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._latencies_ms[endpoint].append(elapsed_ms)

    def snapshot(self, *, wall_clock_seconds: float) -> dict[str, Any]:
        """Return one timing snapshot suitable for reports."""

        by_endpoint = {
            endpoint: _summarize_samples(samples)
            for endpoint, samples in sorted(self._latencies_ms.items())
        }
        total_requests = sum(item["count"] for item in by_endpoint.values())
        total_elapsed_ms = sum(item["total_ms"] for item in by_endpoint.values())
        return {
            "wall_clock_seconds": round(wall_clock_seconds, 3),
            "total_requests": total_requests,
            "total_elapsed_ms": round(total_elapsed_ms, 2),
            "by_endpoint": by_endpoint,
        }


def merge_timing_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-run timing summaries into one aggregate summary."""

    endpoint_samples: dict[str, list[float]] = defaultdict(list)
    total_wall_clock_seconds = 0.0
    for summary in summaries:
        total_wall_clock_seconds += float(summary.get("wall_clock_seconds") or 0.0)
        by_endpoint = dict(summary.get("by_endpoint") or {})
        for endpoint, endpoint_summary in by_endpoint.items():
            endpoint_samples[endpoint].extend(
                float(sample)
                for sample in list(endpoint_summary.get("samples_ms") or [])
            )

    by_endpoint = {
        endpoint: _summarize_samples(samples)
        for endpoint, samples in sorted(endpoint_samples.items())
    }
    total_requests = sum(item["count"] for item in by_endpoint.values())
    total_elapsed_ms = sum(item["total_ms"] for item in by_endpoint.values())
    return {
        "wall_clock_seconds": round(total_wall_clock_seconds, 3),
        "total_requests": total_requests,
        "total_elapsed_ms": round(total_elapsed_ms, 2),
        "by_endpoint": by_endpoint,
    }


def _summarize_samples(samples: list[float]) -> dict[str, Any]:
    """Build one summary block from raw latency samples."""

    ordered = sorted(float(sample) for sample in samples)
    if not ordered:
        return {
            "count": 0,
            "avg_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
            "min_ms": 0.0,
            "total_ms": 0.0,
            "samples_ms": [],
        }
    return {
        "count": len(ordered),
        "avg_ms": round(sum(ordered) / len(ordered), 2),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(_percentile(ordered, 0.95), 2),
        "max_ms": round(max(ordered), 2),
        "min_ms": round(min(ordered), 2),
        "total_ms": round(sum(ordered), 2),
        "samples_ms": [round(sample, 2) for sample in ordered],
    }


def _percentile(samples: list[float], quantile: float) -> float:
    """Return one simple upper-rank percentile from sorted samples."""

    if not samples:
        return 0.0
    index = max(math.ceil(len(samples) * quantile) - 1, 0)
    return samples[min(index, len(samples) - 1)]
