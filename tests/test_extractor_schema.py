from __future__ import annotations

from insight_memory.workers.schemas import ExtractorOutput


def test_extractor_allows_long_temporary_refs() -> None:
    long_draft_id = "draft_commodity_risk_handbook_missing_hedge_validation_workflow"
    long_candidate_id = "candidate_commodity_risk_handbook_missing_hedge_validation_workflow"

    output = ExtractorOutput.model_validate(
        {
            "identity_gate_status": "passed",
            "identity_profile_drafts": [
                {
                    "draft_id": long_draft_id,
                    "who": "Commodity risk handbook",
                    "surface_forms": ["Commodity risk handbook"],
                    "distinguishing_context": ["handbook"],
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
