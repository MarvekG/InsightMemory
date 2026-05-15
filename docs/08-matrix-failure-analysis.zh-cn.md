# Matrix 高并发评测失败分析

本文记录 `full_concurrency20_20260423T104758Z` 这次全量 matrix 评测中的失败原因分析。本文只做问题归因，不包含修复实现。

## 评测摘要

- 执行命令：`evals/scripts/eval_memory_matrix.py --manifest evals/matrix/default_v1.json --max-concurrency 20`
- 报告文件：`evals/reports/matrix/full_concurrency20_20260423T104758Z__20260423T104802Z-949bd768.json`
- 总用例数：167
- 通过用例数：157
- Full pass rate：0.9401
- Answer grounded rate：0.9948
- 失败 case 数：9
- 主要耗时：
  - `ingest`: avg 3569ms, p95 5192ms, max 11321ms
  - `recall`: avg 20132ms, p95 45345ms, max 55999ms

## 问题分类

删除 `hard/multi_hop_conflict_and_history_query` 后，本文保留 9 个失败 case，可以分成 5 类：

1. 后台任务或异步 ingest 未及时完成：2 个。
2. 冲突关系已存在或应存在，但 recall 结果没有稳定暴露 `contradicting_memory:`：1 个。
3. 抽取阶段把原因、缺口、轮次等事件信息误当成独立 entity：3 个。
4. 相关缺口查询没有把邻接 memory 带入回答上下文：2 个。
5. 答案内容和 citation 不一致：1 个。

## 小白版总览

可以先把这个系统理解成 4 步：

1. 写入时，系统先从原文里找出“这条记忆属于谁”。
2. 再把事实保存成一条或多条记忆。
3. 后台慢慢补充索引、关系、主体画像等辅助信息。
4. 查询时，系统先找主体，再找相关记忆，最后拼答案和引用。

这次失败主要不是数据库坏了，也不是所有召回都失败。大部分问题是下面几类：

- 有些记忆还没处理完就开始问了，所以系统只能说“还没准备好”。
- 有些答案说对了，但引用没跟上，像写论文时正文说 A，脚注却指向 B。
- 有些文本里的“原因”被系统误当成了一个新的主体，比如把“缺 customs appendix”当成一个独立记忆对象。
- 有些问题问“还有什么相关缺口”，系统只看到了主风险，没有把旁边那条相关缺口记忆一起拿出来。
- 有些历史分歧已经识别出来了，但返回结果里没有明确打上“这里有冲突记忆”的标记。

几个名词可以这样理解：

- `entity`：记忆的主体，也就是“这条记忆说的是谁”。例如 `Atlas 发布项目`、`Atlas 文档`。
- `memory`：真正保存下来的事实。例如“当前主阻塞是数据库迁移失败”。
- `observation`：原始写入文本，也就是事实的来源。
- `citation`：答案引用的来源。用户看到答案时，需要知道答案来自哪条原文。
- `edge`：两条记忆之间的关系。例如支持、冲突、相关。
- `background task`：后台补充工作，例如建索引、补关系、刷新主体画像。
- `not_ready`：还有关键后台写入任务没完成，系统暂时不允许查询这个空间。

## 1. `generic/history_person_records`

### 一句话

答案说的是第二条历史记录，但引用却指向了第一条历史记录。

### 小白版失败原因

系统脑子里其实有两条记录：

- 第一条：Jordan Lee 同意先补告警再发版。
- 第二条：Jordan Lee 反对直接发版，要求先补回滚演练。

用户问“最新历史记录是什么”，系统回答了第二条，这是对的。但它给出的引用却是第一条。这样就变成“答案对了，证据错了”。评测会认为这个答案没有依据，因为用户如果点开引用，只能看到第一条，不会看到答案里说的第二条。

### 小白版修改方案

回答前要做一次校验：答案里用了哪条记忆，引用就必须包含哪条记忆的来源。不能让答案从 A 记忆来，引用却指向 B 记忆。

### 期望

输入两条 `Jordan Lee` 的 bounded historical records：

- Round 1：支持先补告警再发版。
- Round 2：反对直接发版，要求先补回滚演练。

