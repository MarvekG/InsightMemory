# Memory Read and Write Best Practices

[Back to README](../README.md)

This document describes how callers should write and read memories with the current `memory` design, including
asynchronous ingest, same-name disambiguation, historical evolution, and evidence citations.

For lower-level design details, see [Memory Design](./04-memory-design.md) and
[LlamaIndex Retrieval Design](./05-llamaindex-retrieval-design.zh-cn.md).

## 1. Core Principle

`memory` is not a vector chunk store. The current design is centered on `entity`:

- `entity` means who a memory belongs to. It is identified by a system-assigned opaque `entity_key`.
- `memory` means a stable fact, state, rule, conclusion, or historical record about one entity.
- `observation` stores the original evidence. It is append-only and is not the mutable source of truth.
- `edge` connects memories to observations and to other memories through source, update, support, conflict, or
  relevance relationships.

The short version is:

> When writing, make it clear who the statement is about and what happened. When reading, make it clear who you
> are asking about, whether you want current or historical information, and whether you want a fact or an
> explanation.

## 2. Write Best Practices

### 2.1 Name the Subject Explicitly

The current ingest API has no separate `entity` field. The subject must appear in the natural-language `context`.
Do not rely on prior conversation, pronouns, or caller-side session state.

Recommended:

```text
For the Atlas rollout project, the current main blocker is the database migration failure, and the team needs to roll back before moving forward.
```

Not recommended:

```text
It is currently blocked by the database migration failure.
```

The ingest hot path runs the extractor first. If it cannot extract a stable `identity_profile`, the whole write is
rejected. No observation or memory is created.

### 2.2 Use Stable Subjects, Not One-Off Record Markers

A subject should be something that can be referred to again later, such as a project, system, document, workflow,
team, market object, review, or named artifact.

Recommended:

```text
Cobalt launch review round 1 supported continuing with the initial launch slot.
```

The stable subject is `Cobalt launch review`. `round 1` should remain in the memory content or record marker. It
should not become a separate subject identity.

Not recommended:

```text
Round 1 is the subject and it supported continuing with the initial launch slot.
```

### 2.3 Use Role Words to Separate Same-Name Subjects

If several objects share the same name, keep the role word that separates their identities.

Recommended:

```text
Atlas release project is currently blocked by the database migration failure.
Atlas knowledge document is currently missing the rollback section.
```

Not recommended:

```text
Atlas is currently blocked by the database migration failure.
Atlas is currently missing the rollback section.
```

The system allows different entities to share the same surface form. Words like `release project`, `knowledge
document`, `rollout`, `checklist`, `policy`, `handbook`, and `service` are often identity qualifiers, not cosmetic
phrasing.

### 2.4 Put Facts in Memory Content, Not Identity

`identity_profile` describes who the subject is. It must not carry the current state, owner, blocker, rule body, or
conclusion. Callers do not need to construct `identity_profile` directly, but the input text should not disguise a
fact as part of the subject name.

Recommended:

```text
Gateway policy currently requires every production release to include approval-chain documentation before execution.
```

Not recommended:

```text
The subject is Gateway policy currently requires approval-chain documentation.
```

The first version lets the system treat `Gateway policy` as the identity and the requirement as memory content. The
second can pollute the identity.

### 2.5 Keep Each Input as a Clear Evidence Unit

`observation` stores the original input and is connected to memories with `derived_from` edges. A single `context`
should represent one clear source or one coherent segment.

Recommended:

- Write one meeting conclusion as one context.
- If one email contains several clearly named subjects, it can be written as one context; the system can extract
  multiple drafts and candidates.
- If one long report revolves around one subject and one main conclusion, keep enough context and write it as one
  detailed memory.

Not recommended:

- Joining unrelated snippets from different sources, times, and subjects without boundaries.
- Writing only a vague summary and dropping key evidence terms such as blockers, requirements, dates, document
  names, or approval items.

### 2.6 State Current, Historical, and Additive Changes Explicitly

The resolver decides whether a new memory should `create`, `refresh`, `replace`, `coexist`, or mark an existing
memory `stale`. Callers should make temporal and evolutionary relationships explicit in the text.

