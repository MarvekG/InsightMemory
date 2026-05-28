# Identity Profile V2、Ingest 与 Recall 整体设计

## 背景

当前 InsightMemory 已经是 entity-centered 设计：写入和召回都会先由 LLM 抽取
`identity_profile`，再用该 profile 召回候选实体，最后由 linker 在候选 `entity_key`
中选择、创建或拒绝。

这条链路的问题不是“没有稳定 entity_key”，因为数据库里已经有 opaque
`entity_key`；真正的问题是 `identity_profile` 同时承担了太多职责：

- 它是候选召回输入。
- 它是 linker 判断同一实体的主要上下文。
- 它被 profile writer 刷新后又影响后续召回。
- recall 快路径会用它跳过 linker。

如果 profile 字段混入当前状态、事实内容、时间轮次或泛化描述，系统会出现两类风险：

- 写入侧误合并实体，污染后续所有 memories 和 edges。
- 召回侧误绑定实体，导致 answer composer 在错误实体上回答。

本文设计 Identity Profile V2，并说明 ingest、recall 和后台子图如何围绕 V2 调整。

## 目标

- 明确 `identity_profile` 只表示“它是谁”，不表示“发生了什么”。
- 让 `entity_key` 继续作为唯一实体真相，LLM 不生成、不推断 `entity_key`。
- 提升 recall graph-first 快路径命中时的准确率。
- 保持 ingest 写入侧保守，避免因为更强 profile 结构而扩大误合并风险。
- 让 `identity_profile` 可以自我进化，同时不因为 profile 漂移降低准确率。
- 所有语义判断继续通过 LLM schema、prompt、audit 和 eval 控制，不写关键词、正则、白名单或 case 专用逻辑。

## 非目标

- 不允许调用方在 Memory API 里传入 `entity_key` 或外部实体 ID。
- 不把 `identity_profile` hash 成 `entity_key`。
- 不让 LLM 生成最终实体 ID。
- 不把 recall 降级成纯向量 chunk 检索。
- 不把 parent context、业务系统 ID、事实状态塞进 `identity_profile`。
- 不为了兼容旧数据保留双结构 runtime 分支。

## 不兼容策略

本次设计不做旧结构兼容。V2 上线后，运行时只接受 V2 identity profile。

旧结构：

```json
{
  "who": "Orion runbook",
  "surface_forms": ["Orion runbook"],
  "distinguishing_context": ["runbook"]
}
```

新结构：

```json
{
  "schema_version": 2,
  "who": "Orion runbook",
  "entity_type": "document",
  "surface_forms": ["Orion runbook", "Orion 运行手册"],
  "stable_qualifiers": ["部署手册"],
  "evidence": ["原文明确把 Orion runbook 描述为部署手册"]
}
```

不兼容要求：

- schema、prompt、tests、evals 同步改到 V2。
- `distinguishing_context` 从 schema 中删除，不做运行时 fallback。
- 存量 Memory 数据直接清空，不做离线迁移，不保留旧实体、旧 memories、旧 edges 或旧 LLM audit。
- retrieval index 作为派生数据同步清空；V2 上线后只从新写入的 V2 数据重新生成。
- 旧 eval case 中依赖 `distinguishing_context` 的断言同步替换为 `stable_qualifiers`。

由于当前项目未上线，选择不兼容能减少长期分支和隐性误判来源。

### 存量数据处理

V2 切换时，开发环境中的 Memory 存量数据直接清空。

清空范围：

- `memory_entities`
- `memory_memories`
- `memory_memory_versions`
- `memory_edges`
- `memory_observations`
- `memory_recall_audits`
- `memory_llm_runs`
- `memory_background_tasks`
- retrieval index 相关表或文档行

执行要求：

- 清空只作为一次性运维动作执行，不写入应用启动逻辑。
- 清空前确认目标容器、数据库名和 schema，避免误清非目标环境。
- 清空后重新跑 V2 ingest/eval 生成新数据。
- 不再维护旧 profile 到 V2 profile 的迁移脚本。

## Identity Profile V2 字段

### 字段定义

