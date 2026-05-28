from __future__ import annotations

from fastapi.routing import APIRoute
from pydantic import ValidationError

from insight_memory.api import routes
from insight_memory.api.schemas import PromptEvalRequest
from tests.utils import run_async


def test_prompt_eval_route_is_registered_under_memory_path() -> None:
    paths = {
        route.path
        for route in routes.router.routes
        if isinstance(route, APIRoute)
    }

    assert "/memory/prompt-evals/run" in paths
    assert "/memory/admin/prompt-evals/run" not in paths


def test_prompt_eval_request_forbids_extra_fields() -> None:
    try:
        PromptEvalRequest(
            prompt_key="write_gate",
            payload={"context": "x"},
            case_id="unused",
        )
    except ValidationError as error:
        assert "case_id" in str(error)
    else:
        raise AssertionError("PromptEvalRequest accepted an extra case_id field")


def test_prompt_eval_route_returns_service_result(monkeypatch) -> None:
    async def fake_run(*, prompt_key: str, payload: dict) -> dict:
        return {
            "status": "ok",
            "prompt_key": prompt_key,
            "model": "test-model",
            "latency_ms": 1,
            "output": {"echo": payload},
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
                "cache_miss_tokens": None,
                "reasoning_tokens": None,
            },
        }

    monkeypatch.setattr(routes.prompt_eval_service, "run", fake_run)

    result = run_async(
        routes.run_prompt_eval_memory(
            PromptEvalRequest(
                prompt_key="write_gate",
                payload={"context": "x"},
            )
        )
    )

    assert result.status == "ok"
    assert result.prompt_key == "write_gate"
    assert result.output == {"echo": {"context": "x"}}
