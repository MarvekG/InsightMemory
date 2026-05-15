# System Overview

[Back to README](../README.md)

This document covers the core model, service structure, and repository layout behind InsightMemory.

## Core Concepts

- `memory_scope`: the outer isolation boundary, suitable for tenants, users, experiments, or test runs.
- `entity`: the stable subject a memory belongs to, meaning who this memory is about. It is identified by an
  opaque `entity_key`.
- `memory`: a stable fact, state, rule, conclusion, or historical record belonging to an entity.
- `observation`: append-only raw input evidence. It is not treated as mutable truth.
- `edge`: a relationship between memories, used to express updates, support, conflicts, derivations,
  dependencies, or related context.
- `memory graph`: the associated-memory graph formed by entities, memories, observations, and edges.
- Graph construction has two layers: first build a small graph inside a single entity, then expand across
  entities when useful for associated-memory queries.

For deeper modeling details, see the current [design notes](./04-memory-design.md).

## Features

- Uses an LLM to automatically extract entities from input and determine which stable subject each memory
  belongs to.
- Supports entity resolution for same-name but different subjects, preventing projects, people, documents, and
  rules from polluting each other.
- Automatically extracts candidate memories and determines whether new memories update, extend, conflict with,
  derive from, support, or coexist with existing memories.
- Automatically builds memory-memory edges, using a graph to represent context, causality, dependencies, and
  conflicts between memories.
- Supports associated-memory queries: recall is not based only on text similarity, but can also expand useful
  memory edges.
- Supports additive refresh: new details do not overwrite existing current rules or current state.
- Supports historical memories and current memories existing side by side.
- Supports cross-entity relationship graphs for why or how queries.
- Returns observation citations with recall results for audit and traceability.
- Background tasks support reindexing, entity profile refresh, memory edge repair, lifecycle processing, and
  merge candidate detection.
- Includes a generalization evaluation matrix covering long-term evolution, cross-format documents, long
  history, multi-entity documents, financial or market scenarios, high concurrency, and open-domain inputs.

## Architecture

```text
Client
  |
  | HTTP
  v
FastAPI service
  |
  +-- Ingest graph
  |     - Validate input
  |     - Extract identity profile and candidate memories
  |     - Resolve to an existing entity or create a new entity
  |     - Create, refresh, replace, or preserve memories
  |     - Enqueue background tasks
  |
  +-- Recall graph
  |     - Validate query
  |     - Resolve target entity
  |     - Retrieve memories and evidence
  |     - Expand useful memory edges
  |     - Generate grounded answer
  |
  +-- Background worker
        - Rebuild retrieval indexes
        - Refresh entity profiles
        - Repair memory edges
        - Detect merge candidates
        - Advance lifecycle state

Storage
  |
  +-- PostgreSQL / pgvector
  +-- Local retrieval docstore
```

## Directory Structure

```text
memory/
  insight_memory/
    api/        HTTP schemas and routes
    evals/      LLM evaluation helpers
    graph/      ingest, recall, repair, reindex, merge, and lifecycle workflows
    index/      retrieval index integration
    services/   service-level orchestration
    storage/    database models and repositories
    tasks/      persistent background task runtime
    workers/    background workers, prompts, and LLM providers
  docs/         design documents
  evals/        evaluation cases, matrices, and reports
  evals/scripts/ evaluation CLI scripts
  tests/        pytest tests
```
