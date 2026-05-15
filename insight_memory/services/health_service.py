from __future__ import annotations

from sqlalchemy import text

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.index.version_state import INDEX_STATUS_FAILED, current_index_config, load_index_health
from insight_memory.services.embedding_service import embedding_service
from insight_memory.storage.repository import MemoryRepository
from insight_memory.workers.llm_provider import llm_provider


class HealthService:
    async def check(self) -> dict:
        db_status = "ok"
        retrieval_status = "ok"
        llm_status = "configured" if llm_provider.enabled else "not_configured"
        stats = {
            "entities": 0,
            "memories": 0,
            "observations": 0,
        }
        try:
            async with MemoryRepository() as repository:
                await repository.db.execute(text("SELECT 1"))
                stats = await repository.count_stats()
        except Exception:
            db_status = "error"
        try:
            retrieval_status = str((await retrieval_index.health())["status"])
        except Exception:
            retrieval_status = "error"
        try:
            index_health = await load_index_health()
        except Exception:
            index_health = {"index_status": INDEX_STATUS_FAILED, **current_index_config()}
        index_status = str(index_health["index_status"])
        prewarm_health = embedding_service.prewarm_health()
        prewarm_status = str(prewarm_health["embedding_prewarm_status"])
        return {
            "status": (
                "ok"
                if (
                    db_status == "ok"
                    and retrieval_status == "ok"
                    and llm_status == "configured"
                    and index_status != INDEX_STATUS_FAILED
                    and prewarm_status != "failed"
                )
                else "error"
            ),
            "db": db_status,
            "retrieval": retrieval_status,
            "llm": llm_status,
            "entities": stats["entities"],
            "memories": stats["memories"],
            "observations": stats["observations"],
            **index_health,
            **prewarm_health,
        }

    async def usage_stats(self, *, hours: int | None = None) -> dict:
        async with MemoryRepository() as repository:
            stats = await repository.count_stats()
            usage_stats = await repository.llm_usage_stats(hours=hours)
        return {
            "status": "ok",
            "entities": stats["entities"],
            "memories": stats["memories"],
            "observations": stats["observations"],
            "llm_runs": stats["llm_runs"],
            **usage_stats,
        }


health_service = HealthService()
