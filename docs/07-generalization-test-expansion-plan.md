# 泛化测试扩展计划

这份文档定义 `memory` 记忆系统下一阶段的泛化测试扩展方向。

目标不是描述单个 bug，而是把“如何继续证明系统泛化能力”写成一份可直接执行的实现规格，供后续工程迭代持续扩展。

本文档聚焦：

- 继续扩大测试分布
- 用更难场景暴露真实系统缺陷
- 统一 suite 设计、matrix 接入和验收门槛
- 保证后续修复仍然遵守通用性原则

不在本文档中展开：

- 后台任务调度细节
- 数据库 schema 设计
- 线上运维手册

相关文档：

- 后台任务调度设计见 [06-background-task-scheduling.md](./06-background-task-scheduling.md)
- 总体系统设计见 [README.md](../README.md)

## 1. 当前测试版图

当前 `memory/evals/matrix/default_v1.json` 已接入 37 个 suite：

- 基础与压力：`generic`、`hard`、`expansion`、`noise`、`extreme`、`stress`、`concurrency`
- 长周期与长文：`long_horizon`、`ultralong`、`cross_format_longform`、`multi_subject_document`
- 开放域与远域：`openworld`、`broad`、`farfield`、`out_of_distribution_domains`、`real_debate_longform`
- 结构推理：`deep_graph`、`heterogeneous`、`large_scope_graph`、`deeper_dependency_chain`
- 专项边界：`rule_evolution`、`temporal_reasoning`、`negation_conflict`、`numerical_reasoning`、`implicit_relation`
- 身份与答案边界：`identity_boundary`、`answer_boundary`、`semantic_paraphrase`、`state_transition_boundary`
- 金融与市场：`market`、`finance`
- 跨域迁移：`cross_domain_transfer`
- 真实世界：`realworld_daily`、`realworld_complex`、`realworld_work_ops`、`realworld_software_dev`

这些 suite 已经证明系统具备以下能力：

- 主体识别与同名区分
- `replace / refresh / coexist / updates`
- 历史与当前状态区分
- 跨 entity 依赖与 why query
- 噪声上下文与旁支主体过滤
- mixed-language
- 长文档、多主体、开放域、金融域、真实生活、真实职场和代码开发场景
- 高压下主语义链路仍可用

但这不代表泛化能力已经封顶。当前仍有必要继续扩大分布，重点验证：

- 更复杂格式混合
- 更大 scope 主体数量
- 更长更深的依赖链
- 更细的规则演进矩阵
- 更远离当前熟悉语义的开放域
- 更接近真实业务输入的会议纪要、工单、PR thread、incident timeline、客服对话

## 2. 当前空白点

虽然现有 suite 已经覆盖广，但仍存在下列空白或不足：

### 2.1 格式复杂度仍可继续提高

当前 `format_shift` 和 `cross_format_longform` 已覆盖：

- email thread
- YAML-ish record
- chat transcript
- table record
- field record

仍可继续扩：

- Markdown 长文 + 多级标题 + 引用块混合
- checklist 与 narrative 同段混写
- correction note / amendment / appendix 叠加
- 同一文档中多种结构化片段交错出现

### 2.2 大 scope 与多主体密度仍可继续提高

当前已有：

- `broad`
- `heterogeneous`
- `ultralong`
- `large_scope_graph`

仍可继续扩：

- 单 scope 下 `12-20` 个以上主体同时存在
- 多组同 prefix / 同 surface artifact 同时出现
- 同一长文里主主体、副主体、旁支主体、无效侧提及同时出现

### 2.3 深链依赖仍可继续拉长

当前 `deep_graph` 和 `deeper_dependency_chain` 已经覆盖较深 why query，但仍可继续扩：

- `5-6` hop requirement chain
- 同时包含 direct artifact、co-required item、upstream prerequisite、further-upstream supplement 的完整链
- deeper history disagreement 与 external rule 同时存在的场景

### 2.4 规则演进类样本仍然不够密集

当前 `rule_evolution`、`state_transition_boundary`、`negation_conflict` 已经覆盖较多规则演进和状态边界。仍可继续扩：

- 宽松规则 -> 严格规则
- current + supplement
- 历史规则 + 当前规则 + 补充规则三层并存
- handbook / charter / bulletin / checklist 之间的 rule chain

### 2.5 开放域仍可继续远离当前熟悉领域

当前已经覆盖：

- 通用项目/流程/文档/计划
- archive / herbarium / observatory / vessel 等 farfield
- market / finance
- realworld daily / work ops / software dev

仍可继续扩：

- 航运细化场景
- 档案整理与馆藏维护
- 地质与野外勘测
- 天文观测与值守
- 农务、公共安全、实验设施等更远域

