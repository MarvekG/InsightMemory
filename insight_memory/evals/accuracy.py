from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from uuid import uuid4

import httpx

from insight_memory.storage.models import MemoryRecallAudit
from insight_memory.storage.repository import MemoryRepository
from insight_memory.utils.logger import get_logger
from insight_memory.workers.schemas import AnswerJudgeOutput
from insight_memory.workers.llm_provider import llm_provider
from insight_memory.workers.prompts import get_worker_instructions


DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[2] / "evals" / "reports"
DEFAULT_RAW_DEBATE_SAMPLES_PATH = Path(__file__).resolve().parents[2] / "evals" / "raw" / "real_debate_history_samples.json"
logger = get_logger(__name__)

CRITICAL_SETTLE_TASK_TYPES = (
    "reindex_memory",
    "repair_memory_edges",
    "refresh_entity_profile",
)
PRE_QUERY_SETTLE_TASK_TYPES = ("continue_ingest",)

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(slots=True)
class EvalWriteSpec:
    """One ingest call inside an evaluation case."""

    context: str
    expected_status: str = "accepted"
    scope: str = "primary"
    concurrency_group: str | None = None


@dataclass(slots=True)
class EvalQuerySpec:
    """One recall call inside an evaluation case."""

    query_id: str
    query: str
    expected_status: str = "ok"
    expected_error_code: str | None = None
    expected_result_count: int | None = None
    scope: str = "primary"
    citations_min: int = 0
    non_empty_answer: bool = False
    required_uncertainties: list[str] = field(default_factory=list)
    required_uncertainty_prefixes: list[str] = field(default_factory=list)
    judge_required_facts: list[str] = field(default_factory=list)
    judge_forbidden_facts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalStateExpectation:
    """Expected persisted state for one memory scope."""

    entity_count: int | None = None
    memory_count: int | None = None
    observation_count: int | None = None
    recall_audit_count: int | None = None
    memory_status_counts: dict[str, int] = field(default_factory=dict)
    edge_type_counts: dict[str, int] = field(default_factory=dict)
    required_memory_texts: list[str] = field(default_factory=list)
    forbidden_memory_texts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalCase:
    """A complete accuracy evaluation case."""

    case_id: str
    category: str
    description: str
    memory_scope_templates: dict[str, str]
    writes: list[EvalWriteSpec]
    queries: list[EvalQuerySpec]
    expected: dict[str, EvalStateExpectation]
    settle_timeout_seconds: float | None = None


@dataclass(slots=True)
class EvalMatrixSuite:
    """One suite entry inside an evaluation matrix manifest."""

    suite_id: str
    cases_path: Path
    description: str = ""
    run_id: str | None = None
    settle_timeout_seconds: float | None = None


@dataclass(slots=True)
class ScopeSnapshot:
    """Materialized repository state for one memory scope."""

    memory_scope: str
    entity_count: int
    memory_count: int
    observation_count: int
    recall_audit_count: int
    pending_task_count: int
    running_task_count: int
    failed_task_count: int
    task_type_counts: dict[str, int]
    critical_pending_task_count: int
    critical_running_task_count: int
    critical_task_type_counts: dict[str, int]
    noncritical_pending_task_count: int
    noncritical_running_task_count: int
    memory_status_counts: dict[str, int]
    edge_type_counts: dict[str, int]
    memory_texts: list[str]


@dataclass(slots=True)
class QueryResult:
    """Scored result for one recall query."""

    query_id: str
    query: str
    scope: str
    response: dict[str, Any]
    audit_status: str | None
    audit_error_code: str | None
    deterministic_pass: bool
    deterministic_failures: list[str]
    judge: dict[str, Any] | None = None


@dataclass(slots=True)
class CaseResult:
    """Full result for one evaluation case."""

    case_id: str
    category: str
    description: str
    scopes: dict[str, str]
    writes: list[dict[str, Any]]
    snapshots: dict[str, dict[str, Any]]
    queries: list[dict[str, Any]]
    dimension_pass: dict[str, bool]
    failures: list[str]
    full_pass: bool


class MemoryApi(Protocol):
    """HTTP interface used by the evaluator."""

    async def health(self) -> dict[str, Any]:
        """Return service health information."""

    async def ingest(self, *, memory_scope: str, context: str) -> dict[str, Any]:
        """Send an ingest request."""

    async def recall(self, *, memory_scope: str, query: str) -> dict[str, Any]:
        """Send a recall request."""


class AnswerJudge(Protocol):
    """Semantic answer judge used by the evaluator."""

    async def judge(
        self,
        *,
        memory_space: str,
        request_id: str,
        query: str,
        required_facts: list[str],
        forbidden_facts: list[str],
        answer: str,
        citations: list[dict[str, Any]],
        uncertainties: list[str],
    ) -> dict[str, Any]:
        """Return a semantic answer judgment."""