查询 `Jordan Lee 最新历史记录是什么？` 时，答案应能引用支持最新记录的 observation。

### 实际

接口返回 `ok`，答案说的是 Round 2：

`Jordan Lee 在 coaching-1 第2轮中反对直接发版，要求先补回滚演练。`

但返回的答案引用和 `citations` 指向 Round 1 observation：

- citation summary：`Round: 1 Position: supportive Summary: 同意先补告警再发版。`
- `uncertainties` 中包含 Round 2 的 `contradicting_memory`。

最终 judge 判定 `grounded=false`。

### 详细失败原因

这是答案和 citation 没有绑定一致的问题，不是检索不到数据。

从快照看，数据库状态是正确的：

- `entity_count=1`
- `memory_count=2`
- `edge_type_counts={"derived_from": 2, "contradicts": 1}`

说明两条历史记录都被写入，并且冲突边也存在。问题发生在 recall 输出阶段：

1. 检索/图扩展阶段拿到了多条 memory，其中 Round 2 作为 contradiction 相关 memory 暴露在上下文中。
2. `answer_composer` 可以看到 expanded memories、observations、`recall_answer` 和 uncertainties。
3. 但最终用于输出的 citation 仍然保留 Round 1。
4. composer 生成答案时使用了 Round 2 的内容，citation 却没有同步切到 Round 2。

也就是说，当时系统没有强约束“答案中的事实必须由返回的 citation 覆盖”。当 contradiction memory 进入上下文但没有进入 citation 时，composer 仍可能用它回答，造成 grounding 错配。

### 修复方向

- 让 `answer_composer` 输出 answer 时必须同时输出支撑该 answer 的 citation。
- `answer_composer` 只能使用输入候选 memories、used_edges、observations 中能被 citation 覆盖的事实生成答案。
- 对 `latest/history` 查询，如果答案选择 contradiction 侧 memory，必须同步把该 memory 的 observation 加入 citation。
- 增加 post-check：答案引用了某条 memory 的事实，但 citation 未覆盖时，直接修正 citation 或降低为不确定回答。

## 2. `stress/stress_three_way_same_surface_split`

### 一句话

答案已经对了，但后台还有一个“刷新主体画像”的维护任务没跑完，所以评测判失败。

### 小白版失败原因

这里用户问的是 `Orbit checklist`，系统正确回答了 checklist 的要求，没有串到 `Orbit rollout` 或 `Orbit review`。

失败不是因为答案错，而是因为评测还会检查后台任务是不是都清空了。这个 case 结束时，还有一个 `refresh_entity_profile` 在跑。它更像“整理档案封面”的后台工作，不是这次回答必须依赖的核心工作。

### 小白版修改方案

要决定这类任务到底算不算“查询前必须完成”。如果不影响回答，就不要把它当成评测里的关键阻塞任务；如果必须算关键，就要减少它的耗时和重复执行。

### 期望

同一 scope 下存在三个同前缀主体：

- `Orbit rollout`
- `Orbit checklist`
- `Orbit review`

查询 `Orbit checklist 当前要求什么？` 应命中 checklist，不串到 rollout/review，并且后台任务在 settle timeout 内完成。

### 实际

业务答案完全正确：

`Orbit checklist 当前要求切换前补齐审批链说明和回滚说明。`

但 case 失败在 `background_tasks=false`：

- `pending_task_count=3`
- `running_task_count=1`
- `critical_running_task_count=1`
- `critical_task_type_counts={"refresh_entity_profile": 1}`

### 详细失败原因

这是后台收敛 SLA 问题，不是 recall 正确性问题。

当前 ingest 完成后会为每个 entity enqueue 后续任务：

- `refresh_entity_profile`
- `reindex_memory`
- `repair_memory_edges`
- `detect_merge_candidates`

其中 `refresh_entity_profile` 在评测里被算作 critical task。高并发 20 跑全量 matrix 时，这个 case 的 query 和 answer 已完成，但 post-query settle 时仍有一个 `refresh_entity_profile` 在运行，所以 `background_tasks` 维度失败。

这个任务本身会调用 profile writer，属于 LLM 相关维护任务。在同前缀多 entity 场景下，多个 entity 的 profile refresh 容易排队或长时间运行。由于它不影响这次 answer 的正确性，把它算作必须同步收敛的 critical task，会放大高并发下的偶发失败。