| 字段 | 类型 | 必填 | 参与召回 | 参与快路径匹配 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `schema_version` | integer | 是 | 否 | 否 | 固定为 `2`，只用于 schema 识别。 |
| `who` | string | 是 | 是 | 是 | 主体稳定名称，但不是唯一键。 |
| `entity_type` | enum string | 是 | 是 | 是 | 粗粒度实体类型。 |
| `surface_forms` | list[string] | 是 | 是 | 是 | 原文出现过的别名、简称、跨语言称呼。 |
| `stable_qualifiers` | list[string] | 否 | 是 | 是 | 区分同名实体的稳定身份限定。 |
| `evidence` | list[string] | 否 | 否 | 否 | 身份抽取证据，只用于审计和 profile refresh。 |

### entity_type

`entity_type` 只做粗粒度分类，避免 LLM 在类型上过拟合。它不是完整本体，
也不是业务类型系统；它只用于减少同名实体误连，并辅助 recall 快路径判断。

推荐枚举控制在 13 个有效类型加 `unknown`：

```text
person
organization
market_object
system
document
artifact
project
work_item
workflow
event
decision
strategy
concept
unknown
```

类型说明：

| entity_type | 覆盖范围 | 示例 |
| --- | --- | --- |
| `person` | 具体个人、具名角色持有人 | `Nia Chen`、`基金经理王林` |
| `organization` | 公司、部门、团队、委员会、监管方、供应商 | `Radian 运营组`、`change board` |
| `market_object` | 股票、基金、指数、组合、行业、商品、货币、证券账户 | `BRK.A`、`贵州茅台`、`动量组合` |
| `system` | 软件系统、服务、数据库、API、模型、环境、基础设施组件 | `Trellis service`、`memory-postgres` |
| `document` | 具名文档、手册、报告、规则、政策、备忘录、分析笔记 | `Orion runbook`、`Aurora risk handbook` |
| `artifact` | 非文档制品：文件、配置、数据集、镜像、仓库、模型包、凭证集合 | `release image`、`factor dataset` |
| `project` | 项目、产品线、计划、专项、研究主题、功能建设 | `Gateway 项目`、`Line A 产品线` |
| `work_item` | 任务、ticket、issue、需求、订单、检查项、待办、执行项 | `rollout approval ticket`、`PM order 2026-05-01` |
| `workflow` | 流程、操作规程、pipeline、调度链路、复盘链路 | `daily refresh pipeline`、`post-decision review workflow` |
| `event` | 会议、事故、发布、评审、交易日、实验、轮次化活动 | `Cobalt launch review`、`Q2 rebalance meeting` |
| `decision` | 具名决策、建议、投委结论、审批结论、取舍方案 | `PM risk-off decision`、`仓位调整结论` |
| `strategy` | 投资策略、交易策略、风控策略、规则集、方法论 | `低波红利策略`、`stop-loss policy` |
| `concept` | 稳定抽象主题、指标、风险类别、原则、知识点 | `liquidity risk`、`T+1 约束` |
| `unknown` | 无法可靠分类但主体稳定 | `Mercury` |

规则：

- 只能输出上表中的一个枚举值。
- 不确定时输出 `unknown`，不要强行猜类型。
- `unknown` 可以在 profile refresh 中进化为明确类型。
- 明确类型之间不能由 profile writer 直接互改，必须走 merge/split 风险判断。
- 类型只表达主体“是什么”，不表达当前状态或用途。
- 如果同一个名称同时像多个类型，优先选当前输入真正所属的主体，而不是被提到的依赖项。

选择优先级：

- 具名文档、手册、报告、政策优先 `document`，不要因为文档描述流程就标成 `workflow`。
- 具名服务、数据库、API、模型、运行环境优先 `system`。
- 具名任务、ticket、issue、订单、需求优先 `work_item`。
- 具名评审、会议、事故、发布、实验优先 `event`。
- 具名交易策略、风控策略、投资方法优先 `strategy`。
- 只有当主体是抽象稳定主题且没有更具体载体时，才使用 `concept`。

### 字段边界

可以进入 `identity_profile`：

- 主体名：`Orion runbook`
- 类型：`document`
- 别名：`Orion 运行手册`
- 稳定限定：`部署手册`
- 证据：`原文中称它为运行手册`

