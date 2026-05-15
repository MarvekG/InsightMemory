# Memory 写入与读取最佳实践

[返回 README](../README.zh-cn.md)

这份文档基于当前 `memory` 的实现和设计，说明调用方应该怎样写入记忆、怎样读取记忆，以及怎样处理异步写入、同名主体、历史演进和证据引用。

更底层的模型说明见 [记忆设计](./04-memory-design.md)，检索层说明见 [LlamaIndex 检索层设计](./05-llamaindex-retrieval-design.zh-cn.md)。

## 1. 核心原则

`memory` 不是把输入切成 chunk 后直接做向量检索。当前设计以 `entity` 为中心：

- `entity` 表示“这条记忆属于谁”，由系统分配 opaque `entity_key`。
- `memory` 表示系统围绕某个 entity 记住的稳定事实、状态、规则、结论或历史记录。
- `observation` 保存原始输入证据，append-only，不作为可变真相。
- `edge` 表达 memory 与 observation、memory 与 memory 之间的来源、更新、支持、冲突或相关关系。

所以最佳实践可以压缩成一句话：

> 写入时让系统明确知道“谁发生了什么”；读取时让系统明确知道“要问谁、问当前还是历史、问事实还是原因”。

## 2. 写入最佳实践

### 2.1 明确写出主体

当前写入 API 没有单独的 `entity` 字段，主体必须出现在 `context` 自然语言里。不要依赖上文、代词或调用方自己的会话状态。

推荐：

```text
对于 Atlas rollout 这个项目，当前主阻塞是数据库迁移失败，继续推进前需要先回滚。
```

不推荐：

```text
它现在卡在数据库迁移失败。
```

原因是写入热路径会先运行 extractor。如果不能抽出稳定 `identity_profile`，整次写入会被拒绝，不创建 observation，也不写 memory。

### 2.2 使用稳定主体，不把一次性记录当主体

主体应该是之后还能被再次引用的稳定对象，例如项目、系统、文档、流程、团队、市场标的、审查记录或命名工件。

推荐：

```text
Cobalt launch review round 1 支持按 initial launch slot 继续推进。
```

这里稳定主体是 `Cobalt launch review`，`round 1` 应保留在 memory 内容或 record marker 中，不应变成新的主体身份。

不推荐：

```text
Round 1 这个主体支持按 initial launch slot 继续推进。
```

### 2.3 用角色词区分同名主体

如果同一个名称下有多个不同对象，写入时要保留能区分身份的角色词。

推荐：

```text
Atlas 发布项目 当前主阻塞是数据库迁移失败。
Atlas 知识文档 当前缺少回滚说明。
```

不推荐：

```text
Atlas 当前主阻塞是数据库迁移失败。
Atlas 当前缺少回滚说明。
```

当前系统允许相同 surface form 的不同 entity 并存。`发布项目`、`知识文档`、`rollout`、`checklist`、`policy`、`handbook`、`service` 这类词通常是重要身份限定，不是装饰词。

### 2.4 把事实写进 memory 内容，不写进 identity

`identity_profile` 只描述“这是谁”，不承载当前状态、负责人、阻塞、规则正文或结论。调用方不需要直接构造 `identity_profile`，但写入文本要避免把事实伪装成主体名。

推荐：

```text
Gateway policy 当前要求所有生产发布在执行前补齐审批链说明。
```

不推荐：

```text
主体是 Gateway policy 当前要求补齐审批链说明。
```

前者会让系统把 `Gateway policy` 作为 identity，把要求写成 memory。后者容易污染 identity。

### 2.5 一条输入保持一个清晰证据单元

`observation` 会保存原始输入，并通过 `derived_from` edge 连接到 memory。写入时应让一条 `context` 对应一个清晰来源或一个连贯片段。

推荐：

- 一条会议结论写成一条 context。
- 一封邮件里多个明确主体可以放在同一条 context，系统会拆出多个 draft 和 candidate。
- 一个长报告如果围绕一个主体形成一个主要结论，保留足够上下文写成一条详细 memory。

不推荐：

- 把不同来源、不同时间、不同主体的零散片段无边界地拼在一起。
- 只写摘要，不写关键证据词，例如具体 blocker、要求、日期、文档名、审批项。

### 2.6 显式表达当前态、历史态和补充态

