# Recall 性能优化设计

## 背景

2026-05-27 对本地真实 Memory 服务执行 `smoke_v1` recall 性能测试。服务运行在根
Compose 的 `best_ai_trader_memory` 容器内，Memory 未暴露宿主机 `8010` 端口，因此测试
在容器内直接访问 `http://127.0.0.1:8010`。

测试命令：

```bash
docker exec best_ai_trader_memory python /app/evals/scripts/eval_memory_matrix.py \
  --base-url http://127.0.0.1:8010 \
  --manifest /app/evals/matrix/smoke_v1.json \
  --run-id recall_perf_20260527_tmp \
  --max-concurrency 1 \
  --timeout-seconds 240 \
  --settle-timeout-seconds 60 \
  --database-url postgresql+asyncpg://tradeuser:tradepassword@memory-postgres:5432/memory \
  --suite-output-dir /tmp/memory_eval_reports \
  --matrix-output-dir /tmp/memory_eval_reports/matrix
```

结果：

- 6/6 cases passed
- 5/5 recall queries passed
- grounded answer rate: 100%
- recall average: 10243.16 ms
- recall median: 9450.71 ms
- recall p95 / max: 15137.07 ms
- recall min: 6088.64 ms
- recall samples: 6088.64, 9183.75, 9450.71, 11355.61, 15137.07 ms

测试时数据库规模：

| 项 | 数量 |
| --- | ---: |
| entities | 52 |
| memories | 434 |
| observations | 297 |
| edges | 854 |
| index rows | 486 |

这份文档把本次性能画像转成后续可执行的 recall 优化设计。

## 目标

- 降低 `/memory/recall` 端到端延迟，优先优化单主体和多主体直接召回场景。
- 保持当前 entity-centered、graph-aware、evidence-backed 的 recall 语义能力。
- 让 recall 性能瓶颈可观测，能按阶段定位慢点。
- 通过 LLM schema 和 prompt 判断是否需要跨实体图扩展，不引入关键词、正则、白名单或 case 专用逻辑。
- 保留 `memory_recall_audits` 和 `memory_llm_runs` 的审计可追溯性。

## 非目标

- 不改变 Memory API 的请求格式；调用方仍只传 `memory_scope` 和自然语言 `query`。
- 不允许调用方传入 `entity_key` 或绕过 entity resolution。
- 不删除 cross-entity why/how recall 能力。
- 不把 recall 降级为单纯向量 chunk 检索。
- 不为了 `smoke_v1` 或某个 case 写定制化规则。
- 不在第一阶段绕过 `answer_composer` 直接拼接答案。

## 当前流程

当前主图：

```text
RecallGraph.run
  -> plan_query
  -> run_draft_subgraphs
      -> resolve_entity
      -> recall_memories
           -> retrieval_index.memory_candidates
           -> _expand_graph
           -> _supplement_cross_entity_graph
                -> run_cross_entity_query_builder
                -> retrieval_index.memory_candidates
                -> run_edge_judge
           -> run_answer_composer
  -> write_audit
```

关键特征：

- `plan_query` 是一次全局 `query_planner` LLM 调用。
- planner 输出多个 `query_identity_profile_drafts` 后，每个 draft 会通过 `asyncio.gather` 并发运行 draft subgraph。
- 每个 draft 内部仍需要串行完成 `linker -> retrieval / graph -> answer_composer`。
- 只要存在 expanded memories，当前代码会调用 `_supplement_cross_entity_graph()`。
- `_supplement_cross_entity_graph()` 最多两轮动态跨实体补全，每轮可能运行：
  - `cross_entity_query_builder`，记录为 `memory_llm_runs.worker_type="query_planner"`
  - `edge_judge`

## 性能画像

### 端到端耗时

