# LlamaIndex 检索层设计

[返回 README](./04-memory-design.md)

这份文档描述 `memory` 服务下一版检索层设计：用 LlamaIndex 承担检索编排，用 PostgreSQL/pgvector 承担向量索引持久化，同时保留 BM25 的精确 token 召回能力。

目标不是把现有 memory graph 迁移到 LlamaIndex，而是把 `RetrievalIndex` 从本地 `docstore.json` 升级成可持久化、可重建、可混合召回的检索层。

## 1. 目标

- 支持语义向量召回，提升同义改写、口语化问题、模糊查询的命中率。
- 保留 BM25 召回，覆盖股票代码、项目名、日期、指标名等精确 token。
- 去掉本地 `MEMORY_RETRIEVAL_PERSIST_PATH` 文件，避免单机文件持续膨胀和多实例状态不一致。
- 支持 `MEMORY_EMBEDDING` 本地模型和在线模型两种后端。
- 非容器启动（whl 包和源码启动）只读取 `.env` 配置，不通过命令行参数覆盖配置。
- 不改变现有 entity、memory、observation、edge、version、citation 的业务模型。

## 2. 非目标

- 不用 LlamaIndex 接管 entity resolution、memory version、edge expansion 或 answer composition。
- 不引入 Chroma、Qdrant、Milvus 等第二套存储组件。
- 不把 observation 原文作为可修改真相。
- 不为了检索层改动现有 memory graph 的 prompt 语义。
- 不在第一版实现 reranker 或复杂多阶段学习排序。

## 3. 总体架构

```mermaid
flowchart TD
    ingest["Ingest / Background task"]
    retrieval_index["RetrievalIndex"]
    pgvector["LlamaIndex PGVectorStore<br/>单张 PostgreSQL/pgvector 检索索引表<br/>保存 text、embedding 和 node metadata"]
    recall["Recall graph"]
    bm25["BM25 retriever"]
    vector["Vector retriever"]
    rrf["RRF fusion"]
    edges["Memory edge expansion"]
    answer["Grounded answer composition"]

    ingest -->|"create/update entity or memory"| retrieval_index
    retrieval_index --> pgvector

    recall --> bm25
    recall --> vector
    bm25 --> rrf
    vector --> rrf
    rrf --> edges
    edges --> answer
```

PostgreSQL 保存两类数据：

- 业务真相表：`memory_entities`、`memory_memories`、`memory_observations`、`memory_edges` 等。
- 检索派生表：LlamaIndex `PGVectorStore` 管理的 pgvector 表。

检索派生数据可以通过内部索引重建从业务真相表恢复，不作为最终事实来源。

## 4. 存储设计

### 4.1 单表检索索引

第一版不新增 `memory_retrieval_documents`。检索层只使用 LlamaIndex `PGVectorStore` 管理的一张 pgvector 表。

原因：

- `PGVectorStore` 本身支持保存 text。
- `PGVectorStore` 本身支持保存 node metadata。
- `PGVectorStore` 支持 metadata filter，可按 `memory_space`、`kind`、`ref_doc_id` 等条件过滤。
- 单表可以避免 text、metadata、embedding 在两张表之间出现一致性问题。
- 检索数据是业务真相表的派生索引，从业务表重建，不需要再维护一张应用自定义投影表。

这张表的概念字段如下，实际字段由 LlamaIndex `PGVectorStore` 创建和管理：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| node id | string | 稳定 node id，推荐等于 `ref_doc_id` |
| text | text | entity/memory 的检索投影文本 |
| embedding | vector | embedding 向量 |
| metadata | json/jsonb | `ref_doc_id`、`kind`、`memory_space`、`entity_key`、`memory_id`、`status` 等 |

`ref_doc_id` 格式保持当前约定：

```text
entity:{memory_space}:{entity_key}
memory:{memory_space}:{memory_id}
```

### 4.2 pgvector 表

pgvector 表由 LlamaIndex `PGVectorStore` 管理。默认表名是代码常量，`.env.example` 不暴露这个配置：

```python
MEMORY_VECTOR_TABLE = "memory_node_index"
```

部署者通常不需要、也不应该在 `.env` 中指定向量表名。这样可以减少部署配置项，并避免不同环境误写成不同表名导致索引不可见。

表中的 node metadata 必须包含：

```json
{
  "ref_doc_id": "memory:user:7:general:mem_xxx",
  "kind": "memory",
  "memory_space": "user:7:general",
  "entity_key": "ent_xxx",
  "memory_id": "mem_xxx",
  "status": "active"
}
```

metadata 是过滤条件和回填业务对象的关键，不能只保存 text 和 embedding。

字段作用：

| 字段 | 作用 |
| --- | --- |
| `ref_doc_id` | 稳定检索文档 id，用于删除旧 node、reindex 幂等写入、融合 BM25/vector 结果和去重。 |
| `kind` | 区分 `entity` 与 `memory`，用于 entity resolution 和 memory recall 使用不同候选池。 |
| `memory_space` | 租户/用户/场景隔离边界，所有检索必须按它过滤，避免跨空间污染。 |
| `entity_key` | 回填业务 entity，并用于同一 entity 下的 memory 候选过滤和 edge expansion。 |
| `memory_id` | 回填业务 memory；`kind=entity` 时为空或不写，`kind=memory` 时必须存在。 |
| `status` | memory 生命周期状态，用于过滤 archived/purged 结果，以及 active 优先的业务排序；`kind=entity` 时可为空或不写。 |

