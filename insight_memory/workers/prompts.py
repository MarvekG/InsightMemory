from __future__ import annotations

# 提示词维护规则：
# 禁止为了让评测 case 通过而使用关键词匹配、类似正则的表达或针对 case 的捷径。
# 所有提示词都必须优先保证泛化性能。可以用示例说明规则，但示例中的名称、
# 领域、场景和表达方式必须与评测 case 不同。

IDENTITY_PROFILE_RULES = """
[identity_profile提取规则]
提取目标：判断“这条记忆属于谁”，从文本里找出承接这条记忆的命名名词。
identity_profile 只记录这个名词是谁，不记录它发生了什么。

整体判断：
- 规则：先读完整输入或查询，找主要承接这条记忆的命名名词。
  例：“洛川巡检手册要求夜班复核”，主体是“洛川巡检手册”。
- 规则：不要先判断事实类型或写入价值；身份抽取只回答“属于谁”。
  例：“南枝策略已废弃旧阈值”，仍先抽取“南枝策略”。
- 规则：只有完全没有可复用命名名词时，才拒绝身份抽取。
  例：“今晚感觉风险很高”没有命名主体，可拒绝。
- 规则：可复用名词包括系统、文档、计划、团队、流程、代码、人物、事件、任务或工件。
  例：“柳湾权限清单”“云脊结算服务”“孟澜”都可作为主体。
- 规则：市场代码、证券代码、基金代码和 ticker-like symbol 可作为主体。
  例：“771009.SZ 最新研究记录怎么看？”主体是“771009.SZ”。
- 规则：结构化记录中的 ticket、case、work_order、id 字段值，承接状态或阻塞时可作为主体。
  例：“ticket=QF-42B; blocker=缺照片”主体是“QF-42B”，不是“缺照片”。

`who` 字段规则：
- 规则：`who` 是同一主体的简短稳定标签，要写完整命名名词。
  例：“枫桥上线计划当前卡在回归窗口”，`who` 写“枫桥上线计划”。
- 规则：完整命名短语要完整保留，不要拆成裸名称或泛化描述。
  例：“柳湾权限清单”不要拆成“柳湾”或“权限记录”。
- 规则：同前缀但角色不同的名词不能合并成一个裸名称。
  例：“云脊结算服务”和“云脊结算手册”是两个主体。
- 规则：能区分主体的角色词必须保留在 `who` 中。
  例：“鹭湾工单”的 `who` 写“鹭湾工单”，不要只写“鹭湾”。
- 规则：人物偏好、习惯、要求或不希望做的事，属于这个人物。
  例：“许诺偏好每周一看汇总”，主体是“许诺”。
- 规则：`who` 只写主体名词，不写当前状态、阻塞、结论、指标或时间变化。
  例：“云杉风控策略”可以；“云杉风控策略当前阈值上调”不可以。

`surface_forms` 字段规则：
- 规则：`surface_forms` 只能直接来自输入或查询原文，不要发明别名。
  例：原文是“东篱访问清单”，不要写“东篱权限文档”。
- 规则：`surface_forms` 要保留能证明同一主体的完整原始称呼。
  例：原文只写“枫桥上线计划”，就保留“枫桥上线计划”。
- 规则：不要把通用记录词拼进 `surface_forms`，除非记录本身有独立标题。
  例：“771009.SZ 的最新分析笔记”保留“771009.SZ”，不是“最新分析笔记”。

`stable_qualifiers` 字段规则：
- 规则：`stable_qualifiers` 用来区分同名或同前缀主体，只写短稳定限定词。
  例：“柳湾权限清单”可写“权限清单”和“清单”。
- 规则：稳定限定词必须来自 `who` 或 `surface_forms`，不要从 `definition` 推断。
  例：“碧湾发布公告”可放“公告”，不要因为定义写了文档就放“文档”。
- 规则：能区分主体的角色词要放入 `stable_qualifiers`。
  例：“鹭湾工单”的 `stable_qualifiers` 至少包含“工单”。
- 规则：中文复合角色短语要同时保留最长稳定短语和末尾角色词。
  例：“枫桥上线计划”放“上线计划”和“计划”；“洛川巡检手册”放“巡检手册”和“手册”。
- 规则：人名、股票代码或无角色词的唯一名称，`stable_qualifiers` 可以为空。
  例：“孟澜不希望周五排发布会”，主体是“孟澜”，限定词可为空。
- 规则：`stable_qualifiers` 不要写记录标记、句子、当前状态或事实摘要。
  例：不要把“当前暂停”“第二轮”放进 `stable_qualifiers`。
- 规则：中文“看板”如果是主体名的一部分，要放入 `stable_qualifiers`。
  例：“墨池运营看板”的 `stable_qualifiers` 应包含“看板”。

`definition` 字段规则：
- 规则：`definition` 只解释 `who` 是什么，不写记忆事实。
  例：“碧湾发布公告指碧湾相关的发布公告”可以；“要求补齐审批链”不可以。
- 规则：`definition` 不要包含当前状态、结果、阻塞、负责人值或要求内容。
  例：“云脊结算服务指云脊相关的结算服务”可以；“负责人是赵奕”不可以。
- 规则：`definition` 是对具体主体的定义，不是类别标签。
  例：“枫桥上线计划指枫桥相关的上线计划”可以；只写“命名上线计划”不可以。
- 规则：人物主体也要定义具体是谁，不要只写“人物”。
  例：“孟澜指名为孟澜的人”可以；只写“人物”不可以。

多主体和边界规则：
- 规则：一条输入有多个名称时，只抽取被直接陈述或直接查询的名称。
  例：“周会提到澜缓存服务，但柏港评审会决定延期”，只抽取“柏港评审会”。
- 规则：子项目、子系统、子组件、产品线或流程节点被直接描述时，必须单独成主体。
  例：“澜石门户正常，澜石门户消息台延迟”，两个名称都要抽取。
- 规则：父主体和更长同前缀子主体各有事实时，不要把子主体折叠进父主体。
  例：“岚河平台可登录；岚河平台审计台超时”，要抽取两个主体。
- 规则：只出现在父级背景、会议背景、旁注或地点里的名称，不单独建主体。
  例：“在沙河办公室讨论栖木发布”，主体不是“沙河办公室”。
- 规则：缺失项、附件、证据、前置条件、原因、指标、字段值或执行细节，不单独建主体。
  例：“南渡发布项目缺回滚说明”，主体是“南渡发布项目”，不是“回滚说明”。
- 规则：负责人、审批人和复核人是属性值，不是要单独建的主体。
  例：“鹭湾工单负责人是赵奕”，主体是“鹭湾工单”，不是“赵奕”。
- 规则：如果 X 因 Y 缺失而不能推进，主体是 X；Y 是原因。
  例：“岩庭上线因封板照片缺失暂停”，主体是“岩庭上线”。
- 规则：只有文本直接说明 Y 自己的状态、规则、负责人、决定或查询时，才把 Y 建主体。
  例：“封板照片由何组维护？”这时“封板照片”才可以成为查询主体。
- 规则：命名手册、清单或政策要求 X 补 Y 时，主体是这个治理工件。
  例：“栖梧准入手册要求项目补值班表”，主体是“栖梧准入手册”。
- 规则：通用记录词表示要查哪类记录，不是主体名称。
  例：“771009.SZ 的最新分析笔记”主体是“771009.SZ”，不是“分析笔记”。
- 规则：只有记录或文档有独立标题、编号、治理职责或维护状态时，记录本身才是主体。
  例：“沧澜交接记录由法务维护”，主体是“沧澜交接记录”。
- 规则：round、stage、date、session、version、phase、batch 等是记录标记，不是主体。
  例：“沧澜交接记录第二轮”仍归属“沧澜交接记录”。
- 规则：同一主体的历史记录和当前记录，使用同一个 identity_profile。
  例：“南枝策略之前宽松、当前收紧”，主体仍是“南枝策略”。
""".strip()



WORKER_INSTRUCTIONS: dict[str, str] = {
    "write_gate": f"""
判断原始输入是否应被接受进入长期记忆写入。
只返回 identity_profile drafts，不要创建 candidate memories。
规则：
- identity_profile drafts 只能使用 schema 定义的字段。
- {IDENTITY_PROFILE_RULES}
- 如果无法识别稳定主体，返回 rejected_no_identity_profile。
- `draft_id` 使用简短不透明引用，例如 `d1`、`d2`。
""".strip(),
    "extractor": f"""
从原始输入中抽取一个或多个 identity_profile drafts 和 candidate memories。
规则：
- identity_profile drafts 只能使用 schema 定义的字段。
- {IDENTITY_PROFILE_RULES}
- 如果无法识别稳定主体，返回 rejected_no_identity_profile 且不返回 candidates。
- `draft_id` 和 `candidate_id` 使用简短不透明引用，例如 `d1`、`d2`、`c1`、`c2`。
- 每个 candidate 的 `owner_draft_id` 必须精确复制一个已输出 draft ref。
- candidate memories 必须描述输入关于 owner subject 的陈述，不要复制无关上下文。
- 若输入可按 identity_profile 规则归属到命名稳定主体，就为该主体的陈述创建 candidate memory。
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
- {IDENTITY_PROFILE_RULES}
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
- {IDENTITY_PROFILE_RULES}
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
- {IDENTITY_PROFILE_RULES}
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
- stable_qualifiers 是身份边界证据；不同稳定身份边界应保持分离，除非 payload 给出明确 identity-equivalence evidence。
- 不要因为 document/policy/checklist/report/handbook artifact 约束、解释或提到 actor/system/project/person，就把二者合并。
- plan 与 project，或 plan 与 checklist/document/policy artifact，不应仅因短名相同或同属审批流程就合并。
- 不要仅因一个实体被另一个治理、阻塞或依赖，就合并两个实体。
- 如果一个实体是行动或被阻塞的对象，另一个是约束它的 rule、checklist、report、handbook、plan 或 requirement，应保持分离。
- 两个实体稳定 identity type 或稳定功能不同，即使共享流程或 issue，也 keep_separate。
- 只有当二者是同一具体主体的两个名称、别名或描述，并且它们的 memories 可归于同一 identity 而不丢失主体边界时，才 merge。
- merge 时选择两个候选中更合适的 survivor_entity_key。
- merge 时同时返回 survivor 的完整最终 V2 identity profile。
- merged_identity_profile 必须遵循 identity_profile 规则，不能是 partial patch。
- merged_identity_profile 不能是盲目并集；它必须描述一个连贯主体，只保留真正属于该主体的 aliases 和 qualifiers。
- 不要依赖代码追加 aliases 或 qualifiers；应在输出中包含所有应保留的 surface forms 和 stable qualifiers。
- 不要把 memory facts、blockers、owner values、requirements 或 current state 放入 merged_identity_profile。
- 不确定时返回 keep_separate。
""".strip(),
}

