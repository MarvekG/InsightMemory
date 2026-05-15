# 后台任务调度设计

这份文档定义 `memory` 服务后台任务的调度方式。

目标不是解释记忆语义，而是明确：

- 后台任务如何 claim、执行、重试
- 哪些任务可以并行
- 哪些任务可以合并
- 哪些任务必须串行
- 高并发下为什么会掉 `full_pass`
- 后续实现应按什么验收

## 1. 当前实现摘要

当前后台任务链路由这几部分组成：

- [ingest_graph.py](/home/wang/Codes/Best-AI-Trader/memory/insight_memory/graph/ingest_graph.py)
  - 写入结束后排 follow-up task
- [runtime.py](/home/wang/Codes/Best-AI-Trader/memory/insight_memory/tasks/runtime.py)
  - 负责 claim 和 dispatch task
- [background.py](/home/wang/Codes/Best-AI-Trader/memory/insight_memory/workers/background.py)
  - 轮询执行 due task
- [repository.py](/home/wang/Codes/Best-AI-Trader/memory/insight_memory/storage/repository.py)
  - 保存 `memory_tasks`

当前瓶颈已经被真实高并发 matrix 暴露出来：

- `default_matrix_max_v2`
  - `137` 个 case
  - `21` 个 full pass
  - `full_pass_rate = 15.33%`
  - `answer_grounded_rate = 99.35%`

这里的低分不是主回答链路整体崩掉，而是：

- `background_tasks` 失败 `116` 次
- `state` 失败 `25` 次
- `recall_structured` 失败 `6` 次
- `answer_judge` 失败 `4` 次

这说明当前高并发下的主问题是：

- 后台任务队列清不完
- 图和索引补齐太慢
- 少量结构化输出在高压下漂移

不是“系统已经不会答”。

## 2. 任务分类

### 2.1 可按 entity 合并的重算型任务

这类任务的输入是“当前已落库状态”，最终结果由最新状态决定。

| task_type | 目标对象 | 可并行 | 可合并 | 合并键 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `refresh_entity_profile` | 单个 entity | 仅不同 entity 可并行 | 是 | `memory_space + entity_key` | 最新 active memories 足以覆盖旧 refresh |
| `repair_memory_edges` | 单个 entity 的局部图 | 仅不同 entity 可并行 | 是 | `memory_space + entity_key` | 最新 memory 集合重建一次图即可 |
| `reindex_memory` | entity 或 memory doc | 仅不同 entity 可并行 | 是 | `memory_space + entity_key` | 同 entity 多次 reindex 只需最新一次 |
| `detect_merge_candidates` | 单个 entity | 仅不同 entity 可并行 | 是 | `memory_space + entity_key` | 基于最新 identity profile 检索候选即可 |

这些任务都满足：

- 重跑不会改变真相，只会重复劳动
- 最新一次执行通常覆盖之前几次
- 同一个 entity 上不应并行执行多个相同任务

### 2.2 只能对不相交目标并行的真相修改任务

| task_type | 目标对象 | 可并行 | 可合并 | 说明 |
| --- | --- | --- | --- | --- |
| `merge_entities` | 一对 entity | 仅不相交 entity pair 可并行 | 只做同 pair dedupe | merge 会改归属和索引，不能任意折叠 |
| `forget_memory` | 一组 memory | 仅不重叠 memory set 可并行 | 只做同 bundle dedupe | archive 是生命周期真相修改 |
| `purge_memory` | 一组 archived memory | 仅不重叠 memory set 可并行 | 只做同 bundle dedupe | purge 会真正删数据和索引 |

这些任务不能按“最新状态覆盖旧状态”来理解。

例如：

- `A -> B` merge
- `B -> C` merge

不能被粗暴合成“一次 merge”，因为 survivor 和最终归属会被改变。

### 2.3 全局单例任务

| task_type | 目标对象 | 可并行 | 可合并 | 说明 |
| --- | --- | --- | --- | --- |
| `rebuild_retrieval_index` | 全局 retrieval index | 否 | 只保留一个 pending | embedding 模型或索引投影版本变化后，全量清空并重建向量表 |

它必须全局串行。

## 3. 正式调度规则

### 3.0 入队防抖规则

写入链路为每个受影响 entity 排 follow-up task 时，重算型任务不再使用 `observation_id` 作为去重键，而是使用稳定的
`memory_space + entity_key + task_type`。

适用任务：

- `refresh_entity_profile`
- `repair_memory_edges`
- `reindex_memory`
- `detect_merge_candidates`

这些任务的输入都是“当前已落库状态”，所以同一 entity 的连续写入只需要一次最新状态重算。入队时只合并 `pending` 任务，不合并
`running` 任务：

- 如果已有同 key `pending` 任务，复用它，避免连续写入制造重复 LLM/索引工作
- 如果同 key 任务已经 `running`，新写入必须再创建一个 `pending` follow-up，避免 running 任务已经读过旧状态而漏掉新状态

