# InsightMemory

简体中文 | [English](https://github.com/MarvekW/InsightMemory/blob/main/README.md)

InsightMemory 不是“再包一层向量检索”，而是一套面向 AI Agent、企业 Copilot、研究助手、知识系统的
**AI 原生长期记忆底座**。

在 AI 产品大火的时代，真正拉开差距的，往往已经不是模型第一轮回答有多像人，而是系统能不能持续记住：

- 这段信息到底属于谁；
- 这条新信息是在更新旧事实、补充旧事实，还是与旧事实冲突；
- 当前状态是怎么从历史一路演进过来的；
- 回答背后能不能给出证据链，而不是“像是对的”。

InsightMemory 想解决的就是这个问题：让 AI 从“会聊”升级到“会记、会思考、会总结、会演进、会追溯、会关联推理”。

一句话概括：InsightMemory 让 LLM 应用拥有一个以 `entity` 为中心、可演进、可追溯、能关联推理的长期记忆层。

> 许可证说明：本项目采用 MIT 许可证。详见 [LICENSE](https://github.com/MarvekW/InsightMemory/blob/main/LICENSE)。

## 一眼看懂

- **写入前先思考**：新输入不会直接落成一堆 chunk，而是先被理解成以 entity 为中心的长期记忆。
- **会总结，不只是追加**：新信息可以更新、补充、冲突或支持已有记忆，同时保留历史。
- **召回带推理脉络**：查询时可以沿着 memory edge 扩展上下文，不只是做相似文本匹配。
- **答案自带证据**：返回结果可以附带 citation、supporting observation 和历史上下文。

## 快速开始

当前 API 没有单独的 `entity` 字段。写入时要在自然语言内容里明确说明“这条记忆属于谁”，召回时也要在查询里明确带上目标 entity。

部署方式见 [快速开始文档](./docs/03-getting-started.zh-cn.md)。

写入一条 memory：

```bash
curl -X POST http://127.0.0.1:8010/memory/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "context": "对于 Atlas rollout 这个项目，当前主阻塞是数据库迁移失败，继续推进前需要先回滚。"
  }'
```

带 entity 的 memory 召回：

```bash
curl -X POST http://127.0.0.1:8010/memory/recall \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "query": "对于 Atlas rollout 这个项目，当前主阻塞是什么？"
  }'
```

更完整的部署方式、API 示例和评估流程见 [快速开始文档](./docs/03-getting-started.zh-cn.md)。

## 为什么它不一样

| 能力 | 常见向量记忆 | InsightMemory |
| --- | --- | --- |
| 同名主体隔离 | 往往较弱或要手写逻辑 | 内建 entity resolution |
| 当前态 vs 历史态 | 容易混在一起 | 作为可演进记忆并存 |
| why/how 查询 | 多数只看相似度 | 可沿 memory edge 扩展 |
| 证据回溯 | 往往较弱 | 返回 citation 和 observation 证据链 |
| 长期更新 | 常见是 append-only | 支持 update、support、conflict、derivation |

## Demo 场景

下面这三组文本 demo 都来自仓库自己的评测报告抽样，不是单独编出来的 marketing 示例。

### 1. 同名 Entity 隔离

写入：

- `Atlas 是发布项目，当前主阻塞是数据库迁移失败。`
- `Atlas 是知识文档，当前缺少回滚说明。`

召回：

- Query: `Atlas 发布项目 当前主阻塞是什么？`
- Answer: `Atlas 发布项目当前主阻塞是数据库迁移失败。`

它说明了：

- 同一个 surface form 可以被解析成不同 entity；
- 查询会落在正确的主体上，不会把项目和文档的事实混在一起。

### 2. Current vs Historical

写入：

- `Ashgrove handbook 之前允许团队在 shift 后 24 小时内补录 fallback schedule。`
- `Ashgrove handbook 当前要求所有 fallback schedule 变更必须先经 incident lead 审批。`
- `Ashgrove handbook 最新补充：所有审批记录还必须附在 change packet 中。`

召回：

- Query: `Ashgrove handbook 当前要求什么？`
- Answer: `Ashgrove handbook 当前要求所有 fallback schedule 变更必须先经 incident lead 审批，并补充审批记录必须附在 change packet 中。`

- Query: `Ashgrove handbook 之前允许什么？`
- Answer: `Ashgrove handbook 之前允许团队在 shift 后 24 小时内补录 fallback schedule。`

它说明了：

- 当前记忆和历史记忆可以并存；
- 新补充会被综合进 current memory，而不是把历史信息直接抹掉。

### 3. Why/How + Citation

写入：

- `Billing service 当前还不能切换到新模板，因为税率模板校验流程没有补齐。`
- `Tax template checklist 明确要求切换前必须完成税率模板校验流程。`

召回：

- Query: `为什么 Billing service 还不能切换到新模板？`
- Answer: `Billing service 当前还不能切换到新模板，因为税率模板校验流程没有补齐。Tax template checklist 明确要求切换前必须完成税率模板校验流程。`

它说明了：

- 回答可以同时拉出 blocker 本身和 supporting requirement；
- citation 可以把答案追溯回原始证据。

## 评测快照

下面这些数字直接来自仓库中的 [`evals/reports`](./evals/reports) 评测报告，不是手写营销数字。

| 评测切片 | Case 数 | Full-pass rate | Grounded answer rate | 重点能力 |
| --- | ---: | ---: | ---: | --- |
| Generic accuracy | 39 | 97.4% | 100% | 广义记忆准确率基线 |
| Same-name disambiguation | 2 | 100% | 100% | 同名不同主体拆分 |
| Rule evolution | 6 | 100% | 100% | current vs historical 与补充型更新 |
| Cross-entity why recall | 1 | 100% | 100% | why/how 与外部 requirement 解释链 |

仓库级评测覆盖目前包括：

| 资产 | 数量 |
| --- | ---: |
| Matrix manifests | 11 |
| Case files | 60 |

## 文档导航

- [快速开始](./docs/03-getting-started.zh-cn.md)：镜像版 Docker Compose、本地构建 Docker Compose、pip 安装、源码安装、API 示例和评估命令。
- [产品总览](./docs/01-product-overview.zh-cn.md)：问题定义、项目定位、对比和适用场景。
- [系统总览](./docs/02-system-overview.zh-cn.md)：核心概念、功能特性、架构和目录结构。
- [记忆设计](./docs/04-memory-design.md)：更细的 entity identity 与 memory 建模说明。
- [后台任务调度](./docs/06-background-task-scheduling.md)：后台任务运行时设计。
- [泛化测试扩展计划](./docs/07-generalization-test-expansion-plan.md)：评测覆盖规划和 suite 规则。
- [开发指南](./docs/09-development-guide.md)：中英双语的 memory 逻辑 LLM 优先开发原则。
- [写入与读取最佳实践](./docs/10-memory-read-write-best-practices.zh-cn.md)：如何组织写入内容、查询问题和处理异步召回结果。
- [技术博客草稿](./docs/blogs/zh-cn/blog-index.zh-cn.md)：用于对外发布、解释和推广项目的中文技术文章。

## 支持与协作

InsightMemory 仍在持续开发中。比较有价值的支持方式包括：

- 在真实 AI Agent / Copilot / 知识系统里接入并反馈失败案例；
- 补充同名主体、长周期演进、多主体文档等评估用例；
- 改进文档、示例、部署说明和 benchmark 报告；
- 通过 issue 提交 bug、回归问题和缺失场景；
- 提供可用于测试的 LLM API-KEY、调用额度或赞助支持，帮助我继续完善 prompt、评测覆盖和长周期记忆实验；
- 洽谈协作、集成或赞助。

如果你希望围绕项目合作，可以联系：

```text
marvekwang@gmail.com
```

请不要在公开 issue 或评论中粘贴 API Key。如果你愿意支持项目的 LLM 调用成本，请通过私下方式联系。感谢支持。

## 许可证

本项目采用 MIT 许可证。

完整条款见 [LICENSE](./LICENSE)。
