from __future__ import annotations

import os
from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[1]
DOCKER_ENV_FILE = Path("/app/.env")
DEFAULT_RUNTIME_DIR = Path.home() / ".insight_memory/"
RUNTIME_DIR = DEFAULT_RUNTIME_DIR.expanduser().resolve()
INSIGHT_MEMORY_ENV_VAR = "INSIGHT_MEMORY_ENV"


def _resolve_env_files() -> list[Path]:
    env_path = os.environ.get(INSIGHT_MEMORY_ENV_VAR)
    if env_path:
        return [Path(env_path).expanduser()]
    if BASE_DIR == DOCKER_ENV_FILE.parent:
        return [DOCKER_ENV_FILE]
    return []


ENV_FILES = _resolve_env_files()


class Settings(BaseSettings):
    MEMORY_SERVICE_NAME: str = "insight_memory"
    MEMORY_SERVICE_PORT: int = 8010
    MEMORY_APP_RELOAD: bool = True
    MEMORY_DATABASE_URL: str = "postgresql+asyncpg://postgres:password@memory-postgres:5432/memory"
    MEMORY_DATABASE_SCHEMA: str = "memory"
    MEMORY_DEFAULT_SPACE: str = "default"
    MEMORY_EMBEDDING_PROVIDER: str = "local"
    MEMORY_EMBEDDING_DIM: int = 768
    MEMORY_EMBEDDING_MODEL: str = "BAAI/bge-base-zh-v1.5"
    MEMORY_EMBEDDING_API_KEY: str = ""
    MEMORY_EMBEDDING_BASE_URL: str = ""
    MEMORY_EMBEDDING_TIMEOUT_SECONDS: float = 30.0
    MEMORY_EMBEDDING_CACHE_DIR: str = str(RUNTIME_DIR / "data" / "models")
    MEMORY_EMBEDDING_LOCAL_FILES_ONLY: bool = False
    MEMORY_EMBEDDING_PREWARM_ON_STARTUP: bool = True
    MEMORY_EMBEDDING_PREWARM_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    MEMORY_EMBEDDING_PREWARM_RETRY_SECONDS: float = Field(default=5.0, ge=0.0)
    MEMORY_EMBEDDING_MAX_CONCURRENCY: int = Field(default=8, ge=1)
    MEMORY_LOCAL_EMBEDDING_MAX_CONCURRENCY: int = Field(default=2, ge=1)
    MEMORY_EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1)
    MEMORY_HF_ENDPOINT: str = "https://hf-mirror.com"
    MEMORY_LLM_PROVIDER: str = "deepseek"
    MEMORY_LLM_MODEL: str = "deep_seek"
    MEMORY_LLM_API_KEY: str = ""
    MEMORY_LLM_BASE_URL: str = ""
    MEMORY_LLM_TIMEOUT_SECONDS: float = 60.0
    MEMORY_LLM_PROMPT_VERSION: str = "v1"
    MEMORY_MAX_CONTENT_LENGTH: int = 20000
    MEMORY_MAX_QUERY_LENGTH: int = 2000
    MEMORY_MAX_RECALL_ITEMS: int = 10
    MEMORY_MAX_EVIDENCE_PER_MEMORY: int = 3
    MEMORY_MAX_REWRITE_QUERIES: int = 3
    MEMORY_SIMILARITY_MIN_SCORE: float = Field(default=0.01, ge=0.0, le=1.0)
    MEMORY_VECTOR_RECALL_OVERSAMPLE: int = Field(default=24, ge=4, le=256)
    MEMORY_VECTOR_RRF_K: int = Field(default=50, ge=1, le=500)
    MEMORY_VECTOR_DENSE_MIN_SCORE: float = Field(default=0.12, ge=0.0, le=1.0)
    MEMORY_VECTOR_LEXICAL_MIN_SCORE: float = Field(default=0.08, ge=0.0, le=1.0)
    MEMORY_VECTOR_CHARGRAM_MIN_SCORE: float = Field(default=0.12, ge=0.0, le=1.0)
    MEMORY_OBSERVATION_RETENTION_SECONDS: int = 180 * 24 * 3600
    MEMORY_OBSERVATION_GC_BATCH_SIZE: int = Field(default=100, ge=1, le=5000)
    MEMORY_OBSERVATION_GC_INTERVAL_SECONDS: float = Field(default=3600.0, ge=0.0)
    MEMORY_TASK_LEASE_SECONDS: int = 60
    MEMORY_BACKGROUND_POLL_SECONDS: float = Field(default=0.05, ge=0.0)
    MEMORY_BACKGROUND_MAX_CONCURRENCY: int = Field(default=32, ge=1)
    MEMORY_BACKGROUND_MAX_PER_SPACE: int = Field(default=8, ge=1)
    MEMORY_BACKGROUND_CLAIM_LIMIT: int = Field(default=64, ge=0)
    MEMORY_BACKGROUND_DRAIN_BATCHES_PER_TICK: int = Field(default=256, ge=1)
    MEMORY_BACKGROUND_MAINTENANCE_DEBOUNCE_SECONDS: float = Field(default=3.0, ge=0.0)
    MEMORY_STALE_SCAN_INTERVAL_SECONDS: int = Field(default=300, ge=1)
    MEMORY_LIFECYCLE_POLICY_VERSION: str = "v1"
    MEMORY_ARCHIVE_AFTER_SUPERSEDED_SECONDS: int = 7 * 24 * 3600
    MEMORY_ARCHIVE_AFTER_STALE_SECONDS: int = 7 * 24 * 3600
    MEMORY_ARCHIVE_AFTER_EXPIRED_SECONDS: int = 24 * 3600
    MEMORY_RECENT_RECALL_GRACE_SECONDS: int = 3 * 24 * 3600
    MEMORY_PURGE_AFTER_ARCHIVED_SECONDS: int = 30 * 24 * 3600
    MEMORY_SLOT_COMPACTION_KEEP_COUNT: int = Field(default=2, ge=1)
    MEMORY_GRAPH_UPDATES_BUDGET: int = Field(default=8, ge=1)
    MEMORY_GRAPH_CONTRADICTS_BUDGET: int = Field(default=6, ge=1)
    MEMORY_GRAPH_SUPPORTS_BUDGET: int = Field(default=8, ge=1)
    MEMORY_GRAPH_DERIVED_FROM_BUDGET: int = Field(default=12, ge=1)
    MEMORY_GRAPH_RELATED_TO_BUDGET: int = Field(default=6, ge=1)
    MEMORY_GRAPH_TOTAL_MEMORY_BUDGET: int = Field(default=24, ge=1)

    model_config = ConfigDict(
        case_sensitive=True,
        env_file=ENV_FILES,
        extra="ignore",
    )


settings = Settings()