索引版本信息不写入每个 node metadata。`embedding_provider`、`embedding_model`、`embedding_dim` 这类字段在同一张索引表内高度重复，逐 node 存储会浪费空间，并让模型切换时的版本判断变得分散。版本状态集中保存，见第 10 章。

### 4.3 为什么不用两张表

两张表方案可以做到，但第一版不建议使用。

两张表的代价：

- text 和 metadata 会在 `memory_retrieval_documents` 与 pgvector 表中重复保存。
- refresh、delete、reconcile 都需要维护两份派生状态。
- 写入失败时要处理业务表成功、投影表成功、vector 表失败等更多中间态。
- schema 演进时要同步两套检索表。

单表方案的边界：

- 检索索引表 schema 由 LlamaIndex 管理，不作为业务真相表。
- 如果需要独立审计、人工查询、跨检索后端迁移，再考虑增加应用自定义投影表。
- 第一版 BM25 直接从 PGVectorStore 表读取 text 构造 nodes，不再依赖本地 `docstore.json`。
- 如果 LlamaIndex 的公开 API 不能高效按 metadata 批量读取 text，允许在 `RetrievalIndex` 内部通过只读 SQL 访问同一张 PGVectorStore 表；这仍然是单表方案，不额外创建投影表。

### 4.4 pgvector 初始化

服务启动时在 PostgreSQL 上执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

如果失败，启动失败，并给出明确错误：

- 当前数据库没有安装 pgvector。
- 当前用户没有创建 extension 权限。
- `MEMORY_DATABASE_URL` 指向了普通 PostgreSQL 或错误数据库。

## 5. 文本投影设计

这里的“文本投影”不是新数据模型，也不是让 LLM 再生成一份内容。

它的意思很简单：数据库里保存的是结构化字段，但 BM25 和 embedding 都只能处理一段文本。系统需要把 entity 或 memory 的关键字段按固定格式拼成一段“可检索文本”，再写入 PGVectorStore。

业务真相仍然在原表里：

- entity 真相在 `memory_entities.identity_profile`
- memory 真相在 `memory_memories.title / summary / content`

PGVectorStore 里的 text 只是检索用副本。它坏了可以从业务表重新拼出来。

### 5.1 Entity 文本怎么拼

entity 用来解决“这条记忆属于谁”。所以 entity 的检索文本主要来自 `identity_profile`。

假设数据库里有这个 entity：

```json
{
  "display_name": "Apollo API",
  "identity_profile": {
    "who": "Apollo API",
    "surface_forms": ["Apollo API", "Apollo backend"],
    "distinguishing_context": ["deploy", "migration", "backend service"]
  }
}
```

写入 PGVectorStore 前，拼成这样的 text：

```text
who: Apollo API
surface_forms: Apollo API | Apollo backend
distinguishing_context: deploy | migration | backend service
```

这样做的目的：

- 用户写入“apollo 后端迁移失败”时，系统能找到这个 Apollo API entity。
- 用户查询“apollo 发布阻塞是什么”时，系统能先定位到正确 entity。
- 同名 entity 并存时，`distinguishing_context` 可以帮助区分。

### 5.2 Memory 文本怎么拼

memory 用来解决“系统到底记住了什么”。所以 memory 的检索文本由两部分组成：

1. 所属 entity 的身份文本。
2. memory 自己的 `title / summary / content`。

假设数据库里有这个 memory：

```json
{
  "entity_key": "ent_apollo",
  "title": "数据库迁移失败",
  "summary": "当前主阻塞是数据库迁移失败。",
  "content": "当前主阻塞是数据库迁移失败，需要先回滚。",
  "status": "active"
}
```

结合所属 entity 后，写入 PGVectorStore 的 text 是：

```text
who: Apollo API
surface_forms: Apollo API
distinguishing_context: deploy | migration
数据库迁移失败
当前主阻塞是数据库迁移失败。
当前主阻塞是数据库迁移失败，需要先回滚。
```

这样做的目的：

- BM25 可以命中“数据库迁移”“Apollo API”“回滚”等原文词。
- 向量检索可以命中“发布卡住的原因是什么”这种字面不完全一样的问题。
- 召回结果拿到 `memory_id` 后，再回业务表读取完整 memory 和 citation。

### 5.3 为什么不直接把整张表塞进去

检索文本应该短、稳定、可重建，只放对召回有用的信息。

不建议放入：

- 数据库主键以外的大量内部字段。
- task 状态、审计日志、LLM 调用详情。
- observation 原文全文，除非这段原文已经被提炼成 memory。
- 每个 node 重复的 embedding provider/model/dim 版本字段。

原因：

- 文本太长会降低 BM25 和 embedding 的质量。
- 无关字段会把召回带偏。
- 重复字段会浪费向量表空间。
- 业务真相已经在原表里，检索 text 只需要帮系统“找到哪条 memory”。

### 5.4 一句话总结

文本投影就是：

```text
把 entity/memory 的关键字段拼成一段检索文本，用来做 BM25 和 embedding；真正回答时仍回到业务表读取完整数据。
```

