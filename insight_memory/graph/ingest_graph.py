from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.config import settings
from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.utils.locks import entity_memory_resolution_lock, entity_resolution_lock
from insight_memory.workers.runtime import MemoryWorkers
from insight_memory.workers.schemas import ResolverOutput
logger = get_logger(__name__)


def _display_name_from_profile(identity_profile: dict[str, Any]) -> str:
    """从 identity profile 提取展示名称。

    Args:
        identity_profile: 已规范化的主体画像。

    Returns:
        优先使用首个 surface form；缺失时回退到 `who`，再缺失则返回 `Unknown`。
    """

    surface_forms = identity_profile.get("surface_forms") or []
    if surface_forms:
        return str(surface_forms[0])
    return str(identity_profile.get("who") or "Unknown")


def _identity_profile_key(identity_profile: dict[str, Any]) -> str:
    """为同一 observation 内完全相同的 identity profile 生成稳定去重 key。

    Args:
        identity_profile: 已规范化的主体画像。

    Returns:
        只包含 identity 字段的稳定 JSON 字符串。这里故意只做精确匹配，不做语义相似判断，
        避免把同一篇 observation 里的不同主体误合并。
    """

    payload = {
        "who": str(identity_profile.get("who") or "").strip(),
        "surface_forms": [str(item).strip() for item in identity_profile.get("surface_forms") or []],
        "distinguishing_context": [
            str(item).strip()
            for item in identity_profile.get("distinguishing_context") or []
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _build_hot_path_edges(
    *,
    action: str,
    observation_id: str | None,
    new_memory_id: str | None = None,
    target_memory_id: str | None = None,
) -> list[dict[str, Any]]:
    """根据 resolver 决策生成主路径需要立即写入的边。

    Args:
        action: 当前 resolver 动作。
        observation_id: 触发本次写入的 observation id。
        new_memory_id: 新创建 memory 的 id。
        target_memory_id: resolver 指向的目标 memory id。

    Returns:
        需要立即落库的边列表，仅包含 `derived_from` 和 `updates`。
    """

    edges: list[dict[str, Any]] = []
    if action in {"create", "coexist", "replace"} and new_memory_id and observation_id:
        edges.append(
            {
                "from_id": new_memory_id,
                "to_kind": "observation",
                "to_id": observation_id,
                "edge_type": "derived_from",
                "reason": f"resolver:{action}",
            }
        )
    if action == "refresh" and target_memory_id and observation_id:
        edges.append(
            {
                "from_id": target_memory_id,
                "to_kind": "observation",
                "to_id": observation_id,
                "edge_type": "derived_from",
                "reason": "resolver:refresh",
            }
        )
    if action == "replace" and new_memory_id and target_memory_id:
        edges.append(
            {
                "from_id": new_memory_id,
                "to_kind": "memory",
                "to_id": target_memory_id,
                "edge_type": "updates",
                "reason": "resolver:replace",
            }
        )
    return edges


def _compact_text(value: str) -> str:
    """Normalize text for exact containment checks during generic refresh merging."""

    return " ".join(str(value or "").split()).casefold()


def _direct_entity_resolution_decision(
    *,
    scored_candidates: list[Any],
) -> tuple[str, str | None]:
    """为无歧义场景给出 entity 直连决策。

    这个函数只负责 ingest 主路径里的 fast path 判定，不负责完整的实体消歧。
    候选集来自 `retrieval_index.entity_candidates(...)` 的语义检索结果，因此这里依赖
    语义检索判断“库里是否存在相近实体”，而不是做全量精确匹配，也不是只看 `who`
    字段做字符串比较。

    这里不使用硬编码的相似度阈值直接 `link_existing`。原因是向量检索分数的尺度会受
    embedding 模型、pgvector 距离策略、LlamaIndex 返回值和是否经过融合排序影响；同一个
    数字阈值在不同模型或索引配置下并不稳定。实体误链接的代价高于多一次 linker 调用，
    所以只把语义检索结果作为候选召回信号，真正的实体消歧仍交给 linker。

    决策规则按顺序执行：

    1. 没有候选时，直接返回 `create_new`。
    2. 只要有候选，返回 `needs_linker`，让 linker 基于候选 entity profile 和近期
       memories 做完整判断。

    本次 observation 内刚创建的 entity 不会在当前 draft loop 中写入向量索引，因此
    这里看到的候选只应来自历史已提交索引。历史候选可能是真正的同一主体，也可能只是
    相似但不同的主体，所以只要有候选就交给 linker 做完整判断。

    Args:
        scored_candidates: retrieval 返回的 entity 候选。

    Returns:
        二元组 `(decision, selected_entity_key)`：
        - `create_new`: 当前 draft 可直接新建。
        - `link_existing`: 当前实现不会直接返回；保留该返回值是为了兼容调用方协议。
        - `needs_linker`: 仍需调用 linker 判定。
    """

    if not scored_candidates:
        return "create_new", None

    return "needs_linker", None


def _build_direct_create_resolver(candidate: Any) -> ResolverOutput:
    """为单候选首次写入场景构造等价的 create 决策。

    Args:
        candidate: extractor 输出的 candidate memory。

    Returns:
        与 candidate 内容等价的 `ResolverOutput(action="create")`。
    """

    return ResolverOutput(
        candidate_id=candidate.candidate_id,
        action="create",
        target_memory_id=None,
        title=candidate.title,
        summary=candidate.summary,
        content=candidate.content,
        confidence=candidate.confidence,
        salience=candidate.salience,
        reason="single_candidate_without_existing_memory",
    )


def _merge_refresh_text(*, existing_text: str, refreshed_text: str, detail_label: str) -> str:
    """Preserve existing details when a refresh adds or tightens memory content.

    Args:
        existing_text: The currently persisted memory field.
        refreshed_text: The resolver-provided refreshed field.
        detail_label: Label used when both fields contain distinct details.

    Returns:
        A combined field that keeps both old and new details without duplicating exact text.
    """

    existing = str(existing_text or "").strip()
    refreshed = str(refreshed_text or "").strip()
    if not existing:
        return refreshed
    if not refreshed:
        return existing

    normalized_existing = _compact_text(existing)
    normalized_refreshed = _compact_text(refreshed)
    if normalized_existing and normalized_existing in normalized_refreshed:
        return refreshed
    if normalized_refreshed and normalized_refreshed in normalized_existing:
        return existing
    return f"{existing}\n\n{detail_label}: {refreshed}"


class IngestState(TypedDict, total=False):
    memory_space: str
    request_id: str
    workers: MemoryWorkers
    context: str
    extractor: Any
    observation_id: str
    draft_to_entity: dict[str, str]
    affected_entity_keys: list[str]
    affected_memory_ids: list[str]
    result: dict[str, Any]


class IngestGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def continue_ingest(
        self,
        *,
        memory_space: str,
        request_id: str,
        observation_id: str,
        context: str,
    ) -> dict[str, Any]:
        """从原始上下文重跑完整 extractor，并继续后台写入图。

        Args:
            memory_space: 当前记忆空间。
            request_id: 当前请求 id。
            observation_id: 同步 write_gate 阶段创建的 observation id。
            context: 原始写入内容。

        Returns:
            后台写入图执行结果；如果完整 extractor 拒绝，则返回 rejected 结果。

        Raises:
            ValueError: 缺少必需的 context 字段。
        """

        try:
            result = await self._graph.ainvoke(
                {
                    "memory_space": memory_space,
                    "request_id": request_id,
                    "workers": MemoryWorkers(),
                    "context": context,
                    "observation_id": observation_id,
                    "draft_to_entity": {},
                    "affected_entity_keys": [],
                    "affected_memory_ids": [],
                }
            )
            return dict(result.get("result") or {})
        except Exception as exc:
            async with MemoryRepository() as repository:
                await repository.mark_observation_resolved(
                    memory_space=memory_space,
                    observation_id=observation_id,
                    status="unresolved",
                    metadata={
                        "continuation_error_code": type(exc).__name__,
                        "continuation_error_message": str(exc),
                    },
                )
            raise

    def _build_graph(self):
        graph = StateGraph(IngestState)
        graph.add_node("extract", self._extract)
        graph.add_node("mark_extractor_rejected", self._mark_extractor_rejected)
        graph.add_node("resolve_entities", self._resolve_entities)
        graph.add_node("resolve_candidates", self._resolve_candidates)
        graph.add_node("finalize", self._finalize)

        graph.set_entry_point("extract")
        graph.add_conditional_edges(
            "extract",
            self._route_after_extract,
            {
                "passed": "resolve_entities",
                "rejected": "mark_extractor_rejected",
            },
        )
        graph.add_edge("mark_extractor_rejected", END)
        graph.add_edge("resolve_entities", "resolve_candidates")
        graph.add_edge("resolve_candidates", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def _extract(self, state: IngestState) -> dict[str, Any]:
        """在 graph 内从原始 context 运行完整 extractor。

        Args:
            state: 当前 ingest graph 状态，必须包含原始 context。

        Returns:
            包含完整 extractor 输出的状态增量。

        Raises:
            ValueError: 缺少必需的 context 字段。
        """

        context = str(state.get("context") or "").strip()
        if not context:
            raise ValueError("continue_ingest payload requires non-empty context")

        extractor = await state["workers"].run_extractor(
            memory_space=state["memory_space"],
            request_id=state["request_id"],
            context=context,
        )
        return {"extractor": extractor}

    @staticmethod
    def _route_after_extract(state: IngestState) -> str:
        """根据完整 extractor 的门禁结果选择后续 graph 节点。

        Args:
            state: 已包含 extractor 输出的 graph 状态。

        Returns:
            `passed` 进入正常写入链路，`rejected` 进入 observation unresolved 标记节点。
        """

        extractor = state["extractor"]
        if extractor.identity_gate_status == "passed":
            return "passed"
        return "rejected"

    async def _mark_extractor_rejected(self, state: IngestState) -> dict[str, Any]:
        """处理后台完整 extractor 拒绝的 observation 状态。

        Args:
            state: 已包含 rejected extractor 输出的 graph 状态。

        Returns:
            包含 rejected API 结果的状态增量。
        """

        extractor = state["extractor"]
        error_code = extractor.write_rejection_reason or "cannot_extract_identity_profile"
        async with MemoryRepository() as repository:
            await repository.mark_observation_resolved(
                memory_space=state["memory_space"],
                observation_id=state["observation_id"],
                status="unresolved",
                metadata={
                    "extractor_status": extractor.identity_gate_status,
                    "extractor_rejection_reason": error_code,
                },
            )
        logger.info(
            "continue ingest rejected by background extractor",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "observation_id": state["observation_id"],
                "error_code": error_code,
            },
        )
        return {
            "result": {
                "status": "rejected",
                "observation_id": state["observation_id"],
                "affected_entity_keys": [],
                "affected_memory_ids": [],
                "error_code": error_code,
            }
        }

    async def _resolve_entities(self, state: IngestState) -> dict[str, Any]:
        workers = state["workers"]
        extractor = state["extractor"]
        draft_to_entity = dict(state.get("draft_to_entity") or {})
        affected_entity_keys = list(state.get("affected_entity_keys") or [])
        referenced_draft_ids = {
            candidate.owner_draft_id
            for candidate in extractor.candidates
            if candidate.owner_draft_id
        }
        logger.info(
            "ingest entity resolution started",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "draft_count": len(extractor.identity_profile_drafts),
                "candidate_count": len(extractor.candidates),
                "referenced_draft_ids": sorted(referenced_draft_ids),
            },
        )

        async with entity_resolution_lock(memory_space=state["memory_space"]):
            entities_by_key: dict[str, Any] = {}
            local_entities_by_identity_key: dict[str, Any] = {}
            new_entities_to_refresh: list[Any] = []
            for draft in extractor.identity_profile_drafts:
                if draft.draft_id not in referenced_draft_ids:
                    logger.info(
                        "ingest entity draft skipped without referenced candidates",
                        extra={
                            "memory_space": state["memory_space"],
                            "request_id": state["request_id"],
                            "draft_id": draft.draft_id,
                        },
                    )
                    continue
                identity_profile = draft.model_dump()
                identity_key = _identity_profile_key(identity_profile)
                entity = local_entities_by_identity_key.get(identity_key)
                decision = ""
                selected_entity_key = None
                linker = None
                local_identity_reused = entity is not None
                if entity is None:
                    scored_candidates = await retrieval_index.entity_candidates(
                        memory_space=state["memory_space"],
                        draft=identity_profile,
                        limit=10,
                    )
                    decision, selected_entity_key = _direct_entity_resolution_decision(
                        scored_candidates=scored_candidates,
                    )
                else:
                    scored_candidates = []
                if entity is None and decision == "needs_linker":
                    candidate_payload = []
                    async with MemoryRepository() as repository:
                        for item in scored_candidates:
                            recent_memories = await repository.list_memories(
                                memory_space=state["memory_space"],
                                entity_key=item.entity.entity_key,
                                statuses=("active", "superseded", "stale"),
                                limit=5,
                            )
                            candidate_payload.append(
                                {
                                    "entity_key": item.entity.entity_key,
                                    "display_name": item.entity.display_name,
                                    "identity_profile": item.entity.identity_profile,
                                    "score": item.score,
                                    "recent_memory_summaries": [memory.summary for memory in recent_memories],
                                }
                            )
                    linker = await workers.run_linker(
                        memory_space=state["memory_space"],
                        request_id=state["request_id"],
                        mode="write",
                        identity_profile_draft=identity_profile,
                        entity_candidates=candidate_payload,
                    )
                    logger.info(
                        "ingest entity linker decision",
                        extra={
                            "memory_space": state["memory_space"],
                            "request_id": state["request_id"],
                            "draft_id": draft.draft_id,
                            "draft": identity_profile,
                            "candidate_count": len(candidate_payload),
                            "decision": linker.decision,
                            "selected_entity_key": linker.selected_entity_key,
                        },
                    )
                if entity is None:
                    async with MemoryRepository() as repository:
                        if decision == "link_existing" and selected_entity_key:
                            entity = entities_by_key.get(selected_entity_key)
                            if entity is None:
                                entity = await repository.get_entity(
                                    memory_space=state["memory_space"],
                                    entity_key=selected_entity_key,
                                )
                        elif linker is not None and linker.decision == "link_existing" and linker.selected_entity_key:
                            entity = entities_by_key.get(linker.selected_entity_key)
                            if entity is None:
                                entity = await repository.get_entity(
                                    memory_space=state["memory_space"],
                                    entity_key=linker.selected_entity_key,
                                )
                        if entity is None:
                            entity = await repository.create_entity(
                                memory_space=state["memory_space"],
                                display_name=_display_name_from_profile(identity_profile),
                                identity_profile=identity_profile,
                                metadata={"created_via": "ingest_graph"},
                            )
                            new_entities_to_refresh.append(entity)
                        entities_by_key[entity.entity_key] = entity
                local_entities_by_identity_key[identity_key] = entity
                draft_to_entity[draft.draft_id] = entity.entity_key
                if entity.entity_key not in affected_entity_keys:
                    affected_entity_keys.append(entity.entity_key)
                logger.info(
                    "ingest entity resolved",
                    extra={
                        "memory_space": state["memory_space"],
                        "request_id": state["request_id"],
                        "draft_id": draft.draft_id,
                        "entity_key": entity.entity_key,
                        "display_name": entity.display_name,
                        "local_identity_reused": local_identity_reused,
                    },
                )
            if new_entities_to_refresh:
                await retrieval_index.refresh_entities(entities=new_entities_to_refresh)
                logger.info(
                    "ingest entity batch refresh completed",
                    extra={
                        "memory_space": state["memory_space"],
                        "request_id": state["request_id"],
                        "observation_id": state["observation_id"],
                        "entity_count": len(new_entities_to_refresh),
                    },
                )
        logger.info(
            "ingest entity resolution completed",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "observation_id": state["observation_id"],
                "resolved_entity_count": len(affected_entity_keys),
            },
        )
        return {
            "draft_to_entity": draft_to_entity,
            "affected_entity_keys": affected_entity_keys,
        }

    async def _resolve_candidates(self, state: IngestState) -> dict[str, Any]:
        workers = state["workers"]
        extractor = state["extractor"]
        observation_id = state["observation_id"]
        draft_to_entity = state.get("draft_to_entity") or {}
        affected_memory_ids = list(state.get("affected_memory_ids") or [])

        candidates_by_entity: dict[str, list[Any]] = {}
        for candidate in extractor.candidates:
            entity_key = draft_to_entity.get(candidate.owner_draft_id)
            if entity_key:
                candidates_by_entity.setdefault(entity_key, []).append(candidate)
                continue
            logger.warning(
                "ingest candidate skipped without resolved entity",
                extra={
                    "memory_space": state["memory_space"],
                    "request_id": state["request_id"],
                    "candidate_id": candidate.candidate_id,
                    "owner_draft_id": candidate.owner_draft_id,
                    "resolved_draft_ids": sorted(draft_to_entity),
                },
            )
        if extractor.candidates and not candidates_by_entity:
            logger.warning(
                "ingest has candidates but none mapped to entities",
                extra={
                    "memory_space": state["memory_space"],
                    "request_id": state["request_id"],
                    "candidate_count": len(extractor.candidates),
                    "resolved_draft_ids": sorted(draft_to_entity),
                },
            )

        for entity_key, entity_candidates in candidates_by_entity.items():
            async with entity_memory_resolution_lock(
                memory_space=state["memory_space"],
                entity_key=entity_key,
            ):
                async with MemoryRepository() as repository:
                    existing_memories = await repository.list_memories(
                        memory_space=state["memory_space"],
                        entity_key=entity_key,
                        statuses=("active", "stale", "superseded"),
                        limit=20,
                    )
                candidate_by_id = {
                    candidate.candidate_id: candidate
                    for candidate in entity_candidates
                }
                if not existing_memories and len(entity_candidates) == 1:
                    resolver_outputs = [_build_direct_create_resolver(entity_candidates[0])]
                    logger.info(
                        "ingest resolver fast path used",
                        extra={
                            "memory_space": state["memory_space"],
                            "request_id": state["request_id"],
                            "entity_key": entity_key,
                            "candidate_id": entity_candidates[0].candidate_id,
                        },
                    )
                else:
                    resolver_outputs = await workers.run_resolver(
                        memory_space=state["memory_space"],
                        request_id=state["request_id"],
                        candidate_memories=[candidate.model_dump() for candidate in entity_candidates],
                        existing_memories=[
                            {
                                "memory_id": item.memory_id,
                                "title": item.title,
                                "summary": item.summary,
                                "content": item.content,
                                "status": item.status,
                                "confidence": item.confidence,
                                "salience": item.salience,
                                "record_markers": (item.metadata_json or {}).get("record_markers"),
                                "created_at": item.created_at,
                                "updated_at": item.updated_at,
                            }
                            for item in existing_memories
                        ],
                    )
                    if self._should_retry_same_batch_resolution(
                        existing_memories=existing_memories,
                        resolver_outputs=resolver_outputs,
                    ):
                        resolver_outputs = await workers.run_same_batch_resolver(
                            memory_space=state["memory_space"],
                            request_id=state["request_id"],
                            candidate_memories=[candidate.model_dump() for candidate in entity_candidates],
                            existing_memories=self._build_same_batch_existing_memories(
                                resolver_outputs=resolver_outputs,
                                candidates_by_id=candidate_by_id,
                            ),
                        )
                        logger.info(
                            "ingest resolver same-batch normalization completed",
                            extra={
                                "memory_space": state["memory_space"],
                                "request_id": state["request_id"],
                                "entity_key": entity_key,
                                "candidate_count": len(entity_candidates),
                                "resolver_output_count": len(resolver_outputs),
                            },
                        )
                logger.info(
                    "ingest resolver batch completed",
                    extra={
                        "memory_space": state["memory_space"],
                        "request_id": state["request_id"],
                        "entity_key": entity_key,
                        "candidate_count": len(entity_candidates),
                        "existing_memory_count": len(existing_memories),
                        "resolver_output_count": len(resolver_outputs),
                    },
                )
                existing_memory_ids = {item.memory_id for item in existing_memories}
                batch_created_memory_ids: dict[str, str] = {}
                pending_resolvers = list(resolver_outputs)
                processed_resolvers: set[str] = set()
                while pending_resolvers:
                    progressed = False
                    next_pending: list[Any] = []
                    for resolver in pending_resolvers:
                        candidate = candidate_by_id.get(resolver.candidate_id)
                        if candidate is None:
                            continue
                        if self._resolver_waits_for_batch_target(
                            resolver=resolver,
                            candidate_ids=set(candidate_by_id),
                            existing_memory_ids=existing_memory_ids,
                            batch_created_memory_ids=batch_created_memory_ids,
                        ):
                            next_pending.append(resolver)
                            continue
                        action, created_memory_id, target_memory_id = await self._persist_resolver_output(
                            memory_space=state["memory_space"],
                            request_id=state["request_id"],
                            entity_key=entity_key,
                            observation_id=observation_id,
                            candidate=candidate,
                            resolver=resolver,
                            batch_created_memory_ids=batch_created_memory_ids,
                        )
                        processed_resolvers.add(resolver.candidate_id)
                        if created_memory_id is not None:
                            batch_created_memory_ids[resolver.candidate_id] = created_memory_id
                        hot_path_edges = _build_hot_path_edges(
                            action=action,
                            observation_id=observation_id,
                            new_memory_id=created_memory_id,
                            target_memory_id=target_memory_id,
                        )
                        async with MemoryRepository() as repository:
                            await repository.create_edges(memory_space=state["memory_space"], edges=hot_path_edges)
                        if created_memory_id is not None:
                            affected_memory_ids.append(created_memory_id)
                        elif target_memory_id is not None:
                            affected_memory_ids.append(target_memory_id)
                        logger.info(
                            "ingest hot path edges created",
                            extra={
                                "memory_space": state["memory_space"],
                                "request_id": state["request_id"],
                                "entity_key": entity_key,
                                "candidate_id": candidate.candidate_id,
                                "action": action,
                                "edge_types": [edge["edge_type"] for edge in hot_path_edges],
                            },
                        )
                        progressed = True
                    if not next_pending:
                        break
                    if not progressed:
                        pending_resolvers = next_pending
                        break
                    pending_resolvers = next_pending

                for resolver in pending_resolvers:
                    candidate = candidate_by_id.get(resolver.candidate_id)
                    if candidate is None or resolver.candidate_id in processed_resolvers:
                        continue
                    action, created_memory_id, target_memory_id = await self._persist_resolver_output(
                        memory_space=state["memory_space"],
                        request_id=state["request_id"],
                        entity_key=entity_key,
                        observation_id=observation_id,
                        candidate=candidate,
                        resolver=resolver,
                        batch_created_memory_ids=batch_created_memory_ids,
                    )
                    if created_memory_id is not None:
                        batch_created_memory_ids[resolver.candidate_id] = created_memory_id
                    hot_path_edges = _build_hot_path_edges(
                        action=action,
                        observation_id=observation_id,
                        new_memory_id=created_memory_id,
                        target_memory_id=target_memory_id,
                    )
                    async with MemoryRepository() as repository:
                        await repository.create_edges(memory_space=state["memory_space"], edges=hot_path_edges)
                    if created_memory_id is not None:
                        affected_memory_ids.append(created_memory_id)
                    elif target_memory_id is not None:
                        affected_memory_ids.append(target_memory_id)
                    logger.info(
                        "ingest hot path edges created",
                        extra={
                            "memory_space": state["memory_space"],
                            "request_id": state["request_id"],
                            "entity_key": entity_key,
                            "candidate_id": candidate.candidate_id,
                            "action": action,
                            "edge_types": [edge["edge_type"] for edge in hot_path_edges],
                        },
                    )
        return {"affected_memory_ids": affected_memory_ids}

    async def _persist_resolver_output(
        self,
        *,
        memory_space: str,
        request_id: str,
        entity_key: str,
        observation_id: str,
        candidate: Any,
        resolver: Any,
        batch_created_memory_ids: dict[str, str] | None = None,
    ) -> tuple[str, str | None, str | None]:
        async with MemoryRepository() as repository:
            action = resolver.action
            current_target_memory = None
            if resolver.target_memory_id:
                current_target_memory = await repository.get_memory(
                    memory_space=memory_space,
                    memory_id=resolver.target_memory_id,
                )
                if current_target_memory is None and batch_created_memory_ids is not None:
                    batch_target_memory_id = batch_created_memory_ids.get(resolver.target_memory_id)
                    if batch_target_memory_id:
                        current_target_memory = await repository.get_memory(
                            memory_space=memory_space,
                            memory_id=batch_target_memory_id,
                        )
            if action in {"refresh", "replace", "stale"} and current_target_memory is None:
                action = "create"

            memory_metadata = {
                "candidate_id": candidate.candidate_id,
                "request_id": request_id,
                "record_markers": candidate.record_markers.model_dump() if candidate.record_markers is not None else None,
            }
            created_memory_id: str | None = None
            target_memory_id = current_target_memory.memory_id if current_target_memory is not None else None

            if action in {"create", "coexist", "replace"}:
                new_memory = await repository.create_memory(
                    memory_space=memory_space,
                    entity_key=entity_key,
                    title=resolver.title,
                    summary=resolver.summary,
                    content=resolver.content,
                    confidence=resolver.confidence,
                    salience=resolver.salience,
                    status="active",
                    latest_source_observation_id=observation_id,
                    metadata=memory_metadata,
                )
                await repository.create_memory_version(
                    memory_space=memory_space,
                    memory=new_memory,
                    action=action,
                    trigger_observation_id=observation_id,
                    resolver_output=resolver.model_dump(),
                    change_reason=resolver.reason,
                )
                created_memory_id = new_memory.memory_id
                if action == "replace" and current_target_memory is not None:
                    await repository.update_memory(
                        memory=current_target_memory,
                        status="superseded",
                        metadata={"superseded_by": new_memory.memory_id},
                    )
                logger.info(
                    "ingest memory write created",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "entity_key": entity_key,
                        "candidate_id": candidate.candidate_id,
                        "action": action,
                        "memory_id": new_memory.memory_id,
                        "target_memory_id": target_memory_id,
                    },
                )
                return action, created_memory_id, target_memory_id

            if action == "refresh" and current_target_memory is not None:
                merged_summary = _merge_refresh_text(
                    existing_text=current_target_memory.summary,
                    refreshed_text=resolver.summary,
                    detail_label="Refresh summary",
                )
                merged_content = _merge_refresh_text(
                    existing_text=current_target_memory.content,
                    refreshed_text=resolver.content,
                    detail_label="Refresh detail",
                )
                await repository.update_memory(
                    memory=current_target_memory,
                    title=resolver.title,
                    summary=merged_summary,
                    content=merged_content,
                    confidence=resolver.confidence,
                    salience=resolver.salience,
                    latest_source_observation_id=observation_id,
                    metadata=memory_metadata,
                )
                await repository.create_memory_version(
                    memory_space=memory_space,
                    memory=current_target_memory,
                    action="refresh",
                    trigger_observation_id=observation_id,
                    resolver_output=resolver.model_dump(),
                    change_reason=resolver.reason,
                )
                logger.info(
                    "ingest memory write refreshed",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "entity_key": entity_key,
                        "candidate_id": candidate.candidate_id,
                        "target_memory_id": target_memory_id,
                    },
                )
                return action, None, target_memory_id

            if action == "stale" and current_target_memory is not None:
                await repository.update_memory(
                    memory=current_target_memory,
                    status="stale",
                    latest_source_observation_id=observation_id,
                    metadata=memory_metadata,
                )
                await repository.create_memory_version(
                    memory_space=memory_space,
                    memory=current_target_memory,
                    action="stale",
                    trigger_observation_id=observation_id,
                    resolver_output=resolver.model_dump(),
                    change_reason=resolver.reason,
                )
                logger.info(
                    "ingest memory write marked stale",
                    extra={
                        "memory_space": memory_space,
                        "request_id": request_id,
                        "entity_key": entity_key,
                        "candidate_id": candidate.candidate_id,
                        "target_memory_id": target_memory_id,
                    },
                )
            return action, None, target_memory_id

    @staticmethod
    def _resolver_waits_for_batch_target(
        *,
        resolver: Any,
        candidate_ids: set[str],
        existing_memory_ids: set[str],
        batch_created_memory_ids: dict[str, str],
    ) -> bool:
        target_memory_id = str(resolver.target_memory_id or "").strip()
        if resolver.action not in {"refresh", "replace", "stale"} or not target_memory_id:
            return False
        if target_memory_id in existing_memory_ids:
            return False
        if target_memory_id in batch_created_memory_ids:
            return False
        return target_memory_id in candidate_ids

    @staticmethod
    def _should_retry_same_batch_resolution(
        *,
        existing_memories: list[Any],
        resolver_outputs: list[Any],
    ) -> bool:
        if existing_memories or len(resolver_outputs) <= 1:
            return False
        return all(
            output.action in {"create", "coexist"} and not str(output.target_memory_id or "").strip()
            for output in resolver_outputs
        )

    @staticmethod
    def _build_same_batch_existing_memories(
        *,
        resolver_outputs: list[Any],
        candidates_by_id: dict[str, Any],
    ) -> list[dict[str, Any]]:
        synthetic_existing: list[dict[str, Any]] = []
        for index, output in enumerate(resolver_outputs):
            candidate = candidates_by_id.get(output.candidate_id)
            synthetic_existing.append(
                {
                    "memory_id": output.candidate_id,
                    "title": output.title,
                    "summary": output.summary,
                    "content": output.content,
                    "status": "active",
                    "confidence": output.confidence,
                    "salience": output.salience,
                    "record_markers": (
                        candidate.record_markers.model_dump() if candidate and candidate.record_markers is not None else None
                    ),
                    "created_at": float(index),
                }
            )
        return synthetic_existing

    async def _finalize(self, state: IngestState) -> dict[str, Any]:
        observation_id = state["observation_id"]
        draft_to_entity = state.get("draft_to_entity") or {}
        affected_entity_keys = list(state.get("affected_entity_keys") or [])
        affected_memory_ids = list(state.get("affected_memory_ids") or [])

        async with MemoryRepository() as repository:
            await repository.mark_observation_resolved(
                memory_space=state["memory_space"],
                observation_id=observation_id,
                status="resolved",
                metadata={"draft_to_entity": draft_to_entity},
            )
        await self._enqueue_followup_tasks(
            memory_space=state["memory_space"],
            entity_keys=affected_entity_keys,
            observation_id=observation_id,
        )
        logger.info(
            "ingest finalized",
            extra={
                "memory_space": state["memory_space"],
                "request_id": state["request_id"],
                "observation_id": observation_id,
                "affected_entity_keys": affected_entity_keys,
                "affected_memory_ids": affected_memory_ids,
            },
        )

        return {
            "result": {
                "status": "accepted",
                "observation_id": observation_id,
                "affected_entity_keys": affected_entity_keys,
                "affected_memory_ids": affected_memory_ids,
                "error_code": None,
            }
        }

    async def _enqueue_followup_tasks(
        self,
        *,
        memory_space: str,
        entity_keys: list[str],
        observation_id: str,
    ) -> None:
        async with MemoryRepository() as repository:
            maintenance_available_at = (
                repository.timestamp_now() + settings.MEMORY_BACKGROUND_MAINTENANCE_DEBOUNCE_SECONDS
            )
            for entity_key in entity_keys:
                await repository.create_task(
                    memory_space=memory_space,
                    task_type="refresh_entity_profile",
                    dedupe_key=f"refresh_entity_profile:{entity_key}",
                    priority=8,
                    payload={
                        "memory_space": memory_space,
                        "entity_key": entity_key,
                        "observation_id": observation_id,
                    },
                    available_at=maintenance_available_at,
                    dedupe_statuses=("pending",),
                )
                await repository.create_task(
                    memory_space=memory_space,
                    task_type="reindex_memory",
                    dedupe_key=f"reindex_entity:{entity_key}",
                    priority=12,
                    payload={
                        "memory_space": memory_space,
                        "entity_key": entity_key,
                        "observation_id": observation_id,
                    },
                    available_at=maintenance_available_at,
                    dedupe_statuses=("pending",),
                )
                await repository.create_task(
                    memory_space=memory_space,
                    task_type="detect_merge_candidates",
                    dedupe_key=f"detect_merge_candidates:{entity_key}",
                    priority=4,
                    payload={
                        "memory_space": memory_space,
                        "entity_key": entity_key,
                        "observation_id": observation_id,
                    },
                    available_at=maintenance_available_at,
                    dedupe_statuses=("pending",),
                )
                await repository.create_task(
                    memory_space=memory_space,
                    task_type="repair_memory_edges",
                    dedupe_key=f"repair_memory_edges:{entity_key}",
                    priority=11,
                    payload={
                        "memory_space": memory_space,
                        "entity_key": entity_key,
                        "observation_id": observation_id,
                    },
                    available_at=maintenance_available_at,
                    dedupe_statuses=("pending",),
                )


ingest_graph = IngestGraph()
