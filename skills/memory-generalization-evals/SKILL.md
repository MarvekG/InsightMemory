---
name: memory-generalization-evals
description: Use when adding or updating Best-AI-Trader memory evaluation suites or cases to test generalization, especially non-keyword memory ingest, recall, identity resolution, dependency chains, multi-subject queries, noisy contexts, and out-of-distribution domains.
---

# Memory Generalization Evaluations

Use this skill when the task is to add, revise, or diagnose memory evaluation cases that measure whether the memory system generalizes beyond hand-written examples.

## Core Rules

- Do not add cases that only pass because of keyword matching.
- Do not copy examples from prompts into evaluation samples.
- Do not tune prompts or code for one exact case. Add cases that represent a reusable behavior.
- Keep prompt examples and evaluation samples different in names, domains, and wording.
- Prefer realistic mixed-language inputs because the memory system must handle Chinese, English, and mixed operational terms.
- A case should test one main behavior, with distractors that prove the answer is scoped correctly.

## Where To Add Files

- Add suite cases under `memory/evals/cases/generic_<topic>_v1.json`.
- Register the suite in `memory/evals/matrix/default_v1.json`.
- Use existing suites as schema references:
  - `memory/evals/cases/generic_out_of_distribution_domains_v1.json`
  - `memory/evals/cases/generic_deeper_dependency_chain_v1.json`
  - `memory/evals/cases/generic_large_scope_graph_v1.json`

## Case Shape

Each case should usually include:

```json
{
  "case_id": "stable_unique_case_id",
  "category": "generalization_category",
  "description": "What behavior this case is testing.",
  "memory_scope_templates": {
    "primary": "eval:generic_suite_name_v1:{run_id}:{case_id}"
  },
  "writes": [
    {
      "context": "Durable fact or relationship to ingest.",
      "expected_status": "accepted"
    }
  ],
  "queries": [
    {
      "query_id": "q1",
      "query": "Question to recall the memory.",
      "expected_status": "ok",
      "citations_min": 1,
      "non_empty_answer": true,
      "judge_required_facts": ["fact A", "fact B || acceptable variant"],
      "judge_forbidden_facts": ["distractor fact"]
    }
  ],
  "expected": {
    "primary": {
      "entity_count": 2,
      "memory_count": 2,
      "observation_count": 2,
      "recall_audit_count": 1
    }
  }
}
```

## Designing Good Generalization Cases

Test reusable behavior, not wording:

- Identity separation: same prefix, different artifact types, such as project vs checklist vs handbook.
- Current vs history: current state should not be polluted by old resolved facts.
- Direct answer vs dependency answer: use one narrow query and one why/dependency query when both behaviors matter.
- Cross-entity dependency: target memory says what is blocked; another entity says why or what requirement governs it.
- Noisy context: include unrelated but plausible facts and assert they are forbidden in the answer.
- Out-of-distribution domains: use domains unlike finance/software examples, such as shipping, geology, public safety, lab work, archives, field operations.
- Multi-subject recall: ask about two or more stable subjects and expect independent results instead of a blended answer.
- Large scope: include many entities with similar names to test retrieval precision.

Avoid brittle expectations:

- If a query asks only "what does this target need?", required facts should be the direct missing items. Put governing policy or upstream artifact checks in a separate "why" query.
- If resolver refreshes a supplement into an existing memory, set `memory_count` to the final logical memory count, not the number of writes.
- Use `required_memory_texts` when a detail must be retained after refresh or replace.
- Use `judge_forbidden_facts` for distractors that prove the answer did not cross into the wrong subject.
- Use `||` in `judge_required_facts` only for genuine acceptable variants, not as a way to hide vague expectations.

## Registering A Suite

Add an entry to `memory/evals/matrix/default_v1.json`:

```json
{
  "suite_id": "new_generalization_suite",
  "description": "What behavior this suite covers.",
  "cases": "../cases/generic_new_generalization_suite_v1.json"
}
```

Keep `suite_id`, file name, and `memory_scope_templates` aligned so reports are easy to trace.

## Validation

Before running live evals:

```bash
python -m json.tool memory/evals/cases/generic_<topic>_v1.json >/tmp/generic_<topic>.jsoncheck
```

Run one suite:

```bash
python memory/evals/scripts/eval_memory_matrix.py \
  --suite <suite_id> \
  --run-id <purpose>_$(date -u +%Y%m%dT%H%M%SZ) \
  --max-concurrency 1 \
  --settle-timeout-seconds 120
```

Run concurrency stress:

```bash
python memory/evals/scripts/eval_memory_matrix.py \
  --suite <suite_id> \
  --run-id <purpose>_concurrent_$(date -u +%Y%m%dT%H%M%SZ) \
  --max-concurrency 20 \
  --settle-timeout-seconds 180
```

Reports are written under `memory/evals/reports/`. Use the JSON report for exact failure causes.

## Failure Analysis Checklist

When a case fails, identify the exact stage before changing prompts or code:

- Ingest gate: was the observation accepted or rejected?
- State: do entity, memory, observation, edge, and audit counts match expected logical state?
- Query gate: did planner extract the intended identity profile?
- Linker: did candidate recall include the correct entity before LLM linking?
- Recall graph: were seed memories and expanded memories correct?
- Edge judge: did it create useful `supports`, `related_to`, `contradicts`, or `updates` edges?
- Answer composer: did it receive the right memories and still answer incorrectly?
- Answer judge: is the expectation too broad for the user query?

Use database evidence before deciding:

- `memory.memory_recall_audits` for query result, used edges, and resolution trace.
- `memory.memory_llm_runs` for planner, linker, edge judge, and composer inputs/outputs.
- `memory.memory_memories`, `memory.memory_entities`, and `memory.memory_edges` for persisted state.