Recommended:

```text
Ashgrove handbook previously allowed teams to file fallback schedules within 24 hours after the shift.
Ashgrove handbook currently requires every fallback schedule change to be approved by the incident lead first.
Ashgrove handbook latest supplement: every approval record must also be attached to the change packet.
```

This lets the system keep the historical rule, make the current rule the active head, and refresh the current memory
with the additive requirement.

Not recommended:

```text
Ashgrove handbook requires approval.
Ashgrove handbook also needs a change packet.
```

Without words like `previously`, `currently`, or `latest supplement`, the system will still try to infer the
relationship, but current and historical boundaries become less clear.

### 2.7 Do Not Create Subjects for Missing Items by Default

If a named item is only a missing reason, attachment, prerequisite, or evidence item inside another subject's
statement, keep it inside that subject's memory. Do not turn it into a separate subject by default.

Recommended:

```text
Harborlane rollout cannot enter cutover because the quay memo is still incomplete.
```

Create a separate subject only when that item has its own independent state, owner, rule, or lifecycle:

```text
Harborlane quay memo is currently owned by Ivo Tan.
```

### 2.8 Treat Ingest as Asynchronous

The current `/memory/ingest` path accepts a write and continues processing in the background:

1. The hot path extracts identity drafts.
2. If the gate passes, it creates an observation.
3. It creates a `continue_ingest` background task.
4. The background task performs entity resolution, memory resolution, edge writing, and index refresh.

Do not assume that an `accepted` response means the memory is immediately recallable. If the same `memory_scope` has
pending or running `continue_ingest` tasks, `recall` returns:

```json
{
  "status": "not_ready",
  "error_code": "memory_scope_not_ready",
  "uncertainties": ["continue_ingest_pending"]
}
```

Recommended handling:

- If you need to read immediately after writing, retry `not_ready` with short backoff.
- After bulk import, wait for background tasks to drain before running evaluation or exposing queries to users.
- When debugging, inspect task state, observation state, and LLM run audits instead of relying only on the ingest
  HTTP response.

## 3. Read Best Practices

### 3.1 Include the Target Subject in the Query

Recall first runs a query planner, extracts query identity drafts, and resolves them to entities. The query should
explicitly name the target entity.

Recommended:

```text
What is the current main blocker for the Atlas release project?
```

Not recommended:

```text
What is the current main blocker?
```

If the query cannot be resolved to a stable subject, the system returns `cannot_resolve_query_identity`.

### 3.2 Add Identity Qualifiers for Same-Name Subjects

If the same scope may contain `Atlas release project` and `Atlas knowledge document`, do not query only `Atlas`.

Recommended:

```text
What is the current main blocker for the Atlas release project?
What is currently missing from the Atlas knowledge document?
```

Not recommended:

```text
What happened to Atlas?
```

If multiple candidate entities remain plausible, the system returns `ambiguous_query_identity` and includes the
ambiguous candidates in `uncertainties`.

### 3.3 Make Time Intent Explicit

The query planner recognizes `current`, `latest`, `history`, or `unspecified`. Time intent affects seed memory
filtering and `updates` edge expansion.

Common patterns:

- Current state: `What is the current main blocker for Cedar review?`
- Latest conclusion: `What is the latest decision for Cedar review?`
- Historical evolution: `What blocked Cedar review before, and what is blocking it now?`
- Older rule: `What did Ashgrove handbook previously allow?`

If the question asks about both past and present, say both explicitly. The system will use the history path to expand
the evolution chain.

### 3.4 Preserve Concrete Terms in Why/How Queries

Recall does more than similarity search. It finds seed memories, expands through `updates`, `supports`,
`contradicts`, and `related_to` edges, and may add cross-entity context.

Recommended:

```text
Why can Billing service not switch to the new template yet?
Besides the current blocker, what external context should Nimbus rollout pay attention to?
Why did Topaz transfer review converge from historical disagreement to the current conclusion?
```

These questions preserve useful retrieval signals such as blockers, requirements, missing items, and external rules.