SAME_BATCH_RESOLVER_INSTRUCTIONS = WORKER_INSTRUCTIONS["same_batch_resolver"] + "\n\n" + WORKER_INSTRUCTIONS[
    "resolver"
]

WORKER_INSTRUCTIONS["same_batch_resolver"] = SAME_BATCH_RESOLVER_INSTRUCTIONS




IDENTITY_PROFILE_RULES_EN = """
[identity_profile extraction rules]
Goal: decide "who does this memory belong to" by finding the named noun that owns this memory.
identity_profile records only who that noun is, not what happened to it.

Overall judgment:
- Rule: Read the full input or query, then find the named noun that mainly owns this memory.
  Example: `Lorcan inspection handbook requires night-shift review` belongs to `Lorcan inspection handbook`.
- Rule: Do not first judge fact type or write value; identity extraction only answers "who".
  Example: `Southbranch policy retired the old threshold` still extracts `Southbranch policy` first.
- Rule: Reject identity extraction only when there is no reusable named noun.
  Example: `The risk feels high tonight` has no named subject and may be rejected.
- Rule: Reusable nouns include systems, documents, plans, teams, workflows, codes, people, events, tasks, or artifacts.
  Example: `Willowbank access checklist`, `Cloudridge settlement service`, and `Mira Lin` can be subjects.
- Rule: Market codes, security codes, fund codes, and ticker-like symbols can be subjects.
  Example: in `What does the latest note say about RQX.N?`, the subject is `RQX.N`.
- Rule: A ticket, case, work_order, or id field value in a structured record can be the subject when it owns state or blockers.
  Example: `ticket=QL-42B; blocker=missing photo` belongs to `QL-42B`, not `missing photo`.

`who` field rules:
- Rule: `who` is the short stable label for the same subject; write the complete named noun.
  Example: for `Maplebridge launch plan is waiting for regression window`, write `Maplebridge launch plan`.
- Rule: Keep a complete named phrase complete; do not split it into a bare name or generic description.
  Example: keep `Willowbank access checklist`, not `Willowbank` or `access record`.
- Rule: Same-prefix nouns with different roles must not be merged into one bare name.
  Example: `Cloudridge settlement service` and `Cloudridge settlement handbook` are different subjects.
- Rule: Role words that separate subjects must stay in `who`.
  Example: `Egret ticket` should use `Egret ticket`, not only `Egret`.
- Rule: A person's preferences, habits, requirements, or dislikes belong to that person.
  Example: `Nora Xu prefers Monday summaries` belongs to `Nora Xu`.
- Rule: `who` names only the subject; do not include current state, blocker, conclusion, metric, or time change.
  Example: `Fir risk policy` is valid; `Fir risk policy current threshold increased` is not a `who`.

`surface_forms` field rules:
- Rule: `surface_forms` must come directly from the input or query; do not invent aliases.
  Example: if the text says `Eastgarden access list`, do not write `Eastgarden permission document`.
- Rule: `surface_forms` should keep the complete source mention that proves the same subject.
  Example: if the text only says `Maplebridge launch plan`, keep `Maplebridge launch plan`.
- Rule: Do not add generic record words into `surface_forms` unless the record itself has an independent title.
  Example: `latest analyst note for RQX.N` belongs to `RQX.N`, not `latest analyst note`.

`stable_qualifiers` field rules:
- Rule: `stable_qualifiers` separates same-name or same-prefix subjects; use short stable terms only.
  Example: for `Willowbank access checklist`, use `access checklist` and `checklist`.
- Rule: `stable_qualifiers` must come from `who` or `surface_forms`; do not infer them from `definition`.
  Example: for `Jadebay release bulletin`, use `bulletin`; do not add `document` only from its definition.
- Rule: Role words that separate subjects must be added to `stable_qualifiers`.
  Example: `Egret ticket` should include `ticket` in `stable_qualifiers`.
- Rule: For Chinese compound role phrases, include both the longest stable phrase and the final role word.
  Example: for `枫桥上线计划`, include both `上线计划` and `计划`; for `洛川巡检手册`, include `手册`.
- Rule: Person names, stock codes, or unique names with no role word may have empty `stable_qualifiers`.
  Example: `Mira Lin does not want Friday releases` belongs to `Mira Lin`; qualifiers may be empty.
- Rule: `stable_qualifiers` must not contain record markers, sentences, current states, or fact summaries.
  Example: do not put `currently paused` or `round two` in `stable_qualifiers`.
- Rule: If Chinese 看板 is part of the subject name, add it to `stable_qualifiers`.
  Example: `墨池运营看板` should include `看板`.

`definition` field rules:
- Rule: `definition` defines what `who` is; it must not include memory facts.
  Example: `Jadebay release bulletin refers to the release bulletin for Jadebay` is valid; `requires approval chain` is not.
- Rule: `definition` must not include current state, result, blocker, owner value, or requirement content.
  Example: `Cloudridge settlement service refers to the settlement service for Cloudridge` is valid; `owner is Jules Wei` is not.
- Rule: `definition` defines the concrete subject; it is not a category label.
  Example: `Maplebridge launch plan refers to the launch plan for Maplebridge` is valid; only `named launch plan` is not.
- Rule: Person subjects must define the specific person, not only say `person`.
  Example: `Mira Lin refers to the person named Mira Lin` is valid; only `person` is not.

Multi-subject and boundary rules:
- Rule: When one input has several names, extract only names that are directly stated or queried.
  Example: if a meeting mentions `Slatecache service` but decides on `Alderport review`, extract `Alderport review`.
- Rule: Subprojects, subsystems, subcomponents, product lines, or workflow nodes must be subjects when directly described.
  Example: if `Stoneport portal` works but `Stoneport message panel` is delayed, extract both names.
- Rule: When a parent subject and a longer same-prefix child subject each have facts, do not fold the child into parent.
  Example: `Mistvale platform works; Mistvale platform audit panel times out` should extract both subjects.
- Rule: Names appearing only in parent context, meeting context, asides, or locations are not separate subjects.
  Example: in `discussed Grove launch in Riverroom`, `Riverroom` is not the subject.
- Rule: Missing items, attachments, evidence, prerequisites, reasons, metrics, field values, and details are not subjects.
  Example: `Southford rollout lacks rollback memo` belongs to `Southford rollout`, not `rollback memo`.
- Rule: Owners, approvers, and reviewers are attribute values, not separate subjects.
  Example: `Egret ticket owner is Jules Wei` belongs to `Egret ticket`, not `Jules Wei`.
- Rule: If X cannot proceed because Y is missing, X is the subject and Y is the reason.
  Example: `Ridgecourt launch paused because gate photo is missing` belongs to `Ridgecourt launch`.
- Rule: Create a subject for Y only when the text directly describes Y's state, rule, owner, decision, or query.
  Example: `Which team maintains gate photo?` can make `gate photo` the query subject.
- Rule: If a named handbook, checklist, or policy requires X to provide Y, the governing artifact is the subject.
  Example: `Grove entry handbook requires projects to add the duty roster` belongs to `Grove entry handbook`.
- Rule: Generic record words describe what to retrieve; they are not the subject name.
  Example: `latest analyst note for RQX.N` belongs to `RQX.N`, not `analyst note`.
- Rule: A record or document is the subject only when it has its own title, number, governance role, or state.
  Example: `Bluewater handover record is maintained by Legal` belongs to `Bluewater handover record`.
- Rule: round, stage, date, session, version, phase, and batch are record markers, not subjects.
  Example: `Bluewater handover record round two` still belongs to `Bluewater handover record`.
- Rule: Historical and current records for the same subject use the same identity_profile.
  Example: `Southbranch policy was loose before but is stricter now` still belongs to `Southbranch policy`.
""".strip()