重算型任务会应用 `MEMORY_BACKGROUND_MAINTENANCE_DEBOUNCE_SECONDS` 短延迟。这个延迟的目的不是放宽评估，而是在真实 burst 写入中给同一
entity 的连续变更一个合并窗口，降低重复 profile/edge/detect 调用数。

### 3.1 claim 规则

后台 worker 每一轮执行时，必须先做原子 claim。

要求：

- 只 claim `status = pending`
- `available_at <= now`
- claim 时直接写入：
  - `status = running`
  - `lease_owner`
  - `lease_expires_at`
- 不允许先 select 再逐条改状态

原因：

- 避免多个 worker 抢到同一任务
- 避免高并发下重复执行

### 3.2 coalescing 规则

claim 完成后，进入执行前的任务合并阶段。

#### `refresh_entity_profile`

- 同 `memory_space + entity_key` 的多个 pending/running 任务，只保留一个 leader
- follower 不再单独执行
- leader 直接按当前 entity 最新状态刷新 profile

#### `repair_memory_edges`

- 同 `memory_space + entity_key` 的多个任务，只保留一个 leader
- leader 读取该 entity 当前全部有效 memory，完整重建局部图
- follower 不再单独执行

#### `reindex_memory`

- 同 `memory_space + entity_key` 的多个任务合并
- `memory_ids` 取并集
- leader 执行一次完整刷新
- 普通 entity 级 reindex 只锁定对应 entity，不再占用全局 reconcile 锁

#### `detect_merge_candidates`

- 同 `memory_space + entity_key` 的多个任务合并
- 只对最新 identity state 执行一次候选扫描

### 3.3 并行规则

#### 可以并行

- 不同 `memory_space` 的任务可以并行
- 同一 `memory_space` 下，不同 `entity_key` 的以下任务可以并行：
  - `refresh_entity_profile`
  - `repair_memory_edges`
  - `reindex_memory`
  - `detect_merge_candidates`

#### 不可并行

- 同一 `entity_key` 上的 profile、edge repair、merge detection 重算任务不可并行
- `reindex_memory` 是最终一致的索引投影任务，不加任务锁，允许充分并行
- 共享任一 entity 的 `merge_entities` 不可并行
- 共享任一 memory 的 `forget_memory / purge_memory` 不可并行
- `rebuild_retrieval_index` 必须全局单跑

`rebuild_retrieval_index` 的全局独占由调度层保证：同一批 claimed task 中先跑完普通并发 leader，再单独执行 rebuild。普通
`reindex_memory` 不应因为全局维护锁而互相串行化，否则不同 scope、不同 entity 的局部索引刷新会在高并发下形成队头阻塞。

### 3.4 优先级规则

默认优先级应固定为：

| task_type | priority | 原因 |
| --- | --- | --- |
| `reindex_memory` | 12 | 直接影响召回候选和 query 可见性 |
| `repair_memory_edges` | 11 | 直接影响 relation graph 和 why/history query |
| `refresh_entity_profile` | 8 | 影响后续 entity resolution |
| `detect_merge_candidates` | 4 | 偏治理型，不应压过关键路径 |
| `merge_entities` | 20 | 一旦创建，必须尽快消解重复主体 |
| `rebuild_retrieval_index` | 3 | 全局维护任务，仅在索引模型变化或手工维护时触发 |
| `forget_memory` | 2 | 生命周期低频任务 |
| `purge_memory` | 1 | 真正删除最不紧急 |

规则核心：

- 先执行会影响 query/answer 的关键任务
- 再执行治理和清理任务

## 4. worker 执行模型

推荐实现模型如下：

1. `recover_abandoned_tasks()`
2. `retry_failed_tasks()`
3. `claim_due_tasks(limit=N)`
4. 对 claimed task 做 coalescing
5. 按 worker pool 并发执行 leader task
6. follower task 直接标记为 coalesced 完成
7. 成功 task 标记 `succeeded`
8. 失败 task 标记 `failed / dead_letter`

worker loop 不应每轮只执行一个 batch 后立即 sleep。正式执行方式是：

- 每个 tick 维护一个活动任务池，最多同时运行 `MEMORY_BACKGROUND_MAX_CONCURRENCY` 个 leader task
- 活动池有空位时，立即继续 claim due task 补位，而不是等待当前 batch 的所有 leader 都完成
- 每个 tick 最多 claim `MEMORY_BACKGROUND_DRAIN_BATCHES_PER_TICK` 个非空 batch
- 每次 claim 的数量由 `min(MEMORY_BACKGROUND_CLAIM_LIMIT, free_worker_slots)` 决定
- 当 `MEMORY_BACKGROUND_CLAIM_LIMIT = 0` 时，使用 `MEMORY_BACKGROUND_MAX_CONCURRENCY * 2` 作为动态 claim limit
- 如果暂时没有 due task，但活动池仍有任务运行，worker 只等待一个很短的 poll 窗口，然后重新检查是否有新到期任务
- 如果没有 due task 且活动池为空，本 tick 结束并 sleep