## 3. 泛化测试扩展原则

后续新增 suite 必须遵守以下原则。

### 3.1 先扩分布，再修逻辑

目标不是先写更多 prompt 规则，而是先用更难、更陌生、更复杂的样本把真实缺陷暴露出来。

修复顺序固定为：

1. 先新增 suite
2. 先跑 targeted
3. 发现真实失败
4. 只做通用语义修复
5. 再跑 full

### 3.2 不允许为过用例写定制化逻辑

严禁：

- 关键词匹配分支
- 某个 case 名称专用逻辑
- 某个样本名词专用逻辑
- 面向单一 suite 的硬编码判定

允许：

- 通用 prompt 约束强化
- 通用 graph / retrieval / resolver 行为修复
- 更合理的 eval 收敛窗口

### 3.3 prompt 示例必须和样本脱钩

新增 suite 时，必须继续保持：

- `memory/insight_memory/workers/prompts.py` 里的示例名词
- 不能与 `memory/tests` 和 `memory/evals/cases` 中的样本名词重名

后续任何新 suite 设计前，必须先检查样本名词不会与 prompt 示例冲突。

### 3.4 真实 live 必须是主标准

本地单测只验证：

- loader
- manifest
- grading
- matrix 汇总

真正的泛化证明必须通过：

- 真实 `/memory/ingest`
- 真实 `/memory/recall`
- 真实 LLM

## 4. 新增官方 suite 计划

后续按以下 6 组继续扩展。

### 4.1 `generic_cross_format_longform_v1`

目标：

- 验证同一 durable fact 在更复杂格式下仍能稳定抽取、聚合、回答

覆盖场景：

- Markdown 长文 + 多级标题
- 邮件线程 + 引用块
- YAML-ish + 字段表 + narrative 混合
- bilingual 长摘要
- checklist + prose 混排
- correction note / amendment / appendix 叠加

核心断言：

- 主主体不会被格式噪声稀释
- 同一 artifact 的补充规则优先 `refresh`
- earlier/current/supplement 能稳定区分

### 4.2 `generic_large_scope_graph_v1`

目标：

- 验证大 scope 下多主体同时写入、same-surface 区分、跨实体关联是否仍稳定

覆盖场景：

- 单 scope `12-20` 个主体
- 多组同前缀 artifact
- 多条跨 entity why/dependency query
- 多主体共享 blocker 或共享 requirement，但不应 merge

核心断言：

- 不串记忆
- 不误 merge
- same-surface 不塌缩
- query 不因候选变多而退化到 `ambiguous`

### 4.3 `generic_rule_evolution_matrix_v1`

目标：

- 把规则演进、补充规则、历史规则收成专项 suite

覆盖场景：

- 早期宽松规则
- 当前严格规则
- 当前补充规则
- 历史规则与当前规则并存
- handbook / checklist / manual / bulletin 共同构成约束链

核心断言：

- `replace / refresh / coexist` 边界稳定
- `updates` 链正确形成
- `之前/当前/现在要求什么` 都可稳定回答

### 4.4 `generic_multi_subject_document_v1`

目标：

- 验证一篇超长文档里 `8-12` 个主体混合出现时的主次拆分能力

覆盖场景：

- 主主体 durable claim
- 具有独立 durable fact 的副主体
- 仅被顺手提到的旁支主体
- 同 prefix 的 `plan / review / bulletin / register / checklist`

核心断言：

- 主主体 memory 完整保留
- 副主体只在有独立 durable fact 时才落记忆
- 旁支主体不会因“被提到”而生成垃圾 memory
- prefix 相同 artifact 不会被错误合并

### 4.5 `generic_deeper_dependency_chain_v1`

目标：

- 将依赖链测试继续拉长到 `5-6` hop

覆盖场景：

- `subject -> checklist -> handbook -> bulletin -> register -> roster`
- direct blocker + co-required item + upstream prerequisite
- 历史分歧 + 当前结论 + external governing artifact
- 噪声与深链并存

核心断言：

- 回答必须说全 direct artifact 和最终 concrete prerequisite
- 不得只停留在第一跳或中间跳
- `supports / related_to` 必须区分稳定
- 历史分歧与当前结论不互相吞掉

### 4.6 `generic_out_of_distribution_domains_v1`

目标：

- 继续拉远领域分布，避免系统只在熟悉语义附近表现好

覆盖场景：

- 航运、档案、博物馆、实验室、地质、天文、农务、公共安全
- 同名 artifact/system/document
- mixed-language requirement
- 长历史 review
- noisy context

核心断言：

