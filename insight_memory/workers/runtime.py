from __future__ import annotations

from difflib import get_close_matches
from typing import Any

from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.text import dedupe_preserve_order, normalize_text
from insight_memory.workers.llm_provider import LLMCallResult, llm_provider
from insight_memory.workers.prompts import get_worker_instructions
from insight_memory.workers.schemas import (
    AnswerJudgeOutput,
    AnswerComposerOutput,
    CandidateMemory,
    CrossEntityQueryBuilderOutput,
    EdgeJudgeOutput,
    ExtractorOutput,
    IdentityProfileDraft,
    LinkerOutput,
    MergeJudgeOutput,
    ProfileWriterOutput,
    QueryIdentityProfileDraft,
    QueryPlannerOutput,
    ResolverBatchOutput,
    ResolverOutput,
    WriteGateOutput,
)


logger = get_logger(__name__)


def _normalized_profile_draft(draft: IdentityProfileDraft) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "who": normalize_text(draft.who),
        "surface_forms": dedupe_preserve_order(draft.surface_forms, limit=3),
        "stable_qualifiers": dedupe_preserve_order(draft.stable_qualifiers, limit=4),
        "definition": normalize_text(draft.definition),
    }


def _normalized_surface_set(values: list[str] | None) -> set[str]:
    normalized: set[str] = set()
    for value in values or []:
        item = normalize_text(value).lower()
        if item:
            normalized.add(item)
    return normalized


def _normalized_record_markers(payload: dict[str, Any] | None) -> dict[str, str] | None:
    markers = dict(payload or {})
    normalized = {
        "session_label": normalize_text(markers.get("session_label")),
        "stage_label": normalize_text(markers.get("stage_label")),
        "round_label": normalize_text(markers.get("round_label")),
        "date_hint": normalize_text(markers.get("date_hint")),
    }
    result = {key: value for key, value in normalized.items() if value}
    return result or None


def _resolve_candidate_key_typo(
    *,
    selected_entity_key: str | None,
    candidate_keys: set[str | None],
) -> str | None:
    selected = str(selected_entity_key or "").strip()
    if not selected:
        return None
    valid_keys = sorted(key for key in candidate_keys if key)
    if selected in valid_keys or not valid_keys:
        return selected or None
    matches = get_close_matches(selected, valid_keys, n=2, cutoff=0.94)
    if len(matches) == 1:
        return matches[0]
    return None


def _build_short_ref_maps(values: list[str], prefix: str) -> tuple[dict[str, str], dict[str, str]]:
    """为 LLM 载荷生成稳定的短引用。"""

    value_to_ref: dict[str, str] = {}
    ref_to_value: dict[str, str] = {}
    for index, value in enumerate(values, start=1):
        ref = f"{prefix}{index}"
        value_to_ref[value] = ref
        ref_to_value[ref] = value
    return value_to_ref, ref_to_value