### 修复方向

- 明确 `refresh_entity_profile` 是否真是 recall 前置关键任务。
- 如果不是关键任务，应从 critical settle 条件中移出，作为非阻塞维护任务。
- 如果必须关键，应降低它的执行成本，或避免无变化 entity 重复 refresh。
- 高并发评测可以继续检查该任务，但不要让业务答案正确的 case 因非必要维护任务失败。

## 3. `multi_subject_document/multi_subject_same_prefix_artifacts_split`

### 一句话

一篇长文本里有 5 个主体，后台还没拆完就开始查询了，所以系统返回 `not_ready`。

### 小白版失败原因

这条输入很长，一次性提到了 5 个相似名字的对象：

- plan
- review
- bulletin
- register
- checklist

写入接口先返回 accepted，但真正拆分主体和生成记忆是在后台继续处理的。查询时后台还在跑，记忆还没生成出来，所以系统不允许查询，返回“这个空间还没准备好”。

这里不是最终一定只能抽出 4 个主体。报告里看到 `entity_count=4, memory_count=0`，只是说明当时任务跑到一半，还没处理完。

### 小白版修改方案

要么让这类长文本的后台处理更快，要么让同一篇文本里的多个主体并行处理。核心目标是：用户写入一条长文本后，不要等很久才可查。

### 期望

一篇 digest 中同时包含 5 个同前缀 artifact：

- `Latchmere plan`
- `Latchmere review`
- `Latchmere bulletin`
- `Latchmere register`
- `Latchmere checklist`

系统应拆出 5 个 entity 和 5 条 memory。查询 review/bulletin 应返回对应事实。

### 实际

两次 query 都返回：

- `status=not_ready`
- `error_code=memory_scope_not_ready`
- `uncertainties=["continue_ingest_pending"]`

snapshot：

- `entity_count=4`
- `memory_count=0`
- `running_task_count=1`
- `task_type_counts={"continue_ingest": 1}`

### 详细失败原因

这是单条长 observation 的异步 ingest 没在评测窗口内完成。

写入接口已经 accepted，但真正的多主体抽取、entity resolve、candidate resolve、memory finalize 在 `continue_ingest` 后台任务里执行。这个 case 的 `settle_timeout_seconds=60`，而全量并发 20 下该 `continue_ingest` 仍在 running。

`entity_count=4, memory_count=0` 说明 ingest 已经进入中间阶段：部分 entity 已经创建，但 memory candidate 还没 finalize。由于 `RecallService` 只要发现 scope 里还有 `continue_ingest` pending/running，就直接返回 `memory_scope_not_ready`，所以 query 被整体拦截，不会读取部分结果。

这里的 `entity_count=4` 不能直接判断为最终少抽了一个，因为任务仍在 running；它只说明高并发下中间状态暴露给 snapshot 了。

### 修复方向

- 缩短单条多主体 observation 的 `continue_ingest` 临界路径。
- 对同一 observation 内多个主体的 entity/candidate resolution 并发化，但要保证同一 observation 的最终一致性。
- 评测层面可以把这种用例的 settle timeout 调大，但这只能缓解，不解决 ingest 慢的问题。
- 产品层面如果坚持 recall 必须等待 `continue_ingest`，就需要让 `continue_ingest` 的 p95 明显低于常规 query 前等待时间。

## 4. `openworld/openworld_vessel_log_cross_entity_why`

### 一句话

系统把“缺 customs appendix”这个原因，当成了一条独立主体记忆，导致多存了一条。

### 小白版失败原因

原文意思是：

`Tidal vessel departure plan` 不能确认，因为 `customs appendix` 没补齐。

这里真正应该记住的主体是 `Tidal vessel departure plan`。`customs appendix` 是它的缺失项，是原因，不一定是一个单独要长期追踪的主体。

但系统额外创建了一条类似“customs appendix 没补齐”的记忆。答案没错，但数据库里多了一条不该有的记忆，关系也变多了。小数据时影响不大，记忆多了以后会让召回更吵。

### 小白版修改方案