## 6. Embedding 后端设计

`MEMORY_EMBEDDING_PROVIDER` 支持两个值：

```env
local
openai_compatible
```

### 6.1 配置原则

`.env` 只保留部署者必须填写或确实需要覆盖的配置。默认 embedding 配置放在 `insight_memory/config.py` 中。

部署者通常不需要把默认值写进 `.env`。只有以下情况才建议显式配置：

- 要从本地模型切换到在线 embedding。
- 要换 embedding 模型或维度。
- 要指定模型缓存目录。
- 要禁止本地模型联网下载。

### 6.2 本地模型配置

本地模式使用 HuggingFace / sentence-transformers embedding。

适用场景：

- 离线部署。
- 不希望把记忆文本发送到外部 API。
- 可以接受更重的 Python 依赖、模型下载和启动加载时间。

行为要求：

- 使用 `MEMORY_EMBEDDING_CACHE_DIR` 作为模型缓存目录。
- `MEMORY_EMBEDDING_LOCAL_FILES_ONLY=true` 时禁止联网下载模型。
- 启动预热时生成一次测试 embedding，确认模型可用且维度正确。

默认本地模型配置由代码提供，不需要写进 `.env`：

```env
MEMORY_EMBEDDING_PROVIDER=local
MEMORY_EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
MEMORY_EMBEDDING_DIM=768
MEMORY_EMBEDDING_CACHE_DIR=./data/models
MEMORY_EMBEDDING_LOCAL_FILES_ONLY=false
MEMORY_EMBEDDING_PREWARM_ON_STARTUP=true
MEMORY_EMBEDDING_MAX_CONCURRENCY=8
MEMORY_EMBEDDING_BATCH_SIZE=32
```

本地模式不需要配置：

```env
MEMORY_EMBEDDING_API_KEY
MEMORY_EMBEDDING_BASE_URL
```

### 6.3 在线模型配置

在线模式使用 OpenAI-compatible embedding API。

适用场景：

- 希望 whl 包或源码部署更轻。
- 可以接受外部 API 调用成本和网络依赖。
- 已有 OpenAI-compatible 服务或代理。

行为要求：

- 必须配置 `MEMORY_EMBEDDING_API_KEY`。
- `MEMORY_EMBEDDING_BASE_URL` 为空时使用 SDK 默认地址。
- 请求超时使用 `MEMORY_EMBEDDING_TIMEOUT_SECONDS`。
- 启动预热时调用一次小文本 embedding，确认 API 可用且维度正确。

在线模式只写在线 API 相关配置：

```env
MEMORY_EMBEDDING_PROVIDER=openai_compatible
MEMORY_EMBEDDING_MODEL=text-embedding-3-small
MEMORY_EMBEDDING_DIM=1536
MEMORY_EMBEDDING_API_KEY=your_embedding_api_key
MEMORY_EMBEDDING_BASE_URL=https://api.openai.com/v1
MEMORY_EMBEDDING_TIMEOUT_SECONDS=30
MEMORY_EMBEDDING_PREWARM_ON_STARTUP=true
MEMORY_EMBEDDING_MAX_CONCURRENCY=32
MEMORY_EMBEDDING_BATCH_SIZE=128
```

如果在线 embedding 服务使用 SDK 默认地址，可以省略：

```env
MEMORY_EMBEDDING_BASE_URL
```

在线模式不需要配置：

```env
MEMORY_EMBEDDING_CACHE_DIR
MEMORY_EMBEDDING_LOCAL_FILES_ONLY
```

### 6.4 Embedding 并发与批处理

embedding 必须限制并发，尤其是本地模型。否则高并发 ingest、reindex 或后台任务会同时触发大量 embedding 计算，容易把 CPU 打满，导致 API 服务、后台 worker 和数据库连接都变慢。

这两个配置都允许在 `.env` 中覆盖。默认值由代码提供：

```env
MEMORY_EMBEDDING_MAX_CONCURRENCY=8
MEMORY_EMBEDDING_BATCH_SIZE=32
```

配置含义：

| 配置 | 作用 |
| --- | --- |
| `MEMORY_EMBEDDING_MAX_CONCURRENCY` | 同一进程内允许同时执行的 embedding 请求数。 |
| `MEMORY_EMBEDDING_BATCH_SIZE` | reindex 或批量写入时，一次送入 embedding 后端的文本数量。 |

本地模型建议：

- 默认 `MEMORY_EMBEDDING_MAX_CONCURRENCY=8`。
- 8 是上限保护，不代表一定会持续打满 8 个任务；实际吞吐还受 batch size、模型和硬件影响。
- CPU 部署如果出现抢占严重、接口延迟明显升高，可以把并发降到 `2` 或 `4`。
- 大模型或低配机器可以把 `MEMORY_EMBEDDING_BATCH_SIZE` 降到 `8` 或 `16`。
- 本地 embedding 调用必须通过进程内 semaphore 限流，禁止无限并发。

在线模型建议：

