from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from insight_memory.workers.schemas import (
    AnswerComposerOutput,
    AnswerJudgeOutput,
    CrossEntityQueryBuilderOutput,
    EdgeJudgeOutput,
    ExtractorOutput,
    IdentityProfileExtractionOutput,
    LinkerOutput,
    MergeJudgeOutput,
    ProfileWriterOutput,
    QueryPlannerOutput,
    ResolverBatchOutput,
    WriteGateOutput,
)


@dataclass(frozen=True, slots=True)
class PromptEvalTarget:
    """描述一个允许通过 Prompt Eval API 调用的后端提示词。"""

    prompt_key: str
    instructions_key: str
    schema_type: Type[BaseModel]
    description: str


PROMPT_EVAL_TARGETS: dict[str, PromptEvalTarget] = {
    "identity_profile": PromptEvalTarget(
        prompt_key="identity_profile",
        instructions_key="identity_profile",
        schema_type=IdentityProfileExtractionOutput,
        description="Extract identity profile drafts with the shared identity profile prompt and unified schema.",
    ),
    "write_gate": PromptEvalTarget(
        prompt_key="write_gate",
        instructions_key="write_gate",
        schema_type=WriteGateOutput,
        description="Decide whether input should be accepted for long-term memory and return identity profile drafts.",
    ),
    "extractor": PromptEvalTarget(
        prompt_key="extractor",
        instructions_key="extractor",
        schema_type=ExtractorOutput,
        description="Extract identity profile drafts and candidate memories from raw input.",
    ),
    "query_planner": PromptEvalTarget(
        prompt_key="query_planner",
        instructions_key="query_planner",
        schema_type=QueryPlannerOutput,
        description="Extract query identity profile drafts, query rewrites, and query focus from a recall query.",
    ),
    "linker": PromptEvalTarget(
        prompt_key="linker",
        instructions_key="linker",
        schema_type=LinkerOutput,
        description="Decide whether an identity profile draft can bind to an existing entity candidate.",
    ),
    "resolver": PromptEvalTarget(
        prompt_key="resolver",
        instructions_key="resolver",
        schema_type=ResolverBatchOutput,
        description="Decide whether candidate memories should be created, refreshed, replaced, coexisted, or marked stale.",
    ),
    "same_batch_resolver": PromptEvalTarget(
        prompt_key="same_batch_resolver",
        instructions_key="same_batch_resolver",
        schema_type=ResolverBatchOutput,
        description="Resolve earlier/current evolution between candidate memories in the same ingest batch.",
    ),
    "cross_entity_query_builder": PromptEvalTarget(
        prompt_key="cross_entity_query_builder",
        instructions_key="cross_entity_query_builder",
        schema_type=CrossEntityQueryBuilderOutput,
        description="Generate retrieval query texts for cross-entity recall expansion.",
    ),
    "answer_composer": PromptEvalTarget(
        prompt_key="answer_composer",
        instructions_key="answer_composer",
        schema_type=AnswerComposerOutput,
        description="Compose the final answer from candidate memories, relation edges, and observations.",
    ),
    "answer_judge": PromptEvalTarget(
        prompt_key="answer_judge",
        instructions_key="answer_judge",
        schema_type=AnswerJudgeOutput,
        description="Judge whether an answer satisfies required facts, forbidden facts, and citation constraints.",
    ),
    "profile_writer": PromptEvalTarget(
        prompt_key="profile_writer",
        instructions_key="profile_writer",
        schema_type=ProfileWriterOutput,
        description="Write a complete identity profile after entity refresh or merge decisions.",
    ),
    "edge_judge": PromptEvalTarget(
        prompt_key="edge_judge",
        instructions_key="edge_judge",
        schema_type=EdgeJudgeOutput,
        description="Judge supports, contradicts, or related_to relations between memories.",
    ),
    "merge_judge": PromptEvalTarget(
        prompt_key="merge_judge",
        instructions_key="merge_judge",
        schema_type=MergeJudgeOutput,
        description="Decide whether two entities should be merged and return the merged identity profile.",
    ),
}


def get_prompt_eval_target(prompt_key: str) -> PromptEvalTarget | None:
    """按接口传入的 prompt key 查找可评测提示词配置。

    Args:
        prompt_key: 调用方传入的后端提示词 key。

    Returns:
        找到时返回提示词配置；未知 key 返回 None。
    """

    return PROMPT_EVAL_TARGETS.get(prompt_key)