| case | draft 数 | recall 端到端 |
| --- | ---: | ---: |
| single_fact_owner | 1 | 6076 ms |
| multi_subject_two_results | 2 | 9435 ms |
| multi_subject_three_results | 3 | 9171 ms |
| multi_subject_four_results | 4 | 11338 ms |
| multi_subject_five_results | 5 | 15121 ms |

### 单主体链路

单主体 recall 的 LLM 调用：

| worker | latency |
| --- | ---: |
| query_planner | 1734 ms |
| linker | 1892 ms |
| answer_composer | 2089 ms |
| 非 LLM / 检索 / 写审计 | 361 ms |

结论：单主体 6 秒主要来自 3 次串行 LLM 调用，数据库和检索不是主瓶颈。

### 多主体链路

5 主体 recall 的 LLM 调用数：

| worker | 调用数 |
| --- | ---: |
| query_planner | 7 |
| linker | 5 |
| edge_judge | 6 |
| answer_composer | 5 |
| total | 23 |

多主体 draft subgraph 是并发执行的，所以 LLM latency 求和会大于端到端耗时。但每个 draft 内部仍存在串行段，且简单多主体事实查询也触发了动态跨实体补全。

### LLM 输入规模

| worker | 平均输入 tokens |
| --- | ---: |
| linker | 3.1k - 3.6k |
| edge_judge | 3.9k - 4.3k |
| answer_composer | 2.6k - 3.1k |

结论：性能瓶颈主要来自 LLM 调用次数和 prompt payload 体积，尤其是动态 cross-entity graph 补全。

## 根因

### 1. 单主体固定三段串行 LLM

单主体直接事实召回仍需要：

```text
query_planner -> linker -> answer_composer
```

这条链路当前合理，因为 planner 负责 query gate 和主体草稿，linker 负责实体归并，composer 负责有证据答案。但它决定了单主体 recall 的延迟下限接近三次 provider round-trip。

### 2. 动态跨实体补全默认触发

当前逻辑只要 `expanded_memories` 非空，就进入 `_supplement_cross_entity_graph()`。这使直接事实查询也可能执行：

```text
cross_entity_query_builder -> edge_judge
```

这些步骤对 why/how、依赖链、跨主体规则解释很重要，但对直接事实召回并非总是必要。

### 3. 每个 draft 独立运行补全

多主体问题被拆成多个 draft 后，每个 draft 都可能独立运行动态跨实体补全。5 主体 case 中出现 6 次 cross graph query planner 和 6 次 edge judge。

### 4. Stage timing 不完整

当前可观测性分散在两处：

- `memory_recall_audits.metadata.latency_ms`：端到端 recall 耗时。
- `memory_llm_runs.latency_ms`：每次 LLM 调用耗时。

缺失：

- retrieval 耗时
- local graph expansion 耗时
- dynamic cross-entity step 耗时
- observation / edge / audit DB 读写耗时
- per draft wall-clock timing

因此现在能判断 LLM 是主瓶颈，但还不能精确说明非 LLM 阶段的分布。

## 设计方案

### 方案一：阶段级 Recall Timing

先补可观测性，再调整行为。

在 `RecallGraph` 内部增加轻量 timing 结构，写入 `memory_recall_audits.metadata`：

```json
{
  "stage_timings_ms": {
    "plan_query": 1734,
    "run_draft_subgraphs": 4201,
    "write_audit": 42
  },
  "draft_timings_ms": [
    {
      "draft_index": 0,
      "resolve_entity": 1892,
      "memory_candidates": 35,
      "local_graph_expansion": 48,
      "cross_entity_graph": 0,
      "answer_composer": 2089,
      "total": 4100
    }
  ]
}
```

设计原则：

- timing 只进入 audit metadata，不改变 API response。
- timing 不影响 recall 决策，不参与排序。
- 每个 draft 记录 wall-clock 阶段耗时。
- LLM 细节仍以 `memory_llm_runs` 为准；audit timing 只负责串联阶段。

需要覆盖的阶段：

- main graph:
  - `plan_query`
  - `run_draft_subgraphs`
  - `write_audit`
