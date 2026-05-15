from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_ROOT = SCRIPT_DIR.parents[1]
if str(MEMORY_ROOT) not in sys.path:
    sys.path.insert(0, str(MEMORY_ROOT))


from evals.scripts.eval_timing import TimedMemoryApiClient


DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_EVAL_DATABASE_URL = "postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory"
DEFAULT_CASES_PATH = MEMORY_ROOT / "evals" / "cases" / "generic_accuracy_v1.json"
DEFAULT_REPORT_DIR = MEMORY_ROOT / "evals" / "reports"


def _preview_text(value: object, *, limit: int = 160) -> str:
    """Return a single-line preview for CLI progress output."""

    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _preview_json(value: Any, *, limit: int = 200) -> str:
    """Return a compact JSON preview for CLI progress output."""

    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _render_event_line(event: dict[str, Any]) -> str | None:
    """Render one evaluator event into a human-readable CLI line."""

    event_type = str(event.get("event") or "")
    case_id = event.get("case_id")
    prefix = f"[{event_type}]"
    if case_id:
        prefix = f"{prefix} {case_id}"

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
            f"scope={event.get('scope_alias')} "
            f"expected={event.get('expected_status')} "
            f"actual={event.get('actual_status')} "
            f"passed={event.get('passed')} "
            f"response={_preview_json(event.get('response'))}"
        )
    if event_type == "settle_started":
        return (
            f"{prefix} settle scope={event.get('scope_alias')} "
            f"timeout={event.get('settle_timeout_seconds')}s"
        )
    if event_type == "settle_completed":
        return (
            f"{prefix} settle scope={event.get('scope_alias')} "
            f"result={_preview_json(event.get('settle'))}"
        )
    if event_type == "query_started":
        return (
            f"{prefix} query[{event.get('query_id')}] "
            f"scope={event.get('scope_alias')} "
            f"expected={event.get('expected_status')} "
            f"query={_preview_text(event.get('query'))}"
        )
    if event_type == "query_completed":
        return (
            f"{prefix} query[{event.get('query_id')}] "
            f"status={event.get('status')} "
            f"deterministic_pass={event.get('deterministic_pass')} "
            f"judge={_preview_json(event.get('judge'))} "
            f"response={_preview_json(event.get('response'))}"
        )
    if event_type == "snapshot_started":
        return f"{prefix} scopes={event.get('scope_aliases')}"
    if event_type == "snapshot_completed":
        return f"{prefix} snapshots={_preview_json(event.get('snapshots'), limit=300)}"
    if event_type == "case_completed":
        return (
            f"{prefix} full_pass={event.get('full_pass')} "
            f"failure_count={event.get('failure_count')} "
            f"dimensions={_preview_json(event.get('dimension_pass'))}"
        )
    if event_type == "evaluation_completed":
        return f"{prefix} summary={_preview_json(event.get('summary'), limit=300)}"
    return None


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
        load_eval_cases,
        write_report_files,
    )

    api = TimedMemoryApiClient(
        inner=HttpMemoryApiClient(base_url=args.base_url, timeout_seconds=args.timeout_seconds)
    )
    try:
        evaluator = AccuracyEvaluator(
            api=api,
            inspector=RepositoryInspector(),
            judge=LLMAnswerJudge(),
        )
        cases = load_eval_cases(Path(args.cases))
        run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path(args.output_dir)

        async def _write_progress(report: dict[str, object]) -> None:
            output_paths = write_report_files(
                report=report,
                output_dir=output_dir,
            )
            print(
                "Memory accuracy progress: "
                f"{report.get('completed_case_count', 0)}/{report.get('expected_total_case_count', 0)} "
                f"cases written to {output_paths['latest_markdown']}",
                flush=True,
            )

        async def _print_event(event: dict[str, Any]) -> None:
            line = _render_event_line(event)
            if line:
                print(f"Memory accuracy event: {line}", flush=True)

        started = time.perf_counter()
        report = await evaluator.evaluate_cases(
            cases=cases,
            run_id=run_id,
            settle_timeout_seconds=args.settle_timeout_seconds,
            progress_callback=_write_progress,
            event_callback=_print_event,
        )
        report["timing"] = api.snapshot(
            wall_clock_seconds=time.perf_counter() - started,
        )
        output_paths = write_report_files(
            report=report,
            output_dir=output_dir,
        )
        print(
            f"Memory accuracy timing: {_preview_json(report['timing'], limit=320)}",
            flush=True,
        )
        print(f"Memory accuracy report written to: {output_paths['json']}", flush=True)
        print(f"Memory accuracy summary written to: {output_paths['markdown']}", flush=True)
        return 0
    finally:
        await api.aclose()


def main() -> int:
    """Run the live memory accuracy evaluation suite."""

    parser = argparse.ArgumentParser(description="Evaluate live memory accuracy against the real memory service.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL of the live memory service.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to the JSON case corpus.")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for JSON and Markdown reports.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
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
        help="How long to wait for background tasks in one scope to settle.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
