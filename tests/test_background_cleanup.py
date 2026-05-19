from __future__ import annotations

from types import SimpleNamespace

from insight_memory.workers import background as background_module
from insight_memory.workers.background import BackgroundWorker
from tests.utils import run_async


class _FakeRepository:
    calls: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return None

    async def delete_old_llm_runs(self, *, retention_days: int) -> int:
        self.calls.append(retention_days)
        return 2


def test_background_worker_runs_llm_usage_cleanup_once_per_day(monkeypatch) -> None:
    worker = BackgroundWorker()
    _FakeRepository.calls = []
    monkeypatch.setattr(background_module, "MemoryRepository", _FakeRepository)
    monkeypatch.setattr(background_module, "date", SimpleNamespace(today=lambda: "2026-05-19"))

    first = run_async(worker.run_llm_usage_cleanup_once())
    second = run_async(worker.run_llm_usage_cleanup_once())

    assert first == {"deleted": 2, "retention_days": 7}
    assert second == {"deleted": 0, "retention_days": 7, "skipped": "already_ran_today"}
    assert _FakeRepository.calls == [7]