抽取时要更保守：`X 不能推进，因为 Y 缺失` 默认只保存 X 的状态，把 Y 放进 X 的记忆内容里。除非原文明确给了 Y 自己的负责人、状态、规则或后续可独立查询的信息，才把 Y 当成独立主体。

### 期望

两条记忆：

- `Tidal vessel departure plan` 当前不能确认，因为 `customs appendix` 未补齐。
- `Dockside departure protocol` 要求 departure plan 确认前补齐 `customs appendix`。

应得到 2 个 entity、2 条 memory、1 条 supports edge。

### 实际

答案正确，但状态检查失败：

- `entity_count expected 2, got 3`
- `memory_count expected 2, got 3`
- `edge_type[supports] expected 1, got 3`

多出来的 memory 是：

`customs appendix 还没有补齐，导致 Tidal vessel departure plan 不能确认。`

### 详细失败原因

这是 extractor 把“缺失原因/前置材料”误抽成了独立主体和独立 memory。

在输入里，`customs appendix` 是 `Tidal vessel departure plan` 的缺失项，不是一个被独立追踪的 durable subject。系统应该把它保存在 `Tidal vessel departure plan` 的 memory 内容里，而不是创建一个 `customs appendix` 相关 entity/memory。

多出的 memory 又和 plan/protocol 建了 supports/related edge，导致：

- 状态检查里的 entity/memory 数超预期。
- supports edge 数从 1 膨胀到 3。

答案仍然正确，是因为多出来的 memory 语义上没有破坏回答；但它会污染图结构，后续大规模记忆下会增加噪声和召回成本。

### 修复方向

- extractor 需要更严格地区分“稳定主体”和“主体的缺失项/原因/条件”。
- 缺失项只有在文本给出它自己的 durable 状态、owner、规则、决策或后续可独立查询事实时，才创建独立 entity。
- 对 `X 不能推进，因为 Y 缺失` 这类结构，默认创建 `X` 的 memory，把 `Y` 当作 claim 内容。

## 5. `openworld/openworld_manuscript_conflict_and_current`

### 一句话

同一个 `Solstice manuscript review` 被拆成了 3 个主体，查询时系统不知道该选哪个。

### 小白版失败原因

三条输入其实都在说同一个东西：

- 第一轮这个 review 怎么看。
- 第二轮这个 review 怎么看。
- 当前这个 review 的结论是什么。

`round 1`、`round 2`、`当前结论` 是记录的阶段，不是主体名字的一部分。但系统把它们当成了不同主体，所以数据库里出现了 3 个很像的 entity。

用户再问 `Solstice manuscript review` 时，系统看到 3 个候选都像，于是拒绝回答，说“主体不明确”。

### 小白版修改方案

生成主体身份时，不能把轮次、当前状态、结论这种变化信息塞进去。主体应该固定为 `Solstice manuscript review`，轮次放到记忆内容或记录标记里。

### 期望

三条记录都属于同一个主体 `Solstice manuscript review`：

- round 1：可以按现有注释提交。
- round 2：必须先补齐 provenance appendix。
- 当前结论：先补齐 provenance appendix，再安排提交。

应得到 1 个 entity、3 条 memory，并能回答历史分歧和当前结论。

### 实际

query 被拒绝：

- `status=rejected`
- `error_code=ambiguous_query_identity`
- `uncertainties` 中有 3 个 ambiguous entity。

snapshot：

- `entity_count=3`
- `memory_count=3`
- `edge_type_counts={"derived_from": 3, "supports": 1}`
- 没有 `contradicts`

### 详细失败原因

这是 identity profile 漂移导致同一主体被拆成 3 个 entity。

这三条输入都围绕稳定主体 `Solstice manuscript review`，round/current 是历史记录或当前结论的事件属性，不能进入 entity identity。但实际抽取结果把：

- `Solstice manuscript review round 1`
- `Solstice manuscript review round 2`
- `Solstice manuscript review 当前结论`

拆成了不同 entity。查询时 query planner 生成的是 `Solstice manuscript review`，linker 看到多个候选都相似，无法唯一绑定，于是返回 `ambiguous_query_identity`。