### 3.5 Handle Multi-Subject Queries as Multi-Result Responses

Multi-subject queries can be split into multiple query identity drafts. The response may contain multiple `results`.
Callers should treat each result as an independent answer instead of assuming only the first result matters.

Recommended:

```text
What is the current main blocker for the Atlas release project? What is currently missing from the Atlas knowledge document?
```

The response can contain one result for the release project and one result for the knowledge document.

### 3.6 Always Read Citations and Uncertainties

`answer` is the user-facing response. `citations` and `uncertainties` are essential for trust, UI evidence display,
and debugging.

Suggested handling:

- Show citation summaries or excerpts in the UI.
- Treat `no_relevant_memory_found` as a real no-result state, not as a successful answer.
- For `ambiguous_query_identity`, ask the user to add a subject qualifier.
- For `contradicting_memory:*`, show that conflicting evidence exists.
- For `not_ready`, retry instead of displaying it as a final no-result answer.

## 4. Boundaries Callers Should Not Bypass

### 4.1 Do Not Write Business Tables Directly

Directly inserting into `memory_memories` bypasses the extractor, linker, resolver, versions, edges, profile refresh,
and retrieval index refresh. Recall quality will become unstable.

For historical import, prefer `/memory/ingest` or reuse the ingest graph. If an offline migration is unavoidable,
rebuild the retrieval index and preserve source observations, versions, and edges.

### 4.2 Do Not Treat `entity_key` as a Business ID

`entity_key` is a system-assigned opaque id. Callers should not construct it, guess it, display it as the business
name, or reuse it across scopes. Put the natural-language subject in `context` and `query`; let the system perform
entity resolution.

### 4.3 Do Not Replace Semantic Judgment with Keyword Rules

The project explicitly avoids keyword matching and custom branches for memory generalization. Integration code should
also avoid rules like "if this phrase appears, write this memory type" or "if this phrase appears, query this entity."

When judgment is needed, improve input structure, prompts, schemas, evaluation cases, and LLM decision audits instead
of adding hard-coded semantic rules.

### 4.4 Watch Retrieval Index Health

The retrieval index is derived from the business truth tables. After entities or memories change, the system refreshes
the pgvector retrieval index. After changing the embedding model, embedding dimension, or projection version, the
index must be rebuilt.

Operational checks:

- `/health` fields: `index_status`, `embedding_provider`, `embedding_model`, and `embedding_dim`.
- For local embeddings, `embedding_prewarm_status` should be `ready`.
- Background tasks should not be stuck in `failed` or `dead_letter`.
- If business tables contain data but recall cannot find it, check whether the retrieval index is missing or stale.

## 5. Recommended Call Flow

Write flow:

1. Choose the correct `memory_scope`. Do not mix users, tenants, or experiments in one scope.
2. Shape the input into a `context` that includes a stable subject, key facts, time state, and source context.
3. Call `/memory/ingest`.
4. If the response is `rejected`, fix the subject according to `error_code`.
5. If the response is `accepted`, wait for background processing or handle `not_ready` on the recall side.

Read flow:

1. Name the target subject and identity qualifier in `query`.
2. State the time intent: current, latest, history, or evolution.
3. For why/how questions, keep concrete blocker, requirement, missing item, and external-context terms.
4. Call `/memory/recall`.
5. Process each item in `results`, including `answer`, `citations`, `uncertainties`, and `error_code`.

## 6. Quick Checklist

Before writing:

- Does `context` clearly say which stable subject owns the memory?
- Does a same-name subject include a role word or identity qualifier?
- Are current, historical, additive, and replacement relationships explicit?
- Are key evidence terms preserved?
- Is a missing item only a reason inside the main subject, rather than a mistaken separate subject?

Before reading:

- Does `query` explicitly name the target subject?
- Should a role word be added to avoid same-name ambiguity?
- Does the query ask for current, latest, historical, or evolutionary information?
- Is the caller prepared to handle `not_ready`, `ambiguous_query_identity`, and `no_relevant_memory_found`?
- Will the caller display or log citations and uncertainties?