- 代码默认仍是 `MEMORY_EMBEDDING_MAX_CONCURRENCY=8`、`MEMORY_EMBEDDING_BATCH_SIZE=32`，不根据 provider 做隐藏切换。
- 在线模型通常可以显式覆盖到 `MEMORY_EMBEDDING_MAX_CONCURRENCY=32`、`MEMORY_EMBEDDING_BATCH_SIZE=128`，尽量放大吞吐。
- 如果供应商或网关额度允许，可以继续提高并发；如果出现 429 或超时，再下调。
- 遇到 429、超时或网关限流时要退避重试，不能无限并发重试。

架构要求：

- `refresh_entities`、`refresh_memories`、reindex 和 repair 任务共用同一个 embedding 并发限制器。
- API 请求触发的单条写入也必须经过同一个限制器。
- 后台任务已有自己的 worker 并发配置，但不能替代 embedding 并发限制；embedding 限制是更细粒度的资源保护。
- reindex 必须按 batch 执行，不能一次性把所有 memory 全部送入模型。

### 6.5 维度与模型版本

`MEMORY_EMBEDDING_DIM` 必须与实际模型输出一致。服务不自动猜测维度。

服务会在 embedding 写入前校验输出维度。以下配置共同决定 pgvector 表中向量的语义和维度：

- `MEMORY_EMBEDDING_PROVIDER`
- `MEMORY_EMBEDDING_MODEL`
- `MEMORY_EMBEDDING_DIM`

更换 embedding provider、embedding model、embedding dim 或文本投影版本时，不迁移旧向量，也不尝试把旧向量转换成新向量。系统应通过内部后台任务重建 pgvector 表。

## 7. 检索流程

### 7.1 写入和更新

用途：

- ingest graph 创建或更新 entity/memory 后，会创建 `reindex_memory` 后台任务。
- `reindex_memory_graph`、`refresh_entity_profile_graph`、merge/lifecycle 相关流程会调用 `refresh_entities`、`refresh_memories` 或 delete 接口。
- recall/entity resolution 前会调用 `_ensure_entities_indexed`、`_ensure_memories_indexed`，只补齐候选集合中缺失或过期的 node。
- 目标是让业务表变化后，PGVectorStore 中的检索 node 同步更新。

流程图：

```mermaid
flowchart TD
    business["业务表 entity/memory 已创建或更新"]
    task["后台 reindex_memory 任务<br/>或查询时 ensure indexed"]
    project["生成检索文本投影"]
    refdoc["计算稳定 ref_doc_id"]
    node["创建 LlamaIndex TextNode"]
    metadata["写入 node metadata<br/>ref_doc_id / kind / memory_space / entity_key / memory_id / status"]
    embed["调用 embedding 后端生成向量"]
    validate["校验 embedding 维度"]
    delete_old["删除旧 vector node"]
    store["写入 PGVectorStore"]

    business --> task
    task --> project
    project --> refdoc
    refdoc --> node
    node --> metadata
    metadata --> embed
    embed --> validate
    validate --> delete_old
    delete_old --> store
```

`refresh_entities` 与 `refresh_memories` 负责同步检索索引：

1. 根据 entity/memory 生成投影文本。
2. 创建新的 LlamaIndex `TextNode`，node text 使用投影文本。
3. node metadata 写入 `ref_doc_id`、`kind`、`memory_space`、`entity_key`、`memory_id`、`status` 和 `updated_at`。
4. 通过 embedding 后端生成 embedding。
5. 校验 embedding 维度。
6. 删除同 `ref_doc_id` 的旧 vector node。
7. 写入 `PGVectorStore`。

注意：应先生成并校验新 embedding，再删除旧 node。这样 embedding 后端超时、维度错误或 API 失败时，不会先把已有可用索引删掉。

业务表写入成功但检索写入失败时，第一版建议让当前任务失败并重试，而不是静默降级。原因是 memory 系统依赖检索层做 entity resolution 和 recall，索引缺失会导致行为不可预测。

### 7.2 Entity 候选召回

用途：

- ingest graph 中用于把 `identity_profile_draft` 匹配到已有 entity，决定新 memory 是挂到旧 entity 还是创建新 entity。
- recall graph 中用于把用户 query 解析到目标 entity，再进入 memory recall。
- 它解决的是“这条记忆或这个问题属于谁”，不是直接回答问题。

流程图：

```mermaid
flowchart TD
    draft["identity draft / query focus"]
    entities["读取当前 memory_space 的候选 entities"]
    query["把 draft 拼成 query text"]
    bm25["BM25 检索候选 entity 文本"]
    vector["Vector 检索候选 entity embedding"]
    rrf["RRF 融合 entity 候选"]
    payload["组装 entity_candidates payload"]
    resolver["linker 选择最终 entity"]

    draft --> query
    entities --> bm25
    entities --> vector
    query --> bm25
    query --> vector
    bm25 --> rrf
    vector --> rrf
    rrf --> payload
    payload --> resolver
```

输入：

- LLM 生成的 identity draft。
- 当前 memory_space 下候选 entities。

流程：

1. 将 draft 投影成 query text。
2. BM25 在候选 entity 的投影文本中检索。
3. vector retriever 使用候选 `ref_doc_id` 做参数化过滤；`kind=entity` 已由业务候选集合保证。
4. 使用 RRF 融合两个候选列表。
5. 返回 `ScoredEntity`，保持现有调用接口。

### 7.3 Memory 候选召回

用途：