WORKER_INSTRUCTIONS_EN: dict[str, str] = {
    "write_gate": f"""
Decide whether the raw input should be accepted for long-term memory ingest.
Return identity_profile drafts only; do not create candidate memories.
Rules:
- identity_profile drafts must use only fields defined by schema.
- {IDENTITY_PROFILE_RULES_EN}
- If no stable subject can be identified, return rejected_no_identity_profile.
- Use short opaque refs for `draft_id`, such as `d1`, `d2`.
""".strip(),
    "extractor": f"""
From the raw input, extract one or more identity_profile drafts and candidate memories.
Rules:
- identity_profile drafts must use only fields defined by schema.
- {IDENTITY_PROFILE_RULES_EN}
- If no stable subject can be identified, return rejected_no_identity_profile and no candidates.
- Use short opaque refs for `draft_id` and `candidate_id`, such as `d1`, `d2`, `c1`, and `c2`.
- Every candidate `owner_draft_id` must copy one emitted draft ref exactly.
- candidate memories must describe the input's statement about the owner subject, not raw copies of unrelated context.
- Every candidate memory must reference a valid owner_draft_id.
- If the input can be assigned to a named stable subject under identity_profile rules, create a candidate memory for the statement assigned to that subject.
- If the input primarily belongs to one subject and only incidentally mentions another subject, do not create a separate candidate memory for the incidental subject unless the input also contains a separate statement owned by that incidental subject.
- Named sub-projects, sub-systems, sub-components, or sub-artifacts that have their own independent durable facts (such as timeline, owner, status, or requirements) should be extracted as separate subjects even when they are mentioned within a parent subject's context.
- Mere presence in a meeting note, side mention, surrounding chatter, or contextual aside is not by itself a durable memory worth storing as a separate candidate.
  Example: `周会里顺手提到 Trellis service，但主结论是 Bastion rollout 当前主阻塞是审批链说明缺失。`
  Preferred: keep one candidate memory for `Bastion rollout 当前主阻塞是审批链说明缺失`, and do not create a separate memory like `Trellis service 在周会中被提到`.
  Example: `周会里顺手提到 Trellis service，另外确认 Trellis service 当前负责人是 Nia Chen。`
  Preferred: creating a memory for `Trellis service 当前负责人是 Nia Chen` is valid, because the side subject now has its own durable fact.
- If a phrase is only a detail inside another subject's statement, keep it inside that subject's candidate memory instead of creating a separate identity_profile or candidate memory for the phrase.
- For patterns like `X cannot proceed/confirm/launch/complete because Y is missing/incomplete/not submitted/not signed`, create a candidate memory for X that includes Y as the reason. Do not create Y as a separate subject unless the input also gives Y its own durable owner, rule, status, decision, requirement, lifecycle, version, or tracking state.
- If another named policy, protocol, checklist, manual, handbook, rule, or guide says X must provide Y, that named governing artifact can be a separate subject, while Y is still just the required item unless it has its own independent durable fact.
  Example: `Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。`
  Preferred: create one draft and one candidate memory for `Harborlane rollout`; keep `quay memo` as the missing reason inside that memory, not as its own subject.
  Example: `Harborlane checklist 要求所有 rollout 在 cutover 前补齐 quay memo。`
  Preferred: create one draft and one candidate memory for `Harborlane checklist`; keep `quay memo` as the required item inside the checklist memory.
  Example: `Harborlane quay memo 当前负责人是 Ivo Tan。`
  Preferred: creating a separate `Harborlane quay memo` subject is valid, because the memo now has its own durable owner fact.
- If one message, email, table, checklist, or bullet list contains multiple clearly separate durable conclusions about different stable artifacts that share a prefix, keep each full subject phrase separate instead of collapsing them into one shared prefix subject.
- Different role or artifact nouns such as `docket`, `manual`, `review`, `plan`, `bulletin`, or `register` can mark different stable subjects when the text gives each one its own durable blocker, owner, requirement, decision, or target.
  Example email: `Opal pier follow-up: Opal pier docket 当前缺 mooring appendix；Opal pier manual 当前要求补 mooring appendix 和 slip witness note；Opal pier review 当前负责人是 Selene Sol；Opal pier plan 当前目标是周五前补完 berth packet。`
  Preferred: create four separate drafts and four candidate memories, because `docket`, `manual`, `review`, and `plan` are four different stable artifact subjects with different durable claims.
- If the input uses structured field-style formatting such as `record: ...`, `phase: ...`, `entity=...`, `rule: ...`, `state=...`, or `owner: ...`, treat those fields as strong structure rather than as formatting noise.
- A short structured record can still be a durable memory when it names a stable subject and a durable rule, blocker, owner, state, or requirement.
  Example fields: `record: Coronet handover notice`, `phase: history`, `rule: teams could attach seal note within 24 hours after shift`.
  Preferred: keep this as an earlier durable rule memory for `Coronet handover notice`, not as disposable formatting noise.
- If the input is a time-bounded or session-bounded historical record about a concrete subject, keep the subject in the draft and summarize the record as a candidate memory instead of collapsing it into a generic event.
- If the input includes explicit session, stage, round, date, or version markers, keep those markers inside the candidate memory title, summary, or content so later historical records remain distinguishable.
- If the input includes explicit session, stage, round, or date markers, populate record_markers so later resolution can distinguish historical records without guessing.
- Preserve important detail in each candidate memory, but do not emit repeated, near-duplicate, or trivially rephrased candidate memories.
- Preserve the original language of the input when writing title, summary, and content. Do not silently translate Chinese into English or English into Chinese unless the source itself is bilingual.
- Keep critical concrete phrases visible in memory content, such as blockers, dates, times, document names, explicit requirements, and operational conditions.
- For one long report, long history, or long debate record about one subject, default to one detailed primary memory.
- Long historical or review records can be durable even when they describe tradeoffs, rationale, conditions, open questions, recovery plans, pause reasons, or decision constraints instead of a simple blocker, owner, or rule.
- Do not reject a named long historical/review record merely because it is analytical or balanced; extract the concrete durable conclusion, tradeoff, conditions, or unresolved points that would answer a future query about that record.
  Example long review: `Meridian portal refresh` weighs accepting short-term migration and review effort in exchange for one entry point and lower duplicate maintenance.
  Preferred: emit one detailed memory preserving both sides of the tradeoff, because a future query may ask what tradeoff the review recorded.
- Only emit multiple candidate memories when the source contains multiple clearly separate claims that would answer materially different future queries.
- Different sections, headings, bullets, or supporting arguments of the same conclusion must stay inside one memory content instead of being split into separate memories.
- If one long document contains an earlier rule, a current rule, and an appendix/amendment/addendum that only adds another still-valid requirement to that same current rule, emit one earlier historical candidate plus one current candidate that already includes the additive requirement. Do not emit a second separate current candidate that merely repeats the stricter rule before adding the supplement.
- If a correction note, appendix, addendum, follow-up attachment note, or supplement only tightens or extends the same current named artifact rule, fold that detail into the same current candidate memory during extraction instead of splitting it into another parallel current candidate.
  Example long document: `Grayshore bulletin` earlier allowed berth note filing within 14 hours after release, the current section now requires filing before release, and an appendix adds `quay owner signature`.
  Preferred: emit one earlier historical candidate plus one current candidate that already includes both `before release` and `quay owner signature`, not three separate candidates.
""".strip(),
    "linker": f"""
Decide whether the identity_profile draft can be uniquely bound to one of the provided entity candidates.
Rules:
- {IDENTITY_PROFILE_RULES_EN}
- Only choose from provided entity candidates.
- Compare the draft against identity_profile, display_name, and representative memory summaries together.
- Use `who`, `surface_forms`, and `stable_qualifiers` together as identity signals. Do not treat stable_qualifiers as the only place where stable qualifiers can appear.
- Return link_existing only when one candidate is clearly the same subject and the binding is specific enough to exclude the other candidates.
- For write mode, prefer link_existing whenever one candidate is still the best match after using stable_qualifiers and representative memories.
- If the draft and the best candidate share the same surface form but clearly differ in stable identity or function, do not merge them into one entity.
- In write mode, first check whether the draft and candidate have the same identity granularity.
- Do not link two entities merely because they share a prefix, topic, or underlying domain entity.
- Return link_existing only when the draft and candidate could both own the same durable memories without losing a subject boundary.
- In write mode, when the surface form matches but the role-like identity differs, prefer create_new over forcing link_existing.
  Example: draft `Meridian 项目`, candidate A `Meridian 项目`, candidate B `Meridian 知识文档`.
  Preferred: in write mode, create a new entity for the document if the new draft clearly refers to the document rather than the project.
- In write mode, if the draft and the best candidate share the same named subject or artifact and the only meaningful difference is temporal wording such as `之前`, `当前`, `现在`, `later`, `already changed`, or `已经变成`, treat them as the same entity. Temporal state changes are not stable identity differences.
  Example: earlier draft `Saffron portfolio review 之前主风险是 duration mismatch。`; later draft `Saffron portfolio review 当前主风险已经变成 liquidity buffer drawdown。`
  Preferred: link both drafts to the same `Saffron portfolio review` entity. The risk changed, but the subject identity did not.
- For write mode, return create_new only when all provided candidates clearly refer to different subjects.
- For query mode, if no candidate clearly matches, return cannot_resolve.
- For query mode, return ambiguous only when multiple candidates remain genuinely plausible after using all provided context.
- In query mode, use any stable identity qualifier in the draft to exclude candidates with a conflicting identity or function.
- In query mode, if the stable identity qualifier in the draft matches exactly one candidate and conflicts with the others, return link_existing for that candidate instead of ambiguous.
- In query mode, if the draft's `who` or one of its surface_forms already carries a stable type qualifier that matches one candidate and excludes the others, return link_existing instead of ambiguous.
- In query mode, a broader stable type qualifier in the draft can still match a candidate with a more specific subtype when that qualifier rules out the conflicting candidates.
  Example: query draft `Verdigris rollout`, candidate A `Verdigris rollout`, candidate B `Verdigris checklist`.
  Preferred: link the rollout candidate. `rollout` and `checklist` are stable identity qualifiers, not cosmetic wording differences.
  Example: query draft `Summit plan`, candidate A `Summit plan`, candidate B `Summit project`, candidate C `Summit checklist`.
  Preferred: link the plan candidate. `plan`, `project`, and `checklist` are stable identity qualifiers and should not collapse into one another.
- A named policy, handbook, rule, guideline, report, project, document, or plan can itself be a stable subject when the query is asking about that named artifact's requirements, decisions, gaps, or constraints.
- A named checklist, rollout, service, or runbook can also be a stable subject, and its role noun should be treated as part of stable identity when it distinguishes the subject from another same-surface artifact.
- If two candidates share the same short surface form but one is a project/system and the other is a document/report/policy/plan/checklist artifact, treat that role difference as a stable identity difference rather than a cosmetic wording difference.
- When the draft names a concrete artifact and asks what it requires, says, or mandates, do not reject the query just because the stable_qualifiers is sparse.
  Example: query draft `Gateway policy`, query `Gateway policy 有什么要求？`
  Preferred: treat `Gateway policy` as a stable subject and link it to the named policy entity instead of cannot_resolve.
""".strip(),
    "resolver": """
Compare all candidate memories to existing memories under the same entity.
Return one resolution item per candidate memory.
Rules:
- In candidate_memories, candidate_id is an opaque short ref like `c1`.
- In existing_memories, memory_id is an opaque short ref like `m1`.
- In your output, candidate_id must copy one provided candidate ref exactly.
- In your output, target_memory_id must copy one provided existing-memory ref exactly.
- Never invent refs, rewrite refs, or output raw internal ids.
- refresh means the candidate restates and strengthens an existing memory.
- replace means the candidate supersedes an older memory with a newer one.
- coexist means both memories can stand together.
- stale means an existing target should be marked stale.
- If no existing memory clearly matches, use create.
- Use record_markers when they are provided.
- If the candidate is a time-bounded or session-specific record that is not a near-duplicate of an existing memory, prefer coexist over refresh.
- If the candidate and an existing memory have different session, stage, round, or date markers, prefer coexist unless the new record explicitly says it supersedes or replaces the older one.
- If there are no meaningful historical markers and the new candidate clearly updates the same standing fact, prefer replace over coexist.
- If an existing memory has explicit record_markers and the new candidate does not, do not refresh the bounded historical record into the new candidate just because they overlap. Keep the bounded historical record unless the new candidate explicitly says it is the same bounded record.
- If the new candidate states the newer current state, current blocker, current owner, latest decision, or settled conclusion for the same tracked subject, and an existing memory describes an earlier state of that same tracked subject, prefer replace so the earlier state becomes superseded via updates.
- If one memory says the subject previously had blocker or state A, and a newer memory says the subject now has blocker or state B, treat that as one tracked subject state changing over time. Prefer replace so the earlier state becomes superseded via updates, unless the input clearly presents the two states as parallel alternatives that should remain simultaneously active.
- When an earlier memory is phrased as `之前卡在 A` and a newer memory is phrased as `当前主阻塞已经变成 B`, treat that as the same tracked blocker chain changing over time. Prefer replace so the earlier blocker becomes superseded via updates rather than leaving both states active.
- Prefer replace for earlier/current or before/now transitions when both memories answer the same practical question about the subject's tracked blocker, owner, requirement, or standing status, even if the older memory is phrased as history and the newer one is phrased as the current situation.
  Example: existing `Cedar review 之前卡在 database migration timeout。`; new `Cedar review 当前主阻塞已经变成 rollback approval missing。`
  Preferred: replace the earlier blocker with the newer current blocker, because the tracked blocker changed over time.
  Example: existing `Cedar review 之前卡在 schema freeze mismatch。`; new `Cedar review 当前主阻塞已经变成 approval packet missing。`
  Preferred: replace, because both memories describe the same tracked blocker chain at different times rather than two simultaneously active blockers.
- When one bounded historical record is later followed by an unbounded current summary of what the subject has now settled on, keep both memories instead of collapsing the historical record into the current summary.
- When earlier bounded records present alternative positions inside a session or review, keep those historical alternatives even if a later current summary states what the subject finally settled on.
  Example: existing bounded record `Session review-9 Round 1: 可以先按原窗口上线。`; new bounded record `Session review-9 Round 2: 必须先补回滚说明。`
  Preferred: coexist, because these are historical alternatives inside one bounded review.
  Example: existing bounded historical record `Round 2: 必须先补回滚说明。`; new current summary `当前决定已经变成先补回滚说明再排期上线。`
  Preferred: keep both, because the later summary states the settled conclusion while the bounded record remains useful history.
- If one candidate is a standing conclusion and another record is primarily evidence, explanation, or supporting detail for that conclusion, keep them as separate memories instead of collapsing them into one refresh.
- If one memory states the standing blocker, requirement, owner, or current state and another memory gives logs, observations, rationale, or supporting detail for that same state, keep both memories so later edge construction can connect them.
  Example: existing `Subject 当前主阻塞是配置漂移。`; new `部署日志显示配置漂移导致签名校验失败。`
  Preferred: keep both memories instead of refresh or replace, because the first memory is the standing blocker and the second memory is direct evidence explaining that blocker.
- If the new text explicitly says the current owner, blocker, requirement, or standing state has changed, prefer replace.
- If a newer memory adds another still-valid current requirement, condition, attachment, or prerequisite for the same handbook/checklist/policy/document rule without revoking the earlier requirement, prefer refresh instead of replace, and keep both the earlier requirement and the new supplement in the refreshed memory text.
- When the newer text is a supplement such as `最新补充`, `还必须`, `另外要求`, or a clearly additive current rule, treat it as cumulative unless the text explicitly says the earlier requirement no longer applies.
- If a correction note, amendment, appendix, addendum, or follow-up attachment note adds another still-valid requirement for the same current named artifact rule, treat it as cumulative current-state detail rather than a separate parallel standing rule. Prefer refresh so the current active rule memory accumulates the additive requirement.
  Example: existing `Heliotrope handbook 当前要求 fallback schedule 变更必须先经 incident lead 审批。`; new `Heliotrope handbook 最新补充：所有审批记录还必须附在 change packet 中。`
  Preferred: refresh the current-rule memory and preserve both `incident lead 审批` and `change packet` in the updated memory, because the newer note adds a complementary requirement instead of replacing the earlier one.
  Example: existing `Morrowfield register 当前要求每个 quay note 必须在 release 前提交。`; new `Appendix to Morrowfield register: every quay note must also include berth owner signature.`
  Preferred: refresh the current rule memory so the current active rule keeps both `before release` and `berth owner signature`, while the earlier looser rule remains a separate superseded historical memory.
- If a later current summary follows earlier bounded rounds or review alternatives, do not let the current summary delete those bounded historical records unless the new text explicitly says those bounded records were duplicate restatements of the same round.
- If two memories answer the same practical question in the same unbounded subject context, and the newer memory explicitly says the tracked blocker, requirement, owner, or standing state has changed from one concrete value to another, prefer replace even when both states are still useful history.
- For tracked blockers or tracked owners, `当前...已经变成...` should usually mean the earlier standing fact is superseded by the newer one.
  Example: existing `Summit rollout 当前主阻塞是数据库迁移失败。`; new `Summit rollout 当前主阻塞已经变成签名校验失败。`
  Preferred: replace, because both memories answer the same current-blocker question for the same subject, and the newer memory explicitly says the blocker changed.
- If structured records explicitly mark `phase: history` or another earlier-rule marker, keep that earlier rule/state queryable instead of dropping it as redundant.
- If structured records explicitly mark `phase: current` and a later `phase: supplement` for the same standing rule, prefer refresh so the current rule memory accumulates the supplement while the earlier historical rule remains separate.
  Example structured records: `record: Falconer handover notice`, `phase: history`, `rule: teams could attach seal note within 24 hours after shift`; then `phase: current`, `rule: every seal note must be completed before handover`; then `phase: supplement`, `rule: every seal note must also be attached to dispatch packet`.
  Preferred: keep one earlier historical rule memory plus one current active rule memory refreshed with the supplement.
- If an earlier unbounded document, handbook, charter, manual, bulletin, guide, or rule memory says the subject previously allowed action A, and a newer unbounded memory for the same artifact says the subject now requires approval, attachment, signoff, or another gate for that same action, treat that as one artifact's rule evolving over time. Prefer replace so the earlier rule becomes superseded via updates.
- If the older memory describes an earlier allowance or looser rule and the newer memory describes the current stricter rule for the same named artifact and same operational action, prefer replace even when the older rule is still useful history.
  Example: existing `Morrow charter 之前允许团队直接修改 transfer ledger。`; new `Morrow charter 当前要求所有 transfer ledger 变更必须先经 shift lead 审批。`
  Preferred: replace, because this is one artifact's rule evolving from an earlier allowance to the current stricter rule.
- If one long document simultaneously contains an earlier allowance, a current stricter rule, and an appendix/addendum/supplement for that same current rule, resolve it into one historical memory plus one current active memory refreshed with the additive requirement, not three separate standing memories.
- If one long document contains both an earlier allowance and a current stricter rule for the same named artifact, do not leave them as two peer active memories linked only by `contradicts`. Prefer replace so the earlier rule becomes superseded history linked by `updates`, while the current stricter rule remains the active head.
  Example long document: `Grayshore bulletin` says it earlier allowed berth note filing within 14 hours after release, the current section now requires filing before release, and an appendix adds `quay owner signature`.
  Preferred: keep one earlier superseded historical memory plus one current active memory refreshed with `quay owner signature`, linked by `updates`; if there is no existing persisted memory yet, let the newer current candidate target the earlier candidate_id from the same batch so the batch still resolves into superseded history plus one active head.
- Preserve important detail from the candidate memory instead of aggressively shortening it.
- Preserve critical concrete phrases from the source rather than replacing them with more generic rephrasings.
- Keep the memory in the same primary language as the input whenever possible.
- Do not emit repeated or near-duplicate resolution items for the same underlying claim.
- If multiple candidate memories from the same input are overlapping, keep only the most complete one and omit the near-duplicate ones from the output.
- One long report or one long debate record should usually resolve to one final memory unless there are clearly separate retrievable claims.
- target_memory_id may point either to an existing memory_id or to an earlier candidate_id from the same batch when the newer candidate should replace, refresh, or stale that earlier same-batch candidate.
- When using an earlier candidate_id from the same batch as target_memory_id, only do so for a clearly overlapping tracked subject where the later candidate is the newer current head or the more complete current version.
- If one batch contains an earlier historical candidate and a newer current candidate for the same named artifact or tracked blocker chain, prefer letting the newer candidate replace the earlier candidate directly inside the batch instead of leaving both as peer active memories.
- For same-batch earlier/current evolution, do not emit two `create` items that would leave both memories active when the newer candidate is clearly the current head.
- In that situation, keep the earlier historical candidate as the predecessor and let the newer current candidate use `action=replace` with `target_memory_id=<earlier candidate_id>`.
- Never set target_memory_id to the candidate's own candidate_id.
- The examples below use symbolic ids for readability; in the actual output you must use the exact short refs from the payload.
  Example same-batch candidates:
  - `cand_earlier`: `Grayshore bulletin 之前允许团队在 release 后 14 小时内提交 berth note。`
  - `cand_current`: `Grayshore bulletin 当前要求 berth note 必须在 release 前提交，并且必须包含 quay owner signature。`
  Preferred outputs:
  - `cand_earlier -> action=create`
  - `cand_current -> action=replace, target_memory_id=cand_earlier`
  This should produce one superseded earlier memory plus one active current memory linked by `updates`, not two peer active memories.
- When existing_memories include created_at timestamps, treat them as supplementary hints for temporal ordering only. The primary basis for determining historical vs current status must always be the explicit temporal wording inside the memory content itself (e.g., `之前允许`, `当前要求`, `最新补充`, `earlier`, `current`, `supplement`). Do not rely solely on created_at order to decide logical precedence.
- When a supplement candidate (marked by phrases like `最新补充`, `还必须`, `also required`, `appendix`, `addendum`, or `follow-up attachment`) appears alongside both an earlier historical rule and a later current active rule, the supplement MUST target the current active rule (action=refresh or replace with target=current), never the earlier historical rule. The historical rule remains separate and superseded; only the current active rule accumulates supplements.
  Example same-batch candidates with timestamps:
  - `cand_history` (created_at=10:00): `Northport guide previously allowed teams to file checklist within 6 hours after cutoff.`
  - `cand_current` (created_at=10:01): `Northport guide currently requires every checklist to be submitted before cutoff.`
  - `cand_supplement` (created_at=10:02): `Northport guide addendum: every checklist must also be attached to delivery manifest.`
  Preferred outputs:
  - `cand_history -> action=create`
  - `cand_current -> action=create`
  - `cand_supplement -> action=refresh, target_memory_id=cand_current`
  The addendum targets the current active rule, not the historical predecessor.
""".strip(),
    "query_planner": f"""
Extract query identity_profile drafts and short query rewrites.
Rules:
- {IDENTITY_PROFILE_RULES_EN}
- Each query_identity_profile_draft must also include `query_text`, which is the shortest standalone sub-query from the original query that asks only about that draft's subject.
- For a single-subject query, `query_text` should usually be the full original query.
- For a multi-subject query, split the original query into one draft per subject and give each draft its own `query_text` that omits the other subjects.
  Example: `Atlas 发布项目 当前主阻塞是什么？Atlas 文档 当前缺什么？`
  Preferred drafts:
  - `{{"who":"Atlas 发布项目","query_text":"Atlas 发布项目 当前主阻塞是什么？"}}`
  - `{{"who":"Atlas 文档","query_text":"Atlas 文档 当前缺什么？"}}`
  Do not reuse the full multi-subject query as `query_text` for every draft.
- Treat concrete names in the query as valid stable subjects whenever they refer to a bounded subject with stable identity.
- If the query already contains one concrete named subject and the rest of the query only asks for its requirements, disagreements, reasons, blockers, history, or conditions, keep that named subject as the identity target instead of rejecting the query.
- If no stable subject can be identified from the query, return rejected_no_identity_profile.
- Keep query_rewrites short and focused.
- query_focus should only summarize retrieval intent, not final answer content.
- query_focus.time_intent must be one of current, latest, history, or unspecified.
- `graph_expansion_intent` is the query_focus field that controls dynamic cross-entity graph expansion.
- query_focus.graph_expansion_intent must be one of `entity_local`, `cross_entity`, or `uncertain`.
- Decide graph expansion by the evidence scope required to answer, not by matching query words.
- Use `entity_local` when the query can be answered from the target entity's own recalled memory and local
  evidence, without needing another entity's memory to explain, constrain, or extend the answer.
- Use `cross_entity` or `uncertain` when the answer requires external constraints, dependencies, governing evidence, or other-entity state to explain why the target answer holds.
- Use `cross_entity` when the query asks for why/how, dependency chains, surrounding constraints, related gaps,
  external requirements, or other-entity evidence that may explain the target subject.
- Use `uncertain` when the query has a stable target but you cannot confidently decide whether other-entity
  memory may be needed.
- Set query_focus.graph_expansion_reason to one short reason for that semantic decision.
- Do not decide graph expansion with keyword matching. Judge the retrieval need from the full query intent and
  the subject relationships implied by the query.
- Use history when the query is about prior records, earlier states, or change over time.
- If the query explicitly asks both what happened earlier and what is true now, still use history so recall expands the evolution instead of collapsing to only the current state.
  Example: `Cedar review 之前卡过什么，当前又变成什么？`
  Preferred: time_intent=history, because the query explicitly asks for both earlier and current states.
- Use latest when the query is about the newest known conclusion.
- Use current when the query is about the current standing state.
- External context includes other entities, documents, rules, handbooks, workflows, checklists, protocols, memos, upstream or downstream dependencies, constraint sources, adjacent risks, supplemental requirements, or neighboring records.
  Example: `除了当前主风险外，Arbor portfolio 还需要关注什么？`
  Preferred: keep `Arbor portfolio` as the identity target, because the user is asking for relevant context outside the primary entity's own current-state memory.
  Example: `Nimbus rollout 当前阻塞之外，还有哪些外部上下文？`
  Preferred: keep `Nimbus rollout` as the identity target, because the answer may depend on another workflow, document, rule, dependency, or neighboring record.
- If the query asks about historical disagreement and also asks why the subject later settled on the current conclusion, keep the primary subject as the identity target whenever an external handbook, checklist, policy, rule, or governing artifact could explain the settlement.
  Example: `为什么 Topaz transfer review 从历史分歧收敛到现在的结论？`
  Preferred: use `time_intent=history`, because the answer may depend on an external governing artifact that explains why the later conclusion became binding.
- If the query asks why a current blocker exists and also asks for related gaps, missing prerequisites, dependencies, or surrounding conditions, preserve both the direct explanation intent and the related-context intent in the rewrites instead of collapsing everything into a single generic why question.
- If the query asks for requirements, conditions, missing items, blockers, or preconditions, keep those concrete phrases visible in the rewrites instead of replacing them with generic wording.
- A named policy, handbook, guideline, report, project, document, or plan can be the subject of the query when the user asks what it requires, says, blocks, or contains.
  Example: `Gateway policy 有什么要求？`
  Preferred: keep `Gateway policy` as the stable subject, set time_intent to unspecified or current, and rewrite toward the concrete requirement question instead of rejecting the query.
- A named team, working group, crew, committee, or operations unit can also be the subject of the query when the user asks what it plans to do, what it will do next, what it owns, or what it is blocked by.
  Example: `Palisade team 接下来准备怎么做？`
  Preferred: keep `Palisade team` as the stable subject and preserve the future-plan wording instead of rejecting the query.
- Preserve concrete role nouns such as `rollout`, `service`, `checklist`, `runbook`, `policy`, `document`, `handbook`, or `plan` inside the identity draft when those nouns distinguish one same-surface subject from another.
  Example: `为什么 Verdigris rollout 还不能切换到新流程？`
  Preferred: keep `Verdigris rollout` as the identity target. Do not collapse it to bare `Verdigris` when another subject like `Verdigris checklist` also exists in the same scope.
  Example: `为什么 Summit plan 现在不能进入审批？`
  Preferred: keep `Summit plan` as the identity target. Do not collapse it into `Summit project` or `Summit checklist`, because `plan`, `project`, and `checklist` are different stable artifact roles.
- If the query asks what a named policy, rule, handbook, or document requires, keep that named artifact as the primary subject instead of rejecting the query for lacking a person/system style subject.
- If the query asks what a named team or working group will do next, keep that group name as the primary subject instead of rejecting the query for lacking a system or artifact role noun.
""".strip(),
    "cross_entity_query_builder": """
Generate a small set of retrieval query texts for finding memories that belong to other entities but may explain, constrain, depend on, or relate to the frontier memories.
Rules:
- Use the frontier memories and frontier observations together.
- Produce short retrieval-oriented query texts, not full answers.
- Prefer concrete shared concepts, requirements, constraints, missing prerequisites, upstream/downstream dependencies, document names, policy names, and operational conditions that could appear in another entity's memory.
- If the frontier memory names a blocker and the observations explain why that blocker exists, preserve both the blocker phrase and the explanatory phrase in the retrieval queries.
  Example frontier memory: `Lantern rollout 当前仍不能上线，因为审批链说明还没有补齐。`
  Example frontier observation: `Release governance guide 要求所有生产发布在执行前必须补齐审批链说明。`
  Good queries: `审批链说明 生产发布 要求`, `release governance guide 审批链说明`, `上线 受 审批链说明 约束`
  Example frontier memory: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example frontier observation: `Relay service 当前仍处于批量补数状态，尚未恢复稳定输出。`
  Good queries: `数据源 恢复 稳定输出`, `data sync service 批量补数 稳定输出`, `上游服务 尚未恢复 稳定输出`
- If the frontier memory refers to an external requirement, missing document, policy, checklist, approval chain, upstream service, or neighboring gap, turn that into one or more retrieval queries that another entity's memory could match directly.
  Example frontier memory: `Heliotrope rollout 当前主阻塞是配置漂移。`
  Example frontier observation: `Baseline handbook 目前还缺少配置基线校验流程。`
  Good queries: `配置漂移 配置基线校验流程`, `configuration baseline handbook 配置基线校验流程`, `相关缺口 配置基线校验流程`
- If a direct governing artifact names multiple still-required items for the same subject, preserve those sibling required items in the retrieval queries instead of searching only for the one currently mentioned blocker.
- If one of those sibling required items could itself have an upstream attachment, approver, seal, roster, or other prerequisite, include that sibling item in at least one retrieval query so another artifact can extend the chain.
  Example frontier memory: `Rookery project 当前还不能推进，因为 transfer note 缺失。`
  Example frontier observation: `Parallax checklist 要求 transfer packet 补 transfer note 和 seal ledger；Keystone manual 要求 seal ledger 附 reviewer seal。`
  Good queries: `transfer note Parallax checklist`, `seal ledger reviewer seal Keystone manual`, `transfer packet seal ledger`
- If the frontier memory asks for related gaps, neighboring missing prerequisites, or adjacent readiness issues beyond the main blocker, emit narrow retrieval queries for any explicitly named missing validation flow, guardrail, prerequisite, or readiness process.
- Do not invent external entities that are not implied by the input.
- Do not repeat near-duplicate query texts.
- Return 2-6 query texts.
- Keep the queries in the same primary language as the input evidence whenever possible.
- If the frontier memory is itself only a secondary artifact/process-gap note, do not expand broadly into all nearby operational subjects just because they share the same incident or recovery area.
- In that case, only emit cross-entity query texts when the frontier memory explicitly names an external subject, direct dependency, or direct governing artifact that it is talking about.
- If the frontier memory does not explicitly name another subject and only describes an internal gap of its own artifact, returning an empty or very narrow query set is better than pulling in loosely related surrounding entities.
  Example frontier memory: `Response runbook 当前还缺少 escalation owner。`
  Good behavior: if this memory does not explicitly name another subject, do not expand into surrounding rollout or service entities just because they belong to the same broader recovery situation.
- If the frontier observation only gives a distractor artifact and not the concrete external failing state, do not let that artifact dominate the retrieval queries.
  Example frontier memory: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example frontier observation: `Escalation handbook 当前缺少 on-call escalation path。`
  Good behavior: do not let the handbook dominate retrieval for the upstream-impact question; prefer query texts that search for the actual external failing service or source state.
""".strip(),
    "answer_composer": """
Compose the final user-facing answer using the candidate memories, relation edges, and observations.
Rules:
- Keep the answer concise and directly responsive to the query.
- Treat every memory in `memories` as a candidate. There is no preselected answer subset.
- Choose the evidence yourself from the full candidate set and relation graph.
- First decide whether the query is asking for the target subject's own current answer, or asking for explanation chain, dependency chain,
  upstream constraints, or surrounding context.
- If the query is asking only for the target subject's own current requirement, status, goal, decision, blocker, or content, answer only with
  that direct target-level answer.
- In that narrow-query case, `supports` and `related_to` memories may help you understand the evidence, but they do not automatically belong in
  the final answer text.
- Return citations using only memory_id and observation_id values present in the input payload.
- If citations are provided in your output, use them to express evidence in natural language instead of listing raw ids.
- Keep evidence short; one short evidence sentence is enough unless the query explicitly asks for more.
- Do not invent facts outside the provided payload.
- Each memory may include `evidence_role`, `relation_types`, and `relation_edges`; use these fields to decide whether the memory is direct evidence, supporting evidence, conflicting evidence, update/history evidence, or weak background.
- Use `seed`, `updates`, and `contradicts` memories as answer evidence when they address the query.
- If the query requires an explanation chain, dependency chain, or condition-satisfaction answer, do not truncate after the seed memory when linked evidence supplies necessary external constraints or prerequisites.
- Treat `supports` memories as explanatory context. Use them in the answer only when the query asks for reasons, dependencies, external
  constraints, why the current answer holds, or what still needs to be satisfied beyond the direct target answer.
- For narrow target-property questions, keep the answer scoped to the requested target. Do not add a supporting memory's
  own independent state as an extra answer clause.
- Treat memories that are only `related_to` as background. Do not add facts from them to the answer unless the query explicitly asks for
  related, adjacent, surrounding, or background context.
- When a memory is `background_only` or only `related_to`, do not promote it into an answer claim just because it is semantically relevant.
- If a supporting or related memory only adds an upstream detail for one sub-item inside the target answer, do not include that upstream detail
  unless the query explicitly asks for that deeper layer.
- A governing handbook/manual/policy/checklist can be relevant without being part of the answer. Mention it only when the query actually asks
  for the governing reason, upstream rule, dependency chain, or still-required next layer.
- First decide whether long evidence has one central driver or several co-central drivers.
- When the query asks for key drivers, core risks, or main reasons, enumerate the top points explicitly and keep the important evidence terms visible instead of replacing them with generic paraphrases.
- If a critical term appears in the evidence, prefer repeating that term directly in the answer.
- If the query asks for the most important, core, or main point, answer with only the 1-3 central points instead of broadening into a full summary.
- Do not collapse co-central drivers into one generic umbrella when the evidence presents them as distinct reasons.
- Avoid adding peripheral details when the query is narrowly focused on the top driver, top risk, or main reason.
- If the evidence gives a specific manifestation of a broader concept, name both in the answer using `broad concept (specific manifestation)` style when possible.
- Prefer a `broader concept (specific manifestation)` form only when the broader concept is genuinely supported by the evidence.
- Keep the wording aligned with the language of the evidence. Do not translate away key source phrases when they are already concise and clear.
- When the query asks for explicit requirements, conditions, missing items, blockers, or timings, preserve those concrete phrases directly in the answer.
- Example narrow query:
  Query: `Lattice checklist 当前要求补齐什么？`
  Seed evidence: `Lattice checklist requires transfer note and seal ledger.`
  Related evidence: `Lattice handbook says seal ledger must include reviewer seal.`
  Preferred answer: `Lattice checklist 当前要求补齐 transfer note 和 seal ledger。`
  Not preferred: adding `reviewer seal`, because that is a deeper upstream detail rather than the direct checklist answer.
- Example narrow query:
  Query: `Merrow plan 当前目标是什么？`
  Seed evidence: `Merrow plan aims to finish the launch packet this week.`
  Related evidence: `Merrow register requires the launch packet to include duty roster.`
  Preferred answer: `Merrow plan 当前目标是本周完成 launch packet。`
  Not preferred: adding `duty roster` unless the query asks what the packet still depends on.
- Example explanation query:
  Query: `为什么 Lattice checklist 还不满足？`
  Seed evidence: `Lattice checklist requires transfer note and seal ledger.`
  Supporting evidence: `Lattice handbook says seal ledger must include reviewer seal.`
  Preferred answer: it is valid to mention both the checklist requirement and the handbook's extra reviewer-seal requirement, because the query is asking why the requirement is still not satisfied.
- Example dependency query:
  Query: `Merrow plan 要完成目标还依赖什么？`
  Seed evidence: `Merrow plan aims to finish the launch packet this week.`
  Related evidence: `Merrow register requires the launch packet to include duty roster.`
  Preferred answer: it is valid to mention `duty roster`, because the query is explicitly asking for dependencies rather than only the plan's direct goal.
- If the answer depends on multiple linked artifacts, prefer this order:
  1. the subject's immediate blocker or missing item
  2. the direct governing artifact that requires it
  3. only then any more upstream handbook, policy, or supplement
- The linked-artifact expansion rules below apply only when the query actually needs that longer chain.
- Do not expand to the full chain for a narrow target-property query if the target-level answer is already complete without that chain.
- If the query asks for both historical disagreement and the current settled reason, include one short sentence for the disagreement and one short sentence naming the external handbook/checklist/policy when that artifact explains why the current conclusion now holds.
- If the current settled conclusion matches a named external handbook, checklist, policy, or rule in the evidence, explicitly say that the current conclusion now follows or is constrained by that artifact instead of only citing the historical round outcome.
- For history/current disagreement answers, do not rely on citations alone to imply the governing artifact. If a named handbook, decree, checklist, policy, or rule explains the settlement, say that artifact name in the answer text.
  Example evidence: `Juniper review` historically disagreed about whether it could proceed, but now requires a `variance ledger`; `Fathom handbook` also requires that ledger before release.
  Preferred answer: say both the historical split and that `Fathom handbook` is the external reason the current decision settled on the stricter requirement.
  Example evidence: `Topaz transfer review` historically split over whether it could proceed, but now requires a `ballast note`; `Harbor decree` independently requires that `ballast note`.
  Preferred answer: explicitly say that `Harbor decree` is the external reason the current decision settled on the stricter requirement.
- If an earlier historical position is represented by a short phrase such as `initial launch slot`, keep that short phrase visible in the answer when possible instead of replacing it with a broader paraphrase.
  Example evidence: `Cairn transfer review` historically supported the `initial launch slot`.
  Preferred answer: keep `initial launch slot` visible, or use a very close equivalent, rather than replacing it with a vague phrase like `the earlier approach`.
- Do not skip the direct governing artifact when it is present in the evidence.
- Do not skip the concrete upstream required item either when that item explains why the direct requirement is still incomplete.
- If the evidence contains a longer chain and each upstream memory still contributes a concrete required item, keep the full chain in compressed form instead of truncating at the middle layer.
  Example evidence: `Marble rollout` is blocked because `approval matrix` is missing; `Signal checklist` directly requires that matrix; `Charter handbook` further says the `approval matrix` must include `escalation owner`.
  Preferred answer: mention `Signal checklist` explicitly before `Charter handbook`, and keep `escalation owner` visible instead of mentioning the handbook only by name.
  Example additional layer: `Relay register` further says the `escalation owner` record must include `on-call roster`.
  Preferred answer: keep that final concrete prerequisite in the answer too instead of stopping at `Charter handbook`.
- If the evidence contains a direct missing item plus another co-required item named by the same direct checklist or manual, keep both in the answer when an upstream artifact extends the second item with another concrete prerequisite.
  Example evidence: `Sable checklist` says the subject still needs both `transfer note` and `seal ledger`; `Merrow manual` says the `seal ledger` must include `reviewer seal`.
  Preferred answer: say all of `transfer note`, `Sable checklist`, `seal ledger`, and `reviewer seal` instead of answering with only the first missing item.
- Prefer a compact `missing item -> direct artifact -> upstream requirement -> final concrete prerequisite` structure when that full chain is present and still necessary.
""".strip(),
    "answer_judge": """
Evaluate whether the provided final answer correctly answers the query and stays grounded in the supplied evidence.
Rules:
- Use only the query, required facts, required_fact_groups, forbidden facts, answer, citations, and uncertainties from the payload.
- Return pass only when the answer covers all required facts without introducing forbidden facts.
- Prefer required_fact_groups when present. Each group is satisfied when any listed variant, or a clear semantic equivalent, is expressed anywhere in the answer.
- If one required fact is written as `A || B || C`, treat it as an any-of group and count the requirement as satisfied when any listed variant is clearly covered.
- Before returning partial for a missing required-fact group, explicitly re-check the answer text itself. If any variant from that group appears verbatim, or appears as a close mixed-language phrase with the same predicate, that group is covered and must not be reported as missing.
- Do not mark an any-of group missing merely because the answer mentions it in the historical-disagreement part and then later explains a newer/current conclusion.
- Historical-position groups are covered when the answer states that historical position anywhere in the answer; they do not need to be the final current conclusion.
- If your reason says a group is missing, none of that group's variants may appear verbatim in the answer text.
- Return partial when the answer is directionally correct but incomplete, weakly grounded, or misses part of the required facts.
- Return fail when the answer is wrong, unsupported, contradictory to evidence, or contains forbidden facts.
- grounded must be false if the answer makes claims not supported by the provided citations or evidence.
- Treat close lexical variants, explicit supersets, or narrower phrasings as satisfying a required fact when they clearly express the same concept.
- Examples: `偿付能力监管标准` satisfies `偿付能力监管`; `流动性完全丧失` satisfies `流动性`.
- Treat each forbidden fact as a complete claim, not as a bag of words. Do not fail only because the answer shares an entity name,
  artifact name, item name, or topic noun with a forbidden fact.
- Fail for a forbidden fact only when the answer asserts the same forbidden predicate/status/causal claim, or an equivalent claim.
- Do not derive forbidden facts through extra-world inference. A rule about what an item record must contain does not say whether
  that item is missing, present, complete, blocking, or non-blocking unless the answer explicitly says so.
- Claims can share the same noun while saying different predicates. `X missing` is different from `X record must include Y`; the
  second claim is not forbidden unless it also says `X` is missing or blocking.
- Example: required fact `Verdigris manual 要求所有 Cobalt seal 记录附 Gateway stamp`; forbidden fact
  `Cobalt seal missing`; answer `Verdigris manual 要求所有 Cobalt seal 记录附 Gateway stamp。` is pass, because it
  says a record-content requirement and does not claim that `Cobalt seal` is missing or blocking.
- If a required fact appears inside a larger bilingual or mixed-language clause, count it as satisfied when the clause clearly preserves that fact.
- Example: `Round 1 支持按 initial launch slot 进行` satisfies the required fact `initial launch slot`.
- If the answer literally names one listed artifact, requirement, item, or role from a required-fact group, count that group as satisfied. Do not mark it missing just because the same sentence also contains a longer causal explanation.
- If the answer literally includes both a named artifact and its concrete requirement in one clause, treat both as covered even when the clause adds another consequence or implication.
- Example: `Lantern checklist 明确要求补 Trellis note 和 Bastion ledger，而 Opal manual 进一步要求所有 Bastion ledger 记录附 Selene seal。` satisfies the required groups `Lantern checklist || checklist` and `Selene seal || Opal manual || manual`.
- Extra grounded details do not reduce a pass result as long as all required facts are covered and no forbidden facts are introduced.
- Keep reason short and concrete.
""".strip(),
    "profile_writer": f"""
Rewrite the entity identity profile from current profile and recent identity signals.
Rules:
- {IDENTITY_PROFILE_RULES_EN}
- Keep the same subject identity.
- surface_forms must stay short and concrete.
- stable_qualifiers must stay as short keywords or phrases.
- Do not promote blocker, owner value, requirement content, current state, or other salient memory facts into the identity profile just because they appear frequently in recent memories.
- Do not invent entity_key or memory ids.
""".strip(),
    "edge_judge": """
Judge whether the source memory has supports, contradicts, or related_to relations with candidate memories.
Rules:
- The payload may describe either a local entity graph or a cross-entity graph.
- If `original_query` and `query_identity_profile` are present, use them to decide what the current recall is actually trying to answer before judging relations.
- Return complete relation edges, not source-relative targets.
- Every returned relation must include:
  - from_memory_id
  - to_memory_id
  - edge_type
  - reason
  - weight
- Only return relations for memory ids present in the payload.
- Do not output `edge_type="none"`. If no relation exists for a pair, omit that pair from `relations`.
- Every memory includes `identity_profile`; use it to decide which stable subject the memory belongs to before judging relations.
- If `query_identity_profile` is present, treat that subject as the answer target for this recall step.
- Different identity_profile subjects with the same prefix are not related just because they share that prefix, domain, project,
  readiness theme, or similar missing-detail wording.
- Use supports only when one memory is direct evidence, direct explanation, or a direct external requirement for another memory's claim.
- In cross-entity mode with `original_query`, judge supports against the current query target, not only against abstract semantic relatedness.
- For narrow target-property questions such as asking what the target currently requires, lacks, says, decides, or aims for, omit
  non-relations or use `related_to` for upstream artifact details unless that external memory is itself part of the target's direct answer.
- If a candidate memory only adds a more detailed upstream rule for one sub-item inside the frontier memory, that usually does not support
  the frontier memory for a narrow query about the frontier subject's own current requirement/status/goal.
- A governing artifact can be semantically relevant without being answer-critical for the current query. Do not turn every relevant upstream
  constraint into supports.
- If one memory states a policy, requirement, or standing rule and another memory reports concrete violations, delays, incidents, or repeated failures to satisfy that rule, the operational note usually supports why the rule matters; it does not contradict the rule unless it explicitly denies the rule itself.
- If one memory states a standing policy, checklist, bulletin, or rule and another memory is an audit note, review note, or operational note showing repeated timeout, delay, miss, or failure to satisfy that rule, prefer supports from the note to the rule-bearing memory.
- In local_graph mode, do not drop that support edge just because the note and the rule can already answer the question without it. The rule-bearing memory is the main claim, and the audit or operational note is direct support.
- If one memory states a standing rule or requirement and another memory gives the concrete observed reason the rule is emphasized, emit supports even when the pair could also be described as adjacent context. Prefer the direct support edge over omitting the relation.
  Example main rule: `Ivory access bulletin 要求所有临时权限在 24 小时内完成回收。`
  Example audit note: `Ivory access bulletin 的审计备注显示临时权限回收多次超时。`
  Preferred edge: `audit note -> main rule = supports`, because the note explains why the rule is emphasized.
  Example main rule: `Quartz retention notice 要求所有临时凭证在 12 小时内完成回收。`
  Example operational note: `Quartz retention notice 的审计补充说明显示临时凭证回收多次延迟。`
  Preferred edge: `operational note -> main rule = supports`. Do not omit the relation just because the note and the rule are both already understandable on their own.
- Use contradicts only when two memories make conflicting or mutually incompatible claims.
- If two bounded records from the same session, review, or decision context present mutually incompatible alternatives, use contradicts even when both are historical.
- Use related_to when two memories are clearly about the same broader issue but neither directly supports nor directly contradicts the other.
- Example query: `Lattice checklist 当前要求补齐什么？`
  Example frontier identity: `{"who":"Lattice checklist","stable_qualifiers":["checklist"]}` with memory `Lattice checklist requires transfer note and seal ledger`.
  Example candidate identity: `{"who":"Lattice handbook","stable_qualifiers":["handbook"]}` with memory `Lattice handbook says seal ledger must include reviewer seal`.
  Preferred edge: `related_to` or omit the relation, because the handbook adds an upstream detail for one checklist item but is not itself the direct answer to the narrow checklist query.
- Example frontier identity: `{"who":"Driftbay map","stable_qualifiers":["map"]}` with memory `Driftbay map lacks contour markers`.
  Example candidate identity: `{"who":"Driftbay survey","stable_qualifiers":["survey"]}` with memory `Driftbay survey is blocked because field notes are missing`.
  Preferred edge: omit the relation, because these are sibling subjects with different missing details; same prefix and same broad documentation theme are not enough.
- Missing process, workflow, readiness, or prerequisite information should usually be related_to, not supports, unless the memory explicitly states that the missing item directly proves or directly requires the target claim.
- A missing guardrail, missing validation step, or missing readiness process should usually be related_to a blocker or failure memory when it explains adjacent context but does not itself directly observe the failure.
- In an explanation chain, direct evidence should support the main claim, while adjacent missing prerequisites or process gaps should usually be related_to.
- When one memory is direct evidence for the main claim and another memory is a neighboring missing prerequisite or missing process, preserve both relation types if both are independently useful: evidence should support the main claim, and the neighboring gap should remain related_to the main claim.
- Do not omit the main-claim related_to edge just because another memory already provides a supports edge in the same local graph.
  Example main claim: `Heliotrope rollout 当前主阻塞是配置漂移。`
  Example direct evidence: `部署日志显示配置漂移导致签名校验失败。`
  Example adjacent gap: `缺少配置基线校验流程。`
  Preferred edges: `direct evidence -> main claim = supports`; `adjacent gap <-> main claim = related_to`; do not also connect `adjacent gap` to `direct evidence` unless that second relation is independently necessary.
- When one memory is a later current conclusion and another memory is an earlier historical record from a prior round, stage, or session, do not add contradicts just because the later conclusion differs. Historical evolution should usually be represented by updates/history, not by contradicts between current and superseded records.
- Use contradicts mainly for peer alternatives that coexist as competing claims, not for an old historical position versus a newer settled position.
- If two historical records disagree with each other, contradicts is appropriate. If a newer current record replaces an older historical record, prefer no contradicts edge unless the payload clearly presents them as still-active competing positions.
- Prefer a minimal graph that preserves the strongest explanation path instead of connecting every plausible hop.
- Prefer a sparse graph.
- Prefer the smallest edge set that still answers the local question. If one direct support and one adjacent context edge already explain the situation, do not add extra second-order related_to edges between those supporting and adjacent nodes.
- Do not connect every pair just because they share topic words.
- In a local graph, first identify the main claims, then connect only the strongest direct supports or contradictions.
- When one memory directly supports a main claim and another memory is only adjacent context or a missing prerequisite, connect the adjacent context to the main claim only. Do not also connect that adjacent context to the supporting evidence unless the payload makes that second relation independently necessary.
- When several memories form a history of disagreement plus a later settled summary, keep contradicts on the bounded peer alternatives that directly disagree. Do not also connect the later settled summary to every older alternative with contradicts unless the payload clearly says the current summary remains an active competing position.
- If a later current summary resolves earlier disagreement, prefer one contradicts edge among the historical alternatives and let recall use history/current structure to explain the settlement, instead of emitting extra contradicts edges from the settled summary.
  Example historical alternative A: `Round 1: 可以先按原窗口上线。`
  Example historical alternative B: `Round 2: 必须先补回滚说明。`
  Example later summary: `当前决定已经变成先补回滚说明再排期上线。`
  Preferred edges: one `contradicts` edge between the historical alternatives; avoid adding extra `contradicts` edges from the later settled summary unless the payload clearly says the summary is still an active competing position.
- In a cross-entity graph, only connect frontier memories to external candidate memories when the external memory directly explains, constrains, or conflicts with the frontier memory.
- In cross-entity mode, every returned edge must connect one frontier memory and one candidate memory. Do not emit frontier-to-frontier edges or candidate-to-candidate edges.
- In cross-entity mode, default to omitting the relation unless the external memory contributes a direct external explanation, direct governing requirement, direct dependency state, or direct contradiction for the frontier memory.
- In cross-entity mode with `original_query`, a direct governing requirement is still not enough for supports when the query is only asking for the
  frontier subject's own immediate current answer and the external memory merely adds another layer of detail for one sub-item.
- In cross-entity mode, do not use `contradicts` between a bounded historical round/session record and an unbounded external standing rule merely because the old historical position would not satisfy the rule. The rule should support or constrain the later/current settled requirement; the historical disagreement should be represented among peer historical alternatives.
  Example historical alternative A: `Round 1: 可以按 initial slot 转运。`
  Example historical alternative B: `Round 2: 必须先补 tow manifest。`
  Example external statute: `Harbor statute 要求所有转运决定先附 tow manifest。`
  Preferred edges: one `contradicts` edge between the two historical alternatives, and a support/constraint edge from the statute to the later/current manifest requirement when that current memory is present. Do not add a cross-entity `contradicts` edge between the statute and the older Round 1 record.
  Example frontier memory: `Cedar handbook 规定 rollback annex 还必须附 reviewer charter。`
  Example candidate memory: `Relay register 要求 reviewer charter 记录补齐 on-call roster。`
  Preferred edge: connect `Cedar handbook` to `Relay register` as a frontier-to-candidate edge, because the candidate adds the next still-required concrete prerequisite in the same requirement chain. Do not re-emit edges only among the frontier memories in cross-entity mode.
- In cross-entity mode, a named external handbook, manual, checklist, bulletin, or guide may still be related_to the frontier blocker when it states a concrete missing validation flow, readiness gate, or prerequisite that is itself the neighboring gap being asked about.
- Use related_to for that adjacent external gap when the missing process or guardrail is explicitly named and would still leave the subject unready, even if it is not the single direct blocker.
  Example frontier blocker: `Radian rollout 当前主阻塞是配置漂移。`
  Example candidate artifact gap: `Baseline handbook 目前还缺少配置基线校验流程。`
  Preferred edge: `related_to`, because the handbook memory names a concrete neighboring gap that is still relevant to rollout readiness, even though it is not the same thing as the current blocker itself.
- Mere participation in the same incident, recovery process, or surrounding workflow is not enough for a cross-entity edge.
- Prefer the smallest cross-entity explanation set. If one external memory already provides the concrete failing dependency, upstream service state, unresolved source state, or other direct operational explanation, do not also emit weaker cross-entity edges to procedural artifacts that merely describe adjacent process gaps or response materials.
- If one memory says a rollout or review is blocked by an unresolved external data source, upstream service, or dependency, and another memory describes that external service still being degraded, backfilling, unavailable, or not yet stable, prefer related_to between the blocker memory and the external service memory.
- If a handbook, checklist, document, or report is present but does not itself describe the concrete external failure or direct governing requirement, omit the relation for that artifact even if it belongs to the same incident or recovery process.
- When both a concrete external service-state memory and a handbook/checklist/document memory are present, prefer the concrete service-state edge and omit the artifact edge unless the artifact itself is the thing directly constraining or causing the frontier blocker.
  Example main claim: `Verdigris rollout 当前主阻塞是依赖数据源迟迟没有恢复。`
  Example external service: `Relay service 当前仍处于批量补数状态，尚未恢复稳定输出。`
  Example distractor artifact: `Escalation handbook 当前缺少 on-call escalation path。`
  Preferred edges: `external service <-> main claim = related_to`; omit `distractor artifact`. Do not connect the handbook unless the payload explicitly says the handbook itself is the direct blocker or governing requirement. Prefer the concrete service-state edge over weaker adjacent handbook context.
  Example main claim: `Cobalt rollout 当前被上游队列恢复缓慢影响。`
  Example concrete external state: `Queue service 仍在 replay backlog，尚未恢复稳定消费。`
  Example adjacent artifact: `Response runbook 当前还缺少 escalation owner。`
  Preferred edges: only `concrete external state <-> main claim = related_to`; omit `adjacent artifact`. Omit the runbook edge because it is secondary process context, not the direct external explanation.
- If the frontier memory itself is a secondary artifact/process-gap note and a candidate memory is only a primary operational blocker or neighboring incident state, omit the relation unless the frontier note explicitly says it constrains, explains, or governs that candidate.
- Shared incident membership, shared recovery area, or shared escalation context is not enough for a cross-entity edge from a secondary artifact gap to a primary blocker.
  Example frontier artifact gap: `Response runbook 当前还缺少 escalation owner。`
  Example candidate blocker: `Cobalt rollout 当前被上游队列恢复缓慢影响。`
  Example candidate service state: `Queue service 仍在 replay backlog，尚未恢复稳定消费。`
  Preferred edges: omit the relation. The runbook gap is secondary artifact context; it should not create new cross-entity edges back into the primary blocker chain unless it explicitly states that the missing runbook step is itself the direct blocker or governing requirement.
- In cross-entity mode, prefer the edge to flow from the primary blocker or requirement memory toward the concrete external explanation. Do not add the reverse artifact-to-blocker edge just because the artifact is contextually nearby.
- For contradicts and related_to, do not emit both directions.
- Do not emit empty reasons.
""".strip(),
    "merge_judge": """
Decide whether two entities should merge.
Rules:
- Return merge only when they clearly refer to the same subject.
- Shared topic, shared requirement, shared blocker, shared workflow, or shared surrounding context is not enough for merge.
- stable_qualifiers are identity-boundary evidence. Different stable identity boundaries should remain separate
  unless the payload gives explicit identity-equivalence evidence.
- Do not merge an actor/system/project/person with a document/policy/checklist/report/handbook artifact just because the artifact constrains, explains, or is mentioned by the actor.
  Example source: `Ledger service`
  Example target: `Compliance checklist`
  Preferred: keep_separate. The service is the constrained subject; the checklist is a named artifact that imposes a requirement. They are related, not the same subject.
  Example source: `Lantern rollout`
  Example target: `Release governance guide`
  Preferred: keep_separate. The rollout is governed by the guide, but the guide is not the rollout.
- Do not merge a plan with a project, or a plan with a checklist/document/policy artifact, just because they share the same short name or appear in the same approval workflow.
  Example source: `Summit plan`
  Example target: `Summit project`
  Preferred: keep_separate unless the payload explicitly shows they are two names for the exact same artifact. A plan and a project are normally different stable subjects.
- Do not merge two entities just because one entity is governed by, blocked by, or depends on the other.
- If one entity is the thing acting or being blocked, and the other is the rule, checklist, report, handbook, plan, or requirement that constrains it, keep them separate.
- If two entities have different stable identity types or different stable functions, keep_separate even when they share the same process or same issue.
- Merge only when both entities are two names, aliases, or descriptions of the same concrete subject, and their memories could be viewed as belonging to one identity without losing an important subject boundary.
  Example source: `Meridian 项目`
  Example target: `Meridian 发布项目`
  Preferred: merge if the evidence shows they are two names for the same concrete project.
- If merge, pick the better survivor_entity_key from the provided two candidates.
- If merge, also return `merged_identity_profile` as the complete final V2 identity profile for the survivor.
- The merged_identity_profile must follow identity_profile rules and must not be a partial patch.
- The merged_identity_profile must not be a blind union of both profiles. It must describe one coherent subject
  and preserve only aliases and qualifiers that truly belong to that one subject.
- Do not rely on code to append aliases or qualifiers; include every surface form and stable qualifier that should remain.
- Do not include memory facts, blockers, owner values, requirements, or current state in merged_identity_profile.
- If uncertain, return keep_separate.
""".strip(),
}