因为主体被拆散，repair edge 也无法在同一 entity 下稳定生成预期的 `contradicts`。最终既没有回答，也没有正确的历史冲突结构。

### 修复方向

- extractor 和 query planner 必须共享同一套 identity 规则：round、current、conclusion、decision 等只能进入 memory 内容或 record markers，不能进入 identity profile。
- 对同一 `Subject + Session/Stage/Round` 的 bounded historical record，应保持同一个 entity，靠 `record_markers` 区分 memory。
- merge 不能作为主路径兜底；写入阶段就应尽量生成稳定 identity。

## 6. `heterogeneous/heterogeneous_history_disagreement_with_rule`

### 一句话

答案说出了分歧，但返回结构里没标记“存在冲突记忆”。

### 小白版失败原因

系统回答里已经包含：

- 第一轮支持按原窗口转运。
- 第二轮反对，要求补 `ballast variance note`。
- 当前因为规则要求而收敛到新的结论。

这些内容都对。但结构化的 `uncertainties` 没写 `contradicting_memory:`。所以评测认为系统没有明确告诉调用方“这里有历史冲突”。

### 小白版修改方案

只要回答里用到了支持/反对两种历史立场，就必须在返回字段里带上冲突标记。这个标记应该由当前召回上下文决定，不应该依赖后台关系修复任务是否及时完成。

### 期望

`Mica transit review` 有历史分歧、当前收敛结论，并受 `Departure ordinance` 约束。查询应回答分歧、当前原因，并输出 `contradicting_memory:`。

### 实际

答案和 citation 都通过 judge，但 deterministic 检查失败：

`q1 missing uncertainty prefix contradicting_memory:`

snapshot：

- `memory_count=4`
- `edge_type_counts={"derived_from": 4, "contradicts": 1, "supports": 3}`

### 详细失败原因

这是内容召回成功、结构化冲突信号没稳定输出的问题。

当前答案能说出：

- Round 1 支持按原窗口转运。
- Round 2 反对，要求补 `ballast variance note`。
- 当前因 `Departure ordinance` 收敛到补 note 后再排期。

但 `uncertainties=[]`。这说明 recall/composer 可以利用多条 memory 生成自然语言答案，却没有把历史冲突转换为结构化 uncertainty。

高置信推断是：`contradicts` edge 要么在 recall 之后才被后台修复任务创建，要么没有在当前 recall 的 graph expansion 路径中被纳入 `used_edges`。由于 uncertainty 目前依赖 edge 遍历，而不是从 answer context 中二次校验冲突事实，所以出现“答案提到分歧，但结构化 uncertainty 缺失”。

### 修复方向

- 在最终 result 阶段从 expanded memories 和 used edges 补齐 `contradicting_memory:`。
- 对 query focus 为 history/disagreement 的查询，把 bounded records 的 opposing/supportive 关系作为一等输出信号。
- 不应让 uncertainty 是否输出依赖后台 edge repair 是否刚好跑完。

## 7. `heterogeneous/heterogeneous_noisy_multilingual_dependency`

### 一句话

系统又把“corridor packet 缺少 signed seal manifest”这个原因，当成了独立主体记忆。

### 小白版失败原因

原文真正要表达的是：

`Fjord relay corridor` 不能推进，因为 packet 缺少某个材料。

这里应该保存的是 `Fjord relay corridor` 的阻塞原因，以及 `Channel dispatch protocol` 的规则。`corridor packet 缺少 signed seal manifest` 只是阻塞原因，不应该再单独变成一个新主体。

这个问题和 `openworld_vessel_log_cross_entity_why` 一样，只是这次文本更长、还有中英文混合和噪声，更容易让模型误判。

### 小白版修改方案

长噪声文本里，抽取要先找“主结论”和“独立外部规则”。解释性从句、缺失项、材料名默认不要单独建主体。

### 期望

两条记忆：

- `Fjord relay corridor` 当前无法推进，因为 `corridor packet` 缺少 `signed seal manifest`。
- `Channel dispatch protocol` 要求 corridor packet 包含 signed seal manifest。

应得到 2 个 entity、2 条 memory。

### 实际

答案正确，但状态检查失败：

- `entity_count expected 2, got 3`
- `memory_count expected 2, got 3`

多出来的 memory 是：

