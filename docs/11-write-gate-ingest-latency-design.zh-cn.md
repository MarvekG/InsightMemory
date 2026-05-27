# Write Gate Ingest Latency Design / 写入门禁时延优化设计

## 背景

当前 `/memory/ingest` 的同步路径会先运行完整 `extractor` LLM。`extractor` 同时负责主体识别、候选记忆生成、记录标记抽取和内容整理。这个设计能让接口同步返回 `accepted` 或 `rejected`，但也把完整抽取成本放进 HTTP 请求时延里。

一次本地 smoke test 中，完整 `extractor` 输入约 4420 tokens，provider prompt cache 命中率约 98%，但同步调用仍耗时约 2.1 到 3.6 秒。`write_gate` 仍照搬原主体规则和案例，但不再要求候选记忆、摘要、正文和 record markers，因此同步路径的输出与解析成本低于完整 `extractor`。

目标是在保持 `write` 接口同步返回语义的前提下，降低同步路径耗时，并保持最终记忆写入质量由完整抽取链路负责。

## 目标

- `/memory/ingest` 仍同步返回 `accepted` 或 `rejected`。
- 同步路径只判断输入是否能提取稳定主体。
- 只要能提取主体，就创建 observation，并把完整抽取放入后台继续执行。
- 后台完整 `extractor` 仍是候选记忆生成和最终写入质量的权威来源。
- 不引入关键词匹配、正则规则、白名单或定制化场景分支。

## 非目标

- 不改变 Memory API 请求和响应 schema。
- 不让调用方传入 `entity` 或 `entity_key`。
- 不把候选记忆生成放回同步路径。
- 不用代码规则替代 LLM 的主体识别、记忆拆分或语义判断。
- 不改变 recall 的语义路径。

## 当前流程

```text
POST /memory/ingest
  -> MemoryWorkers.run_extractor()
  -> extractor rejected: 返回 rejected
  -> extractor passed: 创建 observation
  -> enqueue continue_ingest(extractor_payload)
  -> 后台 ingest_graph.run(extractor_payload)
```

这个流程的问题是：同步返回只需要知道“是否有稳定主体”，但完整 `extractor` 还做了候选记忆生成等后台才真正需要的工作。

## 目标流程

```text
POST /memory/ingest
  -> MemoryWorkers.run_write_gate()
  -> write_gate rejected: 返回 rejected
  -> write_gate passed: 创建 observation
  -> enqueue continue_ingest(context)
  -> 后台 ingest_graph.continue_ingest(context)
  -> graph 节点 extract: MemoryWorkers.run_extractor()
  -> extractor rejected: observation 标记 unresolved
  -> extractor passed: graph 节点 resolve_entities -> resolve_candidates -> finalize
```

同步路径只运行 `write_gate`。后台任务只负责把 `context` 交给 `ingest_graph.continue_ingest()`；完整 extractor 重跑、extractor reject 处理和后续 entity resolution、resolver、edge、index、follow-up task 流程都归入 graph 边界。

## Write Gate Worker

新增 `write_gate` worker，职责只包含主体门禁：

- 判断输入是否存在一个或多个稳定主体。
- 输出主体画像草稿，仅用于同步门禁结果和 `memory_llm_runs` 审计。
- 在没有稳定主体时返回 `rejected_no_identity_profile`。
- 不输出 candidate memory。
- 不输出 title、summary、content、record_markers。

`write_gate` 应照搬现有 `IDENTITY_PROFILE_RULES`，包括原主体识别规则和原案例。它只在 prompt 外层额外声明“只输出 identity_profile drafts，不输出 candidate memory”，避免为 gate 维护另一套主体判断规则。

建议输出 schema：

```json
{
  "identity_gate_status": "passed",
  "identity_profile_drafts": [
    {
      "draft_id": "d1",
      "who": "Nimbus rollout",
      "surface_forms": ["Nimbus rollout"],
      "distinguishing_context": ["rollout"]
    }
  ],
  "write_rejection_reason": null
}
```

## Gate 策略

`write_gate` 是同步门禁，不是最终抽取器。因此它应偏向避免 false negative：

- 明确没有稳定主体时才 reject。
- 只要输入可以归属到稳定主体，就 pass。
- 如果主体数量、主体边界或候选记忆拆分不确定，也应 pass，让后台完整 `extractor` 处理。
- gate pass 后，后台 extractor 仍可能 reject；这种情况只会产生 unresolved observation，不会写入 memory。

这个策略的核心取舍是：宁可多创建一条 unresolved observation，也不要错误同步拒绝一条可记忆输入。

## 后台任务 Payload

新格式 `continue_ingest` payload：

```json
{
  "memory_space": "user:1:stock:000001.SZ",
  "request_id": "req_xxx",
  "observation_id": "obs_xxx",
  "context": "原始写入内容"
}
```

新实现不保留旧 payload 兼容分支。`continue_ingest` 只接受包含 `context` 的新格式。

执行策略：

