from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_CASES_PATH = MEMORY_ROOT / "evals" / "prompt_cases" / "identity_profile_rules_v1.json"
DEFAULT_REPORT_DIR = MEMORY_ROOT / "evals" / "reports" / "prompt_accuracy"


@dataclass(slots=True)
class ExpectedProfile:
    """单个期望 identity_profile 的判分条件。"""

    who_any: list[str]
    entity_type: str | None = None
    entity_type_any: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromptEvalCase:
    """一条提示词准确性评测用例。"""

    case_id: str
    category: str
    prompt_key: str
    payload: dict[str, Any]
    expected_gate_status: str
    expected_profiles: list[ExpectedProfile] = field(default_factory=list)
    forbidden_who: list[str] = field(default_factory=list)
    min_profile_count: int | None = None
    max_profile_count: int | None = None


def load_prompt_eval_suite(path: Path) -> dict[str, Any]:
    """读取提示词准确性评测套件。

    Args:
        path: JSON 套件文件路径。

    Returns:
        包含套件元数据和用例对象的字典。
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for item in raw.get("cases") or []:
        cases.append(
            PromptEvalCase(
                case_id=str(item["case_id"]),
                category=str(item.get("category") or ""),
                prompt_key=str(item["prompt_key"]),
                payload=dict(item.get("payload") or {}),
                expected_gate_status=str(item.get("expected_gate_status") or "passed"),
                expected_profiles=[
                    ExpectedProfile(
                        who_any=[str(value) for value in profile.get("who_any") or []],
                        entity_type=profile.get("entity_type"),
                        entity_type_any=[str(value) for value in profile.get("entity_type_any") or []],
                    )
                    for profile in item.get("expected_profiles") or []
                ],
                forbidden_who=[str(value) for value in item.get("forbidden_who") or []],
                min_profile_count=item.get("min_profile_count"),
                max_profile_count=item.get("max_profile_count"),
            )
        )
    return {
        "suite_id": str(raw["suite_id"]),
        "description": str(raw.get("description") or ""),
        "minimum_pass_rate": float(raw.get("minimum_pass_rate", 1.0)),
        "cases": cases,
    }


def score_prompt_case(case: PromptEvalCase, response: dict[str, Any]) -> dict[str, Any]:
    """对单条 prompt eval 原始响应进行本地判分。

    Args:
        case: 用例期望。
        response: `/memory/prompt-evals/run` 返回的完整 JSON。

    Returns:
        判分结果，包含是否通过和失败原因。
    """

    failures: list[str] = []
    if response.get("status") != "ok":
        failures.append(f"response status is {response.get('status')!r}, expected 'ok'")
        return _case_result(case=case, response=response, failures=failures)

    output = dict(response.get("output") or {})
    gate_status = _extract_gate_status(output)
    if gate_status != case.expected_gate_status:
        failures.append(f"gate status is {gate_status!r}, expected {case.expected_gate_status!r}")

    profiles = _extract_profiles(output)
    if case.min_profile_count is not None and len(profiles) < case.min_profile_count:
        failures.append(f"profile count is {len(profiles)}, expected at least {case.min_profile_count}")
    if case.max_profile_count is not None and len(profiles) > case.max_profile_count:
        failures.append(f"profile count is {len(profiles)}, expected at most {case.max_profile_count}")

    for expected in case.expected_profiles:
        if not _profile_matches_expected(profiles, expected):
            failures.append(
                "missing expected profile "
                f"who_any={expected.who_any!r} entity_type={_expected_entity_type_text(expected)!r}"
            )

    profile_names = {_normalize_text(profile.get("who")) for profile in profiles}
    for forbidden in case.forbidden_who:
        if _normalize_text(forbidden) in profile_names:
            failures.append(f"forbidden profile was returned: {forbidden!r}")

    return _case_result(case=case, response=response, failures=failures)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总提示词准确性评测结果。

    Args:
        results: 单条用例判分结果列表。

    Returns:
        汇总统计信息。
    """

    total = len(results)
    pass_count = sum(1 for result in results if result["passed"])
    pass_rate = pass_count / total if total else 0.0
    return {
        "total_cases": total,
        "pass_count": pass_count,
        "fail_count": total - pass_count,
        "pass_rate": pass_rate,
        "failing_cases": [result["case_id"] for result in results if not result["passed"]],
    }