不能进入 `identity_profile`：

- 当前状态：`当前 blocker 是数据库迁移失败`
- 事实内容：`要求补齐回滚章节`
- 时间轮次：`round 1`、`昨天`、`当前`
- 结论：`以后必须先检查 owner`
- 业务事实字段：owner、priority、risk、requirement、result
- parent context 或外部业务 ID

### 持久化与版本化

`MemoryEntity.identity_profile` 只保存当前 V2 profile，不保存变更历史。

profile 自我进化的审计状态放在 `MemoryEntity.metadata`，避免污染 identity 字段：

```json
{
  "profile_state": {
    "profile_revision": 3,
    "last_refresh_status": "applied",
    "last_refresh_reason": "added stable alias and qualifier",
    "last_refreshed_at": 1760000000.0
  },
  "profile_history": [
    {
      "revision": 2,
      "previous_profile": {"schema_version": 2},
      "proposed_profile": {"schema_version": 2},
      "applied_changes": {
        "added_surface_forms": ["..."],
        "added_stable_qualifiers": ["..."]
      },
      "risk": "safe",
      "request_id": "..."
    }
  ]
}
```

规则：

- `profile_revision` 每次成功应用 safe update 后递增。
- `profile_history` 只保留最近有限条记录，避免实体 metadata 无限膨胀。
- 被拒绝的 proposal 也要记录简要状态和 reason，但不写入 `identity_profile`。
- recall audit 记录命中时使用的 `profile_revision`，方便定位“profile 刷新后 recall 行为改变”的问题。
- 如后续需要更强审计，再拆出独立 `memory_entity_profile_versions` 表；第一阶段可先复用 metadata。

## 总体数据流

```text
write context
  -> extractor(V2 profile drafts + candidate memories)
  -> ingest_graph
       -> V2 profile normalization
       -> entity candidate retrieval
       -> linker when candidates exist
       -> create entity only when no candidates exist
       -> resolve memories
       -> enqueue refresh/reindex/merge/repair tasks

recall query
  -> query_planner(V2 query profile drafts + query focus)
  -> recall_graph draft subgraphs
       -> entity candidate retrieval
       -> graph-first strict entity binding when safe
       -> linker fallback
       -> memory retrieval and graph expansion
       -> answer composer

background tasks
  -> refresh_entity_profile_graph
  -> reindex_memory_graph
  -> detect_merge_candidates_graph
  -> merge_entities_graph
  -> repair_memory_edges_graph
```

核心原则：

- ingest 写入侧偏保守，避免永久误合并。
- recall 读取侧可以有快路径，但必须严格、可审计、可回退。
- profile refresh 只允许在同一 `entity_key` 下低风险进化。
- merge/split 风险不能由 profile writer 自动吞掉。

## Ingest Graph 设计

### 现状

当前 `ingest_graph` 的主体链路是：

```text
extractor identity_profile_drafts
  -> _identity_profile_key 做 observation 内去重
  -> retrieval_index.entity_candidates
  -> 无候选 create_new
  -> 有候选 run_linker
  -> create/link entity
```

这个方向是正确的：写入侧只要有历史候选，就交给 linker 判断，不因为检索候选相似就直接合并。

### V2 改动

`ingest_graph` 应保持保守策略，只替换 identity payload 结构。

改动点：

- extractor 仍输出 `IdentityProfileDraft`，结构体名称不加 `V2` 后缀，只原地替换字段。
- `_identity_profile_key()` 只用于同一 observation 内的本地去重，字段为：
  - `who`
  - `entity_type`
  - `surface_forms`
  - `stable_qualifiers`
- `_identity_profile_key()` 不包含：
  - `schema_version`
  - `evidence`
- `_display_name_from_profile()` 优先使用 `who`，再使用 `surface_forms[0]`。
- `retrieval_index.entity_candidates()` 使用 V2 projection。
- 有候选时仍然调用 linker。
- 无候选时创建新 entity，写入 V2 profile。
- linker 输出的 `selected_entity_key` 必须属于候选集合，否则丢弃并按不能解析处理。

### 写入侧不做的优化

ingest 不新增“结构匹配唯一则直接 link_existing”的快路径。

理由：