def _map_long_ids_to_short_refs(
    items: list[dict[str, Any]],
    *,
    id_field: str,
    prefix: str,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """将载荷里的长 id 替换为短引用，并返回双向映射。"""

    long_ids = [
        str(item.get(id_field) or "").strip()
        for item in items
        if str(item.get(id_field) or "").strip()
    ]
    long_to_short, short_to_long = _build_short_ref_maps(long_ids, prefix)
    transformed_items = [
        {
            **item,
            id_field: long_to_short[item_id],
        }
        for item in items
        if (item_id := str(item.get(id_field) or "").strip()) in long_to_short
    ]
    return transformed_items, long_to_short, short_to_long


def _map_short_ref_to_long_id(ref: str | None, short_to_long: dict[str, str]) -> str | None:
    """将短引用还原为原始长 id。"""

    return short_to_long.get(str(ref or "").strip()) or None


class MemoryWorkers:
    def __init__(self) -> None:
        pass

    async def run_write_gate(
        self,
        *,
        memory_space: str,
        context: str,
        request_id: str,
    ) -> WriteGateOutput:
        """同步判断写入内容是否具备可归属的稳定主体。

        Args:
            memory_space: 当前记忆空间。
            context: 原始写入内容。
            request_id: 当前请求 id。

        Returns:
            仅包含主体门禁结果和主体草稿的结构化输出。
        """

        payload = {
            "memory_space": memory_space,
            "context": context,
        }
        call = await self._run(
            provider_worker_type="write_gate",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=WriteGateOutput,
        )
        result = call.parsed
        normalized_drafts = []
        for draft in result.identity_profile_drafts:
            normalized = _normalized_profile_draft(draft)
            if not normalized["who"] or not normalized["surface_forms"]:
                continue
            normalized_drafts.append(
                IdentityProfileDraft(
                    schema_version=2,
                    draft_id=draft.draft_id,
                    who=normalized["who"],
                    surface_forms=normalized["surface_forms"],
                    stable_qualifiers=normalized["stable_qualifiers"],
                    definition=normalized["definition"],
                )
            )
        gate_status = "passed" if normalized_drafts else "rejected_no_identity_profile"
        logger.info(
            "worker write gate normalized",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "draft_count": len(normalized_drafts),
                "gate_status": gate_status,
                "drafts": [draft.model_dump() for draft in normalized_drafts],
            },
        )
        return WriteGateOutput(
            identity_gate_status=gate_status,
            identity_profile_drafts=normalized_drafts,
            write_rejection_reason=None if normalized_drafts else "cannot_extract_identity_profile",
        )

    @staticmethod
    async def _record_llm_run_best_effort(
        *,
        memory_space: str,
        worker_type: str,
        model: str,
        prompt_version: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any],
        parse_status: str,
        request_id: str,
        latency_ms: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        cached_tokens: int | None = None,
        cache_miss_tokens: int | None = None,
        reasoning_tokens: int | None = None,
    ) -> None:
        try:
            async with MemoryRepository() as repository:
                await repository.record_llm_run(
                    memory_space=memory_space,
                    worker_type=worker_type,
                    model=model,
                    prompt_version=prompt_version,
                    input_json=input_json,
                    output_json=output_json,
                    parse_status=parse_status,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                    cache_miss_tokens=cache_miss_tokens,
                    reasoning_tokens=reasoning_tokens,
                )
        except Exception as exc:
            logger.warning(
                "llm worker run logging skipped",
                extra={
                    "memory_space": memory_space,
                    "worker_type": worker_type,
                    "request_id": request_id,
                    "parse_status": parse_status,
                    "log_error": str(exc),
                },
            )

    async def run_extractor(
        self,
        *,
        memory_space: str,
        context: str,
        request_id: str,
    ) -> ExtractorOutput:
        payload = {
            "memory_space": memory_space,
            "context": context,
        }
        call = await self._run(
            provider_worker_type="extractor",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=ExtractorOutput,
        )
        result = call.parsed
        normalized_drafts = []
        for draft in result.identity_profile_drafts:
            normalized = _normalized_profile_draft(draft)
            if not normalized["who"] or not normalized["surface_forms"]:
                continue
            normalized_drafts.append(
                IdentityProfileDraft(
                    schema_version=2,
                    draft_id=draft.draft_id,
                    who=normalized["who"],
                    surface_forms=normalized["surface_forms"],
                    stable_qualifiers=normalized["stable_qualifiers"],
                    definition=normalized["definition"],
                )
            )
        valid_draft_ids = {draft.draft_id for draft in normalized_drafts}
        candidates = []
        for candidate in result.candidates:
            if candidate.owner_draft_id not in valid_draft_ids:
                logger.warning(
                    "worker extractor dropped candidate with invalid owner draft",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "candidate_id": candidate.candidate_id,
                        "owner_draft_id": candidate.owner_draft_id,
                        "valid_draft_ids": sorted(valid_draft_ids),
                    },
                )
                continue
            markers = _normalized_record_markers(
                candidate.record_markers.model_dump() if candidate.record_markers is not None else None
            )
            candidates.append(CandidateMemory.model_validate({**candidate.model_dump(), "record_markers": markers}))
        gate_status = "passed" if normalized_drafts else "rejected_no_identity_profile"
        logger.info(
            "worker extractor normalized",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "draft_count": len(normalized_drafts),
                "candidate_count": len(candidates),
                "gate_status": gate_status,
                "drafts": [draft.model_dump() for draft in normalized_drafts],
            },
        )
        return ExtractorOutput(
            identity_gate_status=gate_status,
            identity_profile_drafts=normalized_drafts,
            candidates=candidates,
            write_rejection_reason=None if normalized_drafts else "cannot_extract_identity_profile",
        )

    async def run_linker(
        self,
        *,
        memory_space: str,
        request_id: str,
        mode: str,
        identity_profile_draft: dict[str, Any],
        entity_candidates: list[dict[str, Any]],
    ) -> LinkerOutput:
        payload = {
            "mode": mode,
            "identity_profile_draft": identity_profile_draft,
            "entity_candidates": entity_candidates,
        }
        call = await self._run(
            provider_worker_type="linker",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=LinkerOutput,
        )
        result = call.parsed
        candidate_keys = {item.get("entity_key") for item in entity_candidates}
        corrected_entity_key = _resolve_candidate_key_typo(
            selected_entity_key=result.selected_entity_key,
            candidate_keys=candidate_keys,
        )
        if corrected_entity_key and corrected_entity_key != result.selected_entity_key:
            logger.info(
                "worker linker corrected candidate key typo",
                extra={
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "mode": mode,
                    "selected_entity_key": result.selected_entity_key,
                    "corrected_entity_key": corrected_entity_key,
                },
            )
            result = LinkerOutput(
                decision=result.decision,
                selected_entity_key=corrected_entity_key,
                ambiguous_entity_keys=result.ambiguous_entity_keys,
                confidence=result.confidence,
                reason=result.reason,
            )
        if result.selected_entity_key and result.selected_entity_key not in candidate_keys:
            logger.info(
                "worker linker selected unknown candidate",
                extra={
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "mode": mode,
                    "selected_entity_key": result.selected_entity_key,
                    "candidate_keys": sorted(item for item in candidate_keys if item),
                },
            )
            return LinkerOutput(decision="create_new" if mode == "write" else "cannot_resolve", confidence=0.0, reason="selected_entity_not_in_candidates")
        if result.decision == "ambiguous":
            ambiguous_keys = [item for item in result.ambiguous_entity_keys if item in candidate_keys]
            logger.info(
                "worker linker ambiguous",
                extra={
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "mode": mode,
                    "candidate_count": len(entity_candidates),
                    "ambiguous_entity_keys": ambiguous_keys,
                    "confidence": result.confidence,
                },
            )
            return LinkerOutput(
                decision="ambiguous",
                ambiguous_entity_keys=ambiguous_keys,
                confidence=result.confidence,
                reason=result.reason,
            )
        logger.info(
            "worker linker resolved",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "mode": mode,
                "decision": result.decision,
                "selected_entity_key": result.selected_entity_key,
                "candidate_count": len(entity_candidates),
                "confidence": result.confidence,
            },
        )
        return result

    async def run_resolver(
        self,
        *,
        memory_space: str,
        request_id: str,
        candidate_memories: list[dict[str, Any]],
        existing_memories: list[dict[str, Any]],
        ) -> list[ResolverOutput]:
        return await self._run_resolver_like(
            worker_type="resolver",
            memory_space=memory_space,
            request_id=request_id,
            candidate_memories=candidate_memories,
            existing_memories=existing_memories,
        )

    async def run_same_batch_resolver(
        self,
        *,
        memory_space: str,
        request_id: str,
        candidate_memories: list[dict[str, Any]],
        existing_memories: list[dict[str, Any]],
    ) -> list[ResolverOutput]:
        return await self._run_resolver_like(
            worker_type="same_batch_resolver",
            memory_space=memory_space,
            request_id=request_id,
            candidate_memories=candidate_memories,
            existing_memories=existing_memories,
        )

    async def _run_resolver_like(
        self,
        *,
        worker_type: str,
        memory_space: str,
        request_id: str,
        candidate_memories: list[dict[str, Any]],
        existing_memories: list[dict[str, Any]],
    ) -> list[ResolverOutput]:
        allowed_target_ids = {
            str(item.get("memory_id") or "").strip()
            for item in existing_memories
        } | {
            str(item.get("candidate_id") or "").strip()
            for item in candidate_memories
        }
        candidate_payload, _, candidate_ref_to_id = _map_long_ids_to_short_refs(
            candidate_memories,
            id_field="candidate_id",
            prefix="c",
        )
        existing_payload, _, existing_ref_to_id = _map_long_ids_to_short_refs(
            existing_memories,
            id_field="memory_id",
            prefix="m",
        )
        payload = {
            "candidate_memories": candidate_payload,
            "existing_memories": existing_payload,
        }
        call = await self._run(
            provider_worker_type=worker_type,
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=ResolverBatchOutput,
        )
        resolved_by_candidate_id: dict[str, ResolverOutput] = {}
        for item in call.parsed.items:
            candidate_id = _map_short_ref_to_long_id(item.candidate_id, candidate_ref_to_id)
            if not candidate_id:
                logger.warning(
                    "worker resolver returned unknown candidate ref",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "worker_type": worker_type,
                        "candidate_ref": item.candidate_id,
                        "known_candidate_refs": sorted(candidate_ref_to_id),
                    },
                )
                continue
            target_memory_id = (
                _map_short_ref_to_long_id(item.target_memory_id, existing_ref_to_id)
                or _map_short_ref_to_long_id(item.target_memory_id, candidate_ref_to_id)
            )
            if item.target_memory_id and target_memory_id is None:
                logger.warning(
                    "worker resolver returned unknown target ref",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "worker_type": worker_type,
                        "candidate_id": candidate_id,
                        "target_ref": item.target_memory_id,
                        "known_candidate_refs": sorted(candidate_ref_to_id),
                        "known_existing_refs": sorted(existing_ref_to_id),
                        "allowed_target_ids": sorted(allowed_target_ids),
                    },
                )
            resolved_by_candidate_id[candidate_id] = item.model_copy(
                update={
                    "candidate_id": candidate_id,
                    "target_memory_id": target_memory_id,
                }
            )
        outputs: list[ResolverOutput] = []
        for candidate in candidate_memories:
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            resolved = resolved_by_candidate_id.get(candidate_id)
            if resolved is None:
                logger.warning(
                    "worker resolver dropped candidate without output",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "worker_type": worker_type,
                        "candidate_id": candidate_id,
                        "returned_candidate_ids": sorted(resolved_by_candidate_id),
                    },
                )
                continue
            if resolved.target_memory_id and resolved.target_memory_id not in allowed_target_ids:
                logger.warning(
                    "worker resolver ignored invalid target memory",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "worker_type": worker_type,
                        "candidate_id": candidate_id,
                        "target_memory_id": resolved.target_memory_id,
                        "allowed_target_ids": sorted(allowed_target_ids),
                    },
                )
                resolved = resolved.model_copy(update={"target_memory_id": None, "action": "create"})
            if resolved.action in {"refresh", "replace", "stale"} and not resolved.target_memory_id:
                logger.warning(
                    "worker resolver action missing usable target memory",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "worker_type": worker_type,
                        "candidate_id": candidate_id,
                        "action": resolved.action,
                    },
                )
                resolved = resolved.model_copy(update={"target_memory_id": None, "action": "create"})
            outputs.append(resolved)
        logger.info(
            "worker resolver batch resolved",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "worker_type": worker_type,
                "candidate_count": len(candidate_memories),
                "existing_count": len(existing_memories),
                "output_count": len(outputs),
                "actions": [item.action for item in outputs],
                "target_memory_ids": [item.target_memory_id for item in outputs if item.target_memory_id],
            },
        )
        return outputs

    async def run_query_planner(
        self,
        *,
        memory_space: str,
        query: str,
        request_id: str,
    ) -> QueryPlannerOutput:
        payload = {"memory_space": memory_space, "query": query}
        call = await self._run(
            provider_worker_type="query_planner",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=QueryPlannerOutput,
        )
        result = call.parsed
        normalized_drafts = []
        for draft in result.query_identity_profile_drafts:
            normalized = _normalized_profile_draft(draft)
            query_text = normalize_text(draft.query_text)
            if not normalized["who"] or not normalized["surface_forms"] or not query_text:
                continue
            normalized_drafts.append(
                QueryIdentityProfileDraft(
                    schema_version=2,
                    draft_id=draft.draft_id,
                    who=normalized["who"],
                    surface_forms=normalized["surface_forms"],
                    stable_qualifiers=normalized["stable_qualifiers"],
                    definition=normalized["definition"],
                    query_text=query_text,
                )
            )
        gate_status = "passed" if normalized_drafts else "rejected_no_identity_profile"
        rewrites = dedupe_preserve_order(result.query_rewrites, limit=3)
        logger.info(
            "worker query planner normalized",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "gate_status": gate_status,
                "draft_count": len(normalized_drafts),
                "query_rewrite_count": len(rewrites),
                "time_intent": getattr(result.query_focus, "time_intent", None),
            },
        )
        return QueryPlannerOutput(
            query_gate_status=gate_status,
            query_identity_profile_drafts=normalized_drafts,
            query_rewrites=rewrites,
            query_focus=result.query_focus,
            query_rejection_reason=None if normalized_drafts else "cannot_resolve_query_identity",
        )

    async def run_cross_entity_query_builder(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> CrossEntityQueryBuilderOutput:
        call = await self._run(
            provider_worker_type="cross_entity_query_builder",
            record_worker_type="query_planner",
            instructions_key="cross_entity_query_builder",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=CrossEntityQueryBuilderOutput,
        )
        query_texts = dedupe_preserve_order(call.parsed.query_texts, limit=6)
        logger.info(
            "worker cross entity query builder completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "query_text_count": len(query_texts),
                "query_texts": query_texts,
            },
        )
        return CrossEntityQueryBuilderOutput(query_texts=query_texts)

    async def run_answer_composer(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> AnswerComposerOutput:
        call = await self._run(
            provider_worker_type="answer_composer",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=AnswerComposerOutput,
        )
        logger.info(
            "worker answer composer completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "answer_length": len(str(call.parsed.answer or "")),
                "citation_count": len(call.parsed.citations),
                "uncertainty_count": len(call.parsed.uncertainties),
            },
        )
        return call.parsed

    async def run_answer_judge(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> AnswerJudgeOutput:
        call = await self._run(
            provider_worker_type="answer_judge",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=AnswerJudgeOutput,
        )
        logger.info(
            "worker answer judge completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "verdict": call.parsed.verdict,
                "grounded": call.parsed.grounded,
            },
        )
        return call.parsed

    async def run_profile_writer(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> ProfileWriterOutput:
        call = await self._run(
            provider_worker_type="profile_writer",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=ProfileWriterOutput,
        )
        normalized = _normalized_profile_draft(
            IdentityProfileDraft(
                schema_version=2,
                draft_id="profile_writer",
                who=call.parsed.who,
                surface_forms=call.parsed.surface_forms,
                stable_qualifiers=call.parsed.stable_qualifiers,
                definition=call.parsed.definition,
            )
        )
        logger.info(
            "worker profile writer completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "who": normalized["who"],
                "surface_forms": normalized["surface_forms"],
            },
        )
        return ProfileWriterOutput(**normalized)

    async def run_edge_judge(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> EdgeJudgeOutput:
        call = await self._run(
            provider_worker_type="edge_judge",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=EdgeJudgeOutput,
        )
        logger.info(
            "worker edge judge completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "relation_count": len(call.parsed.relations),
                "edge_types": [item.edge_type for item in call.parsed.relations],
            },
        )
        return call.parsed

    async def run_merge_judge(
        self,
        *,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> MergeJudgeOutput:
        call = await self._run(
            provider_worker_type="merge_judge",
            memory_space=memory_space,
            request_id=request_id,
            payload=payload,
            schema_type=MergeJudgeOutput,
        )
        parsed = call.parsed
        if parsed.merged_identity_profile is not None:
            normalized = _normalized_profile_draft(
                IdentityProfileDraft(
                    schema_version=2,
                    draft_id="merge_judge",
                    who=parsed.merged_identity_profile.who,
                    surface_forms=parsed.merged_identity_profile.surface_forms,
                    stable_qualifiers=parsed.merged_identity_profile.stable_qualifiers,
                    definition=parsed.merged_identity_profile.definition,
                )
            )
            parsed = MergeJudgeOutput(
                decision=parsed.decision,
                survivor_entity_key=parsed.survivor_entity_key,
                merged_identity_profile=ProfileWriterOutput(**normalized),
                reason=parsed.reason,
            )
        logger.info(
            "worker merge judge completed",
            extra={
                "memory_space": memory_space,
                "request_id": request_id,
                "decision": parsed.decision,
                "survivor_entity_key": parsed.survivor_entity_key,
            },
        )
        return parsed

    async def _run(
        self,
        *,
        provider_worker_type: str,
        memory_space: str,
        request_id: str,
        payload: dict[str, Any],
        schema_type,
        record_worker_type: str | None = None,
        instructions_key: str | None = None,
    ) -> LLMCallResult:
        effective_record_worker_type = record_worker_type or provider_worker_type
        effective_instructions_key = instructions_key or provider_worker_type
        try:
            instructions = get_worker_instructions(effective_instructions_key)
            logger.info(
                "llm worker call started",
                extra={
                    "worker_type": provider_worker_type,
                    "record_worker_type": effective_record_worker_type,
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "instructions_preview": instructions,
                    "payload_keys": sorted(payload.keys()),
                    "llm_input": payload,
                },
            )
            call = await llm_provider.generate(
                worker_type=provider_worker_type,
                instructions=instructions,
                payload=payload,
                schema_type=schema_type,
            )
            await self._record_llm_run_best_effort(
                memory_space=memory_space,
                worker_type=effective_record_worker_type,
                model=call.model,
                prompt_version=call.prompt_version,
                input_json=payload,
                output_json=call.output_json,
                parse_status="ok",
                request_id=request_id,
                latency_ms=call.latency_ms,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cached_tokens=call.cached_tokens,
                cache_miss_tokens=call.cache_miss_tokens,
                reasoning_tokens=call.reasoning_tokens,
            )
            logger.info(
                "llm worker call completed",
                extra={
                    "worker_type": provider_worker_type,
                    "record_worker_type": effective_record_worker_type,
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "model": call.model,
                    "latency_ms": call.latency_ms,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "llm_output": call.output_json,
                },
            )
            return call
        except Exception as exc:
            await self._record_llm_run_best_effort(
                memory_space=memory_space,
                worker_type=effective_record_worker_type,
                model=llm_provider.model_name,
                prompt_version=llm_provider.prompt_version,
                input_json=payload,
                output_json={"error": str(exc)},
                parse_status="schema_error",
                request_id=request_id,
                latency_ms=None,
                input_tokens=None,
                output_tokens=None,
            )
            logger.exception(
                "llm worker call failed",
                extra={
                    "worker_type": provider_worker_type,
                    "record_worker_type": effective_record_worker_type,
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "llm_input": payload,
                    "error": str(exc),
                },
            )
            raise
