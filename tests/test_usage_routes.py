from __future__ import annotations

from insight_memory.api import routes
from tests.utils import run_async


def test_clear_usage_stats_route_returns_deleted_count(monkeypatch) -> None:
    async def fake_clear_usage_stats() -> dict:
        return {"status": "ok", "deleted": 4}

    monkeypatch.setattr(routes.health_service, "clear_usage_stats", fake_clear_usage_stats)

    result = run_async(routes.clear_usage_stats_memory())

    assert result.status == "ok"
    assert result.deleted == 4