- 写入侧错误会永久改变 memory 归属。
- V2 profile 仍然来自 LLM 抽取，不是系统确定事实。
- 单个候选也可能只是相似实体，不等于同一实体。

写入侧可以因为 V2 profile 降低 linker 误判，但不应绕过 linker。

### Ingest 审计

写入审计需要记录：

- `identity_schema_version`
- `draft_count`
- `entity_type`
- `surface_form_count`
- `stable_qualifier_count`
- `candidate_count`
- `linker_decision`
- `selected_entity_key`
- `created_entity_key`
- `profile_refresh_queued`

这可以帮助区分“候选召回失败”“linker 判断失败”和“profile 抽取失败”。

## Recall Graph 设计

### 现状问题

当前 recall graph-first 快路径已经可以跳过 linker，但存在一个高风险兜底：

```python
if candidate_count == 1 and not matched_candidates:
    matched_candidates = scored_candidates
```

这意味着单候选时，即使 query profile 与候选 profile 没有结构匹配，也可能直接绑定。
这会提升速度，但会降低准确率。

### V2 快路径原则

V2 后 recall 快路径只在低风险 entity-local 查询中启用。

必须同时满足：

- query planner 输出 `graph_expansion_intent == "entity_local"`。
- query draft 是 V2 profile。
- candidate profile 是 V2 profile。
- 候选经过结构匹配后唯一。
- `who` 或 `surface_forms` 能形成主体匹配。
- `entity_type` 兼容。
- query 的 `stable_qualifiers` 能被候选 profile 覆盖；如果 query 没有 qualifier，则必须没有多个同名或近似主体候选。

不满足任一条件时，回退 linker。

### 结构匹配

结构匹配只使用 identity 字段：

- `who`
- `entity_type`
- `surface_forms`
- `stable_qualifiers`

不使用：

- `evidence`
- memory content
- current state
- query_text 中的事实内容
- retrieval score 阈值

匹配结果应输出 reason：

```json
{
  "subject_match": true,
  "entity_type_match": true,
  "stable_qualifier_match": true,
  "matched_entity_key": "ent_xxx",
  "fallback_reason": ""
}
```

### entity_type 兼容

兼容规则：

- 相同类型兼容。
- 任一侧为 `unknown` 时兼容，但降低快路径置信。
- 两个明确且不同的类型不兼容，必须回 linker。

示例：

```text
query:  Orion runbook, type=document
entity: Orion project, type=project
result: fallback linker
```

### stable_qualifiers 覆盖

`stable_qualifiers` 是快路径消歧的关键。

规则：

- query 有 qualifiers 时，候选 profile 必须覆盖这些稳定限定。
- query 无 qualifiers 且候选存在多个同名或同 surface form 实体时，不能快路径。
- qualifiers 只做身份限定，不使用事实内容。

### 删除单候选盲绑

V2 必须删除单候选盲绑逻辑。新的行为：

```text
candidate_count == 1
  + 结构匹配成功 -> graph-first link_existing
  + 结构匹配失败 -> fallback linker
```

这会降低部分单实体 recall 的快路径命中率，但能显著降低误绑定风险。

### Recall 审计

`memory_recall_audits.metadata` 需要补充：

- `identity_schema_version`
- `graph_first_attempted`
- `graph_first_used`
- `graph_first_fallback_reason`
- `graph_first_candidate_count`
- `graph_first_subject_match`
- `graph_first_entity_type_match`
- `graph_first_stable_qualifier_match`
- `graph_first_selected_entity_key`

这些字段用于评估 V2 的效果：

- 快路径命中率
- 快路径回退原因
- linker fallback 后是否仍能正确回答
- 误绑定是否下降

## 其他子图调整

### Workers schemas

结构体命名沿用现有名称，不新增 `*V2` 后缀类型。V2 是 payload schema version，
不是 Python/Pydantic 类型名。需要原地替换字段的结构体：

- `IdentityProfileDraft`
- `QueryIdentityProfileDraft`
- `ProfileWriterOutput`

`IdentityProfileDraft` 字段固定为：

```text
schema_version
draft_id
who
entity_type
surface_forms
stable_qualifiers
evidence
```

`QueryIdentityProfileDraft` 额外包含：

