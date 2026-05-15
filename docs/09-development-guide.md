# Development Guide / 开发指南：LLM-First Logic Judgment

## 中文

### 总原则

Memory 系统代码应保持简单、透明、可验证。代码负责工程流程和确定性边界，复杂逻辑判断交给 LLM。

这里的“逻辑判断”特指需要语义理解、身份判定、记忆抽取、事实合并、关系推理、检索意图理解、答案组织、风险判断或多因素综合决策的判断。代码中仍可以保留必要的确定性控制流，例如参数校验、权限校验、状态流转、异常处理和 I/O 编排。

### 职责边界

代码负责：

- 输入输出校验：类型、必填字段、取值范围、JSON Schema、Pydantic schema。
- 工程流程：API 调用、任务调度、数据库读写、缓存、队列、重试、超时、幂等。
- 安全边界：认证、授权、敏感字段过滤、外部输入清洗。
- 状态管理：任务状态、会话状态、记忆生命周期、失败状态和恢复流程。
- 可观测性：日志、trace id、LLM 请求与响应记录、错误码。
- 结果校验：校验 LLM 输出结构是否符合 schema，不替 LLM 补做语义判断。

LLM 负责：

- 从自然语言输入中抽取候选记忆。
- 判断两个实体是否指向同一身份。
- 判断新旧记忆是补充、更新、冲突、重复还是无关。
- 判断记忆之间的支持、矛盾、依赖、因果或相关关系。
- 理解用户查询意图并选择合适的召回路径。
- 组合证据、生成答案、解释不确定性并保留引用。
- 判断上下文中哪些事实更重要、更可信或更适合回答当前问题。

### 开发规则

1. 不在代码中写复杂业务规则树。
2. 不用硬编码关键词、白名单、黑名单或正则去模拟语义判断。
3. 不在代码中维护多因素打分、权重、阈值组合来替代 LLM 决策。
4. 不为了让单个测试样例通过而添加定制化分支。
5. 需要判断时，先设计 LLM 输入上下文、输出 schema 和校验逻辑。
6. LLM 输出必须结构化，代码只消费结构化结果。
7. LLM 输出不合规时，代码应返回明确错误、降级为 `needs_review`，或要求重试，不自行推断业务结论。
8. 所有 LLM 决策都应保留关键输入、输出、理由、置信度和不确定性，便于审计和评估。

### 判断是否应交给 LLM

如果准备新增的代码符合任一情况，应交给 LLM：

- 条件分支超过简单工程校验。
- 需要解释“为什么”。
- 需要比较多个候选记忆、实体或证据的优劣。
- 需要理解自然语言、隐含指代、同义表达、上下文省略或跨语言表达。
- 需要把 observation、memory、entity、edge、query 等多类信息组合起来判断。
- 代码里开始出现“如果包含某词就认为某含义”的逻辑。
- 代码里开始出现打分权重、经验阈值或场景偏好。

可以留在代码里的判断：

- 字段是否为空。
- 数字是否越界。
- 用户是否有权限。
- 任务是否处于允许执行的状态。
- 外部服务是否超时。
- LLM 输出是否符合 schema。
- 数据库记录是否存在。
- 是否需要重试、回滚或进入人工复核。

### 推荐实现模式

1. **构造上下文**

   代码从数据库、API、缓存或任务结果中收集事实，整理成结构化上下文。上下文只提供事实，不提前下语义结论。

2. **调用 LLM**

   Prompt 中明确说明任务、约束、可用事实、禁止臆测规则和输出 schema。

3. **结构化输出**

   LLM 输出应至少包含：

   ```json
   {
     "decision": "merge|update|keep_separate|needs_review",
     "confidence": 0.73,
     "reasons": ["..."],
     "evidence": ["..."],
     "uncertainties": ["..."],
     "next_actions": ["..."]
   }
   ```

   具体字段可按记忆抽取、实体合并、关系判断、召回回答等场景调整，但必须让代码能稳定校验和消费。

4. **代码执行**

   代码只根据 LLM 的结构化输出执行后续流程，例如保存记忆、合并实体、创建边、进入人工复核或返回不确定性。

### 反模式

不要写这种代码：

```python
if "阻塞" in content or "blocked" in content:
    memory_type = "blocker"
elif "依赖" in content or "depends on" in content:
    memory_type = "dependency"
else:
    memory_type = "note"
```

应该改为：

```python
context = build_memory_extraction_context(observation=observation)
result = await memory_llm_service.extract_memories(context)
validated_result = validate_extraction_schema(result)
```

代码负责收集事实和校验结果，记忆类型、语义关系和重要性判断由 LLM 完成。

### 测试原则

- 测试代码路径、schema 校验、异常处理、降级行为和持久化结果。
- 使用 mock LLM 输出测试不同结构化结果下的流程。
- 不通过硬编码业务规则来制造“正确答案”。
- 不把测试样例中的关键词写回 prompt 或代码规则。
- 泛化测试应覆盖不同表达方式、不同领域、跨语言输入、噪声输入和多主体场景。

### 代码审查检查项

提交前检查：

- 是否新增了复杂 `if/elif/else` 语义分支。
- 是否新增了关键词匹配、规则表、权重表或魔法阈值。
- 是否把自然语言理解、身份判断、关系判断或召回策略写进了代码。
- 是否有清晰的 LLM 输入上下文和输出 schema。
- LLM 失败、超时、输出不合规时是否有明确处理。
- 是否记录了可审计的 LLM 决策依据。

### 结论

