from __future__ import annotations

from insight_memory import config as config_module
from insight_memory.config import Settings
from insight_memory.index.constants import MEMORY_VECTOR_TABLE


def test_settings_use_memory_database_url_and_service_port_names() -> None:
    settings = Settings(
        MEMORY_DATABASE_URL="postgresql+asyncpg://postgres:password@db.invalid:5432/memory",
        MEMORY_SERVICE_PORT=9001,
    )

    assert settings.MEMORY_DATABASE_URL == "postgresql+asyncpg://postgres:password@db.invalid:5432/memory"
    assert settings.MEMORY_SERVICE_PORT == 9001


def test_local_embedding_runtime_defaults() -> None:
    settings = Settings(MEMORY_EMBEDDING_PROVIDER="local")

    assert settings.MEMORY_EMBEDDING_MAX_CONCURRENCY == 8
    assert settings.MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY == 2
    assert settings.MEMORY_EMBEDDING_BATCH_SIZE == 32
    assert settings.MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS == 5


def test_openai_compatible_embedding_uses_static_runtime_defaults() -> None:
    settings = Settings(MEMORY_EMBEDDING_PROVIDER="openai_compatible")

    assert settings.MEMORY_EMBEDDING_MAX_CONCURRENCY == 8
    assert settings.MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY == 2
    assert settings.MEMORY_EMBEDDING_BATCH_SIZE == 32


def test_embedding_runtime_overrides_are_preserved() -> None:
    settings = Settings(
        MEMORY_EMBEDDING_PROVIDER="openai_compatible",
        MEMORY_EMBEDDING_MAX_CONCURRENCY=48,
        MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY=3,
        MEMORY_EMBEDDING_BATCH_SIZE=256,
    )

    assert settings.MEMORY_EMBEDDING_MAX_CONCURRENCY == 48
    assert settings.MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY == 3
    assert settings.MEMORY_EMBEDDING_BATCH_SIZE == 256


def test_settings_can_load_runtime_env_file(tmp_path, monkeypatch) -> None:
    for env_name in (
        "MEMORY_SERVICE_PORT",
        "MEMORY_DATABASE_URL",
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
        "LITELLM_MEMORY_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MEMORY_SERVICE_PORT=9123",
                "MEMORY_DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory",
                "LITELLM_BASE_URL=http://litellm:4000/v1",
                "LITELLM_API_KEY=sk-litellm",
                "LITELLM_MEMORY_MODEL=memory",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.MEMORY_SERVICE_PORT == 9123
    assert settings.MEMORY_DATABASE_URL == "postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory"
    assert settings.LITELLM_BASE_URL == "http://litellm:4000/v1"
    assert settings.LITELLM_API_KEY == "sk-litellm"
    assert settings.LITELLM_MEMORY_MODEL == "memory"


def test_default_env_files_do_not_scan_source_tree(monkeypatch) -> None:
    monkeypatch.delenv(config_module.INSIGHT_MEMORY_ENV_VAR, raising=False)

    assert config_module._resolve_env_files() == []


def test_default_env_files_use_docker_mounted_env(monkeypatch) -> None:
    monkeypatch.delenv(config_module.INSIGHT_MEMORY_ENV_VAR, raising=False)
    monkeypatch.setattr(config_module, "BASE_DIR", config_module.DOCKER_ENV_FILE.parent)

    assert config_module._resolve_env_files() == [config_module.DOCKER_ENV_FILE]


def test_insight_memory_env_overrides_default_env_file(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "custom.env"
    monkeypatch.setenv(config_module.INSIGHT_MEMORY_ENV_VAR, str(env_file))

    assert config_module._resolve_env_files() == [env_file]


def test_embedding_cache_dir_defaults_to_runtime_data_dir() -> None:
    settings = Settings(_env_file=None)

    assert settings.MEMORY_EMBEDDING_CACHE_DIR == str(config_module.RUNTIME_DIR / "data" / "models")


def test_runtime_dir_defaults_to_home_insight_memory() -> None:
    assert config_module.DEFAULT_RUNTIME_DIR == config_module.Path.home() / ".insight_memory"
    assert config_module.RUNTIME_DIR == config_module.DEFAULT_RUNTIME_DIR.expanduser().resolve()


def test_runtime_dir_is_not_a_setting(tmp_path) -> None:
    runtime_dir = tmp_path / "runtime"
    env_file = tmp_path / ".env"
    env_file.write_text(f"MEMORY_RUNTIME_DIR={runtime_dir}\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert not hasattr(settings, "MEMORY_RUNTIME_DIR")


def test_vector_table_is_code_constant_not_setting() -> None:
    settings = Settings(MEMORY_VECTOR_TABLE="custom_table")

    assert not hasattr(settings, "MEMORY_VECTOR_TABLE")
    assert MEMORY_VECTOR_TABLE == "memory_node_index"