- draft graph:
  - `resolve_entity`
  - `list_entity_memories`
  - `memory_candidates`
  - `local_graph_expansion`
  - `dynamic_cross_entity_graph`
  - `load_observations`
  - `answer_composer`

### 方案二：Planner 输出图扩展意图

给 `QueryPlannerOutput.query_focus` 增加语义字段，例如：

```json
{
  "graph_expansion_intent": "entity_local",
  "graph_expansion_reason": "The query asks for a direct remembered fact about each named subject."
}
```

建议枚举：

| 值 | 含义 |
| --- | --- |
| `entity_local` | 只需要目标 entity 的 seed memory 与本地 edge evidence。 |
| `cross_entity` | 需要跨 entity 补充证据，例如依赖、规则、原因、影响、先决条件或关联主体。 |
| `uncertain` | planner 无法判断是否需要跨实体补全，走保守路径。 |

执行策略：

- `entity_local`：跳过 `_supplement_cross_entity_graph()`，保留 `_expand_graph()` 的本地 graph expansion 和 derived observation evidence。
- `cross_entity`：执行当前动态跨实体补全。
- `uncertain`：执行当前动态跨实体补全，优先保证召回质量。

注意：

- 这是 LLM schema 决策，不是关键词规则。
- prompt 示例必须与 eval 样本脱钩，不能使用现有 case 名词。
- `graph_expansion_intent` 只控制是否运行动态跨实体补全，不改变 entity resolution、seed retrieval 或 answer composition。
- 如果 planner 输出非法值，按 `uncertain` 处理。

预期收益：

- 单主体直接事实：仍是 planner + linker + composer，稳定在约 6 秒附近。
- 多主体直接事实：去掉每个 draft 的 cross query builder 和 edge judge，5 主体从 23 次 LLM 降到约 11 次 LLM。
- why/how 或跨主体依赖查询：仍保留完整图补全能力。

### 方案三：Cross Graph Budget 收敛

当前默认预算：

| 配置 | 默认值 |
| --- | ---: |
| `MEMORY_GRAPH_TOTAL_MEMORY_BUDGET` | 24 |
| `MEMORY_GRAPH_RELATED_TO_BUDGET` | 6 |
| `MEMORY_GRAPH_SUPPORTS_BUDGET` | 8 |
| `_supplement_cross_entity_graph` 动态轮数 | 2 |

建议增加可配置的动态跨实体补全预算：

```text
MEMORY_DYNAMIC_CROSS_ENTITY_STEPS=1
MEMORY_DYNAMIC_CROSS_ENTITY_CANDIDATES=8
```

第一阶段不直接调小全局 graph budget，避免影响已有 why/how eval。先让 planner intent 决定是否进入动态补全，再通过 live eval 数据决定是否调小预算。

### 方案四：Linker Payload 裁剪

当前 linker 平均输入 3k+ tokens。可优化方向：

- 限制每个候选 entity 的 recent memory summaries 数量。
- 对候选 entity 只保留 identity profile、display name、最高相关 memory preview。
- 在候选分数差距明显时减少低分候选 payload。

这部分应作为第二优先级。原因是当前最大额外成本来自动态 cross-entity graph，而 linker 是 entity resolution 的核心质量边界，裁剪需要更谨慎。

## 推荐落地顺序

### Phase 1：补齐可观测性

改动：

- 在 `RecallGraph` 增加 stage timing。
- 将 `stage_timings_ms` 和 `draft_timings_ms` 写入 `memory_recall_audits.metadata`。
- 测试 `RecallGraph._build_audit_metadata()` 兼容新增字段。
- 增加单测验证 audit metadata 包含 timing 且不改变 response。

验收：

- `pytest memory/tests/test_recall.py`
- live smoke report 能关联：
  - recall endpoint timing
  - recall audit stage timing
  - memory_llm_runs worker timing