class HttpMemoryApiClient:
    """Minimal async HTTP client for the memory service."""

    def __init__(self, *, base_url: str, timeout_seconds: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=0),
        )
        self._request_retries = 6
        self._retry_backoff_seconds = 0.5

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""

        await self._client.aclose()

    async def _send_with_retry(
        self,
        *,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        retry_enabled: bool = True,
    ) -> httpx.Response:
        """Send one HTTP request with bounded retries for transient transport failures.

        Args:
            method: HTTP method to use.
            path: Relative API path.
            json_payload: Optional JSON body.

        Returns:
            The final successful response object.

        Raises:
            httpx.HTTPError: If all retry attempts fail.
        """

        if not retry_enabled:
            response = await self._client.request(method, path, json=json_payload)
            response.raise_for_status()
            return response

        last_error: httpx.HTTPError | None = None
        for attempt in range(1, self._request_retries + 1):
            try:
                response = await self._client.request(method, path, json=json_payload)
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                is_last_attempt = attempt >= self._request_retries
                should_retry = self._should_retry_request(error=error)
                if is_last_attempt or not should_retry:
                    raise
                delay_seconds = self._retry_backoff_seconds * attempt
                logger.warning(
                    "memory eval http request failed, retrying | method=%s path=%s attempt=%s delay_seconds=%.2f error=%s",
                    method,
                    path,
                    attempt,
                    delay_seconds,
                    str(error),
                )
                await asyncio.sleep(delay_seconds)
        if last_error is not None:
            raise last_error
        raise RuntimeError("unreachable retry state")

    @staticmethod
    def _should_retry_request(*, error: httpx.HTTPError) -> bool:
        """Return whether one HTTP error is worth retrying.

        Args:
            error: The exception raised by httpx.

        Returns:
            True when the error looks transient.
        """

        if isinstance(error, httpx.TransportError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            return status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        return False

    async def health(self) -> dict[str, Any]:
        """Fetch memory service health."""

        response = await self._send_with_retry(method="GET", path="/memory/health")
        return dict(response.json())

    async def ingest(self, *, memory_scope: str, context: str) -> dict[str, Any]:
        """Call the ingest endpoint."""

        response = await self._send_with_retry(
            method="POST",
            path="/memory/ingest",
            json_payload={"memory_scope": memory_scope, "context": context},
            retry_enabled=False,
        )
        return dict(response.json())

    async def recall(self, *, memory_scope: str, query: str) -> dict[str, Any]:
        """Call the recall endpoint."""

        response = await self._send_with_retry(
            method="POST",
            path="/memory/recall",
            json_payload={"memory_scope": memory_scope, "query": query},
            retry_enabled=False,
        )
        return dict(response.json())


class LLMAnswerJudge:
    """Real-LLM answer judge built on existing memory workers."""

    async def judge(
        self,
        *,
        memory_space: str,
        request_id: str,
        query: str,
        required_facts: list[str],
        forbidden_facts: list[str],
        answer: str,
        citations: list[dict[str, Any]],
        uncertainties: list[str],
    ) -> dict[str, Any]:
        """Run the answer judge worker and return its JSON result."""

        result = await llm_provider.generate(
            worker_type="answer_judge",
            instructions=get_worker_instructions("answer_judge"),
            payload={
                "memory_space": memory_space,
                "request_id": request_id,
                "query": query,
                "required_facts": required_facts,
                "required_fact_groups": build_required_fact_groups(required_facts),
                "forbidden_facts": forbidden_facts,
                "answer": answer,
                "citations": citations,
                "uncertainties": uncertainties,
            },
            schema_type=AnswerJudgeOutput,
        )
        return result.parsed.model_dump()


def build_required_fact_groups(required_facts: list[str]) -> list[dict[str, Any]]:
    """Build structured any-of fact groups for the LLM answer judge.

    Args:
        required_facts: Raw manifest facts. A fact may contain `||` to represent acceptable variants.

    Returns:
        A list of groups where satisfying any variant in a group satisfies that required fact.
    """

    groups: list[dict[str, Any]] = []
    for index, fact in enumerate(required_facts, start=1):
        variants = [variant.strip() for variant in str(fact).split("||") if variant.strip()]
        if not variants:
            continue
        groups.append(
            {
                "group_id": f"required_fact_{index}",
                "raw": str(fact),
                "variants": variants,
                "coverage_rule": "any_variant_or_clear_semantic_equivalent",
            }
        )
    return groups


class RepositoryInspector:
    """Read-only repository inspector used by the evaluator."""

    async def wait_until_settled(
        self,
        *,
        memory_scope: str,
        task_types: tuple[str, ...] | None = None,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.5,
        quiet_seconds: float = 1.0,
    ) -> dict[str, Any]:
        """Wait until the target scope has no pending or running tasks."""

        deadline = time.monotonic() + timeout_seconds
        quiet_deadline: float | None = None
        while True:
            async with MemoryRepository() as repository:
                pending = await repository.list_tasks(
                    memory_space=memory_scope,
                    statuses=("pending", "failed"),
                    task_types=task_types,
                )
                running = await repository.list_tasks(
                    memory_space=memory_scope,
                    statuses=("running",),
                    task_types=task_types,
                )
                failed_count = len(
                    await repository.list_tasks(
                        memory_space=memory_scope,
                        statuses=("dead_letter",),
                        task_types=task_types,
                    )
                )
            if not pending and not running:
                if quiet_deadline is None:
                    quiet_deadline = time.monotonic() + quiet_seconds
                elif time.monotonic() >= quiet_deadline:
                    return {
                        "settled": True,
                        "pending_count": 0,
                        "running_count": 0,
                        "dead_letter_count": failed_count,
                    }
            else:
                quiet_deadline = None
            if time.monotonic() >= deadline:
                return {
                    "settled": False,
                    "pending_count": len(pending),
                    "running_count": len(running),
                    "dead_letter_count": failed_count,
                }
            await asyncio.sleep(poll_seconds)

    async def snapshot_scope(self, *, memory_scope: str) -> ScopeSnapshot:
        """Capture the current persisted state for one scope."""

        async with MemoryRepository() as repository:
            entities = await repository.list_all_entities(memory_space=memory_scope)
            memories = await repository.list_all_memories(memory_space=memory_scope)
            observations = await repository.list_observations(memory_space=memory_scope)
            audits = await repository.list_recall_audits(memory_space=memory_scope)
            pending_tasks = await repository.list_tasks(memory_space=memory_scope, statuses=("pending",))
            running_tasks = await repository.list_tasks(memory_space=memory_scope, statuses=("running",))
            failed_tasks = await repository.list_tasks(memory_space=memory_scope, statuses=("dead_letter",))
            edges = await repository.list_edges(memory_space=memory_scope)
        critical_pending_tasks = [task for task in pending_tasks if task.task_type in CRITICAL_SETTLE_TASK_TYPES]
        critical_running_tasks = [task for task in running_tasks if task.task_type in CRITICAL_SETTLE_TASK_TYPES]
        memory_status_counts: dict[str, int] = {}
        for memory in memories:
            memory_status_counts[memory.status] = memory_status_counts.get(memory.status, 0) + 1
        edge_type_counts: dict[str, int] = {}
        for edge in edges:
            edge_type_counts[edge.edge_type] = edge_type_counts.get(edge.edge_type, 0) + 1
        task_type_counts: dict[str, int] = {}
        for task in [*pending_tasks, *running_tasks, *failed_tasks]:
            task_type_counts[task.task_type] = task_type_counts.get(task.task_type, 0) + 1
        critical_task_type_counts: dict[str, int] = {}
        for task in [*critical_pending_tasks, *critical_running_tasks]:
            critical_task_type_counts[task.task_type] = critical_task_type_counts.get(task.task_type, 0) + 1
        memory_texts = [
            " ".join(part for part in (memory.title, memory.summary, memory.content) if part).strip()
            for memory in memories
        ]
        return ScopeSnapshot(
            memory_scope=memory_scope,
            entity_count=len(entities),
            memory_count=len(memories),
            observation_count=len(observations),
            recall_audit_count=len(audits),
            pending_task_count=len(pending_tasks),
            running_task_count=len(running_tasks),
            failed_task_count=len(failed_tasks),
            task_type_counts=task_type_counts,
            critical_pending_task_count=len(critical_pending_tasks),
            critical_running_task_count=len(critical_running_tasks),
            critical_task_type_counts=critical_task_type_counts,
            noncritical_pending_task_count=len(pending_tasks) - len(critical_pending_tasks),
            noncritical_running_task_count=len(running_tasks) - len(critical_running_tasks),
            memory_status_counts=memory_status_counts,
            edge_type_counts=edge_type_counts,
            memory_texts=memory_texts,
        )

    async def latest_recall_audit(self, *, memory_scope: str, query: str) -> MemoryRecallAudit | None:
        """Return the latest recall audit for the given query."""

        async with MemoryRepository() as repository:
            audits = await repository.list_recall_audits(memory_space=memory_scope, query=query)
        if not audits:
            return None
        return audits[-1]


class AccuracyEvaluator:
    """Run the generic memory accuracy suite against a live memory service."""

    def __init__(
        self,
        *,
        api: MemoryApi,
        inspector: RepositoryInspector,
        judge: AnswerJudge,
    ) -> None:
        self._api = api
        self._inspector = inspector
        self._judge = judge

    async def evaluate_cases(
        self,
        *,
        cases: list[EvalCase],
        run_id: str,
        settle_timeout_seconds: float = 30.0,
        progress_callback: ProgressCallback | None = None,
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        """Evaluate all cases and return a JSON-serializable report."""

        health = await self._api.health()
        if health.get("status") != "ok":
            raise RuntimeError(f"memory service health check failed: {health}")
        if health.get("llm") != "configured":
            raise RuntimeError("memory service is not configured with a real LLM")
        execution_id = build_execution_id()
        logger.info(
            "accuracy eval started",
            extra={
                "run_id": run_id,
                "execution_id": execution_id,
                "case_count": len(cases),
                "health": health,
            },
        )
        await _emit_eval_event(
            event_callback,
            {
                "event": "evaluation_started",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_count": len(cases),
                "health": health,
            },
        )
        case_results = []
        for case in cases:
            logger.info(
                "accuracy eval case started",
                extra={
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "category": case.category,
                },
            )
            await _emit_eval_event(
                event_callback,
                {
                    "event": "case_started",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "category": case.category,
                    "description": case.description,
                },
            )
            case_results.append(
                await self._evaluate_case(
                    case=case,
                    run_id=run_id,
                    execution_id=execution_id,
                    settle_timeout_seconds=settle_timeout_seconds,
                    event_callback=event_callback,
                )
            )
            if progress_callback is not None:
                partial_report = build_accuracy_report(
                    run_id=run_id,
                    execution_id=execution_id,
                    health=health,
                    case_results=case_results,
                    status="in_progress",
                    total_case_count=len(cases),
                )
                callback_result = progress_callback(partial_report)
                if asyncio.iscoroutine(callback_result):
                    await callback_result
        summary = summarize_case_results(case_results)
        logger.info(
            "accuracy eval completed",
            extra={
                "run_id": run_id,
                "execution_id": execution_id,
                "summary": summary,
            },
        )
        await _emit_eval_event(
            event_callback,
            {
                "event": "evaluation_completed",
                "run_id": run_id,
                "execution_id": execution_id,
                "summary": summary,
            },
        )
        return build_accuracy_report(
            run_id=run_id,
            execution_id=execution_id,
            health=health,
            case_results=case_results,
            status="completed",
            total_case_count=len(cases),
        )

    async def _evaluate_case(
        self,
        *,
        case: EvalCase,
        run_id: str,
        execution_id: str,
        settle_timeout_seconds: float,
        event_callback: EventCallback | None = None,
    ) -> dict[str, Any]:
        effective_settle_timeout_seconds = float(case.settle_timeout_seconds or settle_timeout_seconds)
        scopes = {
            alias: render_memory_scope(
                template,
                run_id=run_id,
                execution_id=execution_id,
                case_id=case.case_id,
                scope_alias=alias,
            )
            for alias, template in case.memory_scope_templates.items()
        }
        write_results: list[dict[str, Any]] = []
        ingest_gate_pass = True
        failures: list[str] = []

        next_index = 1
        while next_index <= len(case.writes):
            current = case.writes[next_index - 1]
            if current.concurrency_group:
                batch: list[tuple[int, EvalWriteSpec]] = []
                group = current.concurrency_group
                while next_index <= len(case.writes):
                    candidate = case.writes[next_index - 1]
                    if candidate.concurrency_group != group:
                        break
                    batch.append((next_index, candidate))
                    next_index += 1
                batch_results = await asyncio.gather(
                    *[
                        self._execute_write(
                            case=case,
                            write=write,
                            write_index=write_index,
                            scopes=scopes,
                            run_id=run_id,
                            execution_id=execution_id,
                            event_callback=event_callback,
                        )
                        for write_index, write in batch
                    ]
                )
            else:
                batch_results = [
                    await self._execute_write(
                        case=case,
                        write=current,
                        write_index=next_index,
                        scopes=scopes,
                        run_id=run_id,
                        execution_id=execution_id,
                        event_callback=event_callback,
                    )
                ]
                next_index += 1
            for item in sorted(batch_results, key=lambda result: int(result["write_index"])):
                actual_status = str(item["response"].get("status") or "")
                if not item["passed"]:
                    ingest_gate_pass = False
                    failures.append(
                        f"{case.case_id}: write[{item['write_index']}] expected {item['expected_status']}, got {actual_status}"
                    )
                write_results.append(
                    {
                        "scope": item["scope"],
                        "context": item["context"],
                        "expected_status": item["expected_status"],
                        "response": item["response"],
                        "passed": item["passed"],
                        "concurrency_group": item["concurrency_group"],
                    }
                )

        semantic_settle_results: dict[str, dict[str, Any]] = {}
        for alias, memory_scope in scopes.items():
            await _emit_eval_event(
                event_callback,
                {
                    "event": "settle_started",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle_phase": "pre_query_semantic",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                },
            )
            semantic_settle = await self._inspector.wait_until_settled(
                memory_scope=memory_scope,
                task_types=PRE_QUERY_SETTLE_TASK_TYPES,
                timeout_seconds=effective_settle_timeout_seconds,
            )
            semantic_settle_results[alias] = semantic_settle
            logger.info(
                "accuracy eval scope settled",
                extra={
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle": semantic_settle,
                    "settle_phase": "pre_query_semantic",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                },
            )
            await _emit_eval_event(
                event_callback,
                {
                    "event": "settle_completed",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle_phase": "pre_query_semantic",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                    "settle": semantic_settle,
                },
            )

        query_results: list[dict[str, Any]] = []
        query_gate_pass = True
        recall_structured_pass = True
        answer_judge_pass = True
        for query_spec in case.queries:
            await _emit_eval_event(
                event_callback,
                {
                    "event": "query_started",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "query_id": query_spec.query_id,
                    "scope_alias": query_spec.scope,
                    "memory_scope": scopes[query_spec.scope],
                    "query": query_spec.query,
                    "expected_status": query_spec.expected_status,
                },
            )
            query_result = await self._evaluate_query(
                case=case,
                query_spec=query_spec,
                memory_scope=scopes[query_spec.scope],
                run_id=run_id,
            )
            query_results.append(asdict(query_result))
            if query_result.response.get("status") != query_spec.expected_status:
                query_gate_pass = False
            if not query_result.deterministic_pass:
                recall_structured_pass = False
                failures.extend(query_result.deterministic_failures)
            judge_payload = query_result.judge or {}
            if query_spec.expected_status == "ok":
                if query_result.judge is None:
                    answer_judge_pass = False
                elif judge_payload.get("verdict") != "pass" or not judge_payload.get("grounded", False):
                    answer_judge_pass = False
                    failures.append(
                        f"{case.case_id}:{query_spec.query_id} answer_judge={judge_payload}"
                    )
            logger.info(
                "accuracy eval query completed",
                extra={
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "query_id": query_spec.query_id,
                    "memory_scope": scopes[query_spec.scope],
                    "status": query_result.response.get("status"),
                    "error_code": query_result.response.get("error_code"),
                    "deterministic_pass": query_result.deterministic_pass,
                    "judge": query_result.judge,
                },
            )
            await _emit_eval_event(
                event_callback,
                {
                    "event": "query_completed",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "query_id": query_spec.query_id,
                    "scope_alias": query_spec.scope,
                    "memory_scope": scopes[query_spec.scope],
                    "status": query_result.response.get("status"),
                    "error_code": query_result.response.get("error_code"),
                    "deterministic_pass": query_result.deterministic_pass,
                    "judge": query_result.judge,
                    "response": query_result.response,
                },
            )

        settle_results: dict[str, dict[str, Any]] = {}
        settle_failures: list[str] = []
        for alias, memory_scope in scopes.items():
            await _emit_eval_event(
                event_callback,
                {
                    "event": "settle_started",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle_phase": "post_query_full",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                },
            )
            settle = await self._inspector.wait_until_settled(
                memory_scope=memory_scope,
                task_types=CRITICAL_SETTLE_TASK_TYPES,
                timeout_seconds=effective_settle_timeout_seconds,
            )
            settle_results[alias] = settle
            if not settle.get("settled", False):
                settle_failures.append(f"{case.case_id}: scope {alias} did not settle in time")
            logger.info(
                "accuracy eval scope settled",
                extra={
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle": settle,
                    "settle_phase": "post_query_full",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                },
            )
            await _emit_eval_event(
                event_callback,
                {
                    "event": "settle_completed",
                    "run_id": run_id,
                    "execution_id": execution_id,
                    "case_id": case.case_id,
                    "scope_alias": alias,
                    "memory_scope": memory_scope,
                    "settle_phase": "post_query_full",
                    "settle_timeout_seconds": effective_settle_timeout_seconds,
                    "settle": settle,
                },
            )

        await _emit_eval_event(
            event_callback,
            {
                "event": "snapshot_started",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "scope_aliases": list(scopes.keys()),
            },
        )
        snapshots = {
            alias: _to_mapping(await self._inspector.snapshot_scope(memory_scope=memory_scope))
            for alias, memory_scope in scopes.items()
        }
        await _emit_eval_event(
            event_callback,
            {
                "event": "snapshot_completed",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "snapshots": snapshots,
            },
        )
        state_pass, state_failures = grade_case_state(case=case, snapshots=snapshots)
        failures.extend(state_failures)

        dimension_pass = {
            "ingest_gate": ingest_gate_pass,
            "state": state_pass,
            "query_gate": query_gate_pass,
            "recall_structured": recall_structured_pass,
            "answer_judge": answer_judge_pass,
            "background_tasks": _background_tasks_settled(
                settle_results=settle_results,
                snapshots=snapshots,
            ),
        }
        if not dimension_pass["background_tasks"]:
            failures.extend(settle_failures)
        full_pass = all(dimension_pass.values())
        logger.info(
            "accuracy eval case completed",
            extra={
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "dimension_pass": dimension_pass,
                "failure_count": len(failures),
                "full_pass": full_pass,
            },
        )
        await _emit_eval_event(
            event_callback,
            {
                "event": "case_completed",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "dimension_pass": dimension_pass,
                "failure_count": len(failures),
                "failures": failures,
                "full_pass": full_pass,
            },
        )
        return asdict(
            CaseResult(
                case_id=case.case_id,
                category=case.category,
                description=case.description,
                scopes=scopes,
                writes=write_results,
                snapshots=snapshots,
                queries=query_results,
                dimension_pass=dimension_pass,
                failures=failures,
                full_pass=full_pass,
            )
        )

    async def _evaluate_query(
        self,
        *,
        case: EvalCase,
        query_spec: EvalQuerySpec,
        memory_scope: str,
        run_id: str,
    ) -> QueryResult:
        raw_response = await self._api.recall(memory_scope=memory_scope, query=query_spec.query)
        raw_results = [dict(item) for item in raw_response["results"]]
        response = dict(raw_results[0])
        audit = await self._inspector.latest_recall_audit(
            memory_scope=memory_scope,
            query=query_spec.query,
        )
        deterministic_pass, deterministic_failures = grade_query_response(
            response=response,
            query_spec=query_spec,
            audit=audit,
        )
        count_pass, count_failures = grade_recall_result_count(
            results=raw_results,
            query_spec=query_spec,
        )
        deterministic_pass = deterministic_pass and count_pass
        deterministic_failures.extend(count_failures)
        judge_result: dict[str, Any] | None = None
        if query_spec.expected_status == "ok" and response.get("status") == "ok":
            judge_answer = str(response.get("answer") or "")
            judge_citations = list(response.get("citations") or [])
            judge_uncertainties = list(response.get("uncertainties") or [])
            if query_spec.expected_result_count is not None:
                judge_answer = "\n".join(
                    str(item.get("answer") or "").strip()
                    for item in raw_results
                    if str(item.get("answer") or "").strip()
                )
                judge_citations = [
                    dict(citation)
                    for item in raw_results
                    for citation in list(item.get("citations") or [])
                    if isinstance(citation, dict)
                ]
                judge_uncertainties = [
                    str(uncertainty)
                    for item in raw_results
                    for uncertainty in list(item.get("uncertainties") or [])
                    if str(uncertainty).strip()
                ]
            judge_result = await self._judge.judge(
                memory_space=memory_scope,
                request_id=uuid4().hex,
                query=query_spec.query,
                required_facts=query_spec.judge_required_facts,
                forbidden_facts=query_spec.judge_forbidden_facts,
                answer=judge_answer,
                citations=judge_citations,
                uncertainties=judge_uncertainties,
            )
        logger.info(
            "accuracy eval query judged",
            extra={
                "run_id": run_id,
                "case_id": case.case_id,
                "query_id": query_spec.query_id,
                "memory_scope": memory_scope,
                "audit_status": audit.status if audit is not None else None,
                "audit_error_code": audit.error_code if audit is not None else None,
                "deterministic_pass": deterministic_pass,
                "judge": judge_result,
            },
        )
        return QueryResult(
            query_id=query_spec.query_id,
            query=query_spec.query,
            scope=query_spec.scope,
            response=response,
            audit_status=audit.status if audit is not None else None,
            audit_error_code=audit.error_code if audit is not None else None,
            deterministic_pass=deterministic_pass,
            deterministic_failures=deterministic_failures,
            judge=judge_result,
        )

    async def _execute_write(
        self,
        *,
        case: EvalCase,
        write: EvalWriteSpec,
        write_index: int,
        scopes: dict[str, str],
        run_id: str,
        execution_id: str,
        event_callback: EventCallback | None,
    ) -> dict[str, Any]:
        """Execute one ingest write and return the normalized result."""

        await _emit_eval_event(
            event_callback,
            {
                "event": "write_started",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "write_index": write_index,
                "scope_alias": write.scope,
                "memory_scope": scopes[write.scope],
                "expected_status": write.expected_status,
                "context": write.context,
                "concurrency_group": write.concurrency_group,
            },
        )
        response = await self._api.ingest(
            memory_scope=scopes[write.scope],
            context=write.context,
        )
        actual_status = str(response.get("status") or "")
        passed = actual_status == write.expected_status
        logger.info(
            "accuracy eval write completed",
            extra={
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "write_index": write_index,
                "scope_alias": write.scope,
                "memory_scope": scopes[write.scope],
                "expected_status": write.expected_status,
                "actual_status": actual_status,
                "passed": passed,
                "concurrency_group": write.concurrency_group,
            },
        )
        await _emit_eval_event(
            event_callback,
            {
                "event": "write_completed",
                "run_id": run_id,
                "execution_id": execution_id,
                "case_id": case.case_id,
                "write_index": write_index,
                "scope_alias": write.scope,
                "memory_scope": scopes[write.scope],
                "expected_status": write.expected_status,
                "actual_status": actual_status,
                "passed": passed,
                "response": response,
                "concurrency_group": write.concurrency_group,
            },
        )
        return {
            "write_index": write_index,
            "scope": write.scope,
            "context": write.context,
            "expected_status": write.expected_status,
            "response": response,
            "passed": passed,
            "concurrency_group": write.concurrency_group,
        }


def load_eval_cases(path: Path) -> list[EvalCase]:
    """Load the JSON case corpus."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Evaluation case file must be a JSON list")
    raw_debate_samples = _load_raw_debate_samples()
    cases: list[EvalCase] = []
    for item in raw:
        memory_scope_templates = dict(item.get("memory_scope_templates") or {})
        if "primary" not in memory_scope_templates:
            raise ValueError(f"Case {item.get('case_id')} is missing primary memory_scope_templates")
        cases.append(
            EvalCase(
                case_id=str(item["case_id"]),
                category=str(item["category"]),
                description=str(item["description"]),
                memory_scope_templates=memory_scope_templates,
                writes=[
                    EvalWriteSpec(
                        context=_resolve_write_context(
                            write=write,
                            raw_debate_samples=raw_debate_samples,
                        ),
                        expected_status=str(write.get("expected_status") or "accepted"),
                        scope=str(write.get("scope") or "primary"),
                        concurrency_group=str(write.get("concurrency_group") or "").strip() or None,
                    )
                    for write in list(item.get("writes") or [])
                ],
                queries=[
                    EvalQuerySpec(
                        query_id=str(query["query_id"]),
                        query=str(query["query"]),
                        expected_status=str(query.get("expected_status") or "ok"),
                        expected_error_code=query.get("expected_error_code"),
                        expected_result_count=(
                            int(query["expected_result_count"])
                            if query.get("expected_result_count") is not None
                            else None
                        ),
                        scope=str(query.get("scope") or "primary"),
                        citations_min=int(query.get("citations_min") or 0),
                        non_empty_answer=bool(query.get("non_empty_answer") or False),
                        required_uncertainties=[str(item) for item in list(query.get("required_uncertainties") or [])],
                        required_uncertainty_prefixes=[
                            str(item) for item in list(query.get("required_uncertainty_prefixes") or [])
                        ],
                        judge_required_facts=[str(item) for item in list(query.get("judge_required_facts") or [])],
                        judge_forbidden_facts=[str(item) for item in list(query.get("judge_forbidden_facts") or [])],
                    )
                    for query in list(item.get("queries") or [])
                ],
                expected={
                    str(scope_alias): EvalStateExpectation(
                        entity_count=scope_expectation.get("entity_count"),
                        memory_count=scope_expectation.get("memory_count"),
                        observation_count=scope_expectation.get("observation_count"),
                        recall_audit_count=scope_expectation.get("recall_audit_count"),
                        memory_status_counts={
                            str(key): int(value)
                            for key, value in dict(scope_expectation.get("memory_status_counts") or {}).items()
                        },
                        edge_type_counts={
                            str(key): int(value)
                            for key, value in dict(scope_expectation.get("edge_type_counts") or {}).items()
                        },
                        required_memory_texts=[str(value) for value in list(scope_expectation.get("required_memory_texts") or [])],
                        forbidden_memory_texts=[str(value) for value in list(scope_expectation.get("forbidden_memory_texts") or [])],
                    )
                    for scope_alias, scope_expectation in dict(item.get("expected") or {}).items()
                },
                settle_timeout_seconds=(
                    None
                    if item.get("settle_timeout_seconds") is None
                    else float(item.get("settle_timeout_seconds"))
                ),
            )
        )
    return cases


def load_eval_matrix(path: Path) -> dict[str, Any]:
    """Load an evaluation matrix manifest with suite metadata."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Evaluation matrix file must be a JSON object")
    matrix_id = str(raw.get("matrix_id") or "").strip()
    if not matrix_id:
        raise ValueError("Evaluation matrix file must define matrix_id")
    suites_raw = list(raw.get("suites") or [])
    if not suites_raw:
        raise ValueError("Evaluation matrix file must define at least one suite")
    suites: list[EvalMatrixSuite] = []
    for item in suites_raw:
        if not isinstance(item, dict):
            raise ValueError("Each suite entry must be a JSON object")
        suite_id = str(item.get("suite_id") or "").strip()
        if not suite_id:
            raise ValueError("Each suite entry must define suite_id")
        cases_value = str(item.get("cases") or "").strip()
        if not cases_value:
            raise ValueError(f"Suite {suite_id} must define cases")
        cases_path = Path(cases_value)
        if not cases_path.is_absolute():
            cases_path = (path.parent / cases_path).resolve()
        suites.append(
            EvalMatrixSuite(
                suite_id=suite_id,
                cases_path=cases_path,
                description=str(item.get("description") or ""),
                run_id=str(item.get("run_id") or "").strip() or None,
                settle_timeout_seconds=(
                    None
                    if item.get("settle_timeout_seconds") is None
                    else float(item.get("settle_timeout_seconds"))
                ),
            )
        )
    return {
        "matrix_id": matrix_id,
        "description": str(raw.get("description") or ""),
        "suites": suites,
    }


def build_execution_id() -> str:
    """Build a unique execution id for one evaluation run."""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


async def _emit_eval_event(
    callback: EventCallback | None,
    payload: dict[str, Any],
) -> None:
    """Emit one structured evaluator event to an optional callback."""

    if callback is None:
        return
    callback_result = callback(payload)
    if asyncio.iscoroutine(callback_result):
        await callback_result


def _load_raw_debate_samples() -> dict[str, dict[str, Any]]:
    """Load captured real debate history samples keyed by message id."""

    if not DEFAULT_RAW_DEBATE_SAMPLES_PATH.exists():
        return {}
    raw = json.loads(DEFAULT_RAW_DEBATE_SAMPLES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Raw debate sample file must be a JSON list")
    return {
        str(item["message_id"]): dict(item)
        for item in raw
        if isinstance(item, dict) and item.get("message_id")
    }


def _resolve_write_context(
    *,
    write: dict[str, Any],
    raw_debate_samples: dict[str, dict[str, Any]],
) -> str:
    """Resolve one write context from inline text or a captured raw debate sample."""

    if write.get("context"):
        return str(write["context"])
    raw_sample_id = str(write.get("raw_sample_id") or "").strip()
    if not raw_sample_id:
        raise ValueError("Each write must provide either context or raw_sample_id")
    sample = raw_debate_samples.get(raw_sample_id)
    if sample is None:
        raise ValueError(f"raw debate sample not found: {raw_sample_id}")
    return _build_debate_context_from_raw_sample(sample)


def _build_debate_context_from_raw_sample(sample: dict[str, Any]) -> str:
    """Render one captured real debate sample into ingest context text."""

    stock_code = str(sample.get("stock_code") or "").strip()
    session_id = str(sample.get("session_id") or "").strip()
    stage = str(sample.get("stage") or "").strip()
    round_number = str(sample.get("round_number") or "").strip()
    agent_name = str(sample.get("agent_name") or "").strip()
    agent_role = str(sample.get("agent_role") or "").strip()
    body = str(sample.get("analysis_report_markdown") or sample.get("reasoning") or "").strip()
    parts = [
        f"Historical debate record for {stock_code}.",
        f"Session: {session_id}",
        f"Stage: {stage}",
        f"Round: {round_number}",
        f"Agent: {agent_name} ({agent_role})",
    ]
    if body:
        parts.append(body)
    return "\n".join(parts)


def render_memory_scope(
    template: str,
    *,
    run_id: str,
    execution_id: str,
    case_id: str,
    scope_alias: str,
) -> str:
    """Expand one memory scope template."""

    rendered = template.format(
        run_id=run_id,
        execution_id=execution_id,
        case_id=case_id,
        scope_alias=scope_alias,
    )
    if "{execution_id}" in template:
        return rendered
    return f"{rendered}:exec:{execution_id}"


def grade_case_state(*, case: EvalCase, snapshots: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    """Grade persisted state expectations for one case."""

    failures: list[str] = []
    for scope_alias, expectation in case.expected.items():
        snapshot = snapshots.get(scope_alias)
        if snapshot is None:
            failures.append(f"{case.case_id}: missing snapshot for scope {scope_alias}")
            continue
        if expectation.entity_count is not None and snapshot["entity_count"] != expectation.entity_count:
            failures.append(
                f"{case.case_id}:{scope_alias} entity_count expected {expectation.entity_count}, got {snapshot['entity_count']}"
            )
        if expectation.memory_count is not None and snapshot["memory_count"] != expectation.memory_count:
            failures.append(
                f"{case.case_id}:{scope_alias} memory_count expected {expectation.memory_count}, got {snapshot['memory_count']}"
            )
        if expectation.observation_count is not None and snapshot["observation_count"] != expectation.observation_count:
            failures.append(
                f"{case.case_id}:{scope_alias} observation_count expected {expectation.observation_count}, got {snapshot['observation_count']}"
            )
        if expectation.recall_audit_count is not None and snapshot["recall_audit_count"] != expectation.recall_audit_count:
            failures.append(
                f"{case.case_id}:{scope_alias} recall_audit_count expected {expectation.recall_audit_count}, got {snapshot['recall_audit_count']}"
            )
        for status, expected_count in expectation.memory_status_counts.items():
            actual = int(snapshot["memory_status_counts"].get(status) or 0)
            if actual != expected_count:
                failures.append(
                    f"{case.case_id}:{scope_alias} memory_status[{status}] expected {expected_count}, got {actual}"
                )
        for edge_type, expected_count in expectation.edge_type_counts.items():
            actual = int(snapshot["edge_type_counts"].get(edge_type) or 0)
            if actual != expected_count:
                failures.append(
                    f"{case.case_id}:{scope_alias} edge_type[{edge_type}] expected {expected_count}, got {actual}"
                )
        memory_blob = "\n".join(snapshot["memory_texts"])
        for required_text in expectation.required_memory_texts:
            if required_text not in memory_blob:
                failures.append(f"{case.case_id}:{scope_alias} missing memory text `{required_text}`")
        for forbidden_text in expectation.forbidden_memory_texts:
            if forbidden_text and forbidden_text in memory_blob:
                failures.append(f"{case.case_id}:{scope_alias} forbidden memory text `{forbidden_text}` present")
        if snapshot.get("failed_task_count", 0) > 0:
            failures.append(f"{case.case_id}:{scope_alias} has dead_letter tasks")
    return not failures, failures


def grade_recall_result_count(
    *,
    results: list[dict[str, Any]],
    query_spec: EvalQuerySpec,
) -> tuple[bool, list[str]]:
    """Grade optional multi-result recall expectations.

    Args:
        results: Raw result items from the recall response.
        query_spec: Evaluation query expectation.

    Returns:
        Whether the result-count check passed and the associated failure messages.
    """

    if query_spec.expected_result_count is None:
        return True, []

    failures: list[str] = []
    if len(results) != query_spec.expected_result_count:
        failures.append(
            f"{query_spec.query_id} expected {query_spec.expected_result_count} recall results, got {len(results)}"
        )
    for index, item in enumerate(results, start=1):
        actual_status = str(item.get("status") or "")
        if actual_status != query_spec.expected_status:
            failures.append(
                f"{query_spec.query_id} result[{index}] expected status "
                f"{query_spec.expected_status}, got {actual_status}"
            )
    return not failures, failures


def grade_query_response(
    *,
    response: dict[str, Any],
    query_spec: EvalQuerySpec,
    audit: MemoryRecallAudit | None,
) -> tuple[bool, list[str]]:
    """Grade one recall response without using LLM semantics."""

    failures: list[str] = []
    actual_status = str(response.get("status") or "")
    if actual_status != query_spec.expected_status:
        failures.append(
            f"{query_spec.query_id} expected status {query_spec.expected_status}, got {actual_status}"
        )
    actual_error_code = response.get("error_code")
    if query_spec.expected_error_code != actual_error_code:
        failures.append(
            f"{query_spec.query_id} expected error_code {query_spec.expected_error_code}, got {actual_error_code}"
        )
    if query_spec.non_empty_answer and not str(response.get("answer") or "").strip():
        failures.append(f"{query_spec.query_id} expected non-empty answer")
    if len(list(response.get("citations") or [])) < query_spec.citations_min:
        failures.append(f"{query_spec.query_id} citations below minimum")
    uncertainties = list(response.get("uncertainties") or [])
    for item in query_spec.required_uncertainties:
        if item not in uncertainties:
            failures.append(f"{query_spec.query_id} missing uncertainty `{item}`")
    for prefix in query_spec.required_uncertainty_prefixes:
        if not any(str(item).startswith(prefix) for item in uncertainties):
            failures.append(f"{query_spec.query_id} missing uncertainty prefix `{prefix}`")
    if audit is None:
        failures.append(f"{query_spec.query_id} missing recall audit")
    else:
        if audit.status != actual_status:
            failures.append(f"{query_spec.query_id} audit status mismatch")
        if audit.error_code != actual_error_code:
            failures.append(f"{query_spec.query_id} audit error_code mismatch")
    return not failures, failures


def summarize_case_results(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case results into summary metrics."""

    dimension_totals: dict[str, int] = {}
    dimension_passes: dict[str, int] = {}
    category_totals: dict[str, int] = {}
    category_passes: dict[str, int] = {}
    answer_judge_counts = {"pass": 0, "partial": 0, "fail": 0}
    answer_grounded_true = 0
    total_queries = 0
    full_pass_count = 0
    failure_index: dict[str, list[str]] = {}

    for case in case_results:
        category = str(case["category"])
        category_totals[category] = category_totals.get(category, 0) + 1
        if case.get("full_pass"):
            full_pass_count += 1
            category_passes[category] = category_passes.get(category, 0) + 1
        for dimension, passed in dict(case.get("dimension_pass") or {}).items():
            dimension_totals[dimension] = dimension_totals.get(dimension, 0) + 1
            if passed:
                dimension_passes[dimension] = dimension_passes.get(dimension, 0) + 1
        for query in list(case.get("queries") or []):
            judge = dict(query.get("judge") or {})
            verdict = str(judge.get("verdict") or "").strip()
            if verdict in answer_judge_counts:
                answer_judge_counts[verdict] += 1
                total_queries += 1
                if bool(judge.get("grounded")):
                    answer_grounded_true += 1
        for failure in list(case.get("failures") or []):
            root = failure.split(":", 1)[0]
            failure_index.setdefault(root, []).append(failure)

    total_cases = len(case_results)
    return {
        "total_cases": total_cases,
        "full_pass_count": full_pass_count,
        "full_pass_rate": round(full_pass_count / total_cases, 4) if total_cases else 0.0,
        "dimension_pass_rates": {
            key: round(dimension_passes.get(key, 0) / total, 4) if total else 0.0
            for key, total in dimension_totals.items()
        },
        "category_pass_rates": {
            key: round(category_passes.get(key, 0) / total, 4) if total else 0.0
            for key, total in category_totals.items()
        },
        "answer_judge_counts": answer_judge_counts,
        "answer_grounded_rate": round(answer_grounded_true / total_queries, 4) if total_queries else 0.0,
        "failure_index": failure_index,
    }


def build_accuracy_report(
    *,
    run_id: str,
    execution_id: str,
    health: dict[str, Any],
    case_results: list[dict[str, Any]],
    status: str,
    total_case_count: int,
) -> dict[str, Any]:
    """Build a JSON-serializable accuracy report from current case results."""

    summary = summarize_case_results(case_results)
    return {
        "run_id": run_id,
        "execution_id": execution_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "health": health,
        "status": status,
        "completed_case_count": len(case_results),
        "expected_total_case_count": total_case_count,
        "summary": summary,
        "cases": case_results,
    }


def summarize_matrix_reports(suite_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple suite reports into one matrix summary."""

    total_suites = len(suite_reports)
    total_cases = 0
    full_pass_count = 0
    total_queries = 0
    answer_grounded_true = 0
    failing_suites: list[str] = []
    suite_pass_rates: dict[str, float] = {}

    for suite in suite_reports:
        suite_id = str(suite["suite_id"])
        summary = dict(suite.get("summary") or {})
        total_cases += int(summary.get("total_cases") or 0)
        full_pass_count += int(summary.get("full_pass_count") or 0)
        for case in list(suite.get("cases") or []):
            for query in list(case.get("queries") or []):
                judge = dict(query.get("judge") or {})
                verdict = str(judge.get("verdict") or "").strip()
                if verdict in {"pass", "partial", "fail"}:
                    total_queries += 1
                    if bool(judge.get("grounded")):
                        answer_grounded_true += 1
        suite_pass_rates[suite_id] = float(summary.get("full_pass_rate") or 0.0)
        if float(summary.get("full_pass_rate") or 0.0) < 1.0:
            failing_suites.append(suite_id)

    return {
        "total_suites": total_suites,
        "total_cases": total_cases,
        "full_pass_count": full_pass_count,
        "full_pass_rate": round(full_pass_count / total_cases, 4) if total_cases else 0.0,
        "answer_grounded_rate": round(answer_grounded_true / total_queries, 4) if total_queries else 0.0,
        "suite_pass_rates": suite_pass_rates,
        "failing_suites": failing_suites,
    }


def render_matrix_markdown_report(report: dict[str, Any]) -> str:
    """Render a compact Markdown summary for a suite matrix run."""

    summary = dict(report.get("summary") or {})
    lines = [
        "# Memory Accuracy Matrix",
        "",
        f"- matrix_id: `{report.get('matrix_id')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- total_suites: `{summary.get('total_suites', 0)}`",
        f"- total_cases: `{summary.get('total_cases', 0)}`",
        f"- full_pass_rate: `{summary.get('full_pass_rate', 0.0)}`",
        f"- answer_grounded_rate: `{summary.get('answer_grounded_rate', 0.0)}`",
        "",
        "## Suites",
    ]
    for suite in list(report.get("suites") or []):
        suite_summary = dict(suite.get("summary") or {})
        lines.append(
            "- "
            f"`{suite.get('suite_id')}`: "
            f"{suite_summary.get('full_pass_count', 0)}/{suite_summary.get('total_cases', 0)} "
            f"(rate={suite_summary.get('full_pass_rate', 0.0)})"
        )
    lines.extend(["", "## Failing Suites"])
    failing_suites = list(summary.get("failing_suites") or [])
    if not failing_suites:
        lines.append("- none")
    else:
        for suite_id in failing_suites:
            suite = next((item for item in list(report.get("suites") or []) if item.get("suite_id") == suite_id), None)
            failures = []
            if suite is not None:
                for case in list(suite.get("failing_cases") or []):
                    failures.append(f"`{case['case_id']}`")
            lines.append(f"- `{suite_id}`: {', '.join(failures) if failures else 'see suite report'}")
    return "\n".join(lines) + "\n"


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a compact Markdown summary."""

    summary = dict(report.get("summary") or {})
    lines = [
        "# Memory Accuracy Evaluation",
        "",
        f"- run_id: `{report.get('run_id')}`",
        f"- execution_id: `{report.get('execution_id')}`",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- total_cases: `{summary.get('total_cases', 0)}`",
        f"- full_pass_rate: `{summary.get('full_pass_rate', 0.0)}`",
        f"- answer_grounded_rate: `{summary.get('answer_grounded_rate', 0.0)}`",
        "",
        "## Dimension Pass Rates",
    ]
    for key, value in sorted(dict(summary.get("dimension_pass_rates") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Category Pass Rates"])
    for key, value in sorted(dict(summary.get("category_pass_rates") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Failing Cases"])
    failing_cases = [case for case in list(report.get("cases") or []) if not case.get("full_pass")]
    if not failing_cases:
        lines.append("- none")
    else:
        for case in failing_cases:
            lines.append(f"- `{case['case_id']}`: {'; '.join(case.get('failures') or [])}")
    return "\n".join(lines) + "\n"


def _to_mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    instance_vars = dict(vars(value))
    if instance_vars:
        return instance_vars
    field_names = (
        "memory_scope",
        "entity_count",
        "memory_count",
        "observation_count",
        "recall_audit_count",
        "pending_task_count",
        "running_task_count",
        "failed_task_count",
        "task_type_counts",
        "critical_pending_task_count",
        "critical_running_task_count",
        "critical_task_type_counts",
        "noncritical_pending_task_count",
        "noncritical_running_task_count",
        "memory_status_counts",
        "edge_type_counts",
        "memory_texts",
    )
    return {
        field_name: getattr(value, field_name)
        for field_name in field_names
        if hasattr(value, field_name)
    }


def _background_tasks_settled(
    *,
    settle_results: dict[str, dict[str, Any]],
    snapshots: dict[str, dict[str, Any]],
) -> bool:
    """Return whether background tasks can be treated as settled.

    Args:
        settle_results: Settle probe results keyed by scope alias.
        snapshots: Final snapshots keyed by scope alias.

    Returns:
        ``True`` when every scope either explicitly settled during the wait
        window or the final snapshot shows no pending/running tasks.
    """
    for alias, settle in settle_results.items():
        if settle.get("settled", False):
            continue
        snapshot = snapshots.get(alias, {})
        critical_pending_task_count = int(snapshot.get("critical_pending_task_count", 0) or 0)
        critical_running_task_count = int(snapshot.get("critical_running_task_count", 0) or 0)
        if critical_pending_task_count == 0 and critical_running_task_count == 0:
            continue
        return False
    return True


def write_report_files(*, report: dict[str, Any], output_dir: Path | None = None) -> dict[str, Path]:
    """Write timestamped JSON and Markdown reports plus latest copies."""

    target_dir = output_dir or DEFAULT_REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(report["run_id"])
    execution_id = str(report.get("execution_id") or run_id)
    file_stem = f"{run_id}__{execution_id}"
    json_path = target_dir / f"{file_stem}.json"
    md_path = target_dir / f"{file_stem}.md"
    latest_json = target_dir / "latest.json"
    latest_md = target_dir / "latest.md"
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2)
    rendered_md = render_markdown_report(report)
    json_path.write_text(rendered_json, encoding="utf-8")
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_json.write_text(rendered_json, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "latest_json": latest_json,
        "latest_markdown": latest_md,
    }


def write_matrix_report_files(*, report: dict[str, Any], output_dir: Path | None = None) -> dict[str, Path]:
    """Write timestamped JSON and Markdown reports for an eval matrix."""

    target_dir = output_dir or (DEFAULT_REPORT_DIR / "matrix")
    target_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(report["run_id"])
    execution_id = str(report.get("execution_id") or run_id)
    file_stem = f"{run_id}__{execution_id}"
    json_path = target_dir / f"{file_stem}.json"
    md_path = target_dir / f"{file_stem}.md"
    latest_json = target_dir / "latest.json"
    latest_md = target_dir / "latest.md"
    rendered_json = json.dumps(report, ensure_ascii=False, indent=2)
    rendered_md = render_matrix_markdown_report(report)
    json_path.write_text(rendered_json, encoding="utf-8")
    md_path.write_text(rendered_md, encoding="utf-8")
    latest_json.write_text(rendered_json, encoding="utf-8")
    latest_md.write_text(rendered_md, encoding="utf-8")
    return {
        "json": json_path,
        "markdown": md_path,
        "latest_json": latest_json,
        "latest_markdown": latest_md,
    }
