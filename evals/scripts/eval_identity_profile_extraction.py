from __future__ import annotations

import argparse
import asyncio
import json
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
DEFAULT_REPORT_DIR = MEMORY_ROOT / "evals" / "reports" / "identity_profile_extraction"


@dataclass(slots=True)
class ExpectedIdentityProfile:
    """单个期望 identity_profile 的判分条件。"""

    who_any: list[str]
    surface_forms_any: list[str] = field(default_factory=list)
    surface_forms_all: list[str] = field(default_factory=list)
    stable_qualifiers_any: list[str] = field(default_factory=list)
    stable_qualifiers_all: list[str] = field(default_factory=list)
    definition_required: bool = False
    definition_contains_any: list[str] = field(default_factory=list)
    definition_contains_all: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IdentityExtractionCase:
    """一条 identity_profile 提取评测用例。"""

    case_id: str
    category: str
    prompt_key: str
    target_prompt_key: str
    payload: dict[str, Any]
    expected_gate_status: str
    expected_identities: list[ExpectedIdentityProfile] = field(default_factory=list)
    forbidden_identity_who: list[str] = field(default_factory=list)
    profile_count: int | None = None


def load_identity_extraction_suite(path: Path) -> dict[str, Any]:
    """读取 identity_profile 提取评测套件。

    Args:
        path: JSON 套件文件路径。

    Returns:
        包含套件元数据和用例对象的字典。
    """

    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for item in raw.get("cases") or []:
        prompt_key = str(item["prompt_key"])
        if prompt_key != "identity_profile":
            raise ValueError("identity_profile extraction suites must use prompt_key='identity_profile'")
        target_prompt_key = item.get("target_prompt_key") or raw.get("target_prompt_key")
        if not target_prompt_key:
            raise ValueError("identity_profile extraction cases require target_prompt_key")
        cases.append(
            IdentityExtractionCase(
                case_id=str(item["case_id"]),
                category=str(item.get("category") or ""),
                prompt_key=prompt_key,
                target_prompt_key=str(target_prompt_key),
                payload=dict(item.get("payload") or {}),
                expected_gate_status=str(item.get("expected_gate_status") or "passed"),
                expected_identities=[
                    ExpectedIdentityProfile(
                        who_any=[str(value) for value in profile.get("who_any") or []],
                        surface_forms_any=[str(value) for value in profile.get("surface_forms_any") or []],
                        surface_forms_all=[str(value) for value in profile.get("surface_forms_all") or []],
                        stable_qualifiers_any=[
                            str(value) for value in profile.get("stable_qualifiers_any") or []
                        ],
                        stable_qualifiers_all=[
                            str(value) for value in profile.get("stable_qualifiers_all") or []
                        ],
                        definition_required=bool(profile.get("definition_required", False)),
                        definition_contains_any=[
                            str(value) for value in profile.get("definition_contains_any") or []
                        ],
                        definition_contains_all=[
                            str(value) for value in profile.get("definition_contains_all") or []
                        ],
                    )
                    for profile in item.get("expected_identities") or []
                ],
                forbidden_identity_who=[str(value) for value in item.get("forbidden_identity_who") or []],
                profile_count=item.get("profile_count"),
            )
        )
    return {
        "suite_id": str(raw["suite_id"]),
        "description": str(raw.get("description") or ""),
        "minimum_pass_rate": float(raw.get("minimum_pass_rate", 1.0)),
        "cases": cases,
    }


def score_identity_extraction_case(case: IdentityExtractionCase, response: dict[str, Any]) -> dict[str, Any]:
    """对单条 identity_profile 提取响应进行本地判分。

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
    if case.profile_count is not None and len(profiles) != case.profile_count:
        failures.append(f"profile count is {len(profiles)}, expected exactly {case.profile_count}")

    for expected in case.expected_identities:
        matched_profile = _find_matching_identity_profile(profiles, expected)
        if matched_profile is None:
            failures.append(f"missing expected identity who_any={expected.who_any!r}")
            continue
        failures.extend(_score_profile_fields(matched_profile, expected))

    profile_names = {_normalize_text(profile.get("who")) for profile in profiles}
    for forbidden in case.forbidden_identity_who:
        if _normalize_text(forbidden) in profile_names:
            failures.append(f"forbidden identity was returned: {forbidden!r}")

    return _case_result(case=case, response=response, failures=failures)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总 identity_profile 提取评测结果。

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
    """写入 identity_profile 提取评测报告。

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


def _find_matching_identity_profile(
    identities: list[dict[str, Any]], expected: ExpectedIdentityProfile
) -> dict[str, Any] | None:
    expected_names = {_normalize_text(value) for value in expected.who_any}
    for profile in identities:
        if _normalize_text(profile.get("who")) not in expected_names:
            continue
        return profile
    return None


def _score_profile_fields(profile: dict[str, Any], expected: ExpectedIdentityProfile) -> list[str]:
    failures: list[str] = []
    failures.extend(
        _score_surface_forms_field(
            profile=profile,
            expected_any=expected.surface_forms_any,
            expected_all=expected.surface_forms_all,
        )
    )
    failures.extend(
        _score_exact_list_field(
            profile=profile,
            field_name="stable_qualifiers",
            expected_any=expected.stable_qualifiers_any,
            expected_all=expected.stable_qualifiers_all,
        )
    )
    failures.extend(
        _score_definition_field(
            profile=profile,
            definition_required=expected.definition_required,
            expected_any=expected.definition_contains_any,
            expected_all=expected.definition_contains_all,
        )
    )
    return failures


