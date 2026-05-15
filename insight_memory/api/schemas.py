from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from insight_memory.config import settings


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_scope: str = Field(..., min_length=1, max_length=255)
    context: str = Field(..., min_length=1, max_length=settings.MEMORY_MAX_CONTENT_LENGTH)


class IngestResponse(BaseModel):
    status: str
    observation_id: str | None = None
    affected_entity_keys: list[str] = Field(default_factory=list)
    affected_memory_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_scope: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=settings.MEMORY_MAX_QUERY_LENGTH)


class RecallCitation(BaseModel):
    memory_id: str | None = None
    observation_id: str | None = None
    summary: str = ""
    excerpt: str = ""
    source_memory_ids: list[str] = Field(default_factory=list)


class RecallResultItem(BaseModel):
    status: str
    answer: str = ""
    citations: list[RecallCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    error_code: str | None = None


class RecallResponse(BaseModel):
    results: list[RecallResultItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    db: str
    retrieval: str
    llm: str
    entities: int
    memories: int
    observations: int
    index_status: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    projection_version: str
    embedding_prewarm_status: str
    embedding_prewarm_error: str | None = None
    embedding_prewarm_attempt: int
    embedding_prewarm_max_attempts: int


class UsageStatsResponse(BaseModel):
    status: str = "ok"
    entities: int
    memories: int
    observations: int
    llm_runs: int
    total_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    by_operation: dict = Field(default_factory=dict)


class MemoryPreviewItem(BaseModel):
    memory_id: str
    memory_scope: str
    entity_key: str
    title: str
    summary: str
    content: str
    status: str
    confidence: float
    salience: float
    latest_source_observation_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: float
    updated_at: float


class MemoryPreviewResponse(BaseModel):
    status: str
    total: int
    limit: int
    offset: int
    items: list[MemoryPreviewItem] = Field(default_factory=list)
