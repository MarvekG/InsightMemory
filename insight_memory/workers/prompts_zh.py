from __future__ import annotations

from insight_memory.workers.schemas import ENTITY_TYPE_VALUES


ALLOWED_ENTITY_TYPES_ZH = ", ".join(ENTITY_TYPE_VALUES)

ENTITY_TYPE_RULES_ZH = f"""
允许的 entity_type 取值：
- {ALLOWED_ENTITY_TYPES_ZH}。
- 只能返回这些精确的小写枚举值，不要返回更窄的自然语言子类型。
- 选择最接近的宽泛枚举，把更窄的子类型放入 stable_qualifiers。
- 对命名的软件系统、API、服务、数据库、平台、基础设施组件使用 `system`。
- 对命名的政策、清单、手册、报告、笔记、备忘录、运行手册、指南、登记册、公告、简报等承载文本的工件使用 `document`。
- 对命名的非文档交付物、文件、包、模型、数据集、看板、表格、schema、模板、物理或运营对象使用 `artifact`。
- 对命名的会议、评审、发布、事故、会话、轮次、演习、训练等有时间边界的事件使用 `event`。
- 对命名的周期性流程、流水线、playbook、操作过程或工作流使用 `workflow`。
- 对命名的任务、工单、问题、待办、里程碑和行动项使用 `work_item`。
- 非法示例：`policy`、`checklist`、`handbook`、`manual`、`report`、`note`、`memo`、`runbook`、
  `review`、`meeting`、`incident`、`service`、`api`、`database`、`ticket`。
- 应改成宽泛枚举：policy/checklist/handbook/manual/report/note/memo/runbook -> `document`；
  review/meeting/incident -> `event`；service/api/database -> `system`；ticket/issue/task -> `work_item`。
- 阅读主体本身后仍无法确定宽泛枚举时使用 `unknown`。
""".strip()


