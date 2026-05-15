from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_ROOT = SCRIPT_DIR.parents[1]
if str(MEMORY_ROOT) not in sys.path:
    sys.path.insert(0, str(MEMORY_ROOT))


from evals.scripts.eval_timing import TimedMemoryApiClient, merge_timing_summaries


DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_EVAL_DATABASE_URL = "postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory"
DEFAULT_MANIFEST_PATH = MEMORY_ROOT / "evals" / "matrix" / "default_v1.json"
DEFAULT_SUITE_REPORT_DIR = MEMORY_ROOT / "evals" / "reports"
DEFAULT_MATRIX_REPORT_DIR = MEMORY_ROOT / "evals" / "reports" / "matrix"


def _preview_text(value: object, *, limit: int = 160) -> str:
    """Return a single-line preview for CLI progress output."""

    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _preview_json(value: Any, *, limit: int = 220) -> str:
    """Return a compact JSON preview for CLI progress output."""

    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _render_matrix_event_line(event: dict[str, Any]) -> str | None:
    """Render one matrix/evaluator event into a human-readable CLI line."""

    event_type = str(event.get("event") or "")
    suite_id = event.get("suite_id")
    case_id = event.get("case_id")
    prefix = f"[{event_type}]"
    if suite_id:
        prefix = f"{prefix} suite={suite_id}"
    if case_id:
        prefix = f"{prefix} case={case_id}"

    if event_type == "matrix_started":
        return (
            f"{prefix} run_id={event.get('run_id')} "
            f"execution_id={event.get('execution_id')} "
            f"suites={event.get('suite_count')} "
            f"manifest={event.get('manifest_path')}"
        )
    if event_type == "suite_started":
        return (
            f"{prefix} index={event.get('suite_index')} "
            f"cases_path={event.get('cases_path')} "
            f"suite_run_id={event.get('suite_run_id')}"
        )
    if event_type == "suite_completed":
        return (
            f"{prefix} index={event.get('suite_index')} "
            f"summary={_preview_json(event.get('summary'))} "
            f"timing={_preview_json(event.get('timing'), limit=180)} "
            f"report={event.get('report_markdown_path')}"
        )
    if event_type == "matrix_progress":
        return (
            f"{prefix} completed_suites={event.get('completed_suite_count')}/{event.get('expected_suite_count')} "
            f"latest_matrix_markdown={event.get('latest_markdown_path')}"
        )
    if event_type == "matrix_completed":
        return (
            f"{prefix} summary={_preview_json(event.get('summary'), limit=320)} "
            f"timing={_preview_json(event.get('timing'), limit=220)}"
        )
    if event_type == "evaluation_started":
        return (
            f"{prefix} run_id={event.get('run_id')} "
            f"execution_id={event.get('execution_id')} "
            f"cases={event.get('case_count')} "
            f"health={_preview_json(event.get('health'))}"
        )
    if event_type == "case_started":
        return (
            f"{prefix} category={event.get('category')} "
            f"description={_preview_text(event.get('description'))}"
        )
    if event_type == "write_started":
        return (
            f"{prefix} write[{event.get('write_index')}] "
            f"scope={event.get('scope_alias')} "
            f"expected={event.get('expected_status')} "
            f"context={_preview_text(event.get('context'))}"
        )
    if event_type == "write_completed":
        return (
            f"{prefix} write[{event.get('write_index')}] "
            f"actual={event.get('actual_status')} "
            f"passed={event.get('passed')} "
            f"response={_preview_json(event.get('response'))}"
        )
    if event_type == "settle_started":
        return f"{prefix} settle scope={event.get('scope_alias')} timeout={event.get('settle_timeout_seconds')}s"
    if event_type == "settle_completed":
        return f"{prefix} settle scope={event.get('scope_alias')} result={_preview_json(event.get('settle'))}"
    if event_type == "query_started":
        return (
            f"{prefix} query[{event.get('query_id')}] "
            f"expected={event.get('expected_status')} "
            f"query={_preview_text(event.get('query'))}"
        )
    if event_type == "query_completed":
        return (
            f"{prefix} query[{event.get('query_id')}] "
            f"status={event.get('status')} "
            f"deterministic_pass={event.get('deterministic_pass')} "
            f"judge={_preview_json(event.get('judge'))}"
        )
    if event_type == "snapshot_started":
        return f"{prefix} scopes={event.get('scope_aliases')}"
    if event_type == "snapshot_completed":
        return f"{prefix} snapshots={_preview_json(event.get('snapshots'), limit=320)}"
    if event_type == "case_completed":
        return (
            f"{prefix} full_pass={event.get('full_pass')} "
            f"failure_count={event.get('failure_count')} "
            f"dimensions={_preview_json(event.get('dimension_pass'))}"
        )
    if event_type == "evaluation_completed":
        return f"{prefix} summary={_preview_json(event.get('summary'), limit=320)}"
    return None