当前 resolver 会根据语义判断新旧 memory 是 `create`、`refresh`、`replace`、`coexist` 还是 `stale`。调用方应在文本里明确时间和演进关系。

推荐：

```text
Ashgrove handbook 之前允许团队在 shift 后 24 小时内补录 fallback schedule。
Ashgrove handbook 当前要求所有 fallback schedule 变更必须先经 incident lead 审批。
Ashgrove handbook 最新补充：所有审批记录还必须附在 change packet 中。
```

这种写法可以让系统保留历史规则，把当前规则作为 active head，并把补充要求 refresh 到当前记忆里。

不推荐：

```text
Ashgrove handbook 要求审批。
Ashgrove handbook 还要 change packet。
```

缺少“之前 / 当前 / 最新补充”时，系统仍会尝试判断，但历史和当前边界更容易变得模糊。

### 2.7 不要为缺失项随意创建主体

如果某个名字只是另一个主体的缺失原因、附件、前置条件或证据，通常应留在主主体的 memory 里，不应写成独立主体。

推荐：

```text
Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。
```

只有当缺失项本身有独立状态、负责人、规则或生命周期时，才把它写成独立主体：

```text
Harborlane quay memo 当前负责人是 Ivo Tan。
```

### 2.8 写入后按异步语义处理

当前 `/memory/ingest` 是热路径加后台继续处理：

1. 热路径先抽取 identity draft。
2. gate 通过后创建 observation。
3. 创建 `continue_ingest` 后台任务。
4. 后台继续做 entity resolution、memory resolver、edge 写入和索引刷新。

因此调用方不要假设 `accepted` 响应代表 memory 已经可立即召回。读取时如果同一个 `memory_scope` 仍有 pending/running 的 `continue_ingest`，`recall` 会返回：

```json
{
  "status": "not_ready",
  "error_code": "memory_scope_not_ready",
  "uncertainties": ["continue_ingest_pending"]
}
```

推荐做法：

- 写入后需要立刻读取时，对 `not_ready` 做短退避重试。
- 批量导入后等待后台任务清空，再运行评估或对用户开放查询。
- 调试时查看 task 状态、observation 状态和 LLM run audit，而不是只看 ingest HTTP 响应。

## 3. 读取最佳实践

### 3.1 查询里必须带目标主体

当前 recall 也会先运行 query planner，抽取 query identity draft，再做 entity resolution。查询里应明确写出目标 entity。

推荐：

```text
Atlas 发布项目 当前主阻塞是什么？
```

不推荐：

```text
当前主阻塞是什么？
```

如果 query 不能解析出稳定主体，系统会返回 `cannot_resolve_query_identity`。

### 3.2 同名主体查询要带身份限定

如果同一 scope 中可能存在 `Atlas 发布项目` 和 `Atlas 知识文档`，查询时不要只写 `Atlas`。

推荐：

```text
Atlas 发布项目 当前主阻塞是什么？
Atlas 知识文档 当前缺什么？
```

不推荐：

```text
Atlas 怎么了？
```

当多个候选 entity 都合理时，系统会返回 `ambiguous_query_identity`，并在 uncertainties 里带上歧义候选。

### 3.3 明确时间意图

query planner 会识别 `current`、`latest`、`history` 或 `unspecified`。时间意图会影响 seed memory 过滤和 `updates` edge 扩展。

常用问法：

- 当前状态：`Cedar review 当前主阻塞是什么？`
- 最新结论：`Cedar review 最新决定是什么？`
- 历史演进：`Cedar review 之前卡过什么，当前又变成什么？`
- 旧规则：`Ashgrove handbook 之前允许什么？`

如果问题同时问“之前”和“现在”，应显式写出两者，系统会按 history 路径扩展演进链。

### 3.4 why/how 查询要保留具体问题词

召回不是只做相似度检索。系统会先找 seed memories，再沿 `updates`、`supports`、`contradicts`、`related_to` edge 扩展，并可能补充跨 entity 关系。

推荐：

```text
为什么 Billing service 还不能切换到新模板？
Nimbus rollout 当前阻塞之外，还有哪些外部上下文？
Topaz transfer review 为什么从历史分歧收敛到现在的结论？
```