IDENTITY_PROFILE_RULES_ZH = """
共享 identity_profile 规则：
- 先判断输入或查询归属于哪个命名的稳定主体。
- 如果输入或查询能归属到一个具体稳定主体，就为该主体抽取 identity_profile，不要再对陈述内容做第二道价值/类型闸门。
- 只有在没有任何具体稳定主体拥有该输入或查询时，才拒绝身份抽取。
- 稳定主体是以后可以再次指称的命名对象，例如系统、文档、项目、团队、工作流对象、市场对象、人物或其他命名对象。
- identity 粒度由持久事实所归属的 owner subject 决定，不由只出现在 owner phrase 内部的低层级名词决定。
- 当完整命名短语本身承接结论、要求、状态、决定或其他持久事实时，不要把 owner subject 拆成低层级主体加记录描述词。
- identity 分类必须来自句子里的归属关系，不要靠短语中的角色词匹配。
- 如果某个名称只是另一个主体陈述里的缺失项、附件、证据、前置条件、原因或细节，不要为它创建独立主体。
- 如果某个名称只是顺带提及，输入或查询并不归属于该名称，不要为它创建主体。只有同一输入或查询也包含归属于该名称的独立陈述时才创建。
- identity_profile 只描述主体是谁，不描述主体发生了什么。
- `schema_version` 必须正好为 2。
- `who` 必须是同一主体的简短稳定标签。
- `entity_type` 必须是以下之一：{ALLOWED_ENTITY_TYPES_ZH}。
{ENTITY_TYPE_RULES_ZH}
- `surface_forms` 必须直接来自输入或查询文本。
- `stable_qualifiers` 只能包含用于区分同名主体的简短稳定限定词，不要写成散文。
- `evidence` 可以包含简短身份抽取证据，但仅用于审计，不得包含当前状态、结果、阻塞、负责人值或其他记忆事实。
- 不要把当前状态、阻塞、负责人值、要求内容、结论、指标、时间变化或其他记忆事实放入 identity_profile。
- round、stage、date、session、version 等记录标记不是 identity；把它们保留在 memory content、query_text 或 record_markers 中。
- 同一个命名 review、plan、document、workflow 或 artifact 的历史/当前记录必须保持同一个 identity_profile；轮次和时间放在内容或 record_markers 中区分。
- “this record”“latest note”“analysis note”“history”“report content”等通用记录词通常是检索意图，不是 identity。若查询命名了底层稳定主体，保留底层主体作为 identity，把通用记录词放入 query_text 或 memory content。
- 该通用记录规则不覆盖 owner-subject 归属：如果持久事实本身归属于命名的记录类主体，就保留完整主体作为 identity。
- 命名报告、手册、政策、计划、清单或其他 artifact 自身有稳定名称时仍可作为 identity，不要把它和只描述存储记录类型的通用词混淆。
- 当一个输入或查询包含多个同前缀但不同主体时，保留能区分它们的稳定限定词，不要折叠成裸名称。

示例 1：普通主体陈述
输入：
`Gateway 是项目，当前主阻塞是数据库迁移失败。`
正确 identity_profile：
`{"who":"Gateway 项目","surface_forms":["Gateway","Gateway 项目"],"stable_qualifiers":["项目"]}`
解释：
`项目` 是稳定身份限定词；`数据库迁移失败` 是记忆内容，不属于 identity_profile。

示例 2：同前缀多个主体
输入：
`Radian 运营组 计划本周完成切换；Radian 运行手册 还缺回滚章节。`
期望 drafts：
`[
  {"who":"Radian 运营组","surface_forms":["Radian","Radian 运营组"],"stable_qualifiers":["运营组"]},
  {"who":"Radian 运行手册","surface_forms":["Radian","Radian 运行手册"],"stable_qualifiers":["运行手册"]}
]`
解释：
输入归属于两个不同主体，因此抽取两个 identity_profile drafts。

示例 3：记录轮次不是 identity
输入：
`Cobalt launch review round 1 supported the existing launch slot.`
正确 identity_profile：
`{"who":"Cobalt launch review","surface_forms":["Cobalt launch review"],"stable_qualifiers":["launch review"]}`
错误 identity_profile：
`{"who":"Cobalt launch review round 1","surface_forms":["Cobalt launch review round 1"],"stable_qualifiers":["launch review"]}`
解释：
`round 1` 是记录标记，不是主体 identity 的一部分。

示例 4：缺失项不是独立主体
输入：
`Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。`
正确 identity_profile：
`{"who":"Harborlane rollout","surface_forms":["Harborlane rollout","Harborlane"],"stable_qualifiers":["rollout"]}`
解释：
`quay memo` 是 Harborlane rollout 的缺失原因，不是该输入的 owner subject。

示例 5：命名治理工件
输入：
`Harborlane checklist 要求所有 rollout 在 cutover 前补齐 quay memo。`
正确 identity_profile：
`{"who":"Harborlane checklist","surface_forms":["Harborlane checklist","Harborlane"],"stable_qualifiers":["checklist"]}`
解释：
输入归属于 `Harborlane checklist`。`quay memo` 是要求内容，不是独立主体。

示例 6：顺带提及不是独立主体
输入：
`周会里顺手提到 Trellis service，但主结论是 Bastion rollout 当前主阻塞是审批链说明缺失。`
正确 identity_profile：
`{"who":"Bastion rollout","surface_forms":["Bastion rollout","Bastion"],"stable_qualifiers":["rollout"]}`
解释：
输入归属于 Bastion rollout。Trellis service 只是顺带提及。

示例 7：顺带提及加独立陈述
输入：
`周会里顺手提到 Trellis service，另外确认 Trellis service 当前负责人是 Nia Chen。`
正确 identity_profile：
`{"who":"Trellis service","surface_forms":["Trellis service","Trellis"],"stable_qualifiers":["service"]}`
解释：
第二个分句给 Trellis service 自己的陈述，因此抽取该主体。

示例 8：陈述有 owner subject 时抽取 identity
输入：
`Release calendar records candidate windows; approval still comes from the change board.`
正确 identity_profile：
`{"who":"Release calendar","surface_forms":["Release calendar"],"stable_qualifiers":["calendar"]}`
解释：
输入归属于 Release calendar。identity 抽取不需要先把陈述分类成某种事实类型。

示例 9：通用记录词不是 identity
输入：
`BRK.A 这条 analyst note 里的主要取舍是什么？`
正确 identity_profile：
`{"who":"BRK.A","surface_forms":["BRK.A"],"stable_qualifiers":["market object"]}`
错误 identity_profile：
`{"who":"BRK.A analyst note","surface_forms":["BRK.A","BRK.A analyst note"],"stable_qualifiers":["analyst note"]}`
解释：
查询在问 BRK.A 的已存笔记。稳定主体是 BRK.A；`analyst note` 是检索意图，不是独立 identity。

示例 10：命名 artifact 保持 identity
输入：
`Aurora risk handbook 这条记录里要求哪些审查？`
正确 identity_profile：
`{"who":"Aurora risk handbook","surface_forms":["Aurora risk handbook"],"stable_qualifiers":["risk handbook"]}`
解释：
命名 handbook 是稳定主体。`这条记录` 只说明查询要检查哪条已存记忆。

示例 11：父上下文里的独立子 artifact
输入：
`Product Division 同时运营两条产品线：Line A 本季度聚焦企业客户，负责人是 Wang Lin；Line B 本季度聚焦个人用户，负责人是 Chen Hua。`
期望 drafts：
`[
  {"who":"Product Division","surface_forms":["Product Division"],"stable_qualifiers":["division"]},
  {"who":"Line A","surface_forms":["Line A"],"stable_qualifiers":["line","A"]},
  {"who":"Line B","surface_forms":["Line B"],"stable_qualifiers":["line","B"]}
]`
解释：
每条命名产品线都有自己的独立持久事实，因此即使在 Product Division 上下文内也必须拆成独立主体。
""".strip().replace("{ALLOWED_ENTITY_TYPES_ZH}", ALLOWED_ENTITY_TYPES_ZH).replace(
    "{ENTITY_TYPE_RULES_ZH}", ENTITY_TYPE_RULES_ZH
)


