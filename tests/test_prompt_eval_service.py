from __future__ import annotations

from insight_memory.evals.prompt_registry import get_prompt_eval_target
from insight_memory.services import prompt_eval_service as service_module
from insight_memory.workers.llm_provider import LLMCallResult
from insight_memory.workers.prompts import get_worker_instructions
from insight_memory.workers.schemas import IdentityDefinitionJudgeOutput, IdentityProfileExtractionOutput, WriteGateOutput
from tests.utils import run_async


def test_prompt_registry_maps_write_gate_to_instructions_and_schema() -> None:
    target = get_prompt_eval_target("write_gate")

    assert target.prompt_key == "write_gate"
    assert target.instructions_key == "write_gate"
    assert target.schema_type is WriteGateOutput


def test_prompt_registry_maps_identity_profile_to_shared_prompt_and_schema() -> None:
    target = get_prompt_eval_target("identity_profile")

    assert target.prompt_key == "identity_profile"
    assert target.instructions_key == "identity_profile"
    assert target.schema_type is IdentityProfileExtractionOutput


def test_prompt_registry_maps_identity_definition_judge_to_schema() -> None:
    target = get_prompt_eval_target("identity_definition_judge")

    assert target.prompt_key == "identity_definition_judge"
    assert target.instructions_key == "identity_definition_judge"
    assert target.schema_type is IdentityDefinitionJudgeOutput


def test_identity_prompt_has_no_removed_type_classification_language() -> None:
    zh_instructions = get_worker_instructions("identity_profile", system_language="zh")
    en_instructions = get_worker_instructions("identity_profile", system_language="en")

    assert "使用 `artifact`" not in zh_instructions
    assert "改成 `system`" not in zh_instructions
    assert "use `artifact`" not in en_instructions
    assert "not `system`" not in en_instructions
    assert "extraction_mode" not in zh_instructions
    assert "extraction_mode" not in en_instructions
    assert "candidate memories、query rewrites 或 query_focus" not in zh_instructions
    assert "candidate memories, query rewrites, or query_focus" not in en_instructions
    assert "查询文本只抽取用户查询的目标主体" not in zh_instructions
    assert "写入文本抽取这条记忆主要归属的主体" not in zh_instructions
    assert "In queries, extract only the user's target subject" not in en_instructions
    assert "In write contexts, extract the subject this memory mainly belongs to" not in en_instructions
    assert "只能使用 schema 定义的字段" not in zh_instructions
    assert "rejected_no_identity_profile" not in zh_instructions
    assert "`draft_id`" not in zh_instructions
    assert "must use only fields defined by schema" not in en_instructions
    assert "rejected_no_identity_profile" not in en_instructions
    assert "`draft_id`" not in en_instructions
    assert "补充、修订或附录" not in zh_instructions
    assert "supplement, revision, or appendix" not in en_instructions
    zh_removed_keyword_lists = [
        "可复用名词包括系统、文档、计划、团队、流程、代码、人物、事件、任务或工件",
        "账号、接口端点、运营团队或工作小组",
        "市场代码、证券代码、基金代码",
        "ticket、case、work_order、id",
        "中文“看板”",
        "命名手册、清单或政策",
        "缺失项、附件、证据、前置条件、原因、指标、字段值或执行细节",
        "负责人、审批人和复核人",
        "round、stage、date、session、version、phase、batch",
    ]
    en_removed_keyword_lists = [
        "Reusable nouns include systems, documents, plans, teams, workflows, codes, people, events, tasks, or artifacts",
        "Accounts, endpoints, operations teams, or working groups",
        "Market codes, security codes, fund codes",
        "ticket, case, work_order, or id",
        "Chinese 看板",
        "named handbook, checklist, or policy",
        "Missing items, attachments, evidence, prerequisites, reasons, metrics, field values, and details",
        "Owners, approvers, and reviewers",
        "round, stage, date, session, version, phase, and batch",
    ]

    for text in zh_removed_keyword_lists:
        assert text not in zh_instructions
    for text in en_removed_keyword_lists:
        assert text not in en_instructions


def test_identity_definition_prompt_defines_subject_not_category() -> None:
    zh_instructions = get_worker_instructions("identity_profile", system_language="zh")
    en_instructions = get_worker_instructions("identity_profile", system_language="en")

    assert "主体类别" not in zh_instructions
    assert "natural-language category" not in en_instructions
    assert "回答“这个主体是什么”" in zh_instructions
    assert "不是给一个类别标签" in zh_instructions
    assert 'answers "what is this subject?"' in en_instructions
    assert "it is not a category label" in en_instructions


def test_identity_profile_schema_describes_definition_quality_rule() -> None:
    schema = IdentityProfileExtractionOutput.model_json_schema()
    properties = schema["$defs"]["IdentityProfileDraft"]["properties"]
    definition_schema = properties["definition"]
    surface_forms_schema = properties["surface_forms"]

    assert "what `who` is" in definition_schema["description"]
    assert "generic placeholder" in definition_schema["description"]
    assert "exclude record-scope markers" in surface_forms_schema["description"]


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
        "rejection_reason": None,
    }

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return LLMCallResult(
            parsed=IdentityProfileExtractionOutput.model_validate(output),
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
            prompt_key="identity_profile",
            payload={"context": "Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。"},
        )
    )

    assert calls[0]["worker_type"] == "identity_profile"
    assert calls[0]["schema_type"] is IdentityProfileExtractionOutput
    assert "[identity_profile提取规则]" in calls[0]["instructions"]
    assert result["status"] == "ok"
    assert result["prompt_key"] == "identity_profile"
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
