from __future__ import annotations

import pytest
from pydantic import ValidationError

from insight_memory.workers.schemas import ExtractorOutput, IdentityProfileDraft, QueryFocus


def test_identity_profile_draft_uses_v2_fields_under_original_name() -> None:
    draft = IdentityProfileDraft.model_validate(
        {
            "schema_version": 2,
            "draft_id": "draft_commodity_risk_handbook",
            "who": "Commodity risk handbook",
            "entity_type": "document",
            "surface_forms": ["Commodity risk handbook"],
            "stable_qualifiers": ["risk handbook"],
            "evidence": ["The source calls it a handbook."],
        }
    )

    assert draft.schema_version == 2
    assert draft.entity_type == "document"
    assert draft.stable_qualifiers == ["risk handbook"]
    assert draft.evidence == ["The source calls it a handbook."]


def test_identity_profile_draft_rejects_legacy_distinguishing_context() -> None:
    with pytest.raises(ValidationError):
        IdentityProfileDraft.model_validate(
            {
                "schema_version": 2,
                "draft_id": "draft_commodity_risk_handbook",
                "who": "Commodity risk handbook",
                "entity_type": "document",
                "surface_forms": ["Commodity risk handbook"],
                "distinguishing_context": ["handbook"],
            }
        )


def test_extractor_allows_long_temporary_refs() -> None:
    long_draft_id = "draft_commodity_risk_handbook_missing_hedge_validation_workflow"
    long_candidate_id = "candidate_commodity_risk_handbook_missing_hedge_validation_workflow"

    output = ExtractorOutput.model_validate(
        {
            "identity_gate_status": "passed",
            "identity_profile_drafts": [
                {
                    "schema_version": 2,
                    "draft_id": long_draft_id,
                    "who": "Commodity risk handbook",
                    "entity_type": "document",
                    "surface_forms": ["Commodity risk handbook"],
                    "stable_qualifiers": ["handbook"],
                    "evidence": ["The source names Commodity risk handbook."],
                }
            ],
            "candidates": [
                {
                    "candidate_id": long_candidate_id,
                    "owner_draft_id": long_draft_id,
                    "title": "Commodity risk handbook 缺 hedge validation workflow",
                    "summary": "Commodity risk handbook 目前还缺 hedge validation workflow。",
                    "content": "Commodity risk handbook 目前还缺 hedge validation workflow。",
                }
            ],
        }
    )

    assert output.identity_profile_drafts[0].draft_id == long_draft_id
    assert output.candidates[0].candidate_id == long_candidate_id
    assert output.candidates[0].owner_draft_id == long_draft_id


def test_query_focus_normalizes_invalid_graph_expansion_intent_to_uncertain() -> None:
    output = QueryFocus.model_validate(
        {
            "topic": "Orion service owner",
            "time_intent": "current",
            "graph_expansion_intent": "not_a_valid_intent",
            "graph_expansion_reason": "The model emitted an unknown value.",
        }
    )

    assert output.graph_expansion_intent == "uncertain"
    assert output.graph_expansion_reason == "The model emitted an unknown value."
