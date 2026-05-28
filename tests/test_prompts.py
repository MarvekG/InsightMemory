from __future__ import annotations

from insight_memory.workers.prompts import IDENTITY_PROFILE_RULES, get_worker_instructions


def test_identity_profile_rules_are_shared_across_identity_workers() -> None:
    worker_types = ("write_gate", "extractor", "query_planner", "linker", "profile_writer")

    for worker_type in worker_types:
        instructions = get_worker_instructions(worker_type)
        assert IDENTITY_PROFILE_RULES in instructions


def test_write_gate_uses_original_identity_examples_without_candidate_extraction() -> None:
    instructions = get_worker_instructions("write_gate")

    assert "`Gateway 是项目，当前主阻塞是数据库迁移失败。`" in instructions
    assert "`Product Division 同时运营两条产品线" in instructions
    assert "Return identity_profile drafts only; do not create candidate memories." in instructions
    assert "candidate memories must describe" not in instructions


def test_query_planner_instructions_require_per_draft_query_text() -> None:
    instructions = get_worker_instructions("query_planner")
    assert "`query_text`" in instructions
    assert "shortest standalone sub-query" in instructions
    assert "Do not reuse the full multi-subject query as `query_text` for every draft." in instructions


def test_query_planner_instructions_require_graph_expansion_intent() -> None:
    instructions = get_worker_instructions("query_planner")

    assert "`graph_expansion_intent`" in instructions
    assert "`entity_local`" in instructions
    assert "`cross_entity`" in instructions
    assert "`uncertain`" in instructions
    assert "Do not decide graph expansion with keyword matching" in instructions


def test_identity_profile_rules_prioritize_subject_assignment() -> None:
    assert "First decide which named stable subject owns the input or query." in IDENTITY_PROFILE_RULES
    assert "Do not run a second value/type gate over the statement content." in IDENTITY_PROFILE_RULES
    assert "Reject identity extraction only when no concrete stable subject owns the input or query." in (
        IDENTITY_PROFILE_RULES
    )
    assert "Release calendar records candidate windows; approval still comes from the change board." in IDENTITY_PROFILE_RULES


def test_identity_profile_rules_keep_identity_separate_from_event_facts() -> None:
    assert "identity_profile describes only who the subject is" in IDENTITY_PROFILE_RULES
    assert "not what happened to it" in IDENTITY_PROFILE_RULES
    assert "Do not include current state, blocker, owner value, requirement content" in IDENTITY_PROFILE_RULES


def test_identity_profile_rules_keep_generic_record_words_out_of_identity() -> None:
    assert 'Generic record wording such as "this record", "latest note", "analysis note"' in IDENTITY_PROFILE_RULES
    assert "is usually retrieval intent, not identity" in IDENTITY_PROFILE_RULES
    assert "`BRK.A 这条 analyst note 里的主要取舍是什么？`" in IDENTITY_PROFILE_RULES
    assert '"who":"BRK.A"' in IDENTITY_PROFILE_RULES
    assert '"who":"BRK.A analyst note"' in IDENTITY_PROFILE_RULES
    assert "`analyst note` is retrieval intent" in IDENTITY_PROFILE_RULES


def test_identity_profile_rules_keep_named_artifact_identity() -> None:
    assert "A named report, handbook, policy, plan, checklist, or other artifact can still be identity" in (
        IDENTITY_PROFILE_RULES
    )
    assert "`Aurora risk handbook 这条记录里要求哪些审查？`" in IDENTITY_PROFILE_RULES
    assert '"who":"Aurora risk handbook"' in IDENTITY_PROFILE_RULES
    assert "`这条记录` only says which stored memory the query wants to inspect" in IDENTITY_PROFILE_RULES


def test_identity_profile_rules_include_shared_examples() -> None:
    assert "Correct identity_profile:" in IDENTITY_PROFILE_RULES
    assert "Input:" in IDENTITY_PROFILE_RULES
    assert '当前主阻塞是数据库迁移失败' in IDENTITY_PROFILE_RULES
    assert '"stable_qualifiers":["项目"]' in IDENTITY_PROFILE_RULES
    assert "`schema_version` must be exactly 2." in IDENTITY_PROFILE_RULES
    assert "`entity_type` must be one of:" in IDENTITY_PROFILE_RULES
    assert '`数据库迁移失败` is memory content' in IDENTITY_PROFILE_RULES
    assert '`Radian 运营组 计划本周完成切换；Radian 运行手册 还缺回滚章节。`' in IDENTITY_PROFILE_RULES
    assert "Expected drafts:" in IDENTITY_PROFILE_RULES
    assert '"Radian 运营组"' in IDENTITY_PROFILE_RULES
    assert '"Radian 运行手册"' in IDENTITY_PROFILE_RULES
    assert '`Cobalt launch review round 1 supported the existing launch slot.`' in IDENTITY_PROFILE_RULES
    assert '"Cobalt launch review round 1"' in IDENTITY_PROFILE_RULES
    assert '`Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。`' in IDENTITY_PROFILE_RULES
    assert '`Harborlane checklist 要求所有 rollout 在 cutover 前补齐 quay memo。`' in IDENTITY_PROFILE_RULES
    assert '`周会里顺手提到 Trellis service，但主结论是 Bastion rollout 当前主阻塞是审批链说明缺失。`' in IDENTITY_PROFILE_RULES
    assert '`周会里顺手提到 Trellis service，另外确认 Trellis service 当前负责人是 Nia Chen。`' in IDENTITY_PROFILE_RULES


def test_edge_judge_instructions_use_original_query_for_narrow_cross_entity_calls() -> None:
    instructions = get_worker_instructions("edge_judge")

    assert "If `original_query` and `query_identity_profile` are present" in instructions
    assert "judge supports against the current query target" in instructions
    assert "For narrow target-property questions" in instructions
    assert "`Lattice checklist 当前要求补齐什么？`" in instructions
    assert "Preferred edge: `related_to` or `none`" in instructions


def test_answer_composer_instructions_keep_narrow_queries_scoped() -> None:
    instructions = get_worker_instructions("answer_composer")

    assert "First decide whether the query is asking for the target subject's own current answer" in instructions
    assert "that direct target-level answer" in instructions
    assert "they do not automatically belong" in instructions
    assert "When a memory is `background_only` or only `related_to`, do not promote it into an answer claim" in instructions
    assert "`Lattice checklist 当前要求补齐什么？`" in instructions
    assert "`Merrow plan 当前目标是什么？`" in instructions
    assert "`为什么 Lattice checklist 还不满足？`" in instructions
    assert "`Merrow plan 要完成目标还依赖什么？`" in instructions
