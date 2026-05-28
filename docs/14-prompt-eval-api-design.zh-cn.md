# Prompt Eval API 设计

## 背景

InsightMemory 的提示词集中在 `memory/insight_memory/workers/prompts.py`，实际 LLM 调用统一走
`memory/insight_memory/workers/llm_provider.py`。当前评测主要覆盖完整 ingest/recall 链路：脚本写入记忆、
等待后台任务、发起召回、再根据 case 期望比对结果。

端到端评测能验证系统效果，但定位单个 prompt 问题时成本偏高。以 `IDENTITY_PROFILE_RULES` 为例，它被
`write_gate`、`extractor`、`query_planner` 等多个 worker prompt 复用。为了单独观察某个 worker prompt 在
给定 payload 下的 LLM 输出，需要一个轻量 HTTP 调用入口。

这个接口只负责调用后端已有 prompt 并返回 LLM 输出。case 读取、结果比对、pass/fail 统计和报告生成都由评测脚本
完成，不放进 HTTP 服务。

## 目标

- 支持对 Memory 后端多个 worker prompt 进行单独调用。
- HTTP 接口只做 prompt 选择、LLM 调用和结果返回。
- HTTP 接口不读取 case、不执行断言、不生成 pass/fail、不输出报告。
- 复用现有 `get_worker_instructions(...)`、worker schema 和 `llm_provider.generate(...)`。
- 评测脚本拿到 HTTP 结果后，再和 case 期望进行比对。

## 非目标

- 不替代完整 ingest/recall 评测。
- 不在接口里实现 JSONPath、断言 DSL、评分或报告逻辑。
- 不允许调用方传入任意 prompt 文本；只能选择后端 registry 里允许的 prompt。
- 不单独调用 `IDENTITY_PROFILE_RULES` 裸字符串；它通过真实 worker prompt 间接评测。
- 不把 case、expected 或 comparator 逻辑写入后端服务。

## HTTP 接口

新增接口：

```http
POST /memory/prompt-evals/run
```

该接口定位为 Memory 内部服务能力，不增加 admin 路径，也不增加独立开关。调用方发起请求后同步等待 LLM 结果返回。

### 请求

