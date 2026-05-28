from __future__ import annotations

from datetime import datetime
from datetime import timezone
from types import SimpleNamespace

import pytest

from insight_memory.graph.repair_memory_edges_graph import _memory_payload
from insight_memory.graph.recall_graph import recall_graph


def test_edge_judge_memory_payload_requires_identity_profile() -> None:
    memory = _memory(
        memory_id="mem_map",
        entity_key="ent_map",
        title="Northridge map",
        summary="Northridge map 当前版本缺少 contour interval 标注",
    )
    identity_profile = {
        "who": "Northridge map",
        "surface_forms": ["Northridge map"],
        "stable_qualifiers": ["map"],
    }

    payload = _memory_payload(memory, identity_profile=identity_profile)

    assert payload["identity_profile"] == identity_profile
    assert payload["entity_key"] == "ent_map"


def test_edge_judge_memory_payload_rejects_missing_identity_profile() -> None:
    with pytest.raises(ValueError, match="identity_profile is required"):
        _memory_payload(_memory(memory_id="mem_without_identity"), identity_profile={})


def test_memory_evidence_payloads_pass_full_candidate_memory_and_edges() -> None:
    long_content = "Orbit checklist 明确要求切换前补齐审批链说明和回滚说明。" * 80
    payloads = recall_graph._memory_evidence_payloads(
        memories=[
            _memory(
                memory_id="mem_checklist",
                title="Orbit checklist",
                summary="Orbit checklist 要求补齐审批链说明和回滚说明",
                content=long_content,
            ),
            _memory(
                memory_id="mem_rollout",
                title="Orbit rollout",
                summary="Orbit rollout 当前主阻塞是审批链说明缺失",
                content="Orbit rollout 当前主阻塞是审批链说明缺失。",
            ),
        ],
        seed_memories=[_memory(memory_id="mem_checklist")],
        used_edges=[
            {
                "edge_type": "supports",
                "from_id": "mem_checklist",
                "to_id": "mem_rollout",
                "reason": "checklist explains rollout blocker",
                "weight": 0.8,
            }
        ],
    )

    checklist_payload = payloads[0]
    rollout_payload = payloads[1]
    assert checklist_payload["content"] == long_content
    assert checklist_payload["evidence_role"] == "seed"
    assert rollout_payload["evidence_role"] == "supporting"
    assert rollout_payload["relation_types"] == ["supports"]


def test_memory_evidence_payloads_marks_conflicting_and_historical_roles() -> None:
    payloads = recall_graph._memory_evidence_payloads(
        memories=[
            _memory(
                memory_id="mem_round_1",
                title="Mica transit review round 1",
                summary="Round 1 支持按原窗口转运。",
            ),
            _memory(
                memory_id="mem_round_2",
                title="Mica transit review round 2",
                summary="Round 2 反对直接转运。",
            ),
            _memory(
                memory_id="mem_current",
                title="Mica transit review current",
                summary="当前结论是先补 ballast variance note。",
            ),
        ],
        seed_memories=[_memory(memory_id="mem_current")],
        used_edges=[
            {
                "edge_type": "contradicts",
                "from_id": "mem_round_1",
                "to_id": "mem_round_2",
                "reason": "two bounded rounds disagree",
                "weight": 1.0,
            },
            {
                "edge_type": "updates",
                "from_id": "mem_round_2",
                "to_id": "mem_current",
                "reason": "current decision settled later",
                "weight": 0.9,
            },
        ],
    )

    by_id = {item["memory_id"]: item for item in payloads}
    assert by_id["mem_round_1"]["evidence_role"] == "conflicting"
    assert by_id["mem_round_2"]["evidence_role"] == "conflicting"
    assert by_id["mem_current"]["evidence_role"] == "seed"
    assert by_id["mem_current"]["relation_types"] == ["updates"]


def test_id_ref_maps_shorten_llm_payloads_and_edges() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["mem_checklist", "mem_rollout"],
        observation_ids=["obs_checklist"],
    )
    memory_payloads = [
        {
            "memory_id": "mem_checklist",
            "relation_edges": [
                {
                    "edge_type": "supports",
                    "from_id": "mem_checklist",
                    "to_id": "mem_rollout",
                }
            ],
        }
    ]
    observation_payloads = [{"observation_id": "obs_checklist", "summary": "checklist summary"}]
    used_edges = [
        {
            "edge_type": "derived_from",
            "from_id": "mem_checklist",
            "to_id": "obs_checklist",
        }
    ]

    shortened_memories = recall_graph._shorten_llm_refs(memory_payloads, id_ref_maps=id_ref_maps)
    shortened_observations = recall_graph._shorten_llm_refs(observation_payloads, id_ref_maps=id_ref_maps)
    shortened_edges = recall_graph._shorten_llm_refs(used_edges, id_ref_maps=id_ref_maps)

    assert shortened_memories[0]["memory_id"] == "m1"
    assert shortened_memories[0]["relation_edges"][0]["from_id"] == "m1"
    assert shortened_memories[0]["relation_edges"][0]["to_id"] == "m2"
    assert shortened_observations[0]["observation_id"] == "o1"
    assert shortened_edges[0]["from_id"] == "m1"
    assert shortened_edges[0]["to_id"] == "o1"


