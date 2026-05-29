from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IdentityProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    draft_id: str = Field(..., min_length=1)
    who: str = Field(..., min_length=1, max_length=255)
    surface_forms: list[str] = Field(default_factory=list)
    stable_qualifiers: list[str] = Field(default_factory=list)
    definition: str = Field(default="", max_length=512)

    @model_validator(mode="before")
    @classmethod
    def fix_schema_version(cls, value: object) -> object:
        """在服务端固定 identity profile 结构版本。

        Args:
            value: LLM 输出的原始 identity profile draft。

        Returns:
            补齐并固定 `schema_version=2` 的原始结构。
        """

        if not isinstance(value, dict):
            return value
        return {**value, "schema_version": 2}


class QueryIdentityProfileDraft(IdentityProfileDraft):
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(..., min_length=1)


class IdentityProfileExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_gate_status: Literal["passed", "rejected_no_identity_profile"]
    identity_profile_drafts: list[IdentityProfileDraft] = Field(default_factory=list)
    rejection_reason: str | None = None


class RecordMarkers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_label: str | None = Field(default=None, max_length=255)
    stage_label: str | None = Field(default=None, max_length=255)
    round_label: str | None = Field(default=None, max_length=255)
    date_hint: str | None = Field(default=None, max_length=255)


class CandidateMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., min_length=1)
    owner_draft_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    record_markers: RecordMarkers | None = None


class ExtractorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_gate_status: Literal["passed", "rejected_no_identity_profile"]
    identity_profile_drafts: list[IdentityProfileDraft] = Field(default_factory=list)
    candidates: list[CandidateMemory] = Field(default_factory=list)
    write_rejection_reason: str | None = None


class WriteGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_gate_status: Literal["passed", "rejected_no_identity_profile"]
    identity_profile_drafts: list[IdentityProfileDraft] = Field(default_factory=list)
    write_rejection_reason: str | None = None


class LinkerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["link_existing", "create_new", "ambiguous", "cannot_resolve"]
    selected_entity_key: str | None = None
    ambiguous_entity_keys: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class ResolverOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., min_length=1)
    action: Literal["create", "refresh", "replace", "coexist", "stale"]
    target_memory_id: str | None = None
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class ResolverBatchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResolverOutput] = Field(default_factory=list)


class QueryFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = ""
    time_intent: Literal["current", "latest", "history", "unspecified"] = "unspecified"
    graph_expansion_intent: Literal["entity_local", "cross_entity", "uncertain"] = "uncertain"
    graph_expansion_reason: str = ""
    prefer_status: list[str] = Field(default_factory=list)
    include_history: bool = False
    require_citations: bool = True

    @field_validator("graph_expansion_intent", mode="before")
    @classmethod
    def normalize_graph_expansion_intent(cls, value: object) -> str:
        """
        将非法图扩展意图降级为保守的 `uncertain`。

        Args:
            value: LLM 输出的原始图扩展意图。

        Returns:
            合法的图扩展意图枚举值。
        """
        text = str(value or "").strip().lower()
        if text in {"entity_local", "cross_entity", "uncertain"}:
            return text
        return "uncertain"


class QueryPlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_gate_status: Literal["passed", "rejected_no_identity_profile"]
    query_identity_profile_drafts: list[QueryIdentityProfileDraft] = Field(default_factory=list)
    query_rewrites: list[str] = Field(default_factory=list)
    query_focus: QueryFocus = Field(default_factory=QueryFocus)
    query_rejection_reason: str | None = None


class CrossEntityQueryBuilderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_texts: list[str] = Field(default_factory=list)


class AnswerCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str | None = None
    observation_id: str | None = None
    summary: str = ""
    excerpt: str = ""


class AnswerComposerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = ""
    citations: list[AnswerCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class AnswerJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "partial", "fail"]
    grounded: bool = True
    reason: str = ""


class ProfileWriterOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    who: str = Field(..., min_length=1, max_length=255)
    surface_forms: list[str] = Field(default_factory=list)
    stable_qualifiers: list[str] = Field(default_factory=list)
    definition: str = Field(default="", max_length=512)

    @model_validator(mode="before")
    @classmethod
    def fix_schema_version(cls, value: object) -> object:
        """在服务端固定完整 identity profile 结构版本。

        Args:
            value: LLM 输出的原始 profile writer 结果。

        Returns:
            补齐并固定 `schema_version=2` 的原始结构。
        """

        if not isinstance(value, dict):
            return value
        return {**value, "schema_version": 2}


class EdgeRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_memory_id: str = Field(..., min_length=1, max_length=64)
    to_memory_id: str = Field(..., min_length=1, max_length=64)
    edge_type: Literal["supports", "contradicts", "related_to"]
    reason: str = Field(..., min_length=1)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)


class EdgeJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relations: list[EdgeRelation] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def drop_none_relations(cls, value: object) -> object:
        """丢弃 LLM 用 `none` 表示的无关系记录。

        Args:
            value: LLM 输出的原始结构化结果。

        Returns:
            删除 `edge_type=none` 后的结构化结果；其他非法 edge_type 继续交给
            Pydantic 严格校验。
        """

        if not isinstance(value, dict):
            return value
        relations = value.get("relations")
        if not isinstance(relations, list):
            return value
        sanitized = []
        for relation in relations:
            if isinstance(relation, dict) and str(relation.get("edge_type") or "").strip().lower() == "none":
                continue
            sanitized.append(relation)
        return {**value, "relations": sanitized}


class MergeJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["merge", "keep_separate"]
    survivor_entity_key: str | None = None
    merged_identity_profile: ProfileWriterOutput | None = None
    reason: str = ""