- recall graph 在确定 `entity_key` 后调用。
- repair edge / cross-entity 相关后台任务也可以用它找相关 memory。
- 它负责找 seed memories；之后 why/how、支持/冲突/更新关系仍由 memory edge expansion 处理。

流程图：

```mermaid
flowchart TD
    entity["已解析 entity_key"]
    memories["读取该 entity 下候选 memories"]
    rewrites["query + query_rewrites"]
    corpus["合并成 query corpus"]
    bm25["BM25 检索候选 memory 文本"]
    vector["Vector 检索候选 memory embedding"]
    rrf["RRF 融合 memory 候选"]
    tiebreak["业务排序<br/>active / salience / confidence / updated_at"]
    seeds["seed memories"]
    edges["memory edge expansion"]

    entity --> memories
    rewrites --> corpus
    memories --> bm25
    memories --> vector
    corpus --> bm25
    corpus --> vector
    bm25 --> rrf
    vector --> rrf
    rrf --> tiebreak
    tiebreak --> seeds
    seeds --> edges
```

输入：

- query rewrites 或 query focus 文本。
- 业务层传入的候选 memories。

流程：

1. 合并 query texts 得到 query corpus。
2. BM25 在候选 memory 投影文本中检索。
3. vector retriever 使用候选 `ref_doc_id` 做参数化过滤；`kind=memory` 已由业务候选集合保证。
4. RRF 融合候选。
5. 排序补充 active、salience、confidence、updated_at。
6. 返回 `ScoredMemory`，交给 recall graph 做 edge expansion。

### 7.4 融合策略

用途：

- `entity_candidates()` 和 `memory_candidates()` 都使用同一套融合策略。
- 目的是把 BM25 的精确命中和 vector 的语义命中合成一个稳定候选列表。
- 不直接比较原始分数，避免 BM25 分数和向量相似度分数尺度不一致。

流程图：

```mermaid
flowchart TD
    bm25_list["BM25 ranked list"]
    vector_list["Vector ranked list"]
    rrf_bm25["按 BM25 rank 累加<br/>1 / (k + rank)"]
    rrf_vector["按 vector rank 累加<br/>1 / (k + rank)"]
    scores["合并 ref_doc_id 分数"]
    sort["按 RRF score 排序"]
    limit["截取 top-k"]

    bm25_list --> rrf_bm25
    vector_list --> rrf_vector
    rrf_bm25 --> scores
    rrf_vector --> scores
    scores --> sort
    sort --> limit
```

第一版使用 RRF，避免直接比较 BM25 分数和向量相似度分数。

配置：

```env
MEMORY_VECTOR_RRF_K=50
MEMORY_VECTOR_RECALL_OVERSAMPLE=24
MEMORY_VECTOR_DENSE_MIN_SCORE=0.12
MEMORY_SIMILARITY_MIN_SCORE=0.01
```

过滤规则：

- vector 结果进入 RRF 前，过滤低于 `MEMORY_VECTOR_DENSE_MIN_SCORE` 的候选。
- BM25 结果进入 RRF 前，只保留 `score > 0` 的候选。
- RRF 融合后，过滤低于 `MEMORY_SIMILARITY_MIN_SCORE` 的候选，再做业务排序。
- `MEMORY_VECTOR_LEXICAL_MIN_SCORE` 保留为后续调参入口，第一版不作为 BM25 硬阈值，避免 BM25 分数尺度差异导致误杀。

### 7.5 BM25 与向量召回的组合规则

用途：

- 这是 7.2 entity recall 和 7.3 memory recall 的共同底层规则。
- BM25 与 vector 并行执行，RRF 融合后再交给当前业务流程。
- 对 memory recall 来说，融合结果只是 seed memories，最终回答仍依赖 edge expansion 和 grounded answer composition。

BM25 和向量召回不做二选一。两者职责不同：

- BM25 负责精确 token 命中，适合股票代码、公司名、项目名、日期、指标名和原文术语。
- 向量召回负责语义泛化，适合同义改写、口语化问题、模糊意图和字面不重合的表达。

组合流程图：

```mermaid
flowchart TD
    query["query / draft text"]
    constraints["业务候选约束<br/>memory_space / kind / ref_doc_id"]
    bm25["BM25 retriever<br/>lexical ranked list"]
    vector["Vector retriever<br/>semantic ranked list"]
    rrf["RRF fusion"]
    tiebreak["business tie-break"]
    seeds["seed entities / seed memories"]
    expansion["memory edge expansion<br/>仅 memory recall 后执行"]

    query --> bm25
    query --> vector
    constraints --> bm25
    constraints --> vector
    bm25 --> rrf
    vector --> rrf
    rrf --> tiebreak
    tiebreak --> seeds
    seeds --> expansion
```

实现约束：

1. 先做业务候选约束，再做检索。
   - entity 召回只在当前 `memory_space` 的候选 entities 内检索。
   - memory 召回只在业务层传入的候选 memories 内检索。
   - 先由业务层限定 `memory_space` 和 `kind` 候选集合，再用候选 `ref_doc_id` 参数化过滤 vector retriever。
2. 两路召回都取宽候选。
   - 如果最终需要 top 10，BM25 和 vector 可以各取 top 24 或 top 30。
   - 宽候选数量由 `MEMORY_VECTOR_RECALL_OVERSAMPLE` 控制，计算方式是 `max(limit, MEMORY_VECTOR_RECALL_OVERSAMPLE)`，再受实际候选数量限制。