def write_report_files(*, report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    """写入提示词准确性评测报告。

    Args:
        report: 完整评测报告。
        output_dir: 报告输出目录。

    Returns:
        JSON 和 Markdown 报告路径。
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    suite_id = str(report["suite_id"])
    run_id = str(report["run_id"])
    suffix = uuid4().hex[:8]
    json_path = output_dir / f"{run_id}_{suite_id}__{suffix}.json"
    markdown_path = output_dir / f"{run_id}_{suite_id}__{suffix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _extract_gate_status(output: dict[str, Any]) -> str | None:
    for key in ("identity_gate_status", "query_gate_status"):
        if output.get(key):
            return str(output[key])
    return None


def _extract_profiles(output: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("identity_profile_drafts", "query_identity_profile_drafts"):
        profiles = output.get(key)
        if isinstance(profiles, list):
            return [dict(profile) for profile in profiles if isinstance(profile, dict)]
    return []


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _profile_matches_expected(profiles: list[dict[str, Any]], expected: ExpectedProfile) -> bool:
    expected_names = {_normalize_text(value) for value in expected.who_any}
    expected_types = _expected_entity_types(expected)
    for profile in profiles:
        if _normalize_text(profile.get("who")) not in expected_names:
            continue
        if expected_types and profile.get("entity_type") not in expected_types:
            continue
        return True
    return False


def _expected_entity_types(expected: ExpectedProfile) -> set[str]:
    values = set(expected.entity_type_any)
    if expected.entity_type:
        values.add(expected.entity_type)
    return values


def _expected_entity_type_text(expected: ExpectedProfile) -> str | list[str] | None:
    values = sorted(_expected_entity_types(expected))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return values


def _case_result(*, case: PromptEvalCase, response: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    output = dict(response.get("output") or {})
    profiles = _extract_profiles(output)
    return {
        "case_id": case.case_id,
        "category": case.category,
        "prompt_key": case.prompt_key,
        "passed": not failures,
        "failures": failures,
        "expected_gate_status": case.expected_gate_status,
        "actual_gate_status": _extract_gate_status(output),
        "actual_profiles": [
            {
                "who": profile.get("who"),
                "entity_type": profile.get("entity_type"),
                "surface_forms": profile.get("surface_forms") or [],
                "stable_qualifiers": profile.get("stable_qualifiers") or [],
            }
            for profile in profiles
        ],
        "response_status": response.get("status"),
        "error_code": response.get("error_code"),
        "usage": response.get("usage"),
        "latency_ms": response.get("latency_ms"),
        "model": response.get("model"),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    summary = dict(report["summary"])
    lines = [
        f"# Prompt Accuracy Report: {report['suite_id']}",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Base URL: `{report['base_url']}`",
        f"- Cases: {summary['total_cases']}",
        f"- Pass rate: {summary['pass_rate']:.2%}",
        f"- Minimum pass rate: {report['minimum_pass_rate']:.2%}",
        "",
        "## Cases",
        "",
    ]
    for result in report["cases"]:
        status = "PASS" if result["passed"] else "FAIL"
        lines.append(f"- `{status}` `{result['case_id']}` `{result['prompt_key']}`")
        if result["failures"]:
            lines.append(f"  - failures: {'; '.join(result['failures'])}")
        lines.append(f"  - profiles: `{json.dumps(result['actual_profiles'], ensure_ascii=False)}`")
    lines.append("")
    return "\n".join(lines)


async def _run_case(client: httpx.AsyncClient, case: PromptEvalCase) -> dict[str, Any]:
    response = await client.post(
        "/memory/prompt-evals/run",
        json={"prompt_key": case.prompt_key, "payload": case.payload},
    )
    return score_prompt_case(case, response.json())


async def _run(args: argparse.Namespace) -> int:
    suite = load_prompt_eval_suite(Path(args.cases))
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout_seconds) as client:
        results = []
        for case in suite["cases"]:
            result = await _run_case(client, case)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"Prompt eval case {status}: {result['case_id']}", flush=True)
            for failure in result["failures"]:
                print(f"  - {failure}", flush=True)

    summary = summarize_results(results)
    report = {
        "suite_id": suite["suite_id"],
        "description": suite["description"],
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "cases_path": str(Path(args.cases).resolve()),
        "minimum_pass_rate": suite["minimum_pass_rate"],
        "summary": summary,
        "cases": results,
    }
    paths = write_report_files(report=report, output_dir=Path(args.output_dir))
    print(f"Prompt accuracy report written to: {paths['json']}", flush=True)
    print(f"Prompt accuracy summary written to: {paths['markdown']}", flush=True)
    return 0 if summary["pass_rate"] >= suite["minimum_pass_rate"] else 1


def main() -> int:
    """运行提示词准确性评测命令行入口。

    Returns:
        达到套件最低通过率时返回 0，否则返回 1。
    """

    parser = argparse.ArgumentParser(description="Evaluate prompt accuracy via /memory/prompt-evals/run.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL of the live memory service.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to the prompt eval case suite.")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for reports.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--timeout-seconds", type=float, default=120.0, help="Per-request HTTP timeout.")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
