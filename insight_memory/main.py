from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request

from insight_memory.api.routes import router
from insight_memory.config import settings
from insight_memory.index.version_state import ensure_rebuild_task_if_needed
from insight_memory.services.embedding_service import embedding_service
from insight_memory.storage.database import init_database
from insight_memory.utils.logger import get_logger
from insight_memory.utils.request_context import clear_request_id
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.utils.request_context import set_request_id
from insight_memory.workers.background import background_worker


logger = get_logger(__name__)


async def run_startup() -> None:
    started_at = perf_counter()
    logger.info(
        "memory service startup begin",
        extra={
            "service_name": settings.MEMORY_SERVICE_NAME,
            "port": settings.MEMORY_SERVICE_PORT,
            "database_schema": settings.MEMORY_DATABASE_SCHEMA,
            "llm_provider": settings.MEMORY_LLM_PROVIDER,
            "llm_model": settings.MEMORY_LLM_MODEL,
        },
    )
    step_start = perf_counter()
    await init_database()
    logger.info(
        "step 1 init_database completed",
        extra={"elapsed_ms": round((perf_counter() - step_start) * 1000, 2)},
    )

    embedding_service.start_prewarm_background()
    logger.info(
        "step 2 embedding_prewarm scheduled",
        extra={"elapsed_ms": 0.0},
    )

    step_start = perf_counter()
    await background_worker.recover_pending_tasks()
    logger.info(
        "step 3 recover_pending_tasks completed",
        extra={"elapsed_ms": round((perf_counter() - step_start) * 1000, 2)},
    )

    step_start = perf_counter()
    await ensure_rebuild_task_if_needed()
    logger.info(
        "step 4 ensure_rebuild_task_if_needed completed",
        extra={"elapsed_ms": round((perf_counter() - step_start) * 1000, 2)},
    )

    step_start = perf_counter()
    await background_worker.start()
    logger.info(
        "step 5 background_worker.start completed",
        extra={"elapsed_ms": round((perf_counter() - step_start) * 1000, 2)},
    )

    logger.info(
        "memory service startup completed",
        extra={"elapsed_ms": round((perf_counter() - started_at) * 1000, 2)},
    )


async def run_shutdown() -> None:
    await embedding_service.shutdown()
    await background_worker.shutdown(cancel=True)
    logger.info("memory service shutdown completed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await run_startup()
    try:
        yield
    finally:
        await run_shutdown()


app = FastAPI(
    title=settings.MEMORY_SERVICE_NAME,
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    started_at = perf_counter()
    request_id = get_or_create_request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    token = set_request_id(request_id)
    logger.info(
        "http request started",
        extra={
            "method": request.method,
            "path": request.url.path,
            "query_string": request.url.query,
        },
    )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http request failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        clear_request_id(token)
        raise
    response.headers["x-request-id"] = request_id
    logger.info(
        "http request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 2),
        },
    )
    clear_request_id(token)
    return response


app.include_router(router)