```text
query_text
```

不再允许 `distinguishing_context`。

### Prompts

所有 identity 相关 prompt 同步替换为 V2 术语：

- `distinguishing_context` -> `stable_qualifiers`
- 明确 `entity_type` 是粗粒度类型，不确定时填 `unknown`。
- 明确 `evidence` 不参与身份匹配，只用于审计。
- 明确 parent context、外部业务 ID、状态事实不进入 profile。

需要覆盖的 worker：

- `write_gate`
- `extractor`
- `linker`
- `query_planner`
- `profile_writer`
- `merge_judge`
- `edge_judge`

Prompt 示例必须和 eval 样本不同，避免 case 定制。

### Retrieval Index

`project_identity_profile()` 改成 V2 projection：

```text
who
entity_type
surface_forms
stable_qualifiers
```

不进入 entity retrieval projection：

```text
schema_version
evidence
```

Memory document projection 中可以附带 entity profile V2，但 answer composer 不应把 profile
当作事实引用来源。

V2 上线后需要重建 retrieval index。

### Refresh Entity Profile Graph

`refresh_entity_profile_graph` 是 profile 自我进化的主入口。当前实现会让
`profile_writer` 直接重写 profile，并覆盖 entity。V2 后需要改成“提案 + 守门 + 应用”。

推荐流程：

```text
load_entity_context
  -> propose_profile_update
  -> guard_profile_update
  -> apply_safe_profile_update
  -> refresh_index_when_changed
```

`profile_writer` 不直接返回最终覆盖值，而是返回：

```json
{
  "proposed_profile": {
    "schema_version": 2,
    "who": "...",
    "entity_type": "...",
    "surface_forms": ["..."],
    "stable_qualifiers": ["..."],
    "evidence": ["..."]
  },
  "changes": {
    "who_changed": false,
    "entity_type_changed": false,
    "added_surface_forms": ["..."],
    "added_stable_qualifiers": ["..."],
    "removed_surface_forms": [],
    "removed_stable_qualifiers": []
  },
  "risk": "safe",
  "reason": "..."
}
```

`guard_profile_update` 做确定性守门：

- `schema_version` 必须为 `2`。
- `who` 默认不允许改写；如需改写，只能作为 display name 改善，旧 `who` 必须进入
  `surface_forms`。
- `entity_type` 只允许 `unknown -> 明确类型`。
- `surface_forms` 默认只追加，不删除。
- `stable_qualifiers` 默认只追加，不删除。
- `evidence` 可以替换或截断，因为它不参与匹配。
- 如果 proposal 暗示主体变了，拒绝应用，并排队 `detect_merge_candidates` 或人工/后续
  split 诊断。

应用成功后：

- 更新 `MemoryEntity.identity_profile`。
- 更新 `display_name`。
- 刷新 entity retrieval doc。
- 如 profile 影响 memory projection，排队 `reindex_memory`。

### Detect Merge Candidates Graph

`detect_merge_candidates_graph` 继续用 retrieval index 找相似实体，但检索输入改为 V2
profile projection。

队列策略：

- 相同 `entity_type` 或 `unknown` 兼容实体可以进入 merge candidate。
- 明确不同 `entity_type` 的候选默认不排队 merge。
- 候选只触发 `merge_entities` 任务，不自动合并。
- 任务 payload 记录 V2 profile 摘要和触发原因。

该子图的职责是发现可能重复实体，不负责决定同一实体。

### Merge Entities Graph

`merge_entities_graph` 仍由 `merge_judge` 做最终语义判断。

V2 后需要调整：

- merge_judge 输入包含双方 V2 profile、display name、active memory summaries。
- merge_judge 必须解释：
  - subject 是否相同
  - entity_type 是否兼容
  - stable_qualifiers 是否冲突
  - memory summaries 是否支持同一实体
- 明确不同 `entity_type` 且非 `unknown` 时，默认拒绝 merge，除非 LLM 给出强理由且候选不是系统守门拒绝的类型冲突。
- merge 成功后 survivor profile 通过 safe merge policy 合成：
  - `who` 取 survivor 或更稳定 display name。
  - `entity_type` 取明确类型；两边明确且不同则不应进入 apply。
  - `surface_forms` 合并去重。
  - `stable_qualifiers` 合并去重。
  - `evidence` 合并后截断。
