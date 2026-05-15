from __future__ import annotations

import pytest

from insight_memory.storage import database as database_module
from insight_memory.storage.database import async_database_url


def test_async_database_url_converts_legacy_postgresql_urls() -> None:
    url = async_database_url("postgresql://postgres:password@db.invalid:5432/memory")

    assert url == "postgresql+asyncpg://postgres:password@db.invalid:5432/memory"


def test_async_database_url_rejects_non_postgresql_backends() -> None:
    with pytest.raises(RuntimeError, match="must use PostgreSQL"):
        async_database_url("unsupported://user:password@localhost:1234/memory")


def test_async_engine_uses_asyncpg_timeout_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_async_engine(database_url: str, **kwargs: object) -> object:
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(database_module, "create_async_engine", fake_create_async_engine)

    database_module._create_async_engine()

    kwargs = dict(captured["kwargs"])
    assert kwargs["connect_args"] == {"timeout": 5}