def _load_failed_suite_ids(report_path: Path) -> set[str]:
    """Load failed suite ids from a previous matrix report."""

    raw = json.loads(report_path.read_text(encoding="utf-8"))
    summary = dict(raw.get("summary") or {})
    return {
        str(item)
        for item in list(summary.get("failing_suites") or [])
        if str(item).strip()
    }


def _select_suites(
    *,
    suites: list[Any],
    requested_suite_ids: list[str] | None,
    failed_suite_ids: set[str] | None,
) -> list[Any]:
    """Apply suite filters in a predictable order."""

    selected = list(suites)
    if requested_suite_ids:
        requested = set(requested_suite_ids)
        selected = [suite for suite in selected if suite.suite_id in requested]
        missing = sorted(requested - {suite.suite_id for suite in selected})
        if missing:
            raise RuntimeError(f"Unknown suite ids: {', '.join(missing)}")
    if failed_suite_ids is not None:
        selected = [suite for suite in selected if suite.suite_id in failed_suite_ids]
    return selected


def _build_matrix_report(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    matrix_run_id: str,
    matrix_execution_id: str,
    base_url: str,
    suite_reports: list[dict[str, object]],
    summarize_matrix_reports,
) -> dict[str, Any]:
    """Build the matrix report payload from completed suite reports."""

    timing = merge_timing_summaries(
        [dict(item.get("timing") or {}) for item in suite_reports if item.get("timing")]
    )
    return {
        "matrix_id": manifest["matrix_id"],
        "description": manifest["description"],
        "manifest_path": str(manifest_path.resolve()),
        "run_id": matrix_run_id,
        "execution_id": matrix_execution_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "summary": summarize_matrix_reports(suite_reports),
        "timing": timing,
        "suites": suite_reports,
    }