- merge log 记录 source/target 的原始 V2 profile。

### Repair Memory Edges Graph

`repair_memory_edges_graph` 给 edge_judge 的 memory payload 继续携带
`identity_profile`，但字段改为 V2。

edge_judge 规则需要强调：

- 不同 entity_type 的主体不能因为同名前缀直接 related。
- `stable_qualifiers` 是区分主体边界的重要信号。
- `evidence` 不是 memory fact，不能作为 relation 依据。
- edge 的证据必须来自 memory title、summary、content 或已有 observation，不来自
  identity profile 的 audit evidence。

这样可以减少“同名但不同实体”被关系边粘在一起。

### Reindex Memory Graph

`reindex_memory_graph` 需要在两类情况运行：

- memory 内容变化。
- entity profile V2 变化，导致 memory retrieval projection 中的 entity identity 摘要变化。

`refresh_entity_profile_graph` 如果实际应用了 profile 变化，应负责触发或合并
`reindex_memory` 任务，避免 profile 已变但 memory retrieval doc 仍引用旧 profile。

### Background Task Runtime

后台任务顺序要避免重复和竞态：

- ingest 完成后仍排队 `refresh_entity_profile`、`reindex_memory`、
  `detect_merge_candidates`、`repair_memory_edges`。
- `refresh_entity_profile` 如果应用变更，应刷新 entity index，并排队一次 entity 级
  `reindex_memory`。
- `detect_merge_candidates` 可以在 profile refresh 后再运行，减少旧 profile 触发的无效候选。
- `repair_memory_edges` 使用最新 entity profile payload，但不能依赖 profile evidence 当作事实。

## Identity Profile 自我进化

### 进化目标

profile evolution 只解决身份描述越来越准确的问题：

- 补充别名。
- 补充稳定身份限定。
- 从 `unknown` 类型进化到明确类型。
- 改善 display name。
- 更新审计 evidence。

它不解决：

- 当前事实变化。
- memory 内容更新。
- 跨实体关系更新。
- 实体 merge/split 的最终判断。

### 字段刷新策略

| 字段 | 刷新方式 | 是否允许删除 | 风险处理 |
| --- | --- | --- | --- |
| `schema_version` | 固定为 `2` | 否 | 非 2 拒绝。 |
| `who` | 默认保持；可改善展示名 | 不直接删除旧值 | 旧值进入 `surface_forms`，主体变化则拒绝。 |
| `entity_type` | `unknown` 可变明确类型 | 否 | 明确类型冲突则拒绝，触发 merge/split 诊断。 |
| `surface_forms` | 追加去重 | 默认不删除 | 删除建议只进 audit，不自动应用。 |
| `stable_qualifiers` | 追加去重 | 默认不删除 | 若像事实内容，拒绝或保留现状。 |
| `evidence` | 替换、追加或截断 | 是 | 不参与匹配，低风险。 |

### Refresh 输入

profile writer 的输入应包含：

- 当前 entity profile。
- 当前 display name。
- 最近 active memory summaries。
- 最近写入时的 identity profile drafts。
- 已存在 aliases 和 stable qualifiers。
- 近期 linker/merge/recall audit 中的 identity conflict 迹象。

不要只给 recent memory summaries，否则高频事实容易被错误提升为 identity qualifier。

### Refresh 输出

profile writer 输出必须结构化，至少包含：

- `proposed_profile`
- `changes`
- `risk`
- `reason`

`risk` 建议枚举：

```text
safe
needs_merge_review
needs_split_review
reject
```

只有 `safe` 可以自动应用。

### 准确率保护

profile 自我进化不会影响准确率的前提是：变化必须被限制在低风险字段和低风险方向。

保护机制：

- `entity_key` 永远不变。
- `who` 不做主体迁移。
- `surface_forms` 和 `stable_qualifiers` 以追加为主。
- `entity_type` 只允许从 `unknown` 收敛。
- `evidence` 不参与 retrieval projection 和 graph-first 匹配。
- profile refresh 不自动 merge，不自动 split。
- 任何主体变化迹象都进入 merge/split 诊断，而不是覆盖当前 profile。
- recall graph-first 只使用稳定字段，并且可回退 linker。