### Phase 2：Planner-gated Dynamic Cross Entity

改动：

- 扩展 query planner output schema，加入 `graph_expansion_intent`。
- 更新 query planner prompt，让模型判断是否需要跨实体补全。
- `RecallGraph._recall_memories()` 根据 intent 决定是否调用 `_supplement_cross_entity_graph()`。
- audit metadata 记录：
  - `graph_expansion_intent`
  - `graph_expansion_reason`
  - `dynamic_cross_entity_skipped`

验收：

- 直接事实 recall 不触发 dynamic cross-entity LLM 调用。
- 跨实体 why/how eval 仍触发 dynamic cross-entity LLM 调用。
- 不出现关键词、正则、case 名称或样本名词专用逻辑。

### Phase 3a：Graph-first Entity-local Recall

Phase 2 后，直接事实类查询已经不再运行动态跨实体图补全，但单主体仍需要：

```text
planner -> linker -> local graph -> answer_composer
```

其中 `linker` 是一次独立 LLM 调用。对 `entity_local` 且 graph/candidate 结构已经无歧义的查询，
可以先让本地图结构做实体收敛，跳过 `linker`，保留 `answer_composer` 做有证据回答：

```text
planner -> graph-first resolver -> local graph -> answer_composer
                         |
                         +-- 不确定 -> linker -> local graph -> answer_composer
```

触发条件必须保守：

- `query_focus.graph_expansion_intent == "entity_local"`。
- `retrieval_index.entity_candidates(...)` 只返回一个候选实体；或多候选中只有一个候选的
  identity profile 与 query draft 结构性唯一匹配。
- 该候选实体仍按现有 Memory graph 读取 active / stale / superseded memories，再走 `_expand_graph()`。
- 无候选、多候选但无法唯一结构匹配、`cross_entity`、`uncertain`、schema 缺失或异常场景都回退原 `linker`。

Graph-first resolver 不生成答案，也不做关键词规则。它只基于结构条件决定是否可以把 query draft
绑定到唯一候选实体：

- 候选实体来自现有语义索引，不靠手写字符串规则。
- 多候选消歧以当前正在解析的 `draft_payload` 为准，而不是整次 planner 的 draft 列表；这样多主体查询中每个 draft 可以独立收敛。
- 多候选消歧只比较 identity profile 结构：`who`、`surface_forms`、`distinguishing_context`
  的规范化精确匹配或 draft 稳定限定符是否被候选 identity profile 明确包含。
- 如果多个候选同时匹配、没有候选匹配、或 draft 缺少足够身份结构，则回退 `linker`。
- local graph expansion 仍负责收集 `derived_from`、`updates`、`supports`、`contradicts`、`related_to`
  等结构证据。
- composer 仍只基于 graph 给出的 memories / observations / edges 生成 answer 和 citations。

需要新增 audit 字段：

```json
{
  "graph_first_entity_resolution": {
    "attempted": true,
    "used": true,
    "fallback_reason": "",
    "candidate_count": 1
  }
}
```

多 draft 场景在聚合 metadata 中记录：

- `graph_first_entity_resolution_attempted_count`
- `graph_first_entity_resolution_used_count`
- `graph_first_entity_resolution_fallback_reasons`

预期收益：

- 单主体直接事实少一次 `linker` LLM 调用，单实体 recall 预计从约 5.4s 降到 3.4s - 4.0s。
- 多主体直接事实中，同前缀 artifact 只要 query draft 带有稳定限定符，也可减少 linker 调用数。
- 同名主体、多候选和跨实体 why/how 查询保持原路径，质量风险受控。

2026-05-27 实测结果：

- `recall_phase3a_graph_multi2_20260527` smoke matrix：6/6 通过，grounded rate 100%。
- 单主体：`graph_first_entity_resolution_used_count=1`，`memory_entity_linker` 调用数 0。
- 多主体 2/3/4/5 draft：graph-first 命中数分别为 2/3/4/5，`memory_entity_linker` 调用数 0。
- 相比同日修正前仍回退 linker 的 `recall_phase3a_graph_multi_20260527`，多主体 recall 延迟下降约 18.0% - 27.1%。