- `TaskRuntime._continue_ingest()` 只解析 payload 并调用 `ingest_graph.continue_ingest()`。
- `ingest_graph.continue_ingest()` 只接受包含 `context` 的新 payload，不保留旧 `extractor_payload` 入口。
- LangGraph 从 `extract` 节点开始运行完整 `run_extractor()`。
- `extract` 后通过 conditional edge 分支：完整 extractor rejected 时进入 `mark_extractor_rejected` 节点，标记 observation 为 `unresolved` 并记录 extractor 输出摘要。
- 完整 extractor passed 时进入 `resolve_entities -> resolve_candidates -> finalize` 正常写入链路。

## API 返回语义

`write_gate` rejected 时：

```json
{
  "status": "rejected",
  "observation_id": null,
  "affected_entity_keys": [],
  "affected_memory_ids": [],
  "error_code": "cannot_extract_identity_profile"
}
```

`write_gate` passed 时：

```json
{
  "status": "accepted",
  "observation_id": "obs_xxx",
  "affected_entity_keys": [],
  "affected_memory_ids": [],
  "error_code": null
}
```

`affected_entity_keys` 和 `affected_memory_ids` 保持为空，因为实体解析和 memory 写入仍由后台异步任务完成。

## 审计与可观测性

需要保留以下审计信息：

- `write_gate` LLM run 写入 `memory_llm_runs`，`worker_type="write_gate"`。
- observation metadata 记录 `request_id`。
- 后台完整 extractor rejected 时，observation metadata 记录：
  - `extractor_status`
  - `extractor_rejection_reason`
  - `continuation_error_code`（如有）
  - `continuation_error_message`（如有）

这样可以通过 `memory_llm_runs` 追踪同步 gate 的判断，通过 observation metadata 追踪后台完整 extractor 的最终处理状态。后台不携带 gate 输出，避免任务 payload 变大，也避免把同步门禁结果误用为后台抽取依据。

## 数据库与模型影响

不需要新增业务表。

需要注意 `memory_tasks` 的 task type 约束是否包含 `continue_ingest`。如果当前模型约束中遗漏该 task type，应在模型常量和测试初始化中保持一致。项目未上线阶段，实际数据库 schema 同步仍按项目数据库变更约定由开发者在目标容器内执行。

如需支持 `worker_type="write_gate"`，还要同步更新 `MemoryLLMRun` 的 worker type 约束、测试建表和相关枚举。

## 错误处理

- `write_gate` LLM 调用失败：同步返回错误，不创建 observation，避免把无法判定的输入放入后台。
- observation 创建失败：同步返回错误，不创建后台任务。
- 后台完整 extractor 失败：任务按现有 task retry/dead-letter 机制处理。
- 后台完整 extractor rejected：任务可标记 succeeded，observation 标记 `unresolved`，不进入 `ingest_graph`。
- 后台 `ingest_graph` 异常：沿用现有异常处理，observation 标记 `unresolved`，任务进入失败或重试。

## 预期收益

同步 `write` 路径不再等待候选记忆生成和完整写入图，只等待主体门禁。实际收益取决于当前 LLM provider、prompt cache、网络、模型延迟，以及照搬原主体规则后的 prompt 长度。

最终写入完成时间不会减少，因为完整 extractor 仍在后台执行；优化的是 API 同步返回时延。

## 风险

- Gate false negative：可写入内容被同步拒绝。通过“明确无主体才 reject”的 prompt 策略降低风险。
- Gate false positive：无效内容进入后台。影响是多一条 unresolved observation，不污染 memory。
- Gate 与 extractor 分歧：后台不依赖 gate 输出；需要分析时，通过同一 `request_id` 关联 `memory_llm_runs` 和 observation 状态。
- 部署切换：实现合并前应确保没有旧格式 pending/running `continue_ingest` 任务，或在开发环境中清理旧任务后再启动新代码。

## 测试计划

单元测试：

- `IngestService.ingest()` 调用 `run_write_gate()`，不调用完整 `run_extractor()`。
- gate rejected 时不创建 observation，不 enqueue `continue_ingest`。
- gate passed 时创建 observation，并 enqueue 包含 `context` 的 `continue_ingest`。
- `TaskRuntime._continue_ingest()` 只把新 payload 交给 `ingest_graph.continue_ingest()`，不直接运行 extractor。
- `ingest_graph.continue_ingest()` 要求存在 `context`，且图入口是 `extract` 节点。
- `extract` 节点运行完整 `run_extractor()`，passed 后走 `resolve_entities -> resolve_candidates -> finalize`。
- `extract` 节点后的 rejected 分支进入 `mark_extractor_rejected` 节点，observation 标记为 `unresolved`。
- `write_gate` prompt 包含完整 `IDENTITY_PROFILE_RULES` 和原案例，同时不包含 candidate memory 生成规则。
- `write_gate` LLM run 能被 usage stats 统计。

近邻验证：

```bash
pytest memory/tests/test_recall.py memory/tests/test_ingest_graph.py memory/tests/test_llm_usage_stats.py
pytest memory/tests
```

Live smoke：

```bash
docker compose exec backend curl -sS http://memory:8010/health
docker compose exec backend python - <<'PY'
# 调用 memory_client.write_memory，记录同步 elapsed_ms。
PY
```

验证重点：

- 同步 write 返回 `accepted`。
- 随后立即 recall 仍可能返回 `not_ready`，符合异步写入约束。
- 等后台任务 settled 后，recall 能召回完整 extractor 生成的 memory。
