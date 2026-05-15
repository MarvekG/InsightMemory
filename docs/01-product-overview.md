# Product Overview

[Back to README](../README.md)

This document explains what InsightMemory is for, why it is different from common memory approaches, and where
it fits in AI applications.

## Project Highlights

If you are not looking for yet another RAG component that only retrieves similar text, but for a long-term
memory layer that can make AI applications understand you better over time, accumulate context as they run,
and answer with stronger grounding, InsightMemory's core value can be summarized like this:

- **It remembers entities, not just text**: instead of throwing everything into one shared text pool, it first
  decides who a piece of information belongs to, then builds memory around that stable subject.
- **It returns context, not fragments**: it does not only bring back similar passages; it can bring back
  relations, updates, conflicts, and dependencies, so the answer feels more like reasoning than retrieval
  stitching.
- **It preserves evolution, not only summaries**: current state, historical state, change rationale, and
  supporting evidence can coexist, so the system is less likely to become thinner and less accurate after many
  rounds of refresh.
- **It is built for real-world complexity, not demo-only scenarios**: same-name entities, multi-entity
  documents, long-running evolution, cross-document references, and why or how questions are the actual
  problems AI products run into.
- **It aims for explainable answers, not just plausible answers**: responses can lead back to original
  evidence, historical records, and relationship chains, which makes the system more suitable for audit,
  debugging, and enterprise AI use cases.
- **It behaves more like AI's persistent cognition layer than an external cache**: the model handles
  understanding, while the memory layer handles accumulation, maintenance, and recall, so the AI can keep
  learning from context instead of being smart for only one turn.

Put more directly: InsightMemory's advantage is not simply that it remembers more, but that it remembers more
accurately, connects memory better, explains answers more clearly, and stays useful longer.

## Why It Fits The AI Era

As AI products become more competitive, the gap is less about whether a model can give a good first answer,
and more about three things:

- **Can it keep long-term user and task context alive?** Not just the last turn, but persistent rules,
  preferences, conclusions, relationships, and change history.
- **Can it explain why an answer is correct?** Not just output a conclusion, but bring back citations,
  evidence, conflicts, and the chain of related memories behind it.
- **Can it survive real-world complexity?** Multi-entity inputs, same-name entities, long-running evolution,
  cross-document references, and cross-format data are what real AI systems actually see.

If large models are the brain of an AI product, a long-term memory system is closer to its persistent
cognition layer. Without it, many agents only look clever for a moment. With it, the system has a real chance
to become something accumulative, reusable, and compounding over time.

## Problem

Many LLM applications cannot rely only on chunking text and running vector search. If a system can only
retrieve text that looks similar, it behaves more like one-off search than a real memory system.

The hard part of long-term memory is not whether the system can find similar text. The hard part is whether it
can continuously understand inputs, organize memories, maintain relationships, and follow those relationships
to retrieve the information that actually matters.

A useful memory system must answer these questions:

- Which stable subject does an input belong to?
- Which `entity` should a new memory attach to, instead of being mixed into a global text pool?
- Does a new fact update an old fact, extend it, conflict with it, or coexist with it?
- Do two memories support, depend on, conflict with, derive from, or relate to each other?
- How should memories for different entities with the same name stay isolated?
- How should current-state questions and historical questions return different answers?
- How can recall follow the `memory graph` instead of returning only semantically similar text?
- How can external constraints from other entities participate in why or how queries without polluting entity
  boundaries?
- How can every answer keep its original evidence and citations?

InsightMemory packages these capabilities as an independent HTTP service. The LLM handles semantic
understanding, entity resolution, memory extraction, and relation detection. PostgreSQL, pgvector, and
retrieval indexes handle persistence, recall, and auditable evidence chains.

## Advantages Over Common Memory Approaches

