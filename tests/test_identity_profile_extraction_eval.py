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
from insight_memory.workers.prompts import get_worker_instructions


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
                                "surface_forms_all": ["x"],
                                "stable_qualifiers_any": ["project"],
                                "definition_required": True,
                            }
                        ],
                        "forbidden_identity_who": ["y"],
                        "profile_count": 1,
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
    assert suite["cases"][0].expected_identities[0].surface_forms_all == ["x"]
    assert suite["cases"][0].expected_identities[0].stable_qualifiers_any == ["project"]
    assert suite["cases"][0].expected_identities[0].definition_required is True
    assert suite["cases"][0].profile_count == 1


def test_zh_identity_profile_suite_uses_identity_definition() -> None:
    suite = load_identity_extraction_suite(
        Path("memory/evals/prompt_cases/identity_profile_rules_zh_v1.json")
    )

    memory_fact_fragments = [
        "当前不能",
        "当前无法",
        "当前负责人",
        "要求所有",
        "要求入职",
        "主风险",
        "阈值",
        "暂缓发布",
        "偏好每周",
    ]
    invalid_definitions = []
    missing_definition_checks = []
    for case in suite["cases"]:
        for expected in case.expected_identities:
            if not expected.definition_required:
                missing_definition_checks.append(case.case_id)
            definition_fragments = expected.definition_contains_any + expected.definition_contains_all
            for fragment in definition_fragments:
                if any(memory_fact in fragment for memory_fact in memory_fact_fragments):
                    invalid_definitions.append((case.case_id, fragment))

    assert invalid_definitions == []
    assert missing_definition_checks == []


def test_identity_prompt_examples_do_not_copy_eval_subjects() -> None:
    suites = [
        ("zh", Path("memory/evals/prompt_cases/identity_profile_rules_zh_v1.json")),
        ("en", Path("memory/evals/prompt_cases/identity_profile_rules_v1.json")),
    ]
    copied_subjects = []
    for language, suite_path in suites:
        instructions = get_worker_instructions("write_gate", system_language=language)
        suite = load_identity_extraction_suite(suite_path)
        expected_subjects = {
            subject
            for case in suite["cases"]
            for expected in case.expected_identities
            for subject in expected.who_any
        }
        copied_subjects.extend(
            f"{language}:{subject}" for subject in sorted(expected_subjects) if subject in instructions
        )

    assert copied_subjects == []


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
                surface_forms_all=["Lanturn deployment"],
                definition_required=True,
            )
        ],
        forbidden_identity_who=["escrow approval form"],
        profile_count=1,
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
                        "surface_forms": ["Lanturn deployment"],
                        "definition": "Named deployment.",
                    }
                ],
            },
        },
    )

    assert result["passed"] is True
    assert result["actual_gate_status"] == "passed"
    assert result["actual_identities"][0]["definition"] == "Named deployment."


def test_score_identity_extraction_case_fails_for_forbidden_identity() -> None:
    case = IdentityExtractionCase(
        case_id="bad_missing_item_owner",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[ExpectedIdentityProfile(who_any=["Lanturn deployment"])],
        forbidden_identity_who=["escrow approval form"],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {"who": "escrow approval form"},
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
        expected_identities=[ExpectedIdentityProfile(who_any=["STP.N"])],
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "query_gate_status": "passed",
                "query_identity_profile_drafts": [
                    {"who": "STP.N"},
                ],
            },
        },
    )

    assert result["passed"] is True
    assert result["actual_identities"][0]["who"] == "STP.N"


def test_score_identity_extraction_case_does_not_require_entity_type() -> None:
    case = IdentityExtractionCase(
        case_id="record_marker",
        category="boundary",
        prompt_key="query_planner",
        payload={"query": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Meridian onboarding"],
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
                    {"who": "Meridian onboarding"},
                ],
            },
        },
    )

    assert result["passed"] is True


def test_score_identity_extraction_case_checks_surface_qualifiers_and_definition() -> None:
    case = IdentityExtractionCase(
        case_id="full_profile_fields",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Cedar QA policy"],
                surface_forms_all=["Cedar QA policy"],
                stable_qualifiers_any=["QA policy", "policy"],
                definition_contains_all=["policy"],
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
                        "surface_forms": ["Cedar QA policy"],
                        "stable_qualifiers": ["policy"],
                        "definition": "Named QA policy.",
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
                surface_forms_all=["Cedar QA policy"],
                stable_qualifiers_all=["policy"],
                definition_required=True,
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
                        "surface_forms": ["Cedar policy"],
                        "stable_qualifiers": [],
                        "definition": "",
                    },
                ],
            },
        },
    )

    assert result["passed"] is False
    assert any("surface_forms missing" in failure for failure in result["failures"])
    assert any("stable_qualifiers missing" in failure for failure in result["failures"])
    assert any("definition is required" in failure for failure in result["failures"])


def test_score_identity_extraction_case_fails_extra_surface_forms() -> None:
    case = IdentityExtractionCase(
        case_id="extra_surface_forms",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Cedar QA policy"],
                surface_forms_all=["Cedar QA policy"],
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
                        "surface_forms": ["Cedar QA policy", "Cedar policy"],
                    },
                ],
            },
        },
    )

    assert result["passed"] is False
    assert any("surface_forms has unexpected values" in failure for failure in result["failures"])


def test_score_identity_extraction_case_fails_non_exact_profile_count() -> None:
    case = IdentityExtractionCase(
        case_id="extra_profile",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_identities=[
            ExpectedIdentityProfile(
                who_any=["Cedar QA policy"],
            )
        ],
        profile_count=1,
    )

    result = score_identity_extraction_case(
        case,
        {
            "status": "ok",
            "output": {
                "identity_gate_status": "passed",
                "identity_profile_drafts": [
                    {"who": "Cedar QA policy"},
                    {"who": "release ticket"},
                ],
            },
        },
    )

    assert result["passed"] is False
    assert any("profile count is 2, expected exactly 1" in failure for failure in result["failures"])


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
                    "actual_identities": [{"who": "x", "definition": "Named subject."}],
                }
            ],
        },
        output_dir=tmp_path,
    )

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert "Identity Extraction Report" in Path(paths["markdown"]).read_text(encoding="utf-8")