def test_id_ref_maps_use_field_kind_when_ids_overlap() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["shared_id"],
        observation_ids=["shared_id"],
    )
    payload = [
        {"memory_id": "shared_id"},
        {"observation_id": "shared_id"},
        {"edge_type": "derived_from", "from_id": "shared_id", "to_id": "shared_id"},
    ]

    shortened = recall_graph._shorten_llm_refs(payload, id_ref_maps=id_ref_maps)

    assert shortened[0]["memory_id"] == "m1"
    assert shortened[1]["observation_id"] == "o1"
    assert shortened[2]["from_id"] == "m1"
    assert shortened[2]["to_id"] == "o1"


def test_normalize_composer_citations_accepts_memory_and_observation_refs() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["mem_checklist"],
        observation_ids=["obs_checklist"],
    )
    citations = recall_graph._normalize_composer_citations(
        composer_citations=[
            SimpleNamespace(
                memory_id="m1",
                observation_id="o1",
                summary="",
                excerpt="",
            )
        ],
        expanded_memories=[
            _memory(
                memory_id="mem_checklist",
                title="Orbit checklist",
                summary="Orbit checklist 要求补齐审批链说明和回滚说明",
                content="Orbit checklist 明确要求切换前补齐审批链说明和回滚说明。",
            )
        ],
        observations=[
            _observation(
                observation_id="obs_checklist",
                summary="Orbit checklist 明确要求切换前补齐审批链说明和回滚说明。",
            )
        ],
        used_edges=[
            {
                "edge_type": "derived_from",
                "from_id": "mem_checklist",
                "to_id": "obs_checklist",
            }
        ],
        id_ref_maps=id_ref_maps,
    )

    assert citations == [
        {
            "memory_id": "mem_checklist",
            "observation_id": "obs_checklist",
            "summary": "Orbit checklist 明确要求切换前补齐审批链说明和回滚说明。",
            "excerpt": "Orbit checklist 明确要求切换前补齐审批链说明和回滚说明。",
            "source_memory_ids": ["mem_checklist"],
        }
    ]


def test_normalize_composer_citations_drops_unknown_refs() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["mem_known"],
        observation_ids=["obs_known"],
    )
    citations = recall_graph._normalize_composer_citations(
        composer_citations=[
            SimpleNamespace(
                memory_id="m999",
                observation_id="o999",
                summary="unknown",
                excerpt="unknown",
            )
        ],
        expanded_memories=[_memory(memory_id="mem_known")],
        observations=[_observation(observation_id="obs_known", summary="known")],
        used_edges=[],
        id_ref_maps=id_ref_maps,
    )

    assert citations == []


def test_restore_edge_judge_relations_maps_short_refs_to_long_ids() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["mem_frontier", "mem_candidate"],
        observation_ids=[],
    )

    relations = recall_graph._restore_edge_judge_relations(
        relations=[
            SimpleNamespace(
                from_memory_id="m1",
                to_memory_id="m2",
                edge_type="related_to",
                reason="candidate explains frontier context",
                weight=0.7,
            )
        ],
        id_ref_maps=id_ref_maps,
        memory_space="test",
    )

    assert len(relations) == 1
    assert relations[0].from_memory_id == "mem_frontier"
    assert relations[0].to_memory_id == "mem_candidate"


def test_restore_edge_judge_relations_drops_unknown_short_refs() -> None:
    id_ref_maps = recall_graph._build_id_ref_maps(
        memory_ids=["mem_frontier"],
        observation_ids=[],
    )

    relations = recall_graph._restore_edge_judge_relations(
        relations=[
            SimpleNamespace(
                from_memory_id="m1",
                to_memory_id="m999",
                edge_type="related_to",
                reason="unknown candidate ref",
                weight=0.7,
            )
        ],
        id_ref_maps=id_ref_maps,
        memory_space="test",
    )

    assert relations == []


def test_merge_uncertainties_dedupes_without_reordering_first_seen_items() -> None:
    merged = recall_graph._merge_uncertainties(
        ["ambiguous_entity:ent_1", "contradicting_memory:mem_2"],
        ["contradicting_memory:mem_2", "no_relevant_memory_found"],
    )

    assert merged == [
        "ambiguous_entity:ent_1",
        "contradicting_memory:mem_2",
        "no_relevant_memory_found",
    ]


def _memory(
    memory_id: str,
    *,
    entity_key: str = "ent_default",
    title: str = "",
    summary: str = "",
    content: str = "",
    status: str = "active",
    metadata_json: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        memory_id=memory_id,
        entity_key=entity_key,
        title=title,
        summary=summary,
        content=content,
        status=status,
        metadata_json=metadata_json or {},
    )


def _observation(*, observation_id: str, summary: str) -> SimpleNamespace:
    return SimpleNamespace(
        observation_id=observation_id,
        summary=summary,
        content=summary,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
