from __future__ import annotations

import json
from pathlib import Path

from memory.evals.scripts.eval_prompt_accuracy import (
    ExpectedProfile,
    PromptEvalCase,
    load_prompt_eval_suite,
    score_prompt_case,
    summarize_results,
    write_report_files,
)


def test_load_prompt_eval_suite_reads_cases(tmp_path: Path) -> None:
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
                        "expected_profiles": [{"who_any": ["x"], "entity_type_any": ["workflow", "project"]}],
                        "forbidden_who": ["y"],
                        "min_profile_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    suite = load_prompt_eval_suite(suite_path)

    assert suite["suite_id"] == "identity_profile_rules_v1"
    assert suite["minimum_pass_rate"] == 0.9
    assert len(suite["cases"]) == 1
    assert suite["cases"][0].expected_profiles[0].who_any == ["x"]
    assert suite["cases"][0].expected_profiles[0].entity_type_any == ["workflow", "project"]


def test_score_prompt_case_passes_write_gate_output() -> None:
    case = PromptEvalCase(
        case_id="missing_item_owner",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_profiles=[ExpectedProfile(who_any=["Lanturn deployment"], entity_type="workflow")],
        forbidden_who=["escrow approval form"],
        min_profile_count=1,
        max_profile_count=1,
    )

    result = score_prompt_case(
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
                    }
                ],
            },
        },
    )

    assert result["passed"] is True
    assert result["actual_gate_status"] == "passed"


def test_score_prompt_case_fails_for_forbidden_identity() -> None:
    case = PromptEvalCase(
        case_id="bad_missing_item_owner",
        category="boundary",
        prompt_key="write_gate",
        payload={"context": "x"},
        expected_gate_status="passed",
        expected_profiles=[ExpectedProfile(who_any=["Lanturn deployment"], entity_type="workflow")],
        forbidden_who=["escrow approval form"],
    )

    result = score_prompt_case(
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
    assert any("forbidden profile" in failure for failure in result["failures"])
    assert any("missing expected profile" in failure for failure in result["failures"])


def test_score_prompt_case_reads_query_planner_profiles() -> None:
    case = PromptEvalCase(
        case_id="market_record_word",
        category="market",
        prompt_key="query_planner",
        payload={"query": "x"},
        expected_gate_status="passed",
        expected_profiles=[ExpectedProfile(who_any=["STP.N"], entity_type="market_object")],
    )

    result = score_prompt_case(
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
    assert result["actual_profiles"][0]["who"] == "STP.N"


def test_score_prompt_case_accepts_entity_type_any() -> None:
    case = PromptEvalCase(
        case_id="record_marker",
        category="boundary",
        prompt_key="query_planner",
        payload={"query": "x"},
        expected_gate_status="passed",
        expected_profiles=[
            ExpectedProfile(
                who_any=["Meridian onboarding"],
                entity_type_any=["workflow", "project", "work_item"],
            )
        ],
    )

    result = score_prompt_case(
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
                    "actual_profiles": [{"who": "x", "entity_type": "workflow"}],
                }
            ],
        },
        output_dir=tmp_path,
    )

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert "Prompt Accuracy Report" in Path(paths["markdown"]).read_text(encoding="utf-8")
