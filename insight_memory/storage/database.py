from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from insight_memory.config import settings
from insight_memory.utils.logger import get_logger


logger = get_logger(__name__)


def async_database_url(database_url: str | None = None) -> str:
    """Return the async PostgreSQL SQLAlchemy URL used by the application runtime."""

    url = make_url(database_url or settings.MEMORY_DATABASE_URL)
    backend_name = url.get_backend_name()
    if backend_name != "postgresql":
        raise RuntimeError(
            "MEMORY_DATABASE_URL must use PostgreSQL. "
            f"Got backend '{backend_name}'."
        )
    if "asyncpg" not in url.drivername:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    return url.render_as_string(hide_password=False)


def schema_name() -> str:
    return settings.MEMORY_DATABASE_SCHEMA


def table_args(*items):
    """Build SQLAlchemy table args with the configured schema."""

    schema = schema_name()
    args = list(items)
    if schema:
        args.append({"schema": schema})
    return tuple(args) if args else ({"schema": schema} if schema else tuple())


def _create_async_engine() -> AsyncEngine:
    database_url = async_database_url()
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "connect_args": {"timeout": 5},
        "pool_size": 32,
        "max_overflow": 64,
        "pool_timeout": 5,
    }
    return create_async_engine(database_url, **engine_kwargs)


async_engine = _create_async_engine()
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_database() -> None:
    from insight_memory.storage.models import Base as ModelsBase

    schema = schema_name()
    async with async_engine.begin() as conn:
        if schema:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await conn.run_sync(ModelsBase.metadata.create_all)
    logger.info("database initialization completed", extra={"schema": schema})


async def reset_database() -> None:
    from insight_memory.storage.models import Base as ModelsBase

    schema = schema_name()
    async with async_engine.begin() as conn:
        await conn.run_sync(ModelsBase.metadata.drop_all)
        if schema:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        await conn.run_sync(ModelsBase.metadata.create_all)
