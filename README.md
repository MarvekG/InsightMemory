# InsightMemory

English | [简体中文](https://github.com/MarvekW/InsightMemory/blob/main/README.zh-cn.md)

InsightMemory is an LLM-native long-term memory system that can think through, synthesize, and remember what it stores.

It does more than split text into chunks and put them into a vector database. It understands incoming
content, automatically determines who each memory belongs to, represented as an `entity`, turns scattered
inputs into durable structured `memory` records, builds support, update, conflict, derivation, and related
edges between memories, and supports associated-memory queries with evidence-backed answers.

In short: InsightMemory gives LLM applications an entity-centered, evolvable, traceable, association-aware
long-term memory layer.

> License note: this project is licensed under the MIT License. See [LICENSE](https://github.com/MarvekW/InsightMemory/blob/main/LICENSE).

## At A Glance

- **It thinks before it stores**: incoming text is interpreted into entity-centered memory instead of being
  dropped into a flat chunk pool.
- **It synthesizes, not only appends**: new information can update, extend, conflict with, or support existing
  memory while preserving history.
- **It recalls with reasoning context**: retrieval can expand through memory edges to answer why/how questions,
  not only similarity matches.
- **It keeps evidence attached**: answers can return citations, supporting observations, and historical context.

## Quick Start

The current API does not take a separate `entity` field. Instead, the text you write should explicitly state
who the memory is about, and recall queries should also mention the target entity clearly.

See [Getting Started](./docs/03-getting-started.md) for deployment options.

Write one memory:

```bash
curl -X POST http://127.0.0.1:8010/memory/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "context": "For the Atlas rollout project, the blocker is a failed database migration and it needs rollback."
  }'
```

Recall one entity-centered memory with grounded evidence:

```bash
curl -X POST http://127.0.0.1:8010/memory/recall \
  -H 'Content-Type: application/json' \
  -d '{
    "memory_scope": "demo",
    "query": "For the Atlas rollout project, what is the current blocker?"
  }'
```

For the full deployment path, API examples, and evaluation workflow, see
[Getting Started](./docs/03-getting-started.md).

## Why It Is Different

| Capability | Typical vector memory | InsightMemory |
| --- | --- | --- |
| Same-name entity separation | Usually weak or custom | Built into entity resolution |
| Current vs historical answers | Often mixed together | Modeled as coexisting evolving memory |
| Why/how recall | Mostly similarity-based | Can expand through memory edges |
| Evidence-backed answers | Often indirect | Returns citations and observation traces |
| Long-running updates | Frequently append-only | Supports update, support, conflict, and derivation |

## Demo Scenarios

These text demos are distilled from the repository's own evaluation reports.

### 1. Same-name Entity Separation

Writes:

- `Atlas is a release project. Its current blocker is a failed database migration.`
- `Atlas is a knowledge document. Its current gap is missing rollback notes.`

Recall:

- Query: `What is the current blocker for the Atlas release project?`
- Answer: `The current blocker for the Atlas release project is a failed database migration.`

What it shows:

- the same surface form can resolve to different entities;
- recall stays on the correct entity instead of mixing project and document facts.

### 2. Current vs Historical Memory

Writes:

- `Ashgrove handbook previously allowed teams to file fallback schedules within 24 hours after shift.`
- `Ashgrove handbook now requires incident lead approval for all fallback schedule changes.`
- `Ashgrove handbook supplement: approval records must also be attached to the change packet.`

Recall:

- Query: `What does Ashgrove handbook require now?`
- Answer: `It requires incident lead approval, and approval records must be attached to the change packet.`

- Query: `What did Ashgrove handbook allow before?`
- Answer: `It previously allowed fallback schedules to be filed within 24 hours after shift.`

What it shows:

- current and historical memory can coexist;
- new details can be synthesized into current memory without erasing the old state.

### 3. Why/How Recall With Citations

Writes:

- `Billing service cannot switch to the new template yet because the tax-rate validation workflow is incomplete.`
- `Tax template checklist explicitly requires the validation workflow to be complete before switching.`

Recall:

- Query: `Why can't Billing service switch to the new template yet?`
- Answer: `Because the tax-rate validation workflow is incomplete, and the checklist requires it before switching.`

What it shows:

- the answer can pull both the blocker and its supporting requirement;
- citations trace the answer back to the original evidence.

## Evaluation Snapshot

The numbers below are taken directly from repository eval reports under [`evals/reports`](./evals/reports), not
from hand-written examples.

| Evaluation slice | Cases | Full-pass rate | Grounded answer rate | Focus |
| --- | ---: | ---: | ---: | --- |
| Generic accuracy | 39 | 97.4% | 100% | broad memory accuracy baseline |
| Same-name disambiguation | 2 | 100% | 100% | same surface form, different entities |
| Rule evolution | 6 | 100% | 100% | current vs historical + additive updates |
| Cross-entity why recall | 1 | 100% | 100% | why/how answers with supporting requirements |

Coverage at the repository level currently includes:

| Asset | Count |
| --- | ---: |
| Matrix manifests | 11 |
| Case files | 60 |

## Documentation

- [Getting Started](./docs/03-getting-started.md): image Docker Compose, local-build Docker Compose, pip install, source install, API examples, and evaluation commands.
- [Product Overview](./docs/01-product-overview.md): problem framing, positioning, comparisons, and use cases.
- [System Overview](./docs/02-system-overview.md): core concepts, features, architecture, and repo structure.
- [Memory Design](./docs/04-memory-design.md): deeper design notes for entity identity and memory modeling.
- [Background Task Scheduling](./docs/06-background-task-scheduling.md): background task runtime design.
- [Generalization Test Expansion Plan](./docs/07-generalization-test-expansion-plan.md): eval coverage plan and suite rules.
- [Development Guide](./docs/09-development-guide.md): bilingual LLM-first development principles for memory logic.
- [Read and Write Best Practices](./docs/10-memory-read-write-best-practices.md): how to structure writes, queries,
  and asynchronous recall handling.
- [Technical Blog Drafts](./docs/blogs/zh-cn/blog-index.zh-cn.md): Chinese articles for explaining and promoting
  the project.

## Support and Collaboration

InsightMemory is still under active development. Useful ways to help include:

- trying it in a real AI agent or copilot workflow and sharing failure cases;
- contributing evaluation cases for same-name entities, long-running evolution, and multi-entity documents;
- improving docs, examples, deployment guides, and benchmark reports;
- opening issues for bugs, regressions, and missing use cases;
- sharing LLM API keys, test credits, or sponsorship so the project can keep improving prompts, evaluation
  coverage, and long-running memory experiments;
- reaching out for collaboration, integration, or sponsorship.

If you want to collaborate around the project, contact:

```text
marvekwang@gmail.com
```

Please do not post API keys in public issues or comments. Contact privately if you want to support the project
with LLM API access. Thank you for supporting InsightMemory.

## License

This project is licensed under the MIT License.

See [LICENSE](./LICENSE) for the full text.