这类问法能让 query planner 和 cross-entity query builder 保留 blocker、要求、缺失项、外部规则等检索线索。

### 3.5 处理多主体查询的多结果

多主体查询会被拆成多个 query identity draft，响应中的 `results` 也会有多条。调用方应把每个 result 当成独立答案处理，不要默认只有第一条有意义。

推荐：

```text
Atlas 发布项目 当前主阻塞是什么？Atlas 知识文档 当前缺什么？
```

返回可能包含两个 result，一个对应发布项目，一个对应知识文档。

### 3.6 总是读取 citations 和 uncertainties

`answer` 是给用户看的答案，`citations` 和 `uncertainties` 是调用方判断可信度、展示证据和排障的关键。

建议：

- UI 中展示 citation 的摘要或原文片段。
- 对 `no_relevant_memory_found` 展示“没有找到相关记忆”，不要把空答案当成功内容。
- 对 `ambiguous_query_identity` 引导用户补充主体限定。
- 对 `contradicting_memory:*` 标注存在冲突证据。
- 对 `not_ready` 做重试，不要展示为最终无结果。

## 4. 接入方不要绕过的边界

### 4.1 不直接写业务表绕过 ingest graph

如果直接插入 `memory_memories`，会绕过 extractor、linker、resolver、version、edge、profile refresh 和 retrieval index 刷新，导致召回不稳定。

必须导入历史数据时，优先通过 `/memory/ingest` 或复用 ingest graph；如果确实做离线迁移，迁移后必须重建检索索引并补齐来源、版本和 edge。

### 4.2 不把 `entity_key` 当业务可读 ID

`entity_key` 是系统分配的 opaque id，不应由调用方拼接、猜测、展示为业务名称或跨 scope 复用。调用方应该把自然语言主体写进 `context` 和 `query`，让系统做 entity resolution。

### 4.3 不用关键词规则替代语义判断

当前项目约束明确禁止在记忆系统里用关键词匹配或定制化规则来让个别用例通过。接入层也应避免把“包含某词就写入某类记忆”“包含某词就查某 entity”这类逻辑放到系统外部。

需要判断时，优先改进输入结构、prompt、schema、评估用例和 LLM 决策审计，而不是新增硬编码规则。

### 4.4 关注索引健康

检索索引是业务真相表的派生数据。写入 entity 或 memory 后会刷新 pgvector 检索索引；embedding 模型、维度或投影版本变化后，需要重建索引。

上线和排障时建议检查：

- `/health` 中 `index_status`、`embedding_provider`、`embedding_model`、`embedding_dim`。
- 本地 embedding 的 `embedding_prewarm_status` 是否为 `ready`。
- 后台任务是否有 `failed` 或 `dead_letter`。
- 业务表有数据但 recall 找不到时，优先检查检索索引是否缺失或过期。

## 5. 推荐调用流程

写入流程：

1. 选择正确的 `memory_scope`，不要把不同用户、租户或实验数据混在一起。
2. 把输入整理成包含稳定主体、关键事实、时间状态和来源上下文的 `context`。
3. 调用 `/memory/ingest`。
4. 如果返回 `rejected`，根据 `error_code` 修正输入主体。
5. 如果返回 `accepted`，等待后台继续处理完成，或在 recall 侧处理 `not_ready`。

读取流程：

1. 在 `query` 中明确目标主体和身份限定。
2. 写清楚时间意图：当前、最新、历史或演进。
3. why/how 问题保留具体 blocker、要求、缺失项、外部上下文等词。
4. 调用 `/memory/recall`。
5. 逐条处理 `results`，同时读取 `answer`、`citations`、`uncertainties` 和 `error_code`。

## 6. 快速检查表

写入前检查：

- `context` 是否明确说明这条记忆属于哪个稳定主体。
- 同名主体是否带了角色词或身份限定。
- 当前、历史、补充、替换关系是否写清楚。
- 关键证据词是否保留。
- 缺失项是否只是主主体的原因，而不是被误写成独立主体。

读取前检查：

- `query` 是否明确带上目标主体。
- 是否需要加角色词避免同名歧义。
- 是否明确问当前、最新、历史或演进。
- 是否准备处理 `not_ready`、`ambiguous_query_identity` 和 `no_relevant_memory_found`。
- 是否会展示或记录 citations 与 uncertainties。