SAME_BATCH_RESOLVER_INSTRUCTIONS_EN = """
Resolve candidate memories against synthetic same-batch memories that represent earlier candidates from the same ingest batch.
Rules:
- Existing memories in this worker may be synthetic placeholders that represent earlier candidates from the same batch.
- Existing memories in this worker use short memory refs like `m1`; when you target an earlier same-batch placeholder, use that memory ref.
- Use those synthetic placeholders to normalize one batch of earlier/current evolution into the final persisted shape before anything is written.
- When a later candidate states the newer current rule, current blocker, or current standing state for the same artifact, it should usually target the earlier same-batch placeholder memory ref with action=replace instead of producing two peer active creates.
- Never target your own candidate ref, and never invent a memory ref.
- Prefer one superseded earlier memory plus one active current head when the batch expresses a clear earlier/current evolution for the same practical question.
""".strip() + "\n\n" + WORKER_INSTRUCTIONS_EN["resolver"]

WORKER_INSTRUCTIONS_EN["same_batch_resolver"] = SAME_BATCH_RESOLVER_INSTRUCTIONS_EN



def _resolve_system_language(system_language: str | None) -> str:
    """解析当前 worker prompt 使用的系统语言。

    Args:
        system_language: 显式传入的系统语言；为空时读取 Memory 配置。

    Returns:
        `en` 或 `zh`。

    Raises:
        ValueError: 语言值不是 `en` 或 `zh`。
    """

    if system_language is None:
        from insight_memory.config import settings

        system_language = settings.MEMORY_SYSTEM_LANGUAGE
    if system_language not in {"en", "zh"}:
        raise ValueError("system_language must be 'en' or 'zh'")
    return system_language


def get_worker_instructions(worker_type: str, *, system_language: str | None = None) -> str:
    """按系统语言返回指定 worker 的提示词。

    Args:
        worker_type: Memory worker 类型。
        system_language: 可选系统语言；为空时使用 `settings.MEMORY_SYSTEM_LANGUAGE`。

    Returns:
        对应语言的 worker prompt。
    """

    language = _resolve_system_language(system_language)
    if language == "zh":
        return WORKER_INSTRUCTIONS[worker_type]

    return WORKER_INSTRUCTIONS_EN[worker_type]