3. 不直接相加原始分数。
   - BM25 分数和向量相似度分数尺度不同，不能直接加权求和。
   - 第一版统一使用 RRF，后续有评测数据后再考虑 learned weight。
4. 单路命中也保留。
   - 只被 BM25 命中的结果可能是精确代码或术语命中。
   - 只被向量命中的结果可能是语义改写命中。
   - 两路都高排名命中的结果会因 RRF 自然靠前。
5. RRF 后再做业务 tie-break。
   - memory 候选按 `active`、`salience`、`confidence`、`updated_at` 作为同分或近分补充排序。
   - 业务 tie-break 不能把明显低 RRF 的结果强行提升到前排。
6. edge expansion 放在融合之后。
   - hybrid retrieval 只负责找 seed memories。
   - `supports`、`contradicts`、`updates`、`derived_from`、`related_to` 的关系扩展继续由 recall graph 处理。

RRF 伪代码：

```python
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = 50,
    limit: int = 10,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, ref_doc_id in enumerate(ranked, start=1):
            scores[ref_doc_id] = scores.get(ref_doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
```

memory 候选最终排序建议：

```python
rank_key = (
    rrf_score,
    1 if memory.status == "active" else 0,
    memory.salience,
    memory.confidence,
    memory.updated_at,
)
```

## 8. 启动与配置

非容器启动（whl 包和源码启动）只读取 `.env`。

非容器启动不自动扫描当前目录或 home 目录，必须通过 `INSIGHT_MEMORY_ENV=/absolute/path/to/.env` 显式指定。

`.env` 必须最小化。大部分运行参数放在代码默认值中，避免部署者被大量配置项阻塞。

### 8.1 最小 `.env`

最小配置只包含数据库、端口和 LLM：

```env
MEMORY_DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory
MEMORY_SERVICE_PORT=8010

MEMORY_LLM_PROVIDER=deepseek
MEMORY_LLM_MODEL=deepseek-chat
MEMORY_LLM_API_KEY=
MEMORY_LLM_BASE_URL=https://api.deepseek.com
```

其中：

- `MEMORY_DATABASE_URL` 指向 PostgreSQL/pgvector 数据库。
- `MEMORY_SERVICE_PORT` 是非容器启动端口。
- LLM 配置用于 memory extraction、resolution 和 answer composition。

### 8.2 默认配置

不写入 `.env` 时，代码默认使用：

```env
MEMORY_DATABASE_SCHEMA=memory
MEMORY_EMBEDDING_PROVIDER=local
MEMORY_EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
MEMORY_EMBEDDING_DIM=768
MEMORY_EMBEDDING_CACHE_DIR=$HOME/.insight_memory/data/models
MEMORY_EMBEDDING_TIMEOUT_SECONDS=30
MEMORY_EMBEDDING_LOCAL_FILES_ONLY=false
MEMORY_EMBEDDING_PREWARM_ON_STARTUP=true
MEMORY_EMBEDDING_MAX_CONCURRENCY=8
MEMORY_EMBEDDING_BATCH_SIZE=32
MEMORY_VECTOR_RECALL_OVERSAMPLE=24
MEMORY_VECTOR_RRF_K=50
MEMORY_VECTOR_DENSE_MIN_SCORE=0.12
MEMORY_VECTOR_LEXICAL_MIN_SCORE=0.08
MEMORY_SIMILARITY_MIN_SCORE=0.01
```

这些默认值不应复制到 `.env.example` 的最小配置区，但 `MEMORY_EMBEDDING_MAX_CONCURRENCY` 和 `MEMORY_EMBEDDING_BATCH_SIZE` 应在 `.env.example` 的可选覆盖区列出。`memory_node_index` 这类内部表名属于代码常量，不列为 `.env` 覆盖项。

### 8.3 在线 embedding 覆盖项

只有切换在线 embedding 时，才需要额外写入：

```env
MEMORY_EMBEDDING_PROVIDER=openai_compatible
MEMORY_EMBEDDING_MODEL=text-embedding-3-small
MEMORY_EMBEDDING_DIM=1536
MEMORY_EMBEDDING_API_KEY=your_embedding_api_key
MEMORY_EMBEDDING_BASE_URL=
MEMORY_EMBEDDING_TIMEOUT_SECONDS=30
MEMORY_EMBEDDING_MAX_CONCURRENCY=32
MEMORY_EMBEDDING_BATCH_SIZE=128
```

如果在线 embedding 和 LLM 使用同一个 OpenAI-compatible 网关，也可以复用同一组 API key，但配置上仍保持 `MEMORY_EMBEDDING_*` 和 `MEMORY_LLM_*` 分离，避免两类模型耦合。

### 8.4 本地 embedding 覆盖项

只有更换本地模型或做离线部署时，才需要额外写入：

```env
MEMORY_EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
MEMORY_EMBEDDING_DIM=1024
MEMORY_EMBEDDING_CACHE_DIR=/data/memory/models
MEMORY_EMBEDDING_LOCAL_FILES_ONLY=true
MEMORY_EMBEDDING_MAX_CONCURRENCY=8
MEMORY_EMBEDDING_BATCH_SIZE=16
```

