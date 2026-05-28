from __future__ import annotations

from typing import Any

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


class PromptEvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_key: str = Field(..., min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


class PromptEvalUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None


class PromptEvalResponse(BaseModel):
    status: str
    prompt_key: str
    model: str | None = None
    latency_ms: int | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    usage: PromptEvalUsage | None = None
    error_code: str | None = None
    error_message: str | None = None


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
    cached_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    cache_hit_rate: float = 0.0
    by_operation: dict = Field(default_factory=dict)


class ClearUsageStatsResponse(BaseModel):
    status: str
    deleted: int


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


class RecallAuditPreviewItem(BaseModel):
    audit_id: str
    memory_scope: str
    request_id: str
    query: str
    query_preview: str
    status: str
    resolved_entity_key: str | None = None
    error_code: str | None = None
    answer_preview: str
    answer_length: int
    uncertainties: list[str] = Field(default_factory=list)
    used_edge_count: int
    citation_count: int
    key_memory_ids: list[str] = Field(default_factory=list)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: float


class RecallAuditPreviewResponse(BaseModel):
    status: str
    total: int
    limit: int
    offset: int
    items: list[RecallAuditPreviewItem] = Field(default_factory=list)
