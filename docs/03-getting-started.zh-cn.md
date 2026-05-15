# 快速开始

[返回 README](../README.zh-cn.md)

这份文档只保留实操路径：如何启动服务、写入和召回 memory，以及如何运行评估矩阵。

## 部署

服务支持四种部署方式。推荐顺序是：镜像版 Docker Compose、本地构建 Docker Compose、`pip install InsightMemory`、
源码安装。所有方式都直接从 `.env` 读取配置，不需要再维护一套 uvicorn 命令行参数。

### 方式一：镜像版 Docker Compose（首推）

这是最推荐的部署方式，使用 [docker-compose.image.yml](../docker-compose.image.yml) 启动服务。Compose 会拉取
`ghcr.io/marvekw/insightmemory:latest`，并同时启动专用的 PostgreSQL/pgvector 数据库：

- `memory-postgres`：PostgreSQL 17 + pgvector，宿主机端口 `5433`。
- `memory`：FastAPI memory 服务，宿主机端口 `8010`。

创建运行时环境文件：

```bash
cd memory
cp .env.example .env
```

编辑 `.env`，大多数情况下只需要配置 LLM 相关变量：

```bash
MEMORY_LLM_PROVIDER=deepseek
MEMORY_LLM_MODEL=deepseek-chat
MEMORY_LLM_API_KEY=your_api_key
MEMORY_LLM_BASE_URL=https://api.deepseek.com
```

使用 Docker Compose 时，默认数据库地址已经指向 `memory-postgres`，不需要在 `.env` 里重复配置。Compose 会通过
`env_file` 读取当前目录下的 `.env` 并注入到 memory 容器环境中，不会把 `.env` 挂载进容器文件系统。

启动服务：

```bash
docker compose -f docker-compose.image.yml up -d
```

### 方式二：本地构建 Docker Compose（次推）

如果需要基于当前源码、Dockerfile 或依赖重新构建镜像，使用 [docker-compose.yml](../docker-compose.yml)。
它的服务拓扑和镜像版 Compose 一致，但 memory 镜像在本机 build。

```bash
cd memory
cp .env.example .env
docker compose up -d --build
```

### 方式三：pip 安装（再次）

如果你已经有 PostgreSQL 并启用了 `pgvector` 扩展，可以直接安装发布包。通过 pip 或源码启动时，需要用
`INSIGHT_MEMORY_ENV` 显式指定 `.env` 路径；日志、默认本地 embedding cache 等运行时文件固定放在
`$HOME/.insight_memory/`。

```bash
python -m pip install InsightMemory
mkdir -p "$HOME/.insight_memory/logs"
```

创建 `$HOME/.insight_memory/.env`，至少配置：

```bash
MEMORY_DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory
MEMORY_SERVICE_PORT=8010
MEMORY_LLM_PROVIDER=deepseek
MEMORY_LLM_MODEL=deepseek-chat
MEMORY_LLM_API_KEY=your_api_key
MEMORY_LLM_BASE_URL=https://api.deepseek.com
```

启动服务：

```bash
export INSIGHT_MEMORY_ENV="$HOME/.insight_memory/.env"
insight_memory
```

后台运行：

```bash
nohup insight_memory > "$HOME/.insight_memory/logs/memory.log" 2>&1 &
```

### 方式四：源码安装（最次）

源码安装主要用于开发、调试和临时验证代码改动。它同样要求 PostgreSQL 已安装并启用 `pgvector` 扩展，并通过
`INSIGHT_MEMORY_ENV=/absolute/path/to/.env` 指定配置文件。

```bash
cd memory
cp .env.example .env
export INSIGHT_MEMORY_ENV="$PWD/.env"
python -m pip install -r requirements.txt
python run.py
```

源码开发需要自动 reload 时，在 `.env` 中设置 `MEMORY_APP_RELOAD=true`。

### 验证健康状态

```bash
curl http://127.0.0.1:8010/health
```

返回结构类似：

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
  "projection_version": "v1",
  "embedding_prewarm_status": "ready",
  "embedding_prewarm_error": null,
  "embedding_prewarm_attempt": 1,
  "embedding_prewarm_max_attempts": 5
}
```

如果使用本地向量模型（`embedding_provider=local`），首次启动可能需要在后台下载并预热模型。服务本身会先启动，
但写入、召回和评测应等 `/health` 中 `embedding_prewarm_status` 变为 `ready` 后再执行；下载或加载失败时该字段会变为
`failed`，错误信息会出现在 `embedding_prewarm_error`。

### 停止或重建

以下命令以首推的镜像版 Compose 为例；如果使用本地构建 Compose，把 `-f docker-compose.image.yml` 去掉即可。

停止容器但保留数据库数据：

```bash
docker compose -f docker-compose.image.yml stop memory memory-postgres
```

移除容器但保留 named volume：

```bash
docker compose -f docker-compose.image.yml down
```

使用本地构建 Compose 时，代码或依赖变更后，重新构建并启动 memory 服务：

```bash
docker compose up -d --build memory
```

## HTTP API

当前 API 没有单独的 `entity` 字段。自然语言内容本身必须明确说明“这条记忆属于谁”，召回查询里也要显式带上目标 entity。

### 健康检查

```bash
curl http://127.0.0.1:8010/health
```

### 写入 memory

```bash
curl -X POST http://127.0.0.1:8010/memory/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "context": "对于 Atlas rollout 这个项目，当前主阻塞是数据库迁移失败，需要先回滚。"
  }'
```

示例响应：

```json
{
  "status": "accepted",
  "observation_id": "obs_...",
  "affected_entity_keys": ["ent_..."],
  "affected_memory_ids": ["mem_..."],
  "error_code": null
}
```

### 召回 memory

```bash
curl -X POST http://127.0.0.1:8010/memory/recall \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "query": "对于 Atlas rollout 这个项目，当前主阻塞是什么？"
  }'
```

示例响应：

```json
{
  "results": [
    {
      "status": "ok",
      "answer": "Atlas rollout 当前主阻塞是数据库迁移失败，需要先回滚。",
      "citations": [
        {
          "memory_id": "mem_...",
          "observation_id": "obs_...",
          "summary": "...",
          "excerpt": "...",
          "source_memory_ids": ["mem_..."]
        }
      ],
      "uncertainties": [],
      "error_code": null
    }
  ]
}
```

多主体查询时，`results` 会返回多条相互独立的答案。

## 评估

运行单元测试：

```bash
PYTHONPATH=memory pytest memory/tests -q
```

对运行中的 memory 服务执行默认评估矩阵：

```bash
PYTHONPATH=memory python memory/evals/scripts/eval_memory_matrix.py \
  --base-url http://127.0.0.1:8010 \
  --manifest memory/evals/matrix/default_v1.json \
  --run-id local_default_matrix \
  --max-concurrency 12 \
  --timeout-seconds 240 \
  --settle-timeout-seconds 45 \
  --database-url postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory
```

当前评估覆盖同名主体拆分、规则演进、长历史记录、多主体文档、跨格式输入、高并发写入、开放域、金融/市场记忆，
以及真实生活、真实职场协作和代码开发场景。