这样做的目的不是放宽 settle，而是减少后台队列已经有任务时的 sleep 空窗，同时避免一次 claim 过多任务，让大量还没拿到 semaphore 的任务长时间停留在
`running` 状态。

这个模型修复了旧批处理模型的队头阻塞：旧模型会先 claim 一批任务，然后 `gather` 等整批结束；只要其中一个 LLM 调用很慢，后续已经到期的任务也无法
进入 worker。活动池补位后，快任务释放出的并发 slot 会立刻接新任务，慢任务只占自己的 slot，不再阻塞整个 batch。

### 4.1 并发上限

必须同时有两层限制：

- 全局 worker pool 上限
- 单 `memory_space` 上限

原因：

- 避免一个大 scope 把全局 worker 池占满
- 避免同一 scope 内互相竞争数据库和索引资源

默认值：

- `MEMORY_BACKGROUND_MAX_CONCURRENCY = 512`
- `MEMORY_BACKGROUND_MAX_PER_SPACE = 128`
- `MEMORY_BACKGROUND_CLAIM_LIMIT = 1024`
- `MEMORY_BACKGROUND_DRAIN_BATCHES_PER_TICK = 256`
- `MEMORY_BACKGROUND_MAINTENANCE_DEBOUNCE_SECONDS = 3.0`

这些值仍允许通过环境变量覆盖。`MEMORY_BACKGROUND_POLL_SECONDS` 仍决定 worker 是否启用；未显式启用后台 worker 的部署不应被这次吞吐优化改变语义。

### 4.2 lease 规则

- 每个 running task 必须设置 `lease_expires_at`
- worker 崩溃或超时时，`recover_abandoned_tasks()` 负责回收
- lease 回收后任务重新变回 `pending`

### 4.3 failure 规则

- 可重试失败进入 `failed`
- 超过 `max_attempts` 进入 `dead_letter`
- `dead_letter` 不自动重试

## 5. 与 evaluator 的关系

高并发下，当前 full pass 被压低，不是因为 evaluator 太严格，而是因为它把“回答是否对”和“所有后台任务是否清空”同时作为成功条件。

正式关系应该这样理解：

### 5.1 pre-query semantic settle

query 前需要优先清空关键任务：

- `reindex_memory`
- `repair_memory_edges`
- `refresh_entity_profile`

因为这些任务直接影响：

- 候选召回
- relation graph
- identity resolution

### 5.2 post-query full settle

query 后仍要求所有后台任务都清空。

也就是说：

- 不降低 `full_pass` 标准
- 只是把“答案前必须完成什么”和“最终必须完成什么”拆开

### 5.3 为什么 `background_tasks` 会压低 full pass

在 `default_matrix_max_v2` 中，很多 case 实际上是：

- `query_gate = true`
- `recall_structured = true`
- `answer_judge = true`

但 snapshot 时：

- `pending_task_count > 0`

于是 full pass 失败。

这说明：

- 语义链路常常已经对了
- 后台清队列速度跟不上

## 6. 观测指标

后台调度必须持续观测这些指标：

- `pending_task_count`
- `running_task_count`
- `failed_task_count`
- `dead_letter_count`
- `task_type_counts`
- 每个 task type 的平均等待时长
- 每个 task type 的执行时长
- 每个 `memory_space` 的 inflight task 数
- 每个 `entity_key` 的 coalesced follower 数

重点关注：

- `repair_memory_edges`
- `reindex_memory`
- `refresh_entity_profile`

因为这三类最直接决定 query 质量和 settle 速度。

## 7. 验收标准

这份调度设计最终要用高并发真实 matrix 验收。

验收基线：

- `default_matrix_max_v2`
- `--max-concurrency 15`

目标指标：

- `semantic_rate >= 0.95`
  - 只统计：
    - `ingest_gate`
    - `state`
    - `query_gate`
    - `recall_structured`
    - `answer_judge`
- `background_tasks pass rate >= 0.80`
- `full_pass_rate >= 0.80`
- `answer_grounded_rate >= 0.99`

如果达不到这些指标，先看：

1. `background_tasks`
2. `state`
3. `recall_structured`

而不是优先再调 prompt。

## 8. 当前结论

当前系统在正常并发下，语义已经很强。  
在最大并发下，最先暴露出来的不是回答链路，而是：

- 后台任务调度还是串行瓶颈
- 重复任务没有被合并
- 局部图和索引补齐速度跟不上

所以下一步要优化的是：

- claim 机制
- coalescing
- worker pool
- per-space 限流

不是继续靠提示词或增加 `settle_timeout` 硬顶。
