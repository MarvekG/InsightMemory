from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from memory.evals.scripts.eval_memory_matrix import (
    _build_failed_suite_report,
    _build_matrix_report,
    _load_failed_suite_ids,
    _render_matrix_event_line,
    _select_suites,
)
from insight_memory.evals.accuracy import summarize_matrix_reports


def test_load_failed_suite_ids_reads_summary_block(tmp_path: Path) -> None:
    report_path = tmp_path / "matrix.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "failing_suites": ["generic", "hard"],
                }
            }
        ),
        encoding="utf-8",
    )

    failed_suite_ids = _load_failed_suite_ids(report_path)

    assert failed_suite_ids == {"generic", "hard"}


def test_select_suites_filters_requested_and_failed_ids() -> None:
    suites = [
        SimpleNamespace(suite_id="generic"),
        SimpleNamespace(suite_id="hard"),
        SimpleNamespace(suite_id="noise"),
    ]

    selected = _select_suites(
        suites=suites,
        requested_suite_ids=["generic", "hard"],
        failed_suite_ids={"hard"},
    )

    assert [suite.suite_id for suite in selected] == ["hard"]


def test_build_matrix_report_preserves_metadata_and_summary() -> None:
    manifest = {"matrix_id": "default_v1", "description": "desc"}
    suite_reports = [
        {
            "suite_id": "generic",
            "summary": {"full_pass_rate": 1.0},
            "timing": {
                "wall_clock_seconds": 1.5,
                "by_endpoint": {
                    "ingest": {
                        "samples_ms": [100.0, 200.0],
                    }
                },
            },
            "cases": [],
        }
    ]

    report = _build_matrix_report(
        manifest=manifest,
        manifest_path=Path("/tmp/default_v1.json"),
        matrix_run_id="matrix_run",
        matrix_execution_id="exec_1",
        base_url="http://127.0.0.1:8010",
        suite_reports=suite_reports,
        summarize_matrix_reports=lambda reports: {
            "total_suites": len(reports),
            "total_cases": 39,
            "full_pass_count": 39,
            "full_pass_rate": 1.0,
            "answer_grounded_rate": 1.0,
            "suite_pass_rates": {"generic": 1.0},
            "failing_suites": [],
        },
    )

    assert report["matrix_id"] == "default_v1"
    assert report["run_id"] == "matrix_run"
    assert report["execution_id"] == "exec_1"
    assert report["manifest_path"] == "/tmp/default_v1.json"
    assert report["summary"]["total_suites"] == 1
    assert report["timing"]["wall_clock_seconds"] == 1.5
    assert report["timing"]["by_endpoint"]["ingest"]["count"] == 2
    assert report["suites"] == suite_reports


def test_build_failed_suite_report_marks_failed_status() -> None:
    report = _build_failed_suite_report(
        suite_id="generic",
        description="desc",
        cases_path=Path("/tmp/generic.json"),
        suite_run_id="matrix_run_generic",
        error=RuntimeError("boom"),
    )

    assert report["suite_id"] == "generic"
    assert report["status"] == "failed"
    assert report["summary"]["full_pass_rate"] == 0.0
    assert "boom" in str(report["error"])


def test_summarize_matrix_reports_includes_failed_suite() -> None:
    suite_reports = [
        {
            "suite_id": "generic",
            "summary": {
                "total_cases": 2,
                "full_pass_count": 2,
                "full_pass_rate": 1.0,
            },
            "cases": [],
        },
        {
            "suite_id": "hard",
            "summary": {
                "total_cases": 0,
                "full_pass_count": 0,
                "full_pass_rate": 0.0,
            },
            "cases": [],
            "status": "failed",
            "error": "boom",
        },
    ]

    summary = summarize_matrix_reports(suite_reports)

    assert summary["total_suites"] == 2
    assert summary["suite_pass_rates"]["hard"] == 0.0
    assert "hard" in summary["failing_suites"]


def test_render_matrix_event_line_formats_suite_progress() -> None:
    line = _render_matrix_event_line(
        {
            "event": "suite_completed",
            "suite_id": "generic",
            "suite_index": 1,
            "summary": {"full_pass_rate": 1.0, "total_cases": 39},
            "report_markdown_path": "/tmp/generic.md",
        }
    )

    assert line is not None
    assert "suite=generic" in line
    assert "full_pass_rate" in line
    assert "/tmp/generic.md" in line
