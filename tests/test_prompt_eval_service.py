from __future__ import annotations

from insight_memory.evals.prompt_registry import get_prompt_eval_target
from insight_memory.services import prompt_eval_service as service_module
from insight_memory.workers.llm_provider import LLMCallResult
from insight_memory.workers.schemas import WriteGateOutput
from tests.utils import run_async


def test_prompt_registry_maps_write_gate_to_instructions_and_schema() -> None:
    target = get_prompt_eval_target("write_gate")

    assert target.prompt_key == "write_gate"
    assert target.instructions_key == "write_gate"
    assert target.schema_type is WriteGateOutput


def test_prompt_eval_service_returns_llm_output_and_usage(monkeypatch) -> None:
    calls: list[dict] = []
    output = {
        "identity_gate_status": "passed",
        "identity_profile_drafts": [
            {
                "schema_version": 2,
                "draft_id": "d1",
                "who": "Harborlane rollout",
                "surface_forms": ["Harborlane rollout"],
                "stable_qualifiers": ["rollout"],
                "definition": "Named rollout.",
            }
        ],
        "write_rejection_reason": None,
    }

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return LLMCallResult(
            parsed=WriteGateOutput.model_validate(output),
            output_json=output,
            model="test-model",
            prompt_version="v-test",
            latency_ms=123,
            input_tokens=10,
            output_tokens=5,
            cached_tokens=2,
            cache_miss_tokens=8,
            reasoning_tokens=0,
        )

    monkeypatch.setattr(service_module.llm_provider, "generate", fake_generate)

    result = run_async(
        service_module.prompt_eval_service.run(
            prompt_key="write_gate",
            payload={"context": "Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。"},
        )
    )

    assert calls[0]["worker_type"] == "write_gate"
    assert calls[0]["schema_type"] is WriteGateOutput
    assert "[identity_profile提取规则]" in calls[0]["instructions"]
    assert result["status"] == "ok"
    assert result["prompt_key"] == "write_gate"
    assert result["model"] == "test-model"
    assert result["latency_ms"] == 123
    assert result["output"] == output
    assert "prompt_version" not in result
    assert "output_json" not in result
    assert "parsed_output" not in result
    assert result["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_tokens": 2,
        "cache_miss_tokens": 8,
        "reasoning_tokens": 0,
    }


def test_prompt_eval_service_rejects_unknown_prompt_key() -> None:
    result = run_async(
        service_module.prompt_eval_service.run(
            prompt_key="unknown_worker",
            payload={"context": "x"},
        )
    )

    assert result == {
        "status": "error",
        "prompt_key": "unknown_worker",
        "error_code": "unsupported_prompt_key",
        "error_message": "Unsupported prompt key.",
    }