本地模型覆盖后必须保证模型输出维度和 `MEMORY_EMBEDDING_DIM` 一致。

启动命令不接收 database-url 或 port 参数，非容器启动通过 `INSIGHT_MEMORY_ENV` 指向 `.env`，并结合
`insight_memory/config.py` 默认值读取配置。

whl 包前台启动命令：

```bash
insight_memory
```

源码前台启动命令：

```bash
cd memory
python run.py
```

## 9. 健康检查

`/health` 返回结构：

```json
{
  "status": "ok",
  "db": "ok",
  "retrieval": "ok",
  "llm": "configured",
  "entities": 0,
  "memories": 0,
  "observations": 0,
  "index_status": "ready",
  "embedding_provider": "local",
  "embedding_model": "BAAI/bge-base-zh-v1.5",
  "embedding_dim": 768,
  "projection_version": "v1"
}
```

`status=ok` 条件：

- 数据库连接正常。
- pgvector extension 可用。
- PGVectorStore 检索索引表可读。
- LLM 已配置。

`index_status` 取值：

| 状态 | 说明 | 顶层 `status` |
| --- | --- | --- |
| `ready` | 索引版本与当前配置一致。 | `ok` |
| `stale` | 索引版本缺失或与当前配置不一致，后台重建任务已创建或等待执行。 | `ok` |
| `reindexing` | 内部重建任务正在重建 pgvector 表。 | `ok` |
| `failed` | 最近一次内部重建失败，需要人工排查 embedding、数据库或任务日志。 | `error` |

embedding 后端在服务启动时由 `embedding_service.prewarm()` 校验。

## 10. Reindex 与一致性

reindex 用于从业务真相表刷新检索派生数据。索引维护是系统内部能力，不对业务调用方暴露通用重建 API。

PGVectorStore 只是一份可删除、可重建的检索索引，不是记忆系统的 truth。truth 始终来自：

- `memory_entities`
- `memory_memories`
- 必要时补充读取 `memory_observations` 和 `memory_edges` 做审计或校验

服务启动时不执行全量 reindex，也不自动扫描全库补齐缺失索引。这样可以避免启动一次就消耗大量内存、CPU 和 embedding 成本。

### 10.1 索引版本状态

索引版本不写入每条 vector node。版本状态集中保存在服务级状态记录中，逻辑键固定为：

```text
memory_vector_index_version
```

推荐存储结构：

```text
state_key       string primary key
state_json      json
created_at      float timestamp
updated_at      float timestamp
```

`state_json` 内容：

| 字段 | 作用 |
| --- | --- |
| `embedding_provider` | 索引使用的 embedding provider。 |
| `embedding_model` | 索引使用的 embedding 模型。 |
| `embedding_dim` | 索引使用的 embedding 维度。 |
| `projection_version` | text projection 规则版本，投影逻辑变化时递增。 |
| `indexed_at` | 最近一次成功内部全量重建完成时间。 |
| `status` | `ready`、`stale`、`reindexing` 或 `failed`。 |
| `last_error` | 最近一次内部重建失败原因，成功后清空。 |

启动检查流程：

```mermaid
flowchart TD
    startup["service startup"]
    initdb["init database"]
    prewarm["embedding prewarm"]
    load_state["load vector index version state"]
    compare["compare provider / model / dim / projection"]
    ready["status ready<br/>continue startup"]
    stale["mark stale"]
    enqueue["enqueue rebuild_retrieval_index task"]
    worker["background worker rebuilds index"]

    startup --> initdb
    initdb --> prewarm
    prewarm --> load_state
    load_state --> compare
    compare -->|"match and ready"| ready
    compare -->|"missing / changed / failed"| stale
    stale --> enqueue
    enqueue --> worker
```

触发内部重建的条件：

- `MEMORY_EMBEDDING_PROVIDER` 变化。
- `MEMORY_EMBEDDING_MODEL` 变化。
- `MEMORY_EMBEDDING_DIM` 变化。
- `MEMORY_PROJECTION_VERSION` 变化。
- 索引版本状态缺失。
- 上次状态为 `failed`，并且服务重新启动后需要再次尝试。

以上任一条件触发后，都重建 pgvector 表。系统不复用旧 embedding，也不尝试把旧向量转换成新向量。

### 10.2 内部全量重建

内部重建由后台任务执行，任务类型固定为：

```text
rebuild_retrieval_index
```

任务 payload 可以为空，dedupe key 固定为：

```text
rebuild_retrieval_index:global
```

执行约束：

- 同一时间只允许一个 `rebuild_retrieval_index` 任务运行。
- 与运行中的 `reindex_memory` 通过全局 rebuild 调度隔离，避免重建表时发生并发写入。
- 不提供外部 reindex API；业务调用方不需要感知索引重建入口。

重建流程：

