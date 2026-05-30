from __future__ import annotations


PROMPT_EVAL_INSTRUCTIONS: dict[str, str] = {
    "identity_definition_judge": """
评估 actual_definition 是否语义满足 expected_definitions 中至少一个对 identity_profile.definition 的期望。

输入包含 who、surface_forms、stable_qualifiers、actual_definition 和 expected_definitions。

规则：
- 只判断 definition 是否说明这个主体是什么，不判断记忆事实是否正确。
- pass：actual_definition 能定义同一个主体，并保留足以区分同名或同前缀主体的稳定身份边界。
- pass：actual_definition 可使用同义或更自然表达，不要求逐字包含 expected_definitions。
- pass：当 expected_definitions 表达的是纯人名、短个人称呼或个人姓名主体时，actual_definition 只要明确表示这是个人、个人主体、person 或 individual named who 即可；不要求额外职位、角色、团队或职责。
- fail：如果 expected_definitions 明确要求负责人、审批人、复核人、owner、reviewer 等角色身份，actual_definition 仍必须保留该角色边界，不能只说个人。
- fail：actual_definition 只是重复 who、只说 named object/specific subject/某个对象，或缺少角色、工件、主体类型等身份边界。
- fail：actual_definition 把当前阻塞、负责人值、要求正文、阈值、结论、时间变化等 memory fact 当成定义。
- fail：actual_definition 定义成另一个主体，或把缺失项、附件、原因、属性值当作主体。
- matched_expected 写被满足的 expected definition；没有满足时写空字符串。
- missing_identity_boundary 列出缺失的稳定身份边界；没有则为空数组。
- included_memory_fact 仅当 actual_definition 混入 memory fact 时为 true。
- reason 保持一句简短具体说明。
""".strip(),
}


def get_prompt_eval_instructions(prompt_key: str) -> str:
    """读取独立于生产 worker 的 Prompt Eval 专用提示词。

    Args:
        prompt_key: Prompt Eval 专用提示词 key。

    Returns:
        对应的 Prompt Eval 提示词。
    """

    return PROMPT_EVAL_INSTRUCTIONS[prompt_key]
