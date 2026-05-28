from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from insight_memory.index.retrieval_index import retrieval_index
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.text import dedupe_preserve_order, normalize_text
from insight_memory.utils.request_context import get_or_create_request_id
from insight_memory.workers.runtime import MemoryWorkers


class RefreshEntityProfileState(TypedDict, total=False):
    memory_space: str
    entity_key: str
    entity: Any
    memories: list[Any]
    workers: MemoryWorkers
    profile: dict[str, Any]
    result: dict[str, Any]


def _profile_values(profile: dict[str, Any], field: str) -> list[str]:
    """读取并规范化 profile 中的列表字段。

    Args:
        profile: identity profile payload。
        field: 需要读取的字段名。

    Returns:
        去重后的非空字符串列表。
    """

    return dedupe_preserve_order([str(item) for item in profile.get(field) or []], limit=8)


def _merge_additive_profile(*, current_profile: dict[str, Any], proposed_profile: dict[str, Any]) -> dict[str, Any]:
    """合并低风险的 profile 追加更新。

    Args:
        current_profile: 当前实体 profile。
        proposed_profile: profile writer 提出的新 profile。

    Returns:
        只保留同一主体下低风险新增字段后的 profile。
    """

    current_who = normalize_text(current_profile.get("who"))
    proposed_who = normalize_text(proposed_profile.get("who"))
    who = current_who or proposed_who
    surface_forms = dedupe_preserve_order(
        [*_profile_values(current_profile, "surface_forms"), proposed_who, *_profile_values(proposed_profile, "surface_forms")],
        limit=8,
    )
    stable_qualifiers = dedupe_preserve_order(
        [*_profile_values(current_profile, "stable_qualifiers"), *_profile_values(proposed_profile, "stable_qualifiers")],
        limit=8,
    )
    evidence = dedupe_preserve_order(_profile_values(proposed_profile, "evidence"), limit=4)
    return {
        "schema_version": 2,
        "who": who,
        "entity_type": proposed_profile.get("entity_type")
        if current_profile.get("entity_type") == "unknown"
        else current_profile.get("entity_type", proposed_profile.get("entity_type", "unknown")),
        "surface_forms": surface_forms,
        "stable_qualifiers": stable_qualifiers,
        "evidence": evidence,
    }


def _profile_refresh_risk(*, current_profile: dict[str, Any], proposed_profile: dict[str, Any]) -> tuple[str, str]:
    """判断 profile proposal 是否可自动应用。

    Args:
        current_profile: 当前实体 profile。
        proposed_profile: profile writer 提出的新 profile。

    Returns:
        二元组 `(risk, reason)`，`safe` 表示可自动应用。
    """

    current_who = normalize_text(current_profile.get("who")).casefold()
    proposed_who = normalize_text(proposed_profile.get("who")).casefold()
    current_type = normalize_text(current_profile.get("entity_type")).casefold()
    proposed_type = normalize_text(proposed_profile.get("entity_type")).casefold()
    if proposed_profile.get("schema_version") != 2:
        return "reject", "schema_version_must_be_2"
    if current_type and proposed_type and current_type != "unknown" and proposed_type != "unknown" and current_type != proposed_type:
        return "needs_identity_review", "entity_type_conflict"
    proposed_surfaces = {
        normalize_text(item).casefold()
        for item in proposed_profile.get("surface_forms") or []
        if normalize_text(item)
    }
    if current_who and proposed_who and proposed_who != current_who and proposed_who not in proposed_surfaces:
        return "needs_identity_review", "who_changed_without_alias"
    return "safe", "safe_additive_update"


def _next_profile_metadata(
    *,
    current_metadata: dict[str, Any],
    previous_profile: dict[str, Any],
    proposed_profile: dict[str, Any],
    applied_profile: dict[str, Any],
    risk: str,
    reason: str,
    request_id: str,
    applied: bool,
) -> dict[str, Any]:
    """生成 profile refresh 后的实体 metadata。

    Args:
        current_metadata: 当前实体 metadata。
        previous_profile: 刷新前 profile。
        proposed_profile: profile writer 提议的 profile。
        applied_profile: 实际应用的 profile；拒绝时等于刷新前 profile。
        risk: refresh 风险分类。
        reason: refresh 风险原因。
        request_id: 当前请求 id。
        applied: 是否应用了 proposal。

    Returns:
        更新后的 metadata。
    """

    metadata = dict(current_metadata or {})
    state = dict(metadata.get("profile_state") or {})
    current_revision = int(state.get("profile_revision") or 0)
    next_revision = current_revision + 1 if applied else current_revision
    status = "applied" if applied else risk
    state.update(
        {
            "profile_revision": next_revision,
            "last_refresh_status": status,
            "last_refresh_reason": reason,
        }
    )
    history = list(metadata.get("profile_history") or [])
    history.append(
        {
            "revision": next_revision,
            "previous_profile": dict(previous_profile),
            "proposed_profile": dict(proposed_profile),
            "applied_profile": dict(applied_profile),
            "risk": "safe" if applied else risk,
            "reason": reason,
            "request_id": request_id,
        }
    )
    metadata["profile_state"] = state
    metadata["profile_history"] = history[-10:]
    return metadata


