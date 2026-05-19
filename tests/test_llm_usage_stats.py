from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from insight_memory.storage.repository import MemoryRepository
from insight_memory.workers.llm_provider import StructuredLLMProvider
from tests.utils import run_async


class _FakeExecuteResult:
    def __init__(self, one_result: tuple | None = None, all_result: list[tuple] | None = None) -> None:
        self._one_result = one_result
        self._all_result = all_result or []

    def one(self) -> tuple:
        if self._one_result is None:
            raise AssertionError("one() was not expected")
        return self._one_result

    def all(self) -> list[tuple]:
        return self._all_result


class _FakeStatsSession:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        if self.calls == 1:
            return _FakeExecuteResult((2, 150, 30, 180, 75, 8))
        return _FakeExecuteResult(
            all_result=[
                ("extractor", 1, 100, 20, 120, 60, 5),
                ("answer_composer", 1, 50, 10, 60, 15, 3),
            ]
        )


class _FakeRecordSession:
    def __init__(self) -> None:
        self.rows = []

    def add(self, row) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        return None


def test_memory_llm_usage_stats_include_cached_reasoning_and_hit_rate() -> None:
    repository = MemoryRepository.__new__(MemoryRepository)
    repository.db = _FakeStatsSession()

    stats = run_async(repository.llm_usage_stats())

    assert stats["total_calls"] == 2
    assert stats["input_tokens"] == 150
    assert stats["output_tokens"] == 30
    assert stats["total_tokens"] == 180
    assert stats["cached_tokens"] == 75
    assert stats["reasoning_tokens"] == 8
    assert stats["cache_hit_rate"] == 0.5
    assert stats["by_operation"]["extractor"]["cached_tokens"] == 60
    assert stats["by_operation"]["extractor"]["reasoning_tokens"] == 5
    assert stats["by_operation"]["extractor"]["cache_hit_rate"] == 0.6
    assert stats["by_operation"]["answer_composer"]["cache_hit_rate"] == 0.3


def test_memory_record_llm_run_persists_cached_and_reasoning_tokens() -> None:
    repository = MemoryRepository.__new__(MemoryRepository)
    repository.db = _FakeRecordSession()

    row = run_async(
        repository.record_llm_run(
            memory_space="test-space",
            worker_type="extractor",
            model="deepseek-test",
            prompt_version="v1",
            input_json={"value": "input"},
            output_json={"value": "output"},
            parse_status="ok",
            request_id="req-test",
            latency_ms=12,
            input_tokens=100,
            output_tokens=20,
            cached_tokens=40,
            reasoning_tokens=7,
        )
    )

    assert row.cached_tokens == 40
    assert row.reasoning_tokens == 7
    assert repository.db.rows == [row]


class _SimpleSchema(BaseModel):
    value: str


class _FakeCompletions:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'))],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                prompt_tokens_details={"cached_tokens": 40},
                completion_tokens_details=SimpleNamespace(reasoning_tokens=7),
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_memory_llm_provider_extracts_cached_and_reasoning_tokens() -> None:
    provider = StructuredLLMProvider()
    provider._client = _FakeClient()
    provider._api_key = "test-key"

    result = run_async(
        provider.generate(
            worker_type="extractor",
            instructions="Return JSON.",
            payload={"value": "input"},
            schema_type=_SimpleSchema,
        )
    )

    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cached_tokens == 40
    assert result.reasoning_tokens == 7


class _FakeDeepSeekCompletions:
    async def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'))],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                prompt_cache_hit_tokens=55,
                prompt_cache_miss_tokens=45,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=9),
            ),
        )


class _FakeDeepSeekClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_FakeDeepSeekCompletions())


def test_memory_llm_provider_extracts_deepseek_cache_hit_tokens() -> None:
    provider = StructuredLLMProvider()
    provider._client = _FakeDeepSeekClient()
    provider._api_key = "test-key"

    result = run_async(
        provider.generate(
            worker_type="extractor",
            instructions="Return JSON.",
            payload={"value": "input"},
            schema_type=_SimpleSchema,
        )
    )

    assert result.input_tokens == 100
    assert result.cached_tokens == 55
    assert result.reasoning_tokens == 9
