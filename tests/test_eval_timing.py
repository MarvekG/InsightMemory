from __future__ import annotations

from evals.scripts.eval_timing import merge_timing_summaries


def test_merge_timing_summaries_aggregates_endpoint_samples() -> None:
    summary = merge_timing_summaries(
        [
            {
                "wall_clock_seconds": 2.5,
                "by_endpoint": {
                    "ingest": {
                        "samples_ms": [100.0, 200.0],
                    },
                    "recall": {
                        "samples_ms": [300.0],
                    },
                },
            },
            {
                "wall_clock_seconds": 1.25,
                "by_endpoint": {
                    "ingest": {
                        "samples_ms": [150.0],
                    },
                },
            },
        ]
    )

    assert summary["wall_clock_seconds"] == 3.75
    assert summary["total_requests"] == 4
    assert summary["by_endpoint"]["ingest"]["count"] == 3
    assert summary["by_endpoint"]["ingest"]["avg_ms"] == 150.0
    assert summary["by_endpoint"]["ingest"]["p95_ms"] == 200.0
    assert summary["by_endpoint"]["recall"]["count"] == 1
    assert summary["by_endpoint"]["recall"]["total_ms"] == 300.0