2026-05-27 全量最大并发压力评测：

- 运行配置：`default_v1` 全量 matrix，39 个 suite / 273 个 case，`--max-concurrency 39`。
- 报告路径：`/tmp/memory_eval_reports_phase3a_full_maxconc/matrix/latest.json` 和 `latest.md`。
- Matrix full pass：22/273，full pass rate 8.06%；answer grounded rate 99.7%。
- 加权维度通过率：
  - `ingest_gate`: 96.7%
  - `state`: 85.0%
  - `query_gate`: 90.8%
  - `recall_structured`: 88.3%
  - `answer_judge`: 85.4%
  - `background_tasks`: 10.6%
- 失败主要来自压力下后台任务未在 settle 窗口内清空：`settle_timeout` 245 次，`not_ready` 58 次。
- 评测结束时仍有后台积压：`pending merge_entities=180`、`running merge_entities=4`、`dead_letter repair_memory_edges=1`。
- 本轮适合作为吞吐压力数据，不应直接作为 graph-first 准确率回归结论。

Graph-first 在该压力评测中的观测：

- recall audit 共 381 次。
- `graph_first_entity_resolution_attempted_count` 合计 251。
- `graph_first_entity_resolution_used_count` 合计 222，命中率约 88.4%。
- fallback reason：`identity_match_not_found=26`、`identity_match_not_unique=1`、`graph_intent_cross_entity=99`。
- LLM 调用数：`query_planner=462`、`answer_composer=341`、`linker=130`、`edge_judge=110`。
- 全部 recall 平均 6552.7 ms，p50 5430 ms，p95 13971 ms。
- `entity_local` recall 平均 5354.3 ms；`cross_entity` recall 平均 11965.9 ms。

解释：

- `max-concurrency=39` 会把 39 个 suite 同时启动，写入、continue ingest、reindex、profile refresh、edge repair、merge
  都在同一段时间挤压后台 worker。
- 大量 case 的业务回答本身 grounded，但因为 `background_tasks=false` 被 full pass 拉低；这说明当前瓶颈是后台任务吞吐和
  settle budget，而不是 graph-first 多候选消歧的明显误选。
- 后续判断准确率应补跑 `max-concurrency=4` 或 `8` 的全量 matrix；吞吐优化则应单独评估后台 worker 并发、任务优先级和
  merge/reindex/repair 的队列预算。

### Phase 3b：Payload 与预算优化

改动：

- 裁剪 linker candidate payload；graph-first 未命中的场景仍会用到 linker。
- 增加动态 cross-entity budget 配置。
- 根据 stage timing 和 eval 失败分布决定默认值。
- 单独处理后台任务吞吐：限制全量 eval 并发下的 merge/reindex/repair 堆积，或让 eval settle 只等待 recall 必需链路。

验收：

- 默认 eval matrix 不因裁剪导致 grounded answer rate 下降。
- 多主体直接 recall p95 明显下降。
- why/how、dependency chain、rule evolution 类 suite 保持通过。
- `max-concurrency=4/8` 全量 matrix 中 `background_tasks` 维度不再成为主要失败来源。

## 测试计划

单元测试：

- `test_recall_audit_metadata_contains_stage_timings`
- `test_recall_skips_dynamic_cross_entity_when_planner_intent_entity_local`
- `test_recall_runs_dynamic_cross_entity_when_planner_intent_cross_entity`
- `test_recall_runs_dynamic_cross_entity_when_planner_intent_uncertain`
- `test_query_planner_rejects_invalid_graph_expansion_intent_to_uncertain`
- `test_resolve_entity_uses_graph_first_when_entity_local_has_unique_candidate`
- `test_resolve_entity_falls_back_to_linker_when_graph_first_has_no_unique_identity_match`
- `test_resolve_entity_uses_graph_first_when_multi_candidate_identity_match_is_unique`
- `test_resolve_entity_falls_back_to_linker_when_multi_candidate_identity_match_is_ambiguous`
- `test_resolve_entity_falls_back_to_linker_when_planner_intent_is_cross_entity`

