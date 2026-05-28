from __future__ import annotations

import json
from pathlib import Path

from memory.evals.scripts.eval_identity_profile_extraction import (
    ExpectedIdentityProfile,
    IdentityExtractionCase,
    load_identity_extraction_suite,
    score_identity_extraction_case,
    summarize_results,
    write_report_files,
)


def test_load_identity_extraction_suite_reads_cases(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "suite_id": "identity_profile_rules_v1",
                "description": "desc",
                "minimum_pass_rate": 0.9,
                "cases": [
                    {
                        "case_id": "c1",
                        "category": "boundary",
                        "prompt_key": "write_gate",
                        "payload": {"context": "x"},
                        "expected_gate_status": "passed",
                        "expected_identities": [
                            {
                                "who_any": ["x"],
                                "entity_type_any": ["workflow", "project"],
                                "surface_forms_all": ["x"],
                                "stable_qualifiers_any": ["project"],
                                "evidence_contains_all": ["x"],
                            }
                        ],
                        "forbidden_identity_who": ["y"],
                        "min_profile_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    suite = load_identity_extraction_suite(suite_path)

    assert suite["suite_id"] == "identity_profile_rules_v1"
    assert suite["minimum_pass_rate"] == 0.9
    assert len(suite["cases"]) == 1
    assert suite["cases"][0].expected_identities[0].who_any == ["x"]
    assert suite["cases"][0].expected_identities[0].entity_type_any == ["workflow", "project"]
    assert suite["cases"][0].expected_identities[0].surface_forms_all == ["x"]
    assert suite["cases"][0].expected_identities[0].stable_qualifiers_any == ["project"]
    assert suite["cases"][0].expected_identities[0].evidence_contains_all == ["x"]


def test_score_identity_extraction_case_passes_write_gate_output() -> None:
    case = IdentityExtractionCase(
        case_id="missing_item_owner",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Lanturn deployment"],
                entity_type="workflow",
                surface_forms_all=["Lanturn deployment"],
                evidence_contains_all=["cannot enter final validation"],
            )
        ],
        forbidden_identity_who=["escrow approval form"],
        min_profile_count=1,
        max_profile_count=1,
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {
                        "who": "Lanturn deployment",
                        "entity_type": "workflow",
                        "surface_forms": ["Lanturn deployment"],
                        "evidence": [
                            "Lanturn deployment cannot enter final validation."
                        ],
                    }
                ],
            },
        },
    )

    assert result["passed"] is True
    assert result["actual_gate_status"] == "passed"
    assert result["actual_identities"][0]["evidence"] == [
        "Lanturn deployment cannot enter final validation."
    ]


def test_score_identity_extraction_case_fails_for_forbidden_identity() -> None:
    case = IdentityExtractionCase(
        case_id="bad_missing_item_owner",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[ExpectedIdentityProfile(who_any=["Lanturn deployment"], entity_type="workflow")],
        forbidden_identity_who=["escrow approval form"],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {"who": "escrow approval form", "entity_type": "document"},
                ],
            },
        },
    )

    assert result["passed"] is False
    assert any("forbidden identity" in failure for failure in result["failures"])
    assert any("missing expected identity" in failure for failure in result["failures"])


def test_score_identity_extraction_case_reads_query_planner_profiles() -> None:
    case = IdentityExtractionCase(
        case_id="market_record_word",
        category="market",
        prompt_key="query_planner",
        payload={"query": "x"},
        expected_gate_status="passed",
        expected_identities=[ExpectedIdentityProfile(who_any=["STP.N"], entity_type="market_object")],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "query_gate_status": "passed",
                "query_identity_profile_drafts": [
                    {"who": "STP.N", "entity_type": "market_object"},
                ],
            },
        },
    )

    assert result["passed"] is True
    assert result["actual_identities"][0]["who"] == "STP.N"


def test_score_identity_extraction_case_accepts_entity_type_any() -> None:
    case = IdentityExtractionCase(
        case_id="record_marker",
        category="boundary",
        prompt_key="query_planner",
        payload={"query": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Meridian onboarding"],
                entity_type_any=["workflow", "project", "work_item"],
            )
        ],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "query_gate_status": "passed",
                "query_identity_profile_drafts": [
                    {"who": "Meridian onboarding", "entity_type": "project"},
                ],
            },
        },
    )

    assert result["passed"] is True


def test_score_identity_extraction_case_checks_surface_qualifiers_and_evidence() -> None:
    case = IdentityExtractionCase(
        case_id="full_profile_fields",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Cedar QA policy"],
                entity_type="document",
                surface_forms_all=["Cedar QA policy"],
                stable_qualifiers_any=["QA policy", "policy"],
                evidence_contains_all=["release ticket"],
            )
        ],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {
                        "who": "Cedar QA policy",
                        "entity_type": "document",
                        "surface_forms": ["Cedar QA policy"],
                        "stable_qualifiers": ["policy"],
                        "evidence": ["requires every release ticket to attach a parity matrix"],
                    },
                ],
            },
        },
    )

    assert result["passed"] is True


def test_score_identity_extraction_case_fails_missing_profile_fields() -> None:
    case = IdentityExtractionCase(
        case_id="missing_profile_fields",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Cedar QA policy"],
                entity_type="document",
                surface_forms_all=["Cedar QA policy"],
                stable_qualifiers_all=["policy"],
                evidence_contains_all=["release ticket"],
            )
        ],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {
                        "who": "Cedar QA policy",
                        "entity_type": "document",
                        "surface_forms": ["Cedar policy"],
                        "stable_qualifiers": [],
                        "evidence": ["requires parity matrix"],
                    },
                ],
            },
        },
    )

    assert result["passed"] is False
    assert any("surface_forms missing" in failure for failure in result["failures"])
    assert any("stable_qualifiers missing" in failure for failure in result["failures"])
    assert any("evidence missing" in failure for failure in result["failures"])


def test_summarize_results_counts_failures() -> None:
    summary = summarize_results(
        [
            {"case_id": "a", "passed": True},
            {"case_id": "b", "passed": False},
        ]
    )

    assert summary["total_cases"] == 2
    assert summary["pass_count"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["failing_cases"] == ["b"]


def test_write_report_files_outputs_json_and_markdown(tmp_path: Path) -> None:
    paths = write_report_files(
        report={
            "suite_id": "identity_profile_rules_v1",
            "run_id": "run1",
            "base_url": "http://127.0.0.1:8010",
            "minimum_pass_rate": 1.0,
            "summary": {"total_cases": 1, "pass_rate": 1.0},
            "cases": [
                {
                    "case_id": "c1",
                    "prompt_key": "write_gate",
                    "passed": True,
                    "failures": [],
                    "actual_identities": [{"who": "x", "entity_type": "workflow"}],
                }
            ],
        },
        output_dir=tmp_path,
    )

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert "Identity Extraction Report" in Path(paths["markdown"]).read_text(encoding="utf-8")