这样 profile 可以变得更完整，但不会把一个实体“刷新成另一个实体”。

## LLM 职责边界

LLM 可以做：

- 从文本中抽取 V2 identity signals。
- 在系统提供的候选 `entity_key` 中选择。
- 判断 profile update 是否仍是同一主体。
- 判断两个候选实体是否应 merge。
- 判断 memories 之间的关系。

LLM 不能做：

- 生成 `entity_key`。
- 从自然语言推断 opaque key。
- 把外部业务 ID 写成 Memory 主键。
- 绕过候选集合选择不存在的 key。
- 直接决定 profile 覆盖风险守门。

后端必须校验 LLM 输出的 key 属于候选集合。

## 测试与评测

### 单元测试

需要覆盖：

- V2 schema 拒绝 `distinguishing_context`。
- extractor/query planner normalization。
- ingest 本地 identity key 去重。
- ingest 有候选时仍调用 linker。
- ingest 无候选时 create entity。
- recall graph-first 命中结构匹配唯一候选。
- recall graph-first 在单候选不匹配时回退 linker。
- recall graph-first 在 entity_type 冲突时回退 linker。
- refresh profile 只追加 alias/qualifier。
- refresh profile 拒绝主体变化。
- merge 成功后 V2 profile safe merge。

### Eval

需要新增或更新评测集：

- 同名前缀多实体：项目、文档、流程同时存在。
- 单候选但类型不匹配：必须 fallback linker。
- 单候选且 qualifier 不匹配：必须 fallback linker。
- 多候选唯一结构匹配：应走 graph-first。
- profile 进化后旧别名仍能召回。
- profile 进化后不会把当前状态提升为 stable qualifier。
- merge 后 aliases 和 qualifiers 合并但 facts 不进 profile。

Prompt 示例和 eval 名称、领域、措辞必须不同。

### 指标

需要跟踪：

- graph-first attempted / used / fallback reason。
- graph-first 命中后的 answer grounded rate。
- linker fallback 后的 answer grounded rate。
- profile refresh applied / rejected / needs review。
- profile refresh 后 entity candidate recall 命中率。
- merge task 数量和 merge 实际成功率。
- 因 profile 变化触发的 reindex backlog。

## 实施阶段

### Phase 1: Schema 与 Prompt

- 改 workers schemas 到 V2。
- 改 identity prompt。
- 改 profile writer 输出为 proposal。
- 更新单元测试和 eval case。

### Phase 2: Ingest V2

- 改 ingest graph 使用 V2 profile。
- 保持有候选就 linker。
- 创建 entity 时写 V2 profile。
- 更新 ingest 审计。

### Phase 3: Recall V2 快路径

- 改 recall graph-first 匹配逻辑。
- 删除单候选盲绑。
- 增加 type/qualifier 匹配 trace。
- 更新 recall audits。

### Phase 4: Profile Evolution

- 改 refresh_entity_profile_graph 为 proposal + guard + apply。
- 安全刷新 profile。
- profile 变化后刷新 index 并触发 reindex。

### Phase 5: Background 子图

- 更新 detect merge、merge、repair edges、reindex 的 V2 输入输出。
- 加 merge profile safe merge。
- 加 edge_judge V2 规则。

### Phase 6: 全量评测

- 先跑 `memory/tests`。
- 再跑单并发 smoke/matrix。
- 最后跑有限并发全量矩阵。
- 最大并发压力评测只用于吞吐和后台 backlog，不直接作为准确率结论。

## 验收标准

- 所有 identity profile 都是 V2，没有 runtime 旧字段兼容。
- `distinguishing_context` 在 schema、prompt、tests 中消失。
- ingest 写入侧没有新增危险直连。
- recall 快路径不再单候选盲绑。
- profile refresh 不会直接把一个实体改写成另一个实体。
- profile evolution 的应用、拒绝和 review 原因可审计。
- graph-first 命中时 grounded rate 不低于 linker 路径。
- 单实体 recall 在安全命中快路径时仍能减少一次 linker LLM 调用。