近邻测试：

```bash
pytest memory/tests/test_recall.py memory/tests/test_retrieval_logic.py memory/tests/test_eval_timing.py
```

完整 Memory 测试：

```bash
pytest memory/tests
```

Live smoke：

```bash
docker exec best_ai_trader_memory python /app/evals/scripts/eval_memory_matrix.py \
  --base-url http://127.0.0.1:8010 \
  --manifest /app/evals/matrix/smoke_v1.json \
  --run-id recall_perf_after_cross_gate \
  --max-concurrency 1 \
  --timeout-seconds 240 \
  --settle-timeout-seconds 60 \
  --database-url postgresql+asyncpg://tradeuser:tradepassword@memory-postgres:5432/memory \
  --suite-output-dir /tmp/memory_eval_reports \
  --matrix-output-dir /tmp/memory_eval_reports/matrix
```

需要额外跑的 live suites：

- `multi_subject_document_v1`
- `rule_evolution_v1`
- `cross_format_longform_v1`
- `generalization_extended_v1`

原因：

- `smoke_v1` 证明直接召回收益。
- 多主体文档和长文验证 planner intent 不会漏召回。
- rule evolution 和 dependency 类样本验证 cross-entity / graph reasoning 仍保留。

## 指标门槛

第一阶段观测门槛：

- audit metadata 覆盖 100% recall 请求。
- 每个 ok result 至少有 main stage timing。
- 每个 draft 至少记录 total、resolve_entity、memory_candidates、answer_composer。

第二阶段性能门槛：

- `smoke_v1` full pass rate 保持 100%。
- `smoke_v1` grounded answer rate 保持 100%。
- 多主体直接 recall 的 dynamic cross-entity LLM 调用数降为 0。
- 5 主体 recall p95 目标从约 15s 降到 10s 以内。

第二阶段质量门槛：

- why/how、rule evolution、dependency chain 类 suite 不因跳过策略下降。
- 出现 planner intent 错误时，优先通过 prompt/schema 修复，不写关键词分支。

## 风险与回滚

### 风险

- planner 错误输出 `entity_local`，导致需要跨实体证据的问题漏召回。
- prompt 变更导致 planner draft 拆分质量波动。
- 跳过动态 cross-entity 后，答案 citation 数减少，部分 judge 可能判定证据不足。
- 新增 timing metadata 过大，影响 audit 表写入体积。

### 缓解

- 默认非法或缺失 intent 走 `uncertain`，保持旧路径。
- 第一版只让明确 `entity_local` 的请求跳过动态补全。
- 在 audit 中记录 skipped 状态，方便失败回放。
- timing metadata 只记录整数毫秒和少量阶段名，不保存大 payload。

### 回滚

提供配置开关：

```text
MEMORY_RECALL_PLANNER_GRAPH_INTENT_ENABLED=true
```

关闭后：

- planner intent 字段可继续记录但不参与决策。
- `_recall_memories()` 始终按旧路径调用 `_supplement_cross_entity_graph()`。

## 后续开放问题

- 是否需要为 answer composer 增加轻量模式，处理 evidence 已经高度确定的直接事实？
- 是否需要缓存同一请求内重复的 cross-entity query builder 输入？
- 是否需要把 multi-subject 的 answer composition 合并为一次 batched composer？
- 是否需要在 eval report 中直接输出 recall audit stage timing，而不是只输出 endpoint timing？

这些问题不进入第一阶段。当前最小有效改动是：先补 stage timing，再让 planner 用 LLM schema 控制动态跨实体图补全。
