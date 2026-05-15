# Getting Started

[Back to README](../README.md)

This guide covers the practical path: running the service, writing and recalling memories, and running the
evaluation matrix.

## Deployment

The service supports four deployment options. The recommended order is: image-based Docker Compose,
local-build Docker Compose, `pip install InsightMemory`, and source install. All modes read configuration
directly from `.env`; there are no uvicorn command-line flags to keep in sync.

### Option 1: Image Docker Compose (Recommended)

This is the preferred deployment path. [docker-compose.image.yml](../docker-compose.image.yml) pulls
`ghcr.io/marvekw/insightmemory:latest` and starts a dedicated PostgreSQL/pgvector database:

- `memory-postgres`: PostgreSQL 17 + pgvector, exposed on host port `5433`.
- `memory`: FastAPI memory service, exposed on host port `8010`.

Create the runtime environment file:

```bash
cd memory
cp .env.example .env
```

Edit `.env`. In most cases, you only need to configure the LLM variables:

```bash
MEMORY_LLM_PROVIDER=deepseek
MEMORY_LLM_MODEL=deepseek-chat
MEMORY_LLM_API_KEY=your_api_key
MEMORY_LLM_BASE_URL=https://api.deepseek.com
```

When running with Docker Compose, the default database address already points to `memory-postgres`, so you do
not need to repeat it in `.env`. Compose reads the module-local `.env` through `env_file` and injects those
variables into the memory container environment; it does not mount `.env` into the container filesystem.

Start the service:

```bash
docker compose -f docker-compose.image.yml up -d
```

### Option 2: Local-Build Docker Compose

Use [docker-compose.yml](../docker-compose.yml) when you need to rebuild the image from the local source tree,
Dockerfile, or dependencies. The service topology is the same as the image-based Compose file, but the memory
image is built locally.

```bash
cd memory
cp .env.example .env
docker compose up -d --build
```

### Option 3: pip Install

If PostgreSQL is already available with the `pgvector` extension enabled, install the published Python package
directly. For pip and source startup, set `INSIGHT_MEMORY_ENV` to the `.env` file path explicitly. Runtime files
such as logs and the default local embedding cache are stored under `$HOME/.insight_memory/`.

```bash
python -m pip install InsightMemory
mkdir -p "$HOME/.insight_memory/logs"
```

Create `$HOME/.insight_memory/.env` with at least:

```bash
MEMORY_DATABASE_URL=postgresql+asyncpg://postgres:password@127.0.0.1:5433/memory
MEMORY_SERVICE_PORT=8010
MEMORY_LLM_PROVIDER=deepseek
MEMORY_LLM_MODEL=deepseek-chat
MEMORY_LLM_API_KEY=your_api_key
MEMORY_LLM_BASE_URL=https://api.deepseek.com
```

Start the service:

```bash
export INSIGHT_MEMORY_ENV="$HOME/.insight_memory/.env"
insight_memory
```

For a background process:

```bash
nohup insight_memory > "$HOME/.insight_memory/logs/memory.log" 2>&1 &
```

### Option 4: Source Install

Source install is mainly for development, debugging, or validating local code changes. It also requires
PostgreSQL with the `pgvector` extension enabled and uses `INSIGHT_MEMORY_ENV=/absolute/path/to/.env`.

```bash
cd memory
cp .env.example .env
export INSIGHT_MEMORY_ENV="$PWD/.env"
python -m pip install -r requirements.txt
python run.py
```

For source-tree development with auto-reload, set `MEMORY_APP_RELOAD=true` in `.env`.

### Verify Health

```bash
curl http://127.0.0.1:8010/health
```

Example response:

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

When using the local embedding provider (`embedding_provider=local`), the first startup may need to download
and prewarm the embedding model in the background. The HTTP service can start before that finishes, but ingest,
recall, and live evaluations should wait until `/health` reports `embedding_prewarm_status` as `ready`. If the
download or load fails, the status becomes `failed` and the error is shown in `embedding_prewarm_error`.

### Stop or Rebuild

The commands below use the recommended image-based Compose file. If you use local-build Compose, remove
`-f docker-compose.image.yml`.

Stop containers while keeping database data:

```bash
docker compose -f docker-compose.image.yml stop memory memory-postgres
```

Remove containers while keeping the named volume:

```bash
docker compose -f docker-compose.image.yml down
```

When using local-build Compose, rebuild and start the memory service after code or dependency changes:

```bash
docker compose up -d --build memory
```

## HTTP API

The current API does not take a separate `entity` field. The natural-language content itself must state who or
what the memory belongs to, and recall queries should also mention the target entity clearly.

### Health Check

```bash
curl http://127.0.0.1:8010/health
```

### Write a Memory

```bash
curl -X POST http://127.0.0.1:8010/memory/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "context": "For the Atlas rollout project, the blocker is a failed database migration and it needs rollback."
  }'
```

Example response:

```json
{
  "status": "accepted",
  "observation_id": "obs_...",
  "affected_entity_keys": ["ent_..."],
  "affected_memory_ids": ["mem_..."],
  "error_code": null
}
```

### Recall Memory

```bash
curl -X POST http://127.0.0.1:8010/memory/recall \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "query": "For the Atlas rollout project, what is the main current blocker?"
  }'
```

Example response:

```json
{
  "results": [
    {
      "status": "ok",
      "answer": "The Atlas rollout blocker is the failed database migration and it needs rollback.",
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

For multi-subject queries, `results` can contain multiple independent answer items.

## Evaluation

Run unit tests:

```bash
PYTHONPATH=memory pytest memory/tests -q
```

Run the default evaluation matrix against a running memory service:

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

Current evaluations cover same-name entity separation, rule evolution, long history, multi-entity documents,
cross-format inputs, high-concurrency writes, open-domain inputs, financial or market memory scenarios, and
real-world daily, work operations, and software development cases.
