from __future__ import annotations

from insight_memory.evals.prompt_registry import get_prompt_eval_target
from insight_memory.evals.prompts import get_prompt_eval_instructions
from insight_memory.services import prompt_eval_service as service_module
from insight_memory.workers.llm_provider import LLMCallResult
from insight_memory.workers.prompts import WORKER_INSTRUCTIONS, WORKER_INSTRUCTIONS_EN, get_worker_instructions
from insight_memory.workers.schemas import (
    IdentityDefinitionJudgeOutput,
    IdentityProfileExtractionOutput,
    ProfileWriterOutput,
    QueryPlannerOutput,
    WriteGateOutput,
)
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


def test_identity_definition_judge_prompt_is_eval_only_and_chinese() -> None:
    instructions = get_prompt_eval_instructions("identity_definition_judge")

    assert "identity_definition_judge" not in WORKER_INSTRUCTIONS
    assert "identity_definition_judge" not in WORKER_INSTRUCTIONS_EN
    assert "评估 actual_definition 是否语义满足 expected_definitions" in instructions
    assert "Evaluate whether actual_definition" not in instructions


def test_identity_definition_judge_allows_person_name_definition_without_role() -> None:
    instructions = get_prompt_eval_instructions("identity_definition_judge")

    assert "纯人名" in instructions
    assert "不要求额外职位、角色、团队或职责" in instructions
    assert "周明" not in instructions
    assert "陈岚" not in instructions
    assert "Milo" not in instructions


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


def test_identity_prompt_requires_lowercase_and_source_qualifiers() -> None:
    zh_instructions = get_worker_instructions("identity_profile", system_language="zh")
    en_instructions = get_worker_instructions("identity_profile", system_language="en")

    assert "所有 identity_profile 字符串字段都应输出为小写" in zh_instructions
    assert "不要把 document 缩写成 doc" in zh_instructions
    assert "稳定限定词应优先使用原文连续词或短语" in zh_instructions
    assert "all identity_profile string fields must be lowercase" in en_instructions
    assert "do not shorten document to doc" in en_instructions
    assert "stable qualifiers should prefer contiguous source words or phrases" in en_instructions


def test_identity_prompt_uses_abstract_rules_for_extraction_boundaries() -> None:
    zh_instructions = get_worker_instructions("identity_profile", system_language="zh")
    en_instructions = get_worker_instructions("identity_profile", system_language="en")

    assert "只抽取有独立持久事实的主体" in zh_instructions
    assert "文档、简报、邮件或报告标题默认是容器" in zh_instructions
    assert "不要只写与 who 同义的循环定义" in zh_instructions
    assert "extract only subjects that carry independent durable facts" in en_instructions
    assert "document, briefing, email, or report titles are containers by default" in en_instructions
    assert "Do not write a circular definition" in en_instructions


def test_identity_prompt_resolves_remaining_boundary_ambiguities_abstractly() -> None:
    zh_instructions = get_worker_instructions("identity_profile", system_language="zh")
    en_instructions = get_worker_instructions("identity_profile", system_language="en")

    assert "主体类型词无论出现在 who 的开头、中间还是结尾" in zh_instructions
    assert "只出现在另一个主体的规则正文、条件、依赖、材料、输入、输出或说明内容中" in zh_instructions
    assert "因果或前置条件从句中的从属对象即使带有可用性、完整性或提交状态" in zh_instructions
    assert "背景标签不能覆盖后文独立事实" in zh_instructions
    assert "共享编号、短码、代号或前缀不是同一主体的充分证据" in zh_instructions
    assert "any word or phrase that acts as the subject-type boundary" in en_instructions
    assert "appears only inside another subject's rule body, condition, dependency, material, input, output, or explanatory content" in en_instructions
    assert "A subordinate item inside a causal or prerequisite clause may carry availability, completeness, or submission state" in en_instructions
    assert "A background label must not override a later independent fact" in en_instructions
    assert "Shared numbers, short codes, aliases, or prefixes are not sufficient evidence" in en_instructions


def test_identity_profile_schema_lowercases_identity_fields_but_not_query_text() -> None:
    output = QueryPlannerOutput.model_validate(
        {
            "query_gate_status": "passed",
            "query_identity_profile_drafts": [
                {
                    "schema_version": 2,
                    "draft_id": "d1",
                    "who": "STP.N",
                    "surface_forms": ["STP.N", "青岚结算服务"],
                    "stable_qualifiers": ["API Contract", "服务"],
                    "definition": "STP.N Is The Stock Or Market Object Named STP.N.",
                    "query_text": "What does STP.N require next?",
                }
            ],
            "query_rewrites": [],
            "query_focus": {},
        }
    )

    draft = output.query_identity_profile_drafts[0]
    assert draft.who == "stp.n"
    assert draft.surface_forms == ["stp.n", "青岚结算服务"]
    assert draft.stable_qualifiers == ["api contract", "服务"]
    assert draft.definition == "stp.n is the stock or market object named stp.n."
    assert draft.query_text == "What does STP.N require next?"


def test_profile_writer_schema_lowercases_identity_fields() -> None:
    profile = ProfileWriterOutput.model_validate(
        {
            "schema_version": 2,
            "who": "Ravel Import Service",
            "surface_forms": ["Ravel Import Service", "青岚结算服务"],
            "stable_qualifiers": ["Import Service", "服务"],
            "definition": "Ravel Import Service Is The Import Service Related To Ravel.",
        }
    )

    assert profile.who == "ravel import service"
    assert profile.surface_forms == ["ravel import service", "青岚结算服务"]
    assert profile.stable_qualifiers == ["import service", "服务"]
    assert profile.definition == "ravel import service is the import service related to ravel."


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
    assert result["output"] == {
        "identity_gate_status": "passed",
        "identity_profile_drafts": [
            {
                "schema_version": 2,
                "draft_id": "d1",
                "who": "harborlane rollout",
                "surface_forms": ["harborlane rollout"],
                "stable_qualifiers": ["rollout"],
                "definition": "named rollout.",
            }
        ],
        "rejection_reason": None,
    }
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