代码保持确定性，LLM 承担判断性。Memory 系统的工程代码越薄，语义判断越集中，系统越容易迭代、评估和复盘。

## English

### Core Principle

The memory system code should stay simple, transparent, and verifiable. Code owns engineering flow and deterministic boundaries; complex judgment belongs to the LLM.

In this guide, "logic judgment" means decisions that require semantic understanding, identity resolution, memory extraction, fact merging, relation reasoning, retrieval intent understanding, answer composition, risk assessment, or multi-factor tradeoffs. Code can still keep necessary deterministic control flow, such as validation, authorization, state transitions, error handling, and I/O orchestration.

### Responsibility Boundary

Code owns:

- Input and output validation: types, required fields, value ranges, JSON Schema, and Pydantic schemas.
- Engineering flow: API calls, task scheduling, database writes, caching, queues, retries, timeouts, and idempotency.
- Safety boundaries: authentication, authorization, sensitive-field filtering, and external-input sanitization.
- State management: task state, session state, memory lifecycle, failure state, and recovery flow.
- Observability: logs, trace ids, LLM request and response records, and error codes.
- Result validation: checking whether LLM output matches the schema, without adding semantic judgment in code.

The LLM owns:

- Extracting candidate memories from natural language input.
- Deciding whether two entities refer to the same identity.
- Deciding whether a new memory supplements, updates, contradicts, duplicates, or is unrelated to an existing memory.
- Judging support, contradiction, dependency, causality, or relevance between memories.
- Understanding user query intent and choosing an appropriate recall path.
- Combining evidence, composing answers, explaining uncertainty, and preserving citations.
- Deciding which facts are more important, more credible, or more useful for the current question.

### Development Rules

1. Do not encode complex business rule trees in code.
2. Do not use hard-coded keywords, allowlists, blocklists, or regexes to simulate semantic judgment.
3. Do not maintain multi-factor scores, weights, or threshold combinations as a substitute for LLM decisions.
4. Do not add custom branches just to pass one test case.
5. When judgment is needed, design the LLM context, output schema, and validation logic first.
6. LLM output must be structured, and code should consume only the structured result.
7. If LLM output is invalid, code should return a clear error, downgrade to `needs_review`, or retry. It should not infer the semantic conclusion itself.
8. Every LLM decision should keep key inputs, outputs, reasons, confidence, and uncertainties for audit and evaluation.

### When To Delegate To The LLM

Delegate to the LLM if the new code meets any of these conditions:

- The condition branches go beyond simple engineering validation.
- The decision needs an explanation of "why".
- The decision compares multiple candidate memories, entities, or evidence items.
- The decision requires understanding natural language, implicit references, synonyms, omitted context, or cross-lingual expression.
- The decision combines observations, memories, entities, edges, queries, and other information types.
- The code starts to say "if this phrase appears, it means that".
- The code starts to introduce scoring weights, empirical thresholds, or scenario preferences.

Judgments that can stay in code:

- Whether a field is empty.
- Whether a number is out of range.
- Whether a user has permission.
- Whether a task is in an allowed state.
- Whether an external service timed out.
- Whether LLM output matches the schema.
- Whether a database record exists.
- Whether to retry, roll back, or route to human review.

### Recommended Implementation Pattern

1. **Build context**

   Code gathers facts from databases, APIs, caches, or task results, then shapes them into structured context. The context should provide facts without pre-deciding semantic conclusions.

2. **Call the LLM**

   The prompt should define the task, constraints, available facts, anti-hallucination rules, and output schema.

3. **Return structured output**

   LLM output should include at least:

   ```json
   {
     "decision": "merge|update|keep_separate|needs_review",
     "confidence": 0.73,
     "reasons": ["..."],
     "evidence": ["..."],
     "uncertainties": ["..."],
     "next_actions": ["..."]
   }
   ```

   Fields can vary for memory extraction, entity merge, relation judgment, or recall answering, but code must be able to validate and consume them reliably.

4. **Execute in code**

   Code acts only on the structured LLM output, such as saving a memory, merging an entity, creating an edge, routing to review, or returning uncertainty.

### Anti-Pattern

Do not write code like this:

```python
if "blocked" in content or "阻塞" in content:
    memory_type = "blocker"
elif "depends on" in content or "依赖" in content:
    memory_type = "dependency"
else:
    memory_type = "note"
```

Prefer this:

```python
context = build_memory_extraction_context(observation=observation)
result = await memory_llm_service.extract_memories(context)
validated_result = validate_extraction_schema(result)
```

Code collects facts and validates results. The LLM decides memory type, semantic relations, and importance.

### Testing Principles

- Test code paths, schema validation, error handling, fallback behavior, and persistence.
- Use mocked LLM outputs to test flows under different structured decisions.
- Do not create "correct answers" through hard-coded business rules.
- Do not copy test-case keywords back into prompts or code rules.
- Generalization tests should cover varied wording, varied domains, cross-lingual input, noisy input, and multi-entity scenarios.

### Code Review Checklist

Before submitting, check:

- Did the change add complex semantic `if/elif/else` branches?
- Did it add keyword matching, rule tables, weight tables, or magic thresholds?
- Did it encode natural-language understanding, identity judgment, relation judgment, or recall strategy in code?
- Does it have clear LLM input context and output schema?
- Does it handle LLM failure, timeout, and invalid output clearly?
- Does it record auditable evidence for LLM decisions?

### Conclusion

Keep code deterministic and let the LLM handle judgment. The thinner the engineering code is, and the more centralized semantic judgment is, the easier the memory system is to iterate, evaluate, and review.