def _build_failed_suite_report(
    *,
    suite_id: str,
    description: str,
    cases_path: Path,
    suite_run_id: str,
    error: BaseException,
    timing: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Build a synthetic failed suite report when suite execution crashes.

    Args:
        suite_id: Matrix suite identifier.
        description: Suite description.
        cases_path: Path to the suite cases file.
        suite_run_id: Effective run id used for the suite.
        error: The raised exception.

    Returns:
        A suite-shaped report payload with failure metadata.
    """

    error_message = "".join(
        traceback.format_exception_only(type(error), error)
    ).strip()
    return {
        "suite_id": suite_id,
        "description": description,
        "cases_path": str(cases_path),
        "run_id": suite_run_id,
        "execution_id": None,
        "status": "failed",
        "summary": {
            "total_cases": 0,
            "full_pass_count": 0,
            "full_pass_rate": 0.0,
            "answer_grounded_rate": 0.0,
        },
        "timing": timing or {},
        "report_paths": {},
        "failing_cases": [],
        "cases": [],
        "error": error_message,
    }


async def _run(args: argparse.Namespace) -> int:
    if args.database_url:
        os.environ["MEMORY_DATABASE_URL"] = args.database_url
    elif os.environ.get("MEMORY_EVAL_DATABASE_URL"):
        os.environ["MEMORY_DATABASE_URL"] = os.environ["MEMORY_EVAL_DATABASE_URL"]
    else:
        os.environ["MEMORY_DATABASE_URL"] = DEFAULT_EVAL_DATABASE_URL

    from insight_memory.evals.accuracy import (  # noqa: E402
        AccuracyEvaluator,
        HttpMemoryApiClient,
        LLMAnswerJudge,
        RepositoryInspector,
        build_execution_id,
        load_eval_cases,
        load_eval_matrix,
        summarize_matrix_reports,
        write_matrix_report_files,
        write_report_files,
    )

    manifest_path = Path(args.manifest)
    manifest = load_eval_matrix(manifest_path)
    failed_suite_ids = None
    if args.only_failed_from:
        failed_suite_ids = _load_failed_suite_ids(Path(args.only_failed_from))
    suites = _select_suites(
        suites=list(manifest["suites"]),
        requested_suite_ids=args.suite,
        failed_suite_ids=failed_suite_ids,
    )
    if not suites:
        raise RuntimeError("No suites selected")

    matrix_run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    matrix_execution_id = build_execution_id()
    print(
        _render_matrix_event_line(
            {
                "event": "matrix_started",
                "run_id": matrix_run_id,
                "execution_id": matrix_execution_id,
                "suite_count": len(suites),
                "manifest_path": str(manifest_path.resolve()),
            }
        ),
        flush=True,
    )

    suite_reports_by_index: dict[int, dict[str, object]] = {}

    def _write_partial_matrix_report() -> dict[str, Path]:
        ordered_suite_reports = [
            suite_reports_by_index[item_index]
            for item_index in sorted(suite_reports_by_index)
        ]
        matrix_report = _build_matrix_report(
            manifest=manifest,
            manifest_path=manifest_path,
            matrix_run_id=matrix_run_id,
            matrix_execution_id=matrix_execution_id,
            base_url=args.base_url,
            suite_reports=ordered_suite_reports,
            summarize_matrix_reports=summarize_matrix_reports,
        )
        return write_matrix_report_files(
            report=matrix_report,
            output_dir=Path(args.matrix_output_dir),
        )

    try:
        async def _run_suite(index: int, suite) -> tuple[int, dict[str, object]]:
            cases = load_eval_cases(suite.cases_path)
            suite_run_id = suite.run_id or f"{matrix_run_id}_{suite.suite_id}"
            print(
                _render_matrix_event_line(
                    {
                        "event": "suite_started",
                        "suite_id": suite.suite_id,
                        "suite_index": index + 1,
                        "cases_path": str(suite.cases_path),
                        "suite_run_id": suite_run_id,
                    }
                ),
                flush=True,
            )
            api = TimedMemoryApiClient(
                inner=HttpMemoryApiClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds)
            )
            evaluator = AccuracyEvaluator(
                api=api,
                inspector=RepositoryInspector(),
                judge=LLMAnswerJudge(),
            )
            started = time.perf_counter()

            async def _suite_event_callback(event: dict[str, Any]) -> None:
                enriched_event = {"suite_id": suite.suite_id, **event}
                line = _render_matrix_event_line(enriched_event)
                if line:
                    print(f"Memory matrix event: {line}", flush=True)
            try:
                report = await evaluator.evaluate_cases(
                    cases=cases,
                    run_id=suite_run_id,
                    settle_timeout_seconds=suite.settle_timeout_seconds or args.settle_timeout_seconds,
                    event_callback=_suite_event_callback,
                )
                timing = api.snapshot(wall_clock_seconds=time.perf_counter() - started)
                report["timing"] = timing
                output_paths = write_report_files(
                    report=report,
                    output_dir=Path(args.suite_output_dir),
                )
                print(
                    _render_matrix_event_line(
                        {
                            "event": "suite_completed",
                            "suite_id": suite.suite_id,
                            "suite_index": index + 1,
                            "summary": report["summary"],
                            "timing": timing,
                            "report_markdown_path": str(output_paths["markdown"]),
                        }
                    ),
                    flush=True,
                )
                return (
                    index,
                    {
                        "suite_id": suite.suite_id,
                        "description": suite.description,
                        "cases_path": str(suite.cases_path),
                        "run_id": report["run_id"],
                        "execution_id": report["execution_id"],
                        "status": "completed",
                        "summary": report["summary"],
                        "timing": timing,
                        "report_paths": {
                            key: str(value)
                            for key, value in output_paths.items()
                        },
                        "failing_cases": [
                            {
                                "case_id": case["case_id"],
                                "failures": list(case.get("failures") or []),
                            }
                            for case in list(report.get("cases") or [])
                            if not case.get("full_pass")
                        ],
                        "cases": report["cases"],
                    },
                )
            except Exception as error:  # noqa: BLE001
                timing = api.snapshot(wall_clock_seconds=time.perf_counter() - started)
                print(
                    f"Memory matrix suite failed: suite={suite.suite_id} error={error}",
                    file=sys.stderr,
                    flush=True,
                )
                traceback.print_exc()
                return (
                    index,
                    _build_failed_suite_report(
                        suite_id=suite.suite_id,
                        description=suite.description,
                        cases_path=suite.cases_path,
                        suite_run_id=suite_run_id,
                        error=error,
                        timing=timing,
                    ),
                )
            finally:
                await api.aclose()

        semaphore = asyncio.Semaphore(args.max_concurrency)

        async def _run_suite_guarded(index: int, suite) -> tuple[int, dict[str, object]]:
            async with semaphore:
                return await _run_suite(index, suite)

        tasks = [
            asyncio.create_task(_run_suite_guarded(index, suite))
            for index, suite in enumerate(suites)
        ]
        for finished in asyncio.as_completed(tasks):
            index, suite_report = await finished
            suite_reports_by_index[index] = suite_report
            ordered_suite_reports = [
                suite_reports_by_index[item_index]
                for item_index in sorted(suite_reports_by_index)
            ]
            _write_partial_matrix_report()
            latest_markdown_path = Path(args.matrix_output_dir) / "latest.md"
            print(
                _render_matrix_event_line(
                    {
                        "event": "matrix_progress",
                        "completed_suite_count": len(ordered_suite_reports),
                        "expected_suite_count": len(suites),
                        "latest_markdown_path": str(latest_markdown_path),
                    }
                ),
                flush=True,
            )

        suite_reports = [
            suite_reports_by_index[item_index]
            for item_index in sorted(suite_reports_by_index)
        ]
        matrix_report = _build_matrix_report(
            manifest=manifest,
            manifest_path=manifest_path,
            matrix_run_id=matrix_run_id,
            matrix_execution_id=matrix_execution_id,
            base_url=args.base_url,
            suite_reports=suite_reports,
            summarize_matrix_reports=summarize_matrix_reports,
        )
        output_paths = write_matrix_report_files(
            report=matrix_report,
            output_dir=Path(args.matrix_output_dir),
        )
        print(
            _render_matrix_event_line(
                {
                    "event": "matrix_completed",
                    "summary": matrix_report["summary"],
                    "timing": matrix_report["timing"],
                }
            ),
            flush=True,
        )
        print(f"Memory matrix report written to: {output_paths['json']}", flush=True)
        print(f"Memory matrix summary written to: {output_paths['markdown']}", flush=True)
        return 0
    except Exception as error:  # noqa: BLE001
        print(
            f"Memory matrix run failed: run_id={matrix_run_id} error={error}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        output_paths = _write_partial_matrix_report()
        print(
            f"Memory matrix partial report written to: {output_paths['json']}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"Memory matrix partial summary written to: {output_paths['markdown']}",
            file=sys.stderr,
            flush=True,
        )
        return 1


def main() -> int:
    """Run a matrix of live memory accuracy suites."""

    parser = argparse.ArgumentParser(description="Run a matrix of live memory accuracy suites.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL of the live memory service.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Path to the matrix manifest JSON.")
    parser.add_argument(
        "--suite",
        action="append",
        default=None,
        help="Optional suite id filter. Repeat to include multiple suites.",
    )
    parser.add_argument("--run-id", default=None, help="Optional explicit matrix run id.")
    parser.add_argument(
        "--only-failed-from",
        default=None,
        help="Optional previous matrix report JSON. When set, rerun only suites that failed there.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Optional database URL override for repository inspection. Defaults to MEMORY_EVAL_DATABASE_URL if set.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0, help="Per-request HTTP timeout.")
    parser.add_argument(
        "--settle-timeout-seconds",
        type=float,
        default=30.0,
        help="Default background settle timeout for suites that do not override it.",
    )
    parser.add_argument(
        "--suite-output-dir",
        default=str(DEFAULT_SUITE_REPORT_DIR),
        help="Directory for per-suite JSON and Markdown reports.",
    )
    parser.add_argument(
        "--matrix-output-dir",
        default=str(DEFAULT_MATRIX_REPORT_DIR),
        help="Directory for matrix JSON and Markdown reports.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Maximum number of suites to evaluate concurrently.",
    )
    args = parser.parse_args()
    if args.max_concurrency < 1:
        parser.error("--max-concurrency must be >= 1")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