```json
{
  "prompt_key": "write_gate",
  "payload": {
    "context": "Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。"
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `prompt_key` | 是 | 后端允许调用的 prompt key，例如 `write_gate`、`extractor`、`query_planner`。 |
| `payload` | 是 | 传给对应 worker prompt 的 JSON 对象。HTTP 层不解释 case 语义。 |

### 成功响应

```json
{
  "status": "ok",
  "prompt_key": "write_gate",
  "model": "memory-model-alias",
  "latency_ms": 1234,
  "output": {
    "identity_gate_status": "passed",
    "identity_profile_drafts": [
      {
        "schema_version": 2,
        "draft_id": "d1",
        "who": "Harborlane rollout",
        "entity_type": "workflow",
        "surface_forms": ["Harborlane rollout", "Harborlane"],
        "stable_qualifiers": ["rollout"],
        "evidence": ["Harborlane rollout 不能进入 cutover"]
      }
    ],
    "write_rejection_reason": null
  },
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "cached_tokens": 0,
    "cache_miss_tokens": 100,
    "reasoning_tokens": 0
  }
}
```

响应只保留一个 `output` 字段。`llm_provider.generate(...)` 当前会先拿到模型返回的 JSON，再用对应 Pydantic
schema 校验；如果校验通过，原始 JSON 和 parsed dump 在语义上基本重复，所以接口不同时返回 `output_json` 和
`parsed_output`。

### 失败响应

```json
{
  "status": "error",
  "prompt_key": "unknown_worker",
  "error_code": "unsupported_prompt_key",
  "error_message": "Unsupported prompt key."
}
```

常见错误：

| error_code | 场景 |
| --- | --- |
| `unsupported_prompt_key` | `prompt_key` 不在允许列表。 |
| `llm_provider_not_configured` | Memory LLM provider 未配置。 |
| `llm_call_failed` | LLM 调用失败或返回非 JSON。 |
| `schema_validation_failed` | LLM 输出无法通过对应 worker schema 校验。 |

如果 schema 校验失败，接口应尽量返回可诊断的错误信息。现有 `llm_provider.generate(...)` 在解析或 schema 校验失败时
不会稳定暴露原始文本；实现时可以扩展 provider 的异常类型，让错误响应包含安全截断后的原始输出片段，但不得返回
API key、base URL、环境变量或完整异常堆栈。

## Prompt Registry

新增只读 registry，集中声明接口允许调用哪些 prompt。调用方只能选择 registry 中的 key。

建议文件：

```text
memory/insight_memory/evals/prompt_registry.py
```

初始支持：

| prompt_key | instructions_key | schema |
| --- | --- | --- |
| `write_gate` | `write_gate` | `WriteGateOutput` |
| `extractor` | `extractor` | `ExtractorOutput` |
| `query_planner` | `query_planner` | `QueryPlannerOutput` |
| `linker` | `linker` | `LinkerOutput` |
| `resolver` | `resolver` | `ResolverBatchOutput` |
| `same_batch_resolver` | `same_batch_resolver` | `ResolverBatchOutput` |
| `cross_entity_query_builder` | `cross_entity_query_builder` | `CrossEntityQueryBuilderOutput` |
| `answer_composer` | `answer_composer` | `AnswerComposerOutput` |
| `answer_judge` | `answer_judge` | `AnswerJudgeOutput` |
| `profile_writer` | `profile_writer` | `ProfileWriterOutput` |
| `edge_judge` | `edge_judge` | `EdgeJudgeOutput` |
| `merge_judge` | `merge_judge` | `MergeJudgeOutput` |

Registry item 建议包含：

- `prompt_key`
- `instructions_key`
- `schema_type`
- `description`

`same_batch_resolver` 这类 effective instructions key 也应在 registry 中显式声明，避免评测脚本猜测 runtime 行为。

## 后端执行流程

1. Route 校验请求 schema 和 `prompt_key`。
2. Service 从 prompt registry 获取 `instructions_key` 与 `schema_type`。
3. Service 调用 `get_worker_instructions(instructions_key)` 获取真实 worker prompt。
4. Service 调用 `llm_provider.generate(...)`：
   - `worker_type` 使用 `prompt_key`；
   - `instructions` 使用真实 instructions；
   - `payload` 使用请求中的 `payload`；
   - `schema_type` 使用 registry 中声明的 schema。
5. Service 返回 `LLMCallResult.output_json`、model、latency 和 usage。
6. Route 返回 HTTP 响应，不执行 case 断言。

## 评测脚本职责

评测脚本位于 `memory/evals/scripts/`，负责读取 case、调用 HTTP 接口、比对响应和生成报告。

建议 case 形态：

```json
{
  "case_id": "identity_owner_subject_001",
  "prompt_key": "write_gate",
  "payload": {
    "context": "Harborlane rollout 不能进入 cutover，因为 quay memo 还没补齐。"
  },
  "expected": {
    "identity_gate_status": "passed",
    "required_who": ["Harborlane rollout"],
    "forbidden_who": ["quay memo"]
  }
}
```

脚本执行流程：

1. 读取 case 文件。
2. 对每个 case 发送 `prompt_key + payload` 到 `/memory/prompt-evals/run`。
3. 拿响应里的 `output` 与 case 的 `expected` 比对。
4. 汇总 pass/fail、失败原因、模型、usage 和 latency。
5. 输出 JSON/Markdown 报告到 `memory/evals/reports/`。

不同 prompt 可以由脚本实现不同 comparator：

- identity profile comparator：检查 `who`、`entity_type`、`surface_forms`、`stable_qualifiers`。
- query planner comparator：检查 `query_gate_status`、query drafts、`query_focus`。
- extractor comparator：检查 drafts 与 candidates 的 owner 关系。
- generic JSON comparator：执行简单结构断言。

这些 comparator 不进入 HTTP 服务，避免后端接口变成测试框架。

## 文件边界

建议实现涉及：

```text
memory/insight_memory/api/schemas.py
memory/insight_memory/api/routes.py
memory/insight_memory/services/prompt_eval_service.py
memory/insight_memory/evals/prompt_registry.py
memory/evals/scripts/eval_memory_prompts.py
memory/tests/test_prompt_eval_service.py
memory/tests/test_prompt_eval_routes.py
```

HTTP 接口和 service 是可复用调用层；脚本和 case 是评测层。两者通过 JSON 响应契约连接。

## 安全与日志

- 不允许调用方传入任意 prompt/instructions。
- 请求 payload 长度应受现有 Memory 配置约束，避免过大输入造成异常 token 消耗。
- 日志只记录 `prompt_key`、latency、model 和状态，不记录完整 payload 或完整输出。
- 响应中不返回 API key、base URL、环境变量或完整异常堆栈。
- 该接口是内部服务能力；若未来 Memory 暴露到不可信网络，应再按部署边界统一收紧访问控制。

## 测试策略

单元测试不访问真实 LLM。通过 monkeypatch `llm_provider.generate(...)` 返回固定 `LLMCallResult`：

- prompt key 存在时，service 返回 `output`、model、latency 和 usage。
- prompt key 不存在时，返回 `unsupported_prompt_key`。
- LLM provider 未配置时，返回 `llm_provider_not_configured`。
- LLM schema 校验失败时，返回明确错误。
- route request schema 禁止额外字段，避免接口漂移。

离线脚本测试使用 fake HTTP client 或 monkeypatch 请求函数，验证 case 读取、响应比对和报告汇总，不依赖真实 Memory 服务。
