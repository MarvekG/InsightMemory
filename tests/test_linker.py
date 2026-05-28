from __future__ import annotations

import asyncio

from insight_memory.workers.llm_provider import LLMCallResult
from insight_memory.workers.runtime import MemoryWorkers
from insight_memory.workers.schemas import LinkerOutput


def test_linker_does_not_apply_query_side_exact_match_fallback(monkeypatch) -> None:
    workers = MemoryWorkers()

    async def fake_run(*args, **kwargs):
        del args, kwargs
        return LLMCallResult(
            parsed=LinkerOutput(
                decision="cannot_resolve",
                selected_entity_key=None,
                ambiguous_entity_keys=[],
                confidence=0.0,
                reason="llm_cannot_resolve",
            ),
            output_json={},
            model="test-model",
            prompt_version="test",
            latency_ms=1,
            input_tokens=None,
            output_tokens=None,
            cached_tokens=None,
            cache_miss_tokens=None,
            reasoning_tokens=None,
        )
    monkeypatch.setattr(workers, "_run", fake_run)

    linked = asyncio.run(
        workers.run_linker(
            memory_space="workspace:atlas",
            request_id="corr_1",
            mode="query",
            identity_profile_draft={
                "who": "Atlas rollout",
                "surface_forms": ["Atlas rollout", "Atlas"],
                "stable_qualifiers": ["release program", "session history"],
            },
            entity_candidates=[
                {
                    "entity_key": "ent_1",
                    "display_name": "Atlas rollout",
                    "identity_profile": {
                        "who": "Atlas rollout",
                        "surface_forms": ["Atlas rollout"],
                        "stable_qualifiers": ["historical record", "session record"],
                    },
                    "score": 0.01,
                    "active_memory_summaries": [],
                }
            ],
        )
    )

    assert linked.decision == "cannot_resolve"
    assert linked.selected_entity_key is None
    assert linked.reason == "llm_cannot_resolve"


def test_linker_rejects_selected_entity_key_outside_candidates(monkeypatch) -> None:
    workers = MemoryWorkers()

    async def fake_run(*args, **kwargs):
        del args, kwargs
        return LLMCallResult(
            parsed=LinkerOutput(
                decision="link_existing",
                selected_entity_key="ent_missing",
                ambiguous_entity_keys=[],
                confidence=0.99,
                reason="llm_selected_unknown_candidate",
            ),
            output_json={},
            model="test-model",
            prompt_version="test",
            latency_ms=1,
            input_tokens=None,
            output_tokens=None,
            cached_tokens=None,
            cache_miss_tokens=None,
            reasoning_tokens=None,
        )
    monkeypatch.setattr(workers, "_run", fake_run)

    linked = asyncio.run(
        workers.run_linker(
            memory_space="workspace:atlas",
            request_id="corr_2",
            mode="query",
            identity_profile_draft={
                "who": "Atlas rollout",
                "surface_forms": ["Atlas rollout"],
                "stable_qualifiers": ["release program"],
            },
            entity_candidates=[
                {
                    "entity_key": "ent_1",
                    "display_name": "Atlas rollout",
                    "identity_profile": {
                        "who": "Atlas rollout",
                        "surface_forms": ["Atlas rollout"],
                        "stable_qualifiers": ["release program"],
                    },
                    "score": 0.6,
                    "active_memory_summaries": [],
                }
            ],
        )
    )

    assert linked.decision == "cannot_resolve"
    assert linked.reason == "selected_entity_not_in_candidates"


def test_linker_corrects_single_near_match_candidate_key(monkeypatch) -> None:
    workers = MemoryWorkers()

    async def fake_run(*args, **kwargs):
        del args, kwargs
        return LLMCallResult(
            parsed=LinkerOutput(
                decision="link_existing",
                selected_entity_key="ent_bc2424f3188b4b9eb9a85bbc535fc02a",
                ambiguous_entity_keys=[],
                confidence=0.95,
                reason="llm_selected_doc_with_one_char_typo",
            ),
            output_json={},
            model="test-model",
            prompt_version="test",
            latency_ms=1,
            input_tokens=None,
            output_tokens=None,
            cached_tokens=None,
            cache_miss_tokens=None,
            reasoning_tokens=None,
        )
    monkeypatch.setattr(workers, "_run", fake_run)

    linked = asyncio.run(
        workers.run_linker(
            memory_space="workspace:atlas",
            request_id="corr_3",
            mode="query",
            identity_profile_draft={
                "who": "Quarterly planning doc",
                "surface_forms": ["Quarterly planning doc"],
                "stable_qualifiers": [],
            },
            entity_candidates=[
                {
                    "entity_key": "ent_bc2424f3188f4b9eb9a85bbc535fc02a",
                    "display_name": "Quarterly planning doc",
                    "identity_profile": {
                        "who": "Quarterly planning doc",
                        "surface_forms": ["Quarterly planning doc"],
                        "stable_qualifiers": ["document"],
                    },
                    "score": 0.9,
                    "active_memory_summaries": [],
                },
                {
                    "entity_key": "ent_ca78535e878340c48b7b7c3f048771fe",
                    "display_name": "Fallback checklist",
                    "identity_profile": {
                        "who": "Fallback checklist",
                        "surface_forms": ["Fallback checklist"],
                        "stable_qualifiers": ["artifact"],
                    },
                    "score": 0.1,
                    "active_memory_summaries": [],
                },
            ],
        )
    )

    assert linked.decision == "link_existing"
    assert linked.selected_entity_key == "ent_bc2424f3188f4b9eb9a85bbc535fc02a"
    assert linked.reason == "llm_selected_doc_with_one_char_typo"