`corridor packet 缺少 signed seal manifest，导致 Fjord relay corridor 无法推进。`

### 详细失败原因

这和 `openworld_vessel_log_cross_entity_why` 是同类抽取过度问题。

输入里 `corridor packet 缺少 signed seal manifest` 是 `Fjord relay corridor` 不能推进的原因短语，不是独立主体。extractor 在 noisy mixed-language 文本中把原因短语提升成了单独 memory，导致 entity/memory 计数膨胀。

这个错误在混合语言和长噪声输入下更容易出现，因为模型会把 `corridor packet` 识别成一个看起来像 artifact 的名词短语。但从记忆系统角度，它没有自己的 durable state；它应保留在 `Fjord relay corridor` 的 memory 内容中。

### 修复方向

- 抽取阶段加强“原因短语不是主体”的规则。
- 对 noisy long text，应优先抽主结论和独立外部规则，不要把解释性从句拆成独立 memory。
- 如果确实要把缺失项建成实体，需要额外判断它是否具备可独立追踪的 owner/state/rule。

## 8. `market/market_related_gap_with_noise`

### 一句话

用户问“除了主风险，还有什么相关缺口”，系统只看到了主风险，漏掉了旁边那条相关缺口。

### 小白版失败原因

数据库里其实有两条记忆：

- Redstone Retail 当前主风险是 `commodity hedge missing`。
- Commodity risk handbook 缺 `hedge validation workflow`，这是邻接缺口。

而且系统已经建立了一条 `related_to` 关系，说明它知道两者相关。

但查询时，系统只把第一条主风险拿给答案生成器，没有把第二条相关缺口一起拿出来。答案生成器看不到第二条，就回答“没有提到其他缺口”。这就是典型的“仓库里有，但没取出来”。

### 小白版修改方案

当用户问“相关缺口/其他缺口/邻接问题”时，查询阶段必须主动跨到相关记忆里找，不能只查主实体自己。并且答案生成器不能因为当前拿到的材料里没有，就直接说“没有其他缺口”。

### 期望

主记忆是：

`Redstone Retail 当前主风险是 commodity hedge missing。`

邻接缺口是：

`Commodity risk handbook 目前还缺 hedge validation workflow。`

查询 `除了当前主风险外，Redstone Retail 还有什么相关缺口？` 时，应返回 `hedge validation workflow` 和 `Commodity risk handbook`。

### 实际

答案只引用主风险，并说：

`未提及除此之外的其他缺口。`

snapshot 里实际有：

- `entity_count=2`
- `memory_count=2`
- `edge_type_counts={"derived_from": 2, "related_to": 1}`

### 详细失败原因

这是“相关缺口查询没有使用已存在 related_to 边”的问题。

数据库中已经有 `related_to=1`，说明 edge repair 已经判断主风险和外部 handbook 相关。但当时 recall 的返回只有主风险 memory：

- `citations` 只有主风险 observation。
- 没有 `Commodity risk handbook` 的 citation。

由于 `_expand_graph` 当时只有在 `query_focus.expand_cross_entity=true` 时才会跨 entity 走 `supports/related_to`，而本次结果没有带入外部 memory，说明 query planner 对“除了当前主风险外，还有什么相关内容”这类问题没有稳定打开 cross-entity expansion，或者 cross-entity expansion 没有把 related_to memory 纳入最终 composer 输入。

随后 `answer_composer` 在上下文不足时生成了“未提及其他缺口”这种 absence claim。但 memory store 实际存在相关缺口，只是没有被召回到 composer 上下文，因此这个回答是错误的。

### 修复方向

- query planner 对“相关缺口、邻接缺口、其他缺口、周边缺口、besides current risk”等语义，应稳定设置 `expand_cross_entity=true`，不能只把它当作主实体的当前状态查询。
- cross-entity expansion 对已存在的 `related_to` 边应优先纳入候选。
- answer composer 不应在未执行全 scope 查询时断言“没有其他缺口”；只能说“当前召回上下文未覆盖其他缺口”，但最好避免这种回答进入通过路径。

## 9. `finance/finance_related_gap_with_noise`

### 一句话