Many existing memory systems reduce memory to a vector database, a summary cache, or a key-value profile.
InsightMemory's core difference is that it uses an LLM to understand and organize memory while modeling entity
identity, durable memory, evidence, and the memory graph separately.

### Core Strengths

- **Automatically determines who a memory belongs to**: inputs can be conversations, notes, reports, logs, or
  mixed documents. The system extracts stable subjects and attaches memories to the correct entity.
- **Builds structured long-term memory automatically**: raw observations are converted into memories that can be
  updated, coexist, and remain traceable, instead of treating every source text segment as an equal chunk.
- **Builds memory relationships automatically**: the system identifies support, update, conflict, derivation,
  dependency, and related-context relationships between memories to form a maintainable memory graph.
- **Supports associated-memory queries**: recall can follow memory edges, not only semantic similarity, to
  answer why or how, current vs historical, dependency source, and conflict-cause questions.
- **Preserves evidence chains**: raw observations are saved append-only, and answers can return citations for
  auditing, debugging, and replay.
- **Designed for open-domain generalization**: it favors a general entity or memory or edge model over
  hard-coded schemas or keyword rules for a single scenario.

### Compared With Pure Vector Memory

- It does not only retrieve similar text. It first resolves the stable subject, then answers from that
  subject's memories and associated edges.
- Entities with the same name can be separated, so projects, documents, rules, and reports with the same name
  are not mixed by default.
- New input can be judged as an update, extension, coexistence, or conflict instead of being appended as
  another chunk.
- Associated memories can participate in recall. For example, blockers, upstream dependencies, external
  checklists, and historical decisions can enter the same answer through their relationships.
- Answers can include observation citations for tracing back to the original evidence.

### Compared With Summary-Based Long-Term Memory

- Observations are append-only, so original evidence is not overwritten.
- Memory refresh preserves old details and merges new details, preventing additive rules from overwriting
  current rules.
- Historical records can coexist as independent memories instead of being swallowed by the current state.
- Queries about what is true now and what used to be true can follow different recall paths.
- Queries about why it changed can follow update, support, or conflict relationships to find related memories.

### Compared With Key-Value or Slot Memory

- It does not depend heavily on predefined `memory_type` values or fixed slots.
- It can handle open-domain subjects such as projects, people, documents, rules, market views, and long
  historical records.
- The LLM handles semantic understanding, while the database stores identity, memory, evidence, relations, and
  history.
- For new domains, it reuses the general entity or memory or edge model instead of requiring a new
  domain-specific schema.

### Compared With Single-Turn Agent Memory

- `memory_scope` provides explicit isolation, so evaluations, users, and tenants do not pollute each other.
- Background tasks asynchronously maintain indexes, relationship graphs, entity profiles, and lifecycle state
  instead of pushing all work into foreground requests.
- The relationship graph is based on memory-memory edges, making it possible to explain why a blocker relates
  to an external checklist, handbook, or upstream service.
- The evaluation matrix covers high concurrency, cross-format inputs, open-domain inputs, long documents, and
  financial scenarios, with the goal of testing generalization rather than a single demo.

## Suitable Use Cases

- LLM applications that need to remember users, projects, documents, rules, analysis conclusions, or runtime
  state over the long term.
- Knowledge management systems that need to automatically determine who a memory belongs to.
- Enterprise knowledge bases, agent memory layers, or research record systems that need to separate same-name
  but different subjects.
- Workflows that need to answer current vs historical questions.
- Systems that need to answer why or how, impact scope, dependency source, and conflict-cause questions through
  associated memories.
- Enterprise applications that need original evidence citations for audit and debugging.
- Systems that need continuously evolving open-domain memory instead of one-time RAG retrieval.

## Development Principles

- Prefer entity-centered memory over raw text chunk retrieval.
- Preserve original evidence and citations.
- Avoid keyword matching in memory logic.
- Do not write custom logic only to pass test cases.
- Prompt examples must be different from test samples.
- Additive refresh should preserve old details and add new details.