def _score_definition_field(
    *,
    profile: dict[str, Any],
    definition_required: bool,
    expected_any: list[str],
    expected_all: list[str],
) -> list[str]:
    failures: list[str] = []
    definition = _normalize_text(profile.get("definition"))
    if definition_required and not definition:
        failures.append("definition is required")
        return failures
    failures.extend(
        _score_contains_list_field(
            profile=profile,
            field_name="definition",
            expected_any=expected_any,
            expected_all=expected_all,
        )
    )
    return failures


def _score_surface_forms_field(
    *,
    profile: dict[str, Any],
    expected_any: list[str],
    expected_all: list[str],
) -> list[str]:
    """检查 surface_forms 是否与期望原始称呼一致。

    Args:
        profile: LLM 返回的单个 identity_profile。
        expected_any: 至少命中一个即可的兼容期望。
        expected_all: 完整匹配的期望 surface form 列表。

    Returns:
        失败原因列表；没有失败时返回空列表。
    """

    field_name = "surface_forms"
    values = {_normalize_text(value) for value in _list_field(profile, field_name)}
    failures: list[str] = []
    if expected_any and not values.intersection({_normalize_text(value) for value in expected_any}):
        failures.append(f"{field_name} has no expected value from {expected_any!r}")
    if expected_all:
        expected_values = {_normalize_text(value) for value in expected_all}
        missing = [value for value in expected_all if _normalize_text(value) not in values]
        extra = sorted(value for value in values if value not in expected_values)
        if missing:
            failures.append(f"{field_name} missing expected values {missing!r}")
        if extra:
            failures.append(f"{field_name} has unexpected values {extra!r}")
    return failures


def _score_exact_list_field(
    *,
    profile: dict[str, Any],
    field_name: str,
    expected_any: list[str],
    expected_all: list[str],
) -> list[str]:
    values = {_normalize_text(value) for value in _list_field(profile, field_name)}
    failures: list[str] = []
    if expected_any and not values.intersection({_normalize_text(value) for value in expected_any}):
        failures.append(f"{field_name} has no expected value from {expected_any!r}")
    missing = [
        value
        for value in expected_all
        if _normalize_text(value) not in values
    ]
    if missing:
        failures.append(f"{field_name} missing expected values {missing!r}")
    return failures


def _score_contains_list_field(
    *,
    profile: dict[str, Any],
    field_name: str,
    expected_any: list[str],
    expected_all: list[str],
) -> list[str]:
    raw_value = profile.get(field_name)
    if isinstance(raw_value, list):
        text = _normalize_text(" ".join(str(item) for item in raw_value))
    else:
        text = _normalize_text(raw_value)
    failures: list[str] = []
    if expected_any and not any(_normalize_text(value) in text for value in expected_any):
        failures.append(f"{field_name} contains none of {expected_any!r}")
    missing = [
        value
        for value in expected_all
        if _normalize_text(value) not in text
    ]
    if missing:
        failures.append(f"{field_name} missing expected fragments {missing!r}")
    return failures


def _list_field(profile: dict[str, Any], field_name: str) -> list[str]:
    value = profile.get(field_name)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _case_result(*, case: IdentityExtractionCase, response: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    output = dict(response.get("output") or {})
    profiles = _extract_profiles(output)
    return {
        "case_id": case.case_id,
        "category": case.category,
        "prompt_key": case.prompt_key,
        "target_prompt_key": case.target_prompt_key,
        "passed": not failures,
        "failures": failures,
        "expected_gate_status": case.expected_gate_status,
        "actual_gate_status": _extract_gate_status(output),
        "actual_identities": [
            {
                "who": profile.get("who"),
                "surface_forms": profile.get("surface_forms") or [],
                "stable_qualifiers": profile.get("stable_qualifiers") or [],
                "definition": profile.get("definition") or "",
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
        f"# Identity Extraction Report: {report['suite_id']}",
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
        lines.append(
            f"- `{status}` `{result['case_id']}` "
            f"`{result['prompt_key']}` -> `{result['target_prompt_key']}`"
        )
        if result["failures"]:
            lines.append(f"  - failures: {'; '.join(result['failures'])}")
        lines.append(f"  - identities: `{json.dumps(result['actual_identities'], ensure_ascii=False)}`")
    lines.append("")
    return "\n".join(lines)


async def _run_case(client: httpx.AsyncClient, case: IdentityExtractionCase) -> dict[str, Any]:
    response = await client.post(
        "/memory/prompt-evals/run",
        json={"prompt_key": case.target_prompt_key, "payload": case.payload},
    )
    return score_identity_extraction_case(case, response.json())


async def _run(args: argparse.Namespace) -> int:
    suite = load_identity_extraction_suite(Path(args.cases))
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout_seconds) as client:
        results = []
        for case in suite["cases"]:
            result = await _run_case(client, case)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"Identity extraction case {status}: {result['case_id']}", flush=True)
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
    print(f"Identity extraction report written to: {paths['json']}", flush=True)
    print(f"Identity extraction summary written to: {paths['markdown']}", flush=True)
    return 0 if summary["pass_rate"] >= suite["minimum_pass_rate"] else 1


def main() -> int:
    """运行 identity_profile 提取评测命令行入口。

    Returns:
        达到套件最低通过率时返回 0，否则返回 1。
    """

    parser = argparse.ArgumentParser(description="Evaluate identity extraction via /memory/prompt-evals/run.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL of the live memory service.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH), help="Path to the id extraction case suite.")
    parser.add_argument("--output-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for reports.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    parser.add_argument("--timeout-seconds", type=float, default=120.0, help="Per-request HTTP timeout.")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
