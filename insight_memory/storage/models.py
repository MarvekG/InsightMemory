from __future__ import annotations

import time

from sqlalchemy import CheckConstraint, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from insight_memory.storage.database import Base, table_args


MEMORY_STATUSES = ("active", "stale", "superseded", "archived")
ENTITY_RESOLUTION_STATUSES = ("pending", "resolved", "partially_resolved", "unresolved")
EDGE_TYPES = ("derived_from", "updates", "supports", "contradicts", "related_to")
TASK_STATUSES = ("pending", "running", "succeeded", "failed", "dead_letter", "cancelled")
TASK_TYPES = (
    "extract_candidates",
    "resolve_identity_drafts",
    "resolve_candidates",
    "refresh_entity_profile",
    "detect_merge_candidates",
    "repair_memory_edges",
    "merge_entities",
    "reindex_memory",
    "rebuild_retrieval_index",
    "forget_memory",
    "purge_memory",
)
LLM_WORKER_TYPES = (
    "extractor",
    "linker",
    "resolver",
    "query_planner",
    "answer_composer",
    "answer_judge",
    "profile_writer",
    "merge_judge",
    "edge_judge",
)
VERSION_ACTIONS = ("create", "refresh", "replace", "coexist", "stale", "archive")


def timestamp_now() -> float:
    """返回当前 Unix 时间戳，单位为秒。"""

    return time.time()


class TimestampMixin:
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)
    updated_at: Mapped[float] = mapped_column(
        Float,
        default=timestamp_now,
        onupdate=timestamp_now,
        nullable=False,
    )


class MemoryEntity(Base, TimestampMixin):
    __tablename__ = "memory_entities"
    __table_args__ = table_args(
        Index("ix_memory_entities_space_updated_at", "memory_space", "updated_at"),
    )

    entity_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    identity_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class MemoryEntityMergeLog(Base):
    __tablename__ = "memory_entity_merge_logs"
    __table_args__ = table_args(
        Index("ix_memory_entity_merge_logs_space_created_at", "memory_space", "created_at"),
    )

    merge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_entity_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_entity_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)


class MemoryObservation(Base):
    __tablename__ = "memory_observations"
    __table_args__ = table_args(
        Index("ix_memory_observations_space_created_at", "memory_space", "created_at"),
        CheckConstraint(
            "entity_resolution_status IN ('pending', 'resolved', 'partially_resolved', 'unresolved')",
            name="ck_memory_observations_entity_resolution_status",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entity_resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)


class MemoryMemory(Base, TimestampMixin):
    __tablename__ = "memory_memories"
    __table_args__ = table_args(
        Index("ix_memory_memories_space_entity_status_updated", "memory_space", "entity_key", "status", "updated_at"),
        CheckConstraint(
            "status IN ('active', 'stale', 'superseded', 'archived')",
            name="ck_memory_memories_status",
        ),
    )

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    latest_source_observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class MemoryEdge(Base):
    __tablename__ = "memory_edges"
    __table_args__ = table_args(
        UniqueConstraint("memory_space", "from_id", "to_id", "edge_type", name="uq_memory_edges"),
        Index("ix_memory_edges_space_from_type", "memory_space", "from_id", "edge_type"),
        Index("ix_memory_edges_space_to_type", "memory_space", "to_id", "edge_type"),
        CheckConstraint("from_kind = 'memory'", name="ck_memory_edges_from_kind"),
        CheckConstraint("to_kind IN ('memory', 'observation')", name="ck_memory_edges_to_kind"),
        CheckConstraint(
            "edge_type IN ('derived_from', 'updates', 'supports', 'contradicts', 'related_to')",
            name="ck_memory_edges_edge_type",
        ),
    )

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="memory")
    from_id: Mapped[str] = mapped_column(String(64), nullable=False)
    to_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    to_id: Mapped[str] = mapped_column(String(64), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)


class MemoryMemoryVersion(Base):
    __tablename__ = "memory_memory_versions"
    __table_args__ = table_args(
        UniqueConstraint("memory_space", "memory_id", "version", name="uq_memory_memory_versions"),
        Index("ix_memory_memory_versions_space_memory_created_at", "memory_space", "memory_id", "created_at"),
        CheckConstraint(
            "action IN ('create', 'refresh', 'replace', 'coexist', 'stale', 'archive')",
            name="ck_memory_memory_versions_action",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    memory_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolver_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)


class MemoryTask(Base, TimestampMixin):
    __tablename__ = "memory_tasks"
    __table_args__ = table_args(
        Index("ix_memory_tasks_status_available_priority", "status", "available_at", "priority"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'dead_letter', 'cancelled')",
            name="ck_memory_tasks_status",
        ),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    available_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemorySystemState(Base, TimestampMixin):
    __tablename__ = "memory_system_states"
    __table_args__ = table_args()

    state_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class MemoryLLMRun(Base):
    __tablename__ = "memory_llm_runs"
    __table_args__ = table_args(
        Index("ix_memory_llm_runs_space_worker_created_at", "memory_space", "worker_type", "created_at"),
        CheckConstraint(
            "worker_type IN ('extractor', 'linker', 'resolver', 'query_planner', "
            "'answer_composer', 'answer_judge', 'profile_writer', 'merge_judge', 'edge_judge')",
            name="ck_memory_llm_runs_worker_type",
        ),
        CheckConstraint("parse_status IN ('ok', 'schema_error', 'empty', 'rejected')", name="ck_memory_llm_runs_parse_status"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    worker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_miss_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)


class MemoryRecallAudit(Base):
    __tablename__ = "memory_recall_audits"
    __table_args__ = table_args(
        Index("ix_memory_recall_audits_space_created_at", "memory_space", "created_at"),
        Index("ix_memory_recall_audits_request_id", "request_id"),
    )

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_space: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved_entity_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uncertainties: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    used_edges: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resolution_trace: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=timestamp_now, nullable=False)