和 `market_related_gap_with_noise` 类似，但更严重：相关缺口不仅没被查出来，系统也没提前建好“相关”关系。

### 小白版失败原因

数据库里有两条记忆：

- Cloudspan semiconductor basket 当前主风险是 `channel inventory overhang`。
- Supply discipline memo 缺 `distributor inventory validation workflow`。

这两条应该算相关缺口。但报告显示只有原文来源关系，没有 `related_to`。也就是说，系统写入后没有把这两条记忆连起来。查询时又没有动态把第二条搜出来，所以答案只看到了主风险，并错误地说没有其他相关缺口。

### 小白版修改方案

需要两层修：

1. 写入后的关系修复要更容易识别“主风险 + 邻接缺口”。
2. 查询时只要用户问“相关缺口”，就算关系没提前建好，也要通过语义检索去找可能相关的外部记忆。

### 期望

主记忆是：

`Cloudspan semiconductor basket 当前主风险是 channel inventory overhang。`

邻接缺口是：

`Supply discipline memo 目前还缺 distributor inventory validation workflow。`

查询 `除了当前主风险外，Cloudspan semiconductor basket 还有什么相关缺口？` 时，应返回 `distributor inventory validation workflow` 和 `Supply discipline memo`。

### 实际

答案只引用主风险，并说：

`未提及除主风险外的其他相关缺口。`

snapshot：

- `entity_count=2`
- `memory_count=2`
- `edge_type_counts={"derived_from": 2}`
- 没有 `related_to`

### 详细失败原因

这是 `market_related_gap_with_noise` 的更严重版本：不仅 recall 没带出邻接缺口，edge repair 也没有建立 `related_to`。

两个 memory 都已经存在：

- `Cloudspan semiconductor basket 当前主风险...`
- `Supply discipline memo missing distributor inventory validation workflow...`

但 `edge_type_counts` 只有 `derived_from`，说明 repair 阶段没有把两者识别为相关缺口。这样即使 query planner 打开 cross-entity expansion，recall 也只能依赖动态跨实体检索补充。如果动态检索没有命中 `Supply discipline memo`，composer 就只看到主风险，并生成错误 absence claim。

失败链路包含两个断点：

1. 写入后的 relation repair 没有建立 `related_to`。
2. 查询时 cross-entity retrieval 没有把外部缺口补进上下文。

### 修复方向

- edge judge/repair 对“主风险 + 邻接缺口”这种关系需要更稳定地产生 `related_to`。
- query planner 对 related-gap 查询必须打开 cross-entity expansion。
- dynamic cross-entity query builder 应保留“除了当前主风险外/相关缺口”的检索意图，而不是只围绕主风险文本搜索。
- composer 禁止基于局部召回上下文生成“没有其他缺口”结论。

## 优先级建议

### P0：先修 related-gap 召回

涉及 `market_related_gap_with_noise` 和 `finance_related_gap_with_noise`。这是业务语义错误：用户明确问“还有什么相关缺口”，系统却回答“没有其他缺口”。修复重点是 query planner、cross-entity expansion、edge repair 和 composer absence claim。

### P1：修 identity / extractor 过度拆分

涉及 `openworld_vessel_log_cross_entity_why`、`openworld_manuscript_conflict_and_current`、`heterogeneous_noisy_multilingual_dependency`。这类问题会污染 entity/memory 数量，长期会放大索引和图检索噪声。

### P1：修 contradiction uncertainty 输出

涉及 `heterogeneous_history_disagreement_with_rule`。答案目前能过，但结构化输出不稳定。应让 `contradicting_memory:` 成为 recall 结果的稳定字段，而不是依赖后台边修复时序。

### P2：修 answer-citation 一致性

涉及 `history_person_records`。这是 grounded answer 的基本约束，虽然只出现 1 个 case，但问题性质严重：答案引用了没有被 citation 覆盖的事实。

### P2：处理后台收敛 SLA

涉及 `stress_three_way_same_surface_split` 和 `multi_subject_same_prefix_artifacts_split`。其中 `multi_subject_same_prefix_artifacts_split` 会直接导致 not_ready，优先级高于单纯 profile refresh 超时。应先压缩 `continue_ingest` 临界路径，再考虑评测 timeout。