WORKER_INSTRUCTIONS_ZH: dict[str, str] = {
    "write_gate": f"""
判断原始输入是否应被接受进入长期记忆写入。
只返回 identity_profile drafts，不要创建 candidate memories。
规则：
- identity_profile drafts 只能使用 schema 定义的字段。
- {IDENTITY_PROFILE_RULES_ZH}
- 如果无法识别稳定主体，返回 rejected_no_identity_profile。
- `draft_id` 使用简短不透明引用，例如 `d1`、`d2`。
""".strip(),
    "extractor": f"""
从原始输入中抽取一个或多个 identity_profile drafts 和 candidate memories。
规则：
- identity_profile drafts 只能使用 schema 定义的字段。
- {IDENTITY_PROFILE_RULES_ZH}
- 如果无法识别稳定主体，返回 rejected_no_identity_profile 且不返回 candidates。
- `draft_id` 和 `candidate_id` 使用简短不透明引用，例如 `d1`、`d2`、`c1`、`c2`。
- 每个 candidate 的 `owner_draft_id` 必须精确复制一个已输出 draft ref。
- candidate memories 必须描述输入关于 owner subject 的陈述，不要复制无关上下文。
- 若输入可按共享身份规则归属到命名稳定主体，就为该主体的陈述创建 candidate memory。
- 若输入主要归属于一个主体，只顺带提及另一个主体，不要为顺带主体创建 candidate，除非输入也给该主体独立陈述。
- 命名子项目、子系统、子组件或子 artifact 若有自己的时间线、负责人、状态或要求，应作为独立主体抽取。
- 会议记录、旁注或背景噪声中的“被提到”本身不是值得存储的独立记忆。
- 只作为另一个主体陈述中细节的短语，应留在该主体 candidate memory 内，不要另建 identity_profile 或 candidate。
- 对 `X cannot proceed/confirm/launch/complete because Y is missing/incomplete/not submitted/not signed` 这类模式，创建 X 的 candidate memory，并把 Y 作为原因；除非输入也给 Y 自己的 owner、规则、状态、决定、要求、生命周期、版本或跟踪状态，否则不要把 Y 建成主体。
- 若另一个命名 policy、protocol、checklist、manual、handbook、rule 或 guide 要求 X 提供 Y，该命名治理工件可以是独立主体；Y 仍只是要求项，除非它也有自己的独立持久事实。
- 包含多条同前缀稳定 artifact 的消息、邮件、表格、清单或 bullet list，应保留每个完整主体短语，不要折叠成共享前缀。
- `record: ...`、`phase: ...`、`entity=...`、`rule: ...`、`state=...`、`owner: ...` 等结构化字段是强结构，不是格式噪声。
- 短结构化记录只要命名了稳定主体和持久规则、阻塞、负责人、状态或要求，也可以成为 durable memory。
- 时间有界或会话有界的历史记录，应保留具体主体并把记录总结成 candidate memory，不要折叠成通用 event。
- 输入包含 session、stage、round、date 或 version 标记时，把这些标记保留在 title、summary、content 或 record_markers 中。
- 保留每条 candidate memory 的重要细节，但不要输出重复、近重复或微不足道的改写。
- 写 title、summary、content 时保留输入原语言。不要在源文本不是双语时静默中英互译。
- 在 memory content 中保留 blockers、dates、times、document names、explicit requirements、operational conditions 等关键具体短语。
- 对单主体长报告、长历史或长 debate record，默认输出一条详细主记忆。
- 长历史或评审记录即使包含权衡、理由、条件、开放问题、恢复计划、暂停原因或决策约束，也可以是 durable。
- 不要因为命名长记录是分析性或平衡性的就拒绝它；抽取未来查询会用到的具体结论、权衡、条件或未决点。
- 只有当源文本包含多个会回答明显不同未来查询的独立 claims 时，才输出多条 candidate memories。
- 同一结论的不同章节、标题、bullet 或支持论据应留在同一 memory content 中。
- 若一份长文档包含早期规则、当前规则和只补充当前规则的 appendix/amendment/addendum，输出一条早期历史 candidate 和一条已包含补充要求的当前 candidate；不要把补充拆成平行当前 candidate。
""".strip(),
    "linker": f"""
判断 identity_profile draft 是否能唯一绑定到候选实体之一。
规则：
- {IDENTITY_PROFILE_RULES_ZH}
- 只能从提供的 entity candidates 中选择。
- 同时比较 draft、candidate 的 identity_profile、display_name 和代表性 memory summaries。
- 把 `who`、`surface_forms` 和 `stable_qualifiers` 合在一起作为 identity 信号，不要只看 stable_qualifiers。
- 只有当某个候选明显是同一主体且足以排除其他候选时，才返回 link_existing。
- write mode 下，如果用 stable_qualifiers 和代表性 memories 后仍有一个最佳匹配，优先 link_existing。
- 如果 draft 与候选共享 surface form 但稳定 identity 或功能明显不同，不要合并成一个实体。
- write mode 下先检查 draft 和 candidate 是否有同一 identity 粒度。
- 不要仅因共享前缀、主题或底层领域实体就链接两个实体。
- 只有当 draft 和 candidate 可以承接同一批 durable memories 且不丢失主体边界时，才 link_existing。
- write mode 中 surface form 相同但角色类 identity 不同时，优先 create_new，不要强行 link_existing。
- 时间性措辞（之前、当前、later、already changed 等）不是稳定 identity 差异；同一命名主体的状态变化应链接到同一实体。
- write mode 中，仅当所有候选都明显是不同主体时才 create_new。
- query mode 中，若没有候选明确匹配，返回 cannot_resolve。
- query mode 中，只有在使用所有上下文后多个候选仍真正可行时才返回 ambiguous。
- query mode 中，用 draft 中任何稳定 identity 限定词排除冲突身份或功能的候选。
- 命名 policy、handbook、rule、guideline、report、project、document、plan、checklist、rollout、service、runbook 都可作为稳定主体；区分同名对象的角色名词应视为稳定 identity 的一部分。
""".strip(),
    "resolver": """
比较同一实体下所有 candidate memories 与 existing memories。
每个 candidate memory 返回一个 resolution item。
规则：
- candidate_memories 中的 candidate_id 是 `c1` 这类不透明短引用。
- existing_memories 中的 memory_id 是 `m1` 这类不透明短引用。
- 输出中的 candidate_id 和 target_memory_id 必须精确复制 payload 中提供的引用。
- 不要发明引用、改写引用或输出原始内部 id。
- refresh 表示 candidate 重述并强化现有记忆。
- replace 表示 candidate 用新版本取代旧记忆。
- coexist 表示两条记忆可以同时存在。
- stale 表示某个现有 target 应标记为 stale。
- 没有清晰匹配的 existing memory 时使用 create。
- 提供 record_markers 时必须使用。
- 时间有界或会话特定记录若不是现有记忆近重复，优先 coexist。
- candidate 与 existing memory 的 session、stage、round 或 date markers 不同时，除非新记录明确 supersede/replace 旧记录，否则优先 coexist。
- 没有有意义历史标记且新 candidate 明确更新同一 standing fact 时，优先 replace。
- 若 existing memory 有明确 record_markers 而新 candidate 没有，不要仅因内容重叠就把有界历史记录 refresh 成新 candidate。
- 新 candidate 表示同一跟踪主体的当前状态、阻塞、负责人、最新决定或 settled conclusion，而 existing memory 是该主体早期状态时，优先 replace，让早期状态通过 updates superseded。
- `之前卡在 A` 与 `当前主阻塞已经变成 B` 表示同一 blocker chain 随时间变化，优先 replace，而不是让两个当前状态并存。
- 对 before/now、earlier/current 转换，只要两条记忆回答同一实际问题（阻塞、负责人、要求、standing status），即使旧记忆仍有历史价值，也优先 replace。
- 有界历史记录之后出现无界当前总结时，保留两者；历史记录仍可用于回答历史问题。
- 同一 session/review 内的历史备选立场应 coexist；后续当前总结说明最终结论时，不应删除这些有界历史记录。
- standing conclusion 与主要作为证据、解释或支持细节的记录应分开保留，方便后续 edge construction 建立关系。
- 如果新文本明确说当前 owner、blocker、requirement 或 standing state 已改变，优先 replace。
- 新记忆为同一当前规则增加仍有效的要求、条件、附件或前置条件时，优先 refresh，并在刷新文本中保留旧要求和新补充。
- correction note、amendment、appendix、addendum 或 follow-up attachment note 增加同一当前规则的仍有效要求时，视为累计当前状态，不拆成平行规则。
- 长文档同时包含早期宽松规则、当前更严格规则和当前规则补充时，应解析成一条 superseded historical memory 加一条已吸收补充的 current active memory。
- 同一 batch 中早期 candidate 与当前 candidate 形成清晰演化时，让较新的 current candidate 直接 replace 较早 candidate，而不是输出两个 peer active create。
- supplement candidate 与历史规则、当前规则同时出现时，supplement 必须指向当前 active rule，不要指向 historical predecessor。
- created_at 只能作为时间排序辅助线索，逻辑顺序主要依据内容里的 explicit temporal wording。
""".strip(),
    "same_batch_resolver": """
用代表同一 ingest batch 中较早 candidates 的 synthetic same-batch memories 解析候选记忆。
规则：
- Existing memories 可能是代表同 batch 较早 candidates 的 synthetic placeholders。
- Existing memories 使用 `m1` 这类短 memory refs；指向较早 same-batch placeholder 时必须使用这些 refs。
- 写入前使用这些 synthetic placeholders 归一化一批 earlier/current 演化。
- 当后续 candidate 陈述同一 artifact 的更新当前规则、当前阻塞或当前 standing state 时，通常应以 action=replace 指向较早 same-batch placeholder，而不是产生两个 peer active creates。
- 永远不要 target 自己的 candidate ref，也不要发明 memory ref。
- 当 batch 明确表达同一实际问题的 earlier/current 演化时，优先产出一个 superseded earlier memory 加一个 active current head。
""".strip(),
    "query_planner": f"""
从查询中抽取 query identity_profile drafts 和简短 query rewrites。
规则：
- {IDENTITY_PROFILE_RULES_ZH}
- 每个 query_identity_profile_draft 必须包含 `query_text`，即原始查询中只询问该 draft 主体的最短独立子查询。
- 单主体查询中，`query_text` 通常应是完整原始查询。
- 多主体查询中，按主体拆分 draft，并给每个 draft 自己的 `query_text`，不要包含其他主体。
- 不要为每个 draft 复用完整多主体查询。
- 查询中的具体命名对象只要指向有稳定身份的有界主体，就视为有效稳定主体。
- 若查询已有一个具体命名主体，其余部分只问要求、分歧、原因、阻塞、历史或条件，保留该主体作为 identity target。
- 无法识别稳定主体时返回 rejected_no_identity_profile。
- query_rewrites 保持简短聚焦。
- query_focus 只总结检索意图，不要写最终答案内容。
- query_focus.time_intent 必须是 current、latest、history 或 unspecified。
- query_focus.graph_expansion_intent 必须是 `entity_local`、`cross_entity` 或 `uncertain`。
- 根据回答所需证据范围决定 graph expansion，不要靠关键词匹配。
- 查询可由目标实体自身 recalled memory 和本地证据回答时使用 `entity_local`。
- 需要外部约束、依赖、治理证据或其他实体状态解释目标答案时使用 `cross_entity` 或 `uncertain`。
- 查询 why/how、dependency chains、surrounding constraints、related gaps、external requirements 或 other-entity evidence 时使用 `cross_entity`。
- 目标稳定但不确定是否需要其他实体记忆时使用 `uncertain`。
- query_focus.graph_expansion_reason 用一句短理由说明语义判断。
- 查询早期记录、先前状态或时间变化时使用 history；同时问历史和现在时仍使用 history。
- 最新已知结论使用 latest；当前 standing state 使用 current。
- 外部上下文包括其他实体、文档、规则、手册、流程、清单、协议、memo、上下游依赖、约束来源、邻近风险、补充要求或相邻记录。
- 查询历史分歧及后来为何收敛时，只要外部 handbook、checklist、policy、rule 或 governing artifact 可能解释收敛，就保留主主体作为 identity target。
- 查询当前阻塞原因以及相关缺口、缺失前置条件、依赖或周边条件时，在 rewrites 中同时保留直接解释意图和相关上下文意图。
- 查询 requirements、conditions、missing items、blockers 或 preconditions 时，保留具体短语，不要替换成泛化词。
- 命名 policy、handbook、guideline、report、project、document、plan、team、working group 等可作为查询主体。
- 保留 `rollout`、`service`、`checklist`、`runbook`、`policy`、`document`、`handbook`、`plan` 等用于区分同名主体的具体角色名词。
""".strip(),
    "cross_entity_query_builder": """
生成少量检索查询文本，用于查找其他实体中可能解释、约束、依赖或关联 frontier memories 的记忆。
规则：
- 同时使用 frontier memories 和 frontier observations。
- 输出短检索查询，不要输出完整答案。
- 优先保留共享概念、要求、约束、缺失前置条件、上下游依赖、文档名、政策名和运营条件。
- 如果 frontier memory 命名了 blocker，而 observations 解释 blocker 原因，在 retrieval queries 中保留 blocker phrase 和 explanatory phrase。
- 若 frontier memory 提到外部要求、缺失文档、policy、checklist、approval chain、upstream service 或 neighboring gap，把它转成可直接匹配其他实体记忆的查询。
- 直接治理工件命名多个仍需补齐项时，保留这些 sibling required items，不要只搜索当前提到的 blocker。
- sibling item 自身可能有上游附件、审批人、印章、roster 或其他前置条件时，至少一个查询要包含该 sibling item。
- frontier memory 请求 related gaps、neighboring missing prerequisites 或 adjacent readiness issues 时，为显式命名的 validation flow、guardrail、prerequisite 或 readiness process 生成窄查询。
- 不要发明输入中未暗示的外部实体。
- 不要重复近似查询。
- 返回 2-6 条 query texts；没有合适外部主体时可返回空或很窄的查询集。
- 尽量保持查询与输入证据的主要语言一致。
- 如果 frontier memory 本身只是 secondary artifact/process-gap note，不要仅因同属 incident/recovery area 就广泛扩展到周边运营主体。
- distractor artifact 不应主导检索；优先搜索真正的外部失败服务、来源状态或约束。
""".strip(),
    "answer_composer": """
使用 candidate memories、relation edges 和 observations 生成最终用户答案。
规则：
- 答案简洁并直接回应 query。
- `memories` 中每条 memory 都只是候选，没有预选答案子集。
- 自行从完整候选集和关系图中选择证据。
- 先判断查询是在问目标主体自己的当前答案，还是解释链、依赖链、上游约束或周边上下文。
- 若查询只问目标主体自己的当前要求、状态、目标、决定、阻塞或内容，只回答该直接目标层答案。
- 窄查询中，`supports` 和 `related_to` 可帮助理解证据，但不会自动进入最终答案。
- citations 只能使用输入 payload 中存在的 memory_id 和 observation_id。
- 输出 citations 时，用自然语言表达证据，不要只列 raw ids。
- 证据保持简短；除非查询明确要求更多，一句短证据即可。
- 不要发明 payload 之外的事实。
- 使用 memory 的 `evidence_role`、`relation_types`、`relation_edges` 判断 direct evidence、supporting evidence、conflicting evidence、update/history evidence 或 weak background。
- 查询需要 explanation chain、dependency chain 或 condition-satisfaction answer 时，linked evidence 提供必要外部约束或前置条件时不要截断在 seed memory。
- `supports` memories 只有在查询要求 reasons、dependencies、external constraints、why 或仍需满足什么时才进入答案。
- 窄目标属性问题必须保持范围，不要把 supporting memory 自身的独立状态加成额外答案。
- 仅 `related_to` 或 `background_only` 的 memories 只能作为背景；除非查询明确要求相关/相邻/周边上下文，否则不要提升成答案 claim。
- governing handbook/manual/policy/checklist 可以相关但不一定属于答案；只有查询问治理原因、上游规则、依赖链或下一层要求时才提及。
- 长证据先判断是一个中心驱动还是多个并列中心驱动。
- 查询 key drivers、core risks 或 main reasons 时，显式列出要点并保留关键证据术语。
- 关键术语出现在证据里时，优先直接复用。
- 查询最重要、核心或主要点时，只回答 1-3 个中心点，不要扩成完整摘要。
- 不要把并列中心驱动折叠成一个泛化 umbrella。
- 查询窄聚焦 top driver/top risk/main reason 时，避免外围细节。
- 证据包含具体表现和更宽概念时，可用 `宽概念（具体表现）`，但前提是宽概念被证据支持。
- 答案措辞与证据语言一致，不要翻译掉简洁关键源短语。
- 查询显式要求 requirements、conditions、missing items、blockers 或 timings 时，直接保留这些具体短语。
- 若回答依赖多个 linked artifacts，优先顺序是：目标的直接 blocker/missing item；直接治理工件；再上游 handbook/policy/supplement。
- 链式扩展规则只在查询确实需要长链时适用。
- 窄目标属性查询不要扩展完整链，只要目标层答案已经完整。
- 历史分歧与当前收敛原因同时出现时，简短说明历史分歧，并命名解释当前结论的外部 handbook/checklist/policy/rule。
- 不要只靠 citations 暗示治理工件；证据中有命名 handbook、decree、checklist、policy 或 rule 解释收敛时，要在答案文本中说出。
- 完整依赖链存在且每层都有具体 required item 时，用压缩形式保留完整链，不要停在中间层。
""".strip(),
    "answer_judge": """
评估 final answer 是否正确回答 query，并且是否 grounded in supplied evidence。
规则：
- 只使用 payload 中的 query、required facts、required_fact_groups、forbidden facts、answer、citations 和 uncertainties。
- 只有当 answer 覆盖所有 required facts 且没有引入 forbidden facts 时才返回 pass。
- required_fact_groups 存在时优先使用；每组任一 variant 或明确语义等价表达出现即满足。
- required fact 写成 `A || B || C` 时按 any-of group 处理。
- 报告某 required-fact group 缺失前，必须重新检查 answer text；若任何 variant 原文出现或以同谓词的近似混合语言短语出现，该组已覆盖。
- 不要因为 required group 出现在历史分歧部分、随后又解释新/current 结论，就判为缺失。
- historical-position groups 只要答案任何位置陈述该历史立场即可满足，不必成为最终当前结论。
- 若 reason 说某组缺失，则该组任何 variant 都不能在 answer text 中原文出现。
- 答案方向正确但不完整、grounding 较弱或遗漏部分 required facts 时返回 partial。
- 答案错误、无支持、与证据矛盾或包含 forbidden facts 时返回 fail。
- 答案提出引用或证据不支持的 claim 时，grounded 必须为 false。
- 清晰表达同一概念的近义变体、显式超集或更窄表述可满足 required fact。
- forbidden fact 按完整 claim 判断，不按词袋判断；不要仅因共享实体名、artifact 名、item 名或主题名而 fail。
- 只有答案断言同一 forbidden predicate/status/causal claim 或等价 claim 时，才因 forbidden fact fail。
- 不要通过额外世界知识推导 forbidden facts。
- 同一名词可搭配不同谓词；`X missing` 不等于 `X record must include Y`。
- required fact 在更长的双语或混合语言分句中出现时，只要清晰保留该事实就算满足。
- 额外 grounded details 不会降低 pass，只要 required facts 都覆盖且没有 forbidden facts。
- reason 保持简短具体。
""".strip(),
    "profile_writer": f"""
根据当前 profile 和近期 identity signals 重写实体 identity profile。
规则：
- {IDENTITY_PROFILE_RULES_ZH}
- 保持同一主体 identity。
- surface_forms 必须简短具体。
- stable_qualifiers 必须是简短关键词或短语。
- 不要因为 blocker、owner value、requirement content、current state 或其他显著 memory facts 频繁出现，就把它们提升进 identity_profile。
- 不要发明 entity_key 或 memory ids。
""".strip(),
    "edge_judge": """
判断 source memory 与 candidate memories 是否存在 supports、contradicts 或 related_to 关系。
规则：
- payload 可能描述 local entity graph 或 cross-entity graph。
- 如果存在 `original_query` 和 `query_identity_profile`，先用它们判断当前 recall 实际要回答什么。
- 返回完整 relation edges，不要返回 source-relative targets。
- 每条 relation 必须包含 from_memory_id、to_memory_id、edge_type、reason、weight。
- 只能返回 payload 中存在的 memory ids。
- 不要输出 `edge_type="none"`；无关系时省略该 pair。
- 每条 memory 都包含 `identity_profile`；先判断它属于哪个稳定主体。
- 若存在 `query_identity_profile`，把该主体视为当前 recall 的 answer target。
- 同前缀不同 identity_profile subjects 不会仅因共享前缀、领域、项目、readiness theme 或相似缺失细节就相关。
- supports 仅用于一条 memory 是另一条 claim 的直接证据、直接解释或直接外部要求。
- cross-entity mode 且有 `original_query` 时，按当前 query target 判断 supports，不按抽象语义相关性判断。
- 窄目标属性问题中，外部上游细节通常 omit 或 related_to，除非它本身是目标直接答案的一部分。
- governing artifact 可以相关但不一定 answer-critical；不要把每个相关上游约束都变成 supports。
- standing rule 与 audit/review/operational note 显示反复超时、延迟、未满足时，note 通常 supports rule-bearing memory，而不是 contradicts。
- contradicts 仅用于两条 memory 做出冲突或互斥 claims。
- 同 session/review/decision context 的两个有界历史记录若提出互斥替代方案，可使用 contradicts。
- related_to 用于同一更广问题但既不直接支持也不直接矛盾的 memories。
- missing process、workflow、readiness 或 prerequisite 信息通常 related_to，而不是 supports，除非它明确证明或要求目标 claim。
- 直接证据应 supports main claim；相邻缺失前置条件或 process gap 通常 related_to main claim。
- 后来当前结论与早期历史记录不同，不要仅因此添加 contradicts；历史演化通常由 updates/history 表示。
- contradicts 主要用于仍并存的 peer alternatives，不用于旧历史位置与新 settled position。
- 图应保持稀疏，优先最小 edge set；不要因为共享 topic words 就连接所有 pair。
- local graph 中先找 main claims，再只连接最强直接 supports 或 contradictions。
- cross-entity mode 中，返回边必须连接 frontier memory 与 candidate memory；不要输出 frontier-to-frontier 或 candidate-to-candidate edges。
- cross-entity mode 默认省略关系，除非外部 memory 对 frontier memory 提供直接外部解释、直接治理要求、直接依赖状态或直接矛盾。
- 有界历史 round/session 与无界外部 standing rule 不应仅因旧立场不满足规则而 contradicts；规则应支持或约束 later/current requirement。
- 对外部服务/数据源/依赖未恢复导致 rollout/review blocked 的场景，具体 external service-state memory 优先与 blocker memory related_to；弱的周边 handbook/checklist/document 可省略。
- contradicts 和 related_to 不要双向重复输出。
- reason 不得为空。
""".strip(),
    "merge_judge": """
判断两个实体是否应该合并。
规则：
- 只有当二者明确指向同一主体时才返回 merge。
- 共享主题、要求、阻塞、工作流或周边上下文不足以合并。
- 相同 broad entity_type 只是可比较资格，不是合并证据。
- stable_qualifiers 是身份边界证据；不同稳定身份边界应保持分离，除非 payload 给出明确 identity-equivalence evidence。
- 不要因为 document/policy/checklist/report/handbook artifact 约束、解释或提到 actor/system/project/person，就把二者合并。
- plan 与 project，或 plan 与 checklist/document/policy artifact，不应仅因短名相同或同属审批流程就合并。
- 不要仅因一个实体被另一个治理、阻塞或依赖，就合并两个实体。
- 如果一个实体是行动或被阻塞的对象，另一个是约束它的 rule、checklist、report、handbook、plan 或 requirement，应保持分离。
- 两个实体稳定 identity type 或稳定功能不同，即使共享流程或 issue，也 keep_separate。
- 只有当二者是同一具体主体的两个名称、别名或描述，并且它们的 memories 可归于同一 identity 而不丢失主体边界时，才 merge。
- merge 时选择两个候选中更合适的 survivor_entity_key。
- merge 时同时返回 survivor 的完整最终 V2 identity profile。
- merged_identity_profile 必须遵循共享 identity profile 规则，不能是 partial patch。
- merged_identity_profile 不能是盲目并集；它必须描述一个连贯主体，只保留真正属于该主体的 aliases 和 qualifiers。
- 不要依赖代码追加 aliases 或 qualifiers；应在输出中包含所有应保留的 surface forms 和 stable qualifiers。
- 不要把 memory facts、blockers、owner values、requirements 或 current state 放入 merged_identity_profile。
- 不确定时返回 keep_separate。
""".strip(),
}

SAME_BATCH_RESOLVER_INSTRUCTIONS_ZH = WORKER_INSTRUCTIONS_ZH["same_batch_resolver"] + "\n\n" + WORKER_INSTRUCTIONS_ZH[
    "resolver"
]

WORKER_INSTRUCTIONS_ZH["same_batch_resolver"] = SAME_BATCH_RESOLVER_INSTRUCTIONS_ZH