```mermaid
flowchart TD
    task["rebuild_retrieval_index task"]
    mark_reindexing["mark index status = reindexing"]
    reset_table["drop and recreate pgvector table"]
    scan_entities["batch scan memory_entities"]
    write_entities["refresh_entities"]
    scan_memories["batch scan memory_memories"]
    load_entities["batch load related entities"]
    write_memories["refresh_memories"]
    reconcile["reconcile orphan vector nodes"]
    ready["write version status = ready"]
    failed["write version status = failed<br/>last_error"]

    task --> mark_reindexing
    mark_reindexing --> reset_table
    reset_table --> scan_entities
    scan_entities --> write_entities
    write_entities --> scan_memories
    scan_memories --> load_entities
    load_entities --> write_memories
    write_memories --> reconcile
    reconcile --> ready
    mark_reindexing -. exception .-> failed
    reset_table -. exception .-> failed
    write_entities -. exception .-> failed
    write_memories -. exception .-> failed
```

表重建策略：

- 为了降低复杂度，provider、model、dim、projection 任一变化都统一 drop/recreate pgvector 表。
- 重建期间业务真相表不受影响。
- 重建期间 recall 仍可执行；如果 pgvector 表刚被重建且尚未写完，召回质量可能短暂下降。
- 查询时补索引仍保留，用于覆盖后台任务尚未处理到的候选集合。

### 10.3 增量刷新

索引一致性由三类维护流程保证。

后台增量 reindex：

1. ingest 创建或更新 memory 后，创建 `reindex_memory` 后台任务。
2. `reindex_memory_graph` 按 `entity_key` 或 `memory_ids` 读取业务表。
3. 调用 `refresh_entities` / `refresh_memories` 生成 TextNode。
4. 先生成并校验 embedding。
5. 删除同 `ref_doc_id` 的旧 node。
6. 写入新的 pgvector node。

查询时补索引：

1. `entity_candidates()` / `memory_candidates()` 接收业务层候选集合。
2. 读取这些候选的 pgvector node。
3. 比较 node metadata 中的 `updated_at` 与业务表行 `updated_at`。
4. 只对缺失或过期的候选执行刷新。

孤儿清理：

- 当前没有对外暴露 `/admin/reconcile-index`。
- 单条 entity / memory 删除时，通过 `delete_ref_doc_ids` 删除对应 `ref_doc_id`。
- 模型、维度或投影版本变化时，内部 `rebuild_retrieval_index` 会先清空 PGVectorStore，再从业务真相表批量重建。
- 因此检索索引的完整恢复路径是内部 rebuild，不是业务调用方手工 reconcile。

### 10.4 稳定 id 规则

重建依赖稳定 `ref_doc_id`。所有 node 必须使用同一套 id 规则：

```text
entity node id = entity:{memory_space}:{entity_key}
memory node id = memory:{memory_space}:{memory_id}
```

同一个 `ref_doc_id` 在重建前后表示同一条 entity 或 memory。这样单条更新可以幂等地替换旧 node。

## 11. 测试计划

### 11.1 单元测试

- mock local embedding provider，验证 provider 选择、cache dir、local_files_only。
- mock online embedding provider，验证 api key、base url、timeout。
- 验证 entity/memory 投影文本稳定。
- 验证 RRF 融合不依赖 BM25 和 vector 的原始分数尺度。
- 使用 mock pgvector store 验证 upsert、delete、reconcile 行为。
- 验证启动流程不会调用全量 bootstrap，也不会读取全部 entities/memories。
- 验证索引版本状态一致时不创建内部重建任务。
- 验证索引版本缺失或 provider/model/dim/projection 变化时创建 `rebuild_retrieval_index` 任务。
- 验证内部重建成功后写入 `ready`，失败后写入 `failed` 和 `last_error`。
- 验证 `MEMORY_VECTOR_RECALL_OVERSAMPLE` 控制宽召回数量。
- 验证 vector 低分候选和 RRF 低分候选会被过滤。
- 验证 BM25 和 vector 召回并发执行。
- 验证 `MEMORY_VECTOR_TABLE` 不再从 `.env` 或 Settings 暴露。

### 11.2 PostgreSQL 集成测试

- `CREATE EXTENSION IF NOT EXISTS vector` 成功。
- LlamaIndex `PGVectorStore` 能写入和检索 node。
- ref_doc_id 参数化过滤能限制候选集合。
- local provider mock 和 online provider mock 都能完成索引写入。

### 11.3 手工验收

- Docker Compose 启动 PostgreSQL/pgvector。
- whl 包 `python -m build --wheel` 和 `pip install dist/*.whl` 成功。
- 源码 `pip install -r requirements.txt` 成功。
- 编辑 `.env` 并设置 `INSIGHT_MEMORY_ENV` 后，`insight_memory` 或 `python run.py` 前台启动。
- `/health` 返回 `db=ok`、`retrieval=ok`、`llm=configured`。
- `/health` 返回 `index_status`、embedding 配置和 projection version。
- 写入 memory 后业务表和 LlamaIndex pgvector 表都有记录。
- 使用字面不同但语义接近的问题可以召回目标 memory。
- 重启服务不会在启动时全量扫描业务表。
- 修改 embedding model 后重启服务，会创建内部重建任务，并在后台完成 pgvector 表重建。

## 12. 兼容性说明

第一版迁移不保留旧 `docstore.json`。原因是旧文件只是检索派生数据。

升级后如果旧环境已有大量 memory，且 pgvector 表为空，首次查询或后台任务会按候选集合逐步补齐，不会在启动时全量构建。

模型切换或索引损坏后的完整索引恢复能力由内部 `rebuild_retrieval_index` 后台任务负责。业务调用方不需要调用外部重建接口。
