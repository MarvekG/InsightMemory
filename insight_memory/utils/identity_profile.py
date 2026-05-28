from __future__ import annotations

from typing import Any

from insight_memory.utils.text import normalize_text


def identity_profile_refresh_risk(
    *,
    current_profile: dict[str, Any],
    proposed_profile: dict[str, Any],
) -> tuple[str, str]:
    """判断 identity profile proposal 是否可自动应用。

    Args:
        current_profile: 当前实体 profile。
        proposed_profile: profile writer 提出的新 profile 或被合并实体的 profile。

    Returns:
        二元组 `(risk, reason)`，`safe` 表示可自动应用。
    """

    current_who = normalize_text(current_profile.get("who")).casefold()
    proposed_who = normalize_text(proposed_profile.get("who")).casefold()
    if proposed_profile.get("schema_version") != 2:
        return "reject", "schema_version_must_be_2"
    proposed_surfaces = {
        normalize_text(item).casefold()
        for item in proposed_profile.get("surface_forms") or []
        if normalize_text(item)
    }
    if current_who and proposed_who and proposed_who != current_who and current_who not in proposed_surfaces:
        return "needs_identity_review", "who_changed_without_alias"
    return "safe", "safe_additive_update"


def next_profile_metadata(
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
    """生成 identity profile refresh 或 merge 后的实体 metadata。

    Args:
        current_metadata: 当前实体 metadata。
        previous_profile: 刷新或合并前 profile。
        proposed_profile: profile writer 提议的 profile 或被合并实体 profile。
        applied_profile: 实际应用的 profile；拒绝时等于刷新或合并前 profile。
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