- 不依赖当前熟悉业务词
- 主体识别、same-surface、history/current、cross-entity 保持稳定
- 回答保留原领域核心术语，不乱翻译、不泛化过度

## 5. 每组 suite 的固定产物

每个新官方 suite 都必须同时产出：

- `generic_xxx_v1.json`
- `generic_xxx_targeted_v1.json`

规则：

- `targeted` 只含 `2-4` 条最能暴露系统 bug 的 case
- `full` 是完整覆盖
- 调试阶段优先跑 `targeted`
- 正式验收必须跑 `full`

不允许只加 full 不加 targeted。

## 6. 统一 case 设计规范

所有新增 case 必须遵循统一格式。

### 6.1 顶层字段

每条 case 必须包含：

- `case_id`
- `category`
- `description`
- `memory_scope_templates`
- `writes`
- `queries`
- `expected`

### 6.2 `writes`

每条 write 必须包含：

- `scope`
- `context`
- `expected_status`

可选字段：

- `concurrency_group`

### 6.3 `queries`

每条 query 必须包含：

- `query_id`
- `query`
- `scope`
- `expected_status`
- `required_facts`
- `forbidden_facts`

如适用，增加：

- `expected_uncertainty_prefixes`

### 6.4 `expected`

每条 case 至少覆盖：

- `entity_count`
- `memory_count`
- `memory_status_counts`
- `edge_type_counts`
- answer 层 required fact 组

### 6.5 重 case

重 case 必须显式写：

- `settle_timeout_seconds`

否则默认使用标准窗口，不得隐式依赖更长 settle。

## 7. Matrix 接入规则

所有新官方 suite 都要接入：

- `memory/evals/matrix/default_v1.json`

同时需要一个单独 manifest：

- `memory/evals/matrix/<suite>_v1.json`

目的：

- 单套件调试时可独立跑
- default matrix 可统一汇总

## 8. 验收门槛

每组 suite 固定使用以下门槛。

### 8.1 targeted

真实 live 必须：

- `100%`

### 8.2 full

首次接入允许：

- `full_pass_rate >= 0.80`

正式稳定门槛：

- `answer_grounded_rate >= 0.99`
- `semantic_pass_rate >= 0.95`
  - 指 `ingest_gate / state / query_gate / recall_structured / answer_judge`
- `full_pass_rate >= 0.90`

### 8.3 frontier 类 suite

对 `concurrency / ultralong / frontier`：

- 可以单独观察 `background_tasks`
- 但最终仍要求：
  - `full_pass_rate >= 0.80`

## 9. 回归要求

每新增一组 suite，必须同步补回归。

### 9.1 `memory/tests/test_accuracy_eval.py`

必须新增：

- `load_eval_cases_reads_<suite>_suite`
- `load_eval_matrix_reads_<manifest>_manifest`
- 若 suite 使用特殊 `settle_timeout_seconds`，必须锁住该值

### 9.2 `memory/tests/test_eval_memory_matrix.py`

必须新增：

- suite manifest 加载断言
- default matrix suite 数和尾部顺序断言

### 9.3 生产逻辑回归

如果 suite 首次暴露真实系统 bug，再补对应逻辑回归到：

- `test_recall.py`
- `test_recall_edges.py`
- `test_linker.py`
- `test_ingest.py`
- `test_tasks.py`

只补最贴近 bug 的最小回归，不泛滥补测。

## 10. 推荐执行顺序

后续扩展按以下顺序推进：

1. `generic_rule_evolution_matrix_v1`
2. `generic_cross_format_longform_v1`
3. `generic_multi_subject_document_v1`
4. `generic_large_scope_graph_v1`
5. `generic_deeper_dependency_chain_v1`
6. `generic_out_of_distribution_domains_v1`

原因：

- 规则演进最容易暴露 `replace / refresh / updates` 边界问题
- 格式迁移和多主体长文档最容易暴露 extractor/linker/resolver 的通用性问题
- 更深 dependency chain 和更远域开放场景适合放到后面，基于前面的稳态继续压

## 11. 成功标准

认为“泛化测试扩展计划 v2 已完成”的标准是：

- 上述 6 组 suite 全部落地
- 每组都有 targeted + full
- 每组都接入 default matrix
- `test_accuracy_eval.py` 和 `test_eval_memory_matrix.py` 都补齐
- 每组 full suite 都完成至少一轮真实 live
- 对真实暴露出来的 bug，只做通用语义修复

## 12. 默认约束

本文档默认以下约束始终生效：

- 不新增关键词匹配
- 不新增 case 专用逻辑
- prompt 示例名词不能与样本重名
- 新 bug 修复优先走通用 prompt / graph / resolver / retrieval 修复
- 真实 HTTP + 真实 LLM 才是最终验收标准
