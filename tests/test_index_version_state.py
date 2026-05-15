from __future__ import annotations

from typing import Any

from insight_memory.index import version_state
from tests.utils import run_async


def test_index_config_matches_current_settings() -> None:
    state = version_state.build_index_state(status=version_state.INDEX_STATUS_READY)

    assert version_state.index_config_matches(state)


def test_index_config_detects_model_change() -> None:
    state = version_state.build_index_state(status=version_state.INDEX_STATUS_READY)
    state["embedding_model"] = "different-model"

    assert not version_state.index_config_matches(state)


def test_ensure_rebuild_task_skips_ready_matching_state(monkeypatch) -> None:
    calls: list[str] = []

    class _State:
        state_json = version_state.build_index_state(status=version_state.INDEX_STATUS_READY)

    class _Repository:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback) -> None:
            pass

        async def get_system_state(self, *, state_key: str):
            calls.append(f"get:{state_key}")
            return _State()

    monkeypatch.setattr(version_state, "MemoryRepository", _Repository)

    result = run_async(version_state.ensure_rebuild_task_if_needed())

    assert result == {"status": version_state.INDEX_STATUS_READY, "task_created": False}
    assert calls == [f"get:{version_state.VECTOR_INDEX_STATE_KEY}"]


def test_ensure_rebuild_task_marks_stale_and_creates_task(monkeypatch) -> None:
    calls: list[tuple[str, Any]] = []

    class _Repository:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback) -> None:
            pass

        @staticmethod
        def timestamp_now() -> float:
            return 100.0

        async def get_system_state(self, *, state_key: str):
            calls.append(("get", state_key))
            return None

        async def upsert_system_state(self, *, state_key: str, state_json: dict[str, Any]):
            calls.append(("upsert", state_key, dict(state_json)))

        async def create_task(self, **kwargs):
            calls.append(("create_task", dict(kwargs)))
            return type("Task", (), {"task_id": "task_rebuild"})()

    monkeypatch.setattr(version_state, "MemoryRepository", _Repository)

    result = run_async(version_state.ensure_rebuild_task_if_needed())

    assert result["status"] == version_state.INDEX_STATUS_STALE
    assert result["task_created"] is True
    upsert_call = next(item for item in calls if item[0] == "upsert")
    assert upsert_call[2]["status"] == version_state.INDEX_STATUS_STALE
    create_call = next(item for item in calls if item[0] == "create_task")
    assert create_call[1]["task_type"] == version_state.REBUILD_RETRIEVAL_INDEX_TASK
    assert create_call[1]["dedupe_key"] == version_state.REBUILD_RETRIEVAL_INDEX_DEDUPE_KEY
