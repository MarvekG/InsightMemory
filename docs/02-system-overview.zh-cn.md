# 系统总览

[返回 README](../README.zh-cn.md)

这份文档聚焦 InsightMemory 背后的核心模型、服务结构和仓库目录布局。

## 核心概念

- `memory_scope`：最外层隔离边界，可用于租户、用户、实验或测试运行。
- `entity`：记忆所属的稳定主体，也就是“这条记忆属于谁”，使用 opaque `entity_key` 标识。
- `memory`：属于某个 entity 的稳定事实、状态、规则、结论或历史记录。
- `observation`：原始输入证据，append-only，不作为可变真相。
- `edge`：memory 之间的关系，用于表达更新、支持、冲突、派生、依赖或相关。
- `memory graph`：由 entity、memory、observation 和 edge 组成的关联记忆图。
- 图构建分两层：先构建单个 entity 内的小图，再按需要扩展跨 entity 的大图，用于关联记忆查询。

更细的建模说明见当前的 [设计笔记](./04-memory-design.md)。

## 功能特性

- 基于 LLM 自动抽取输入中的 entity，判断记忆属于哪个稳定主体。
- 支持同名不同主体的 entity resolution，避免不同项目、人物、文档和规则互相污染。
- 自动抽取候选 memory，并判断新记忆与旧记忆之间是更新、补充、冲突、派生、支持还是并存。
- 自动构建 memory-memory edge，用关系图表达记忆之间的上下文、因果、依赖和冲突。
- 支持关联记忆查询：召回不只依赖文本相似度，也会扩展有价值的 memory edge。
- 支持补充型 refresh：新增细节不会覆盖旧的当前规则或当前状态。
- 支持历史记忆和当前记忆并存。
- 支持跨 entity 关系图，用于解释 why/how 查询。
- 召回结果带 observation citation，方便审计和追溯。
- 后台任务支持 reindex、entity profile refresh、memory edge repair、lifecycle 和 merge candidate detection。
- 内置泛化评估矩阵，覆盖长时间演进、跨格式文档、长历史记录、多主体文档、金融或市场场景、高并发和开放域。

## 架构

```text
Client
  |
  | HTTP
  v
FastAPI service
  |
  +-- Ingest graph
  |     - 校验输入
  |     - 抽取 identity profile 和候选 memory
  |     - 解析到已有 entity 或创建新 entity
  |     - 创建、刷新、替换或保留 memory
  |     - 投递后台任务
  |
  +-- Recall graph
  |     - 校验查询
  |     - 解析目标 entity
  |     - 检索 memory 和证据
  |     - 扩展有用的 memory edge
  |     - 生成 grounded answer
  |
  +-- Background worker
        - 重建检索索引
        - 刷新 entity profile
        - 修复 memory edge
        - 检测 merge candidate
        - 推进 lifecycle 状态

Storage
  |
  +-- PostgreSQL / pgvector
  +-- 本地 retrieval docstore
```

## 目录结构

```text
memory/
  insight_memory/
    api/        HTTP schema 和 route
    evals/      LLM 评估辅助逻辑
    graph/      ingest、recall、repair、reindex、merge、lifecycle 工作流
    index/      检索索引集成
    services/   服务级编排
    storage/    数据库模型和 repository
    tasks/      持久化后台任务运行时
    workers/    后台 worker、prompt、LLM provider
  docs/         设计文档
  evals/        评估用例、矩阵和报告
  evals/scripts/ 评估命令行脚本
  tests/        pytest 测试
```