class RefreshEntityProfileGraph:
    def __init__(self) -> None:
        self._graph = self._build_graph()

    async def run(self, *, memory_space: str, entity_key: str) -> dict[str, Any]:
        result = await self._graph.ainvoke(
            {
                "memory_space": memory_space,
                "entity_key": entity_key,
                "workers": MemoryWorkers(),
            }
        )
        return dict(result.get("result") or {})

    def _build_graph(self):
        graph = StateGraph(RefreshEntityProfileState)
        graph.add_node("load_entity_context", self._load_entity_context)
        graph.add_node("skip_missing_entity", self._skip_missing_entity)
        graph.add_node("write_profile", self._write_profile)
        graph.set_entry_point("load_entity_context")
        graph.add_conditional_edges(
            "load_entity_context",
            self._after_load_entity_context,
            {
                "skip_missing_entity": "skip_missing_entity",
                "write_profile": "write_profile",
            },
        )
        graph.add_edge("skip_missing_entity", END)
        graph.add_edge("write_profile", END)
        return graph.compile()

    async def _load_entity_context(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        async with MemoryRepository() as repository:
            entity = await repository.get_entity(memory_space=state["memory_space"], entity_key=state["entity_key"])
            if entity is None:
                return {"entity": None}
            memories = await repository.list_memories(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
                statuses=("active",),
                limit=10,
            )
        return {"entity": entity, "memories": memories}

    @staticmethod
    def _after_load_entity_context(state: RefreshEntityProfileState) -> str:
        return "write_profile" if state.get("entity") is not None else "skip_missing_entity"

    async def _skip_missing_entity(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        return {"result": {"refreshed": False}}

    async def _write_profile(self, state: RefreshEntityProfileState) -> dict[str, Any]:
        entity = state["entity"]
        memories = state.get("memories") or []
        workers = state["workers"]
        request_id = get_or_create_request_id()
        profile_writer = await workers.run_profile_writer(
            memory_space=state["memory_space"],
            request_id=request_id,
            payload={
                "current_identity_profile": entity.identity_profile,
                "current_display_name": entity.display_name,
                "recent_memory_summaries": [memory.summary for memory in memories[:4]],
            },
        )
        proposed_profile = profile_writer.model_dump()
        current_profile = dict(entity.identity_profile or {})
        risk, reason = _profile_refresh_risk(
            current_profile=current_profile,
            proposed_profile=proposed_profile,
        )
        applied = risk == "safe"
        profile = (
            _merge_additive_profile(current_profile=current_profile, proposed_profile=proposed_profile)
            if applied
            else current_profile
        )
        display_name = str(profile.get("who") or entity.display_name)
        async with MemoryRepository() as repository:
            current_entity = await repository.get_entity(
                memory_space=state["memory_space"],
                entity_key=state["entity_key"],
            )
            if current_entity is None:
                return {"result": {"refreshed": False}}
            metadata = _next_profile_metadata(
                current_metadata=dict(current_entity.metadata_json or {}),
                previous_profile=current_profile,
                proposed_profile=proposed_profile,
                applied_profile=profile,
                risk=risk,
                reason=reason,
                request_id=request_id,
                applied=applied,
            )
            await repository.update_entity_profile(
                entity=current_entity,
                display_name=str(display_name),
                identity_profile=profile,
                metadata=metadata,
            )
            if applied:
                await retrieval_index.refresh_entities(entities=[current_entity])
        return {
            "profile": profile,
            "result": {
                "refreshed": applied,
                "entity_key": state["entity_key"],
                "refresh_status": "applied" if applied else risk,
            },
        }


refresh_entity_profile_graph = RefreshEntityProfileGraph()
