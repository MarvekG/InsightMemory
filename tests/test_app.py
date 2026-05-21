from __future__ import annotations

from insight_memory import main as main_module
from insight_memory.main import app, run_shutdown, run_startup
from tests.utils import run_async


def test_app_imports() -> None:
    assert app.title
    assert callable(run_startup)
    assert callable(run_shutdown)


def test_run_startup_schedules_embedding_prewarm(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_init_database() -> None:
        calls.append("init_database")

    def fake_start_prewarm_background() -> None:
        calls.append("schedule_prewarm")

    def fake_schedule_pending_task_recovery() -> None:
        calls.append("schedule_recover_pending_tasks")

    async def fake_ensure_rebuild_task_if_needed() -> None:
        calls.append("ensure_rebuild_task_if_needed")

    async def fake_start() -> None:
        calls.append("start")

    monkeypatch.setattr(main_module, "init_database", fake_init_database)
    monkeypatch.setattr(main_module.embedding_service, "start_prewarm_background", fake_start_prewarm_background)
    monkeypatch.setattr(main_module, "schedule_pending_task_recovery", fake_schedule_pending_task_recovery)
    monkeypatch.setattr(main_module, "ensure_rebuild_task_if_needed", fake_ensure_rebuild_task_if_needed)
    monkeypatch.setattr(main_module.background_worker, "start", fake_start)

    run_async(main_module.run_startup())

    assert calls == [
        "init_database",
        "schedule_prewarm",
        "schedule_recover_pending_tasks",
        "ensure_rebuild_task_if_needed",
        "start",
    ]
