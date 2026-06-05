# Antigravity Phase 2 Brief

## Objective

Implement only Phase 2 of the GMS roadmap:

- Introduce typed memory routing for `semantic`, `operational`, `procedural`, and `session`
- Preserve backward compatibility for the current semantic fact path
- Keep the MCP surface small
- Add focused tests for typed routing and typed persistence

## Repository in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/memory_mcp_server.py`
- `tools/memoryctl.py` only if needed for minimal compatibility or testability
- `tests/test_memory.py`
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond Phase 2
- Do not add graph, entity, relationship, or claim-model work yet
- Do not add LLM-based routing or classifier dependencies
- Do not break existing `mem_save_fact` behavior for semantic facts
- Preserve local-first and MCP-first architecture
- Avoid unrelated refactors
- Keep changes tightly scoped and reviewable

## Required Design

### 1. Typed persistence

Introduce explicit storage buckets:

- `semantic` -> existing semantic facts store
- `operational` -> separate operational store
- `procedural` -> separate procedural store
- `session` -> do not persist; return an explicit no-op / session-only result

Use simple local JSON-backed storage for the new typed buckets. Do not introduce a database migration for Phase 2 beyond what is already present.

### 2. Deterministic routing contract

Add a small MCP-facing routing entry point that follows the GBrain-style boundary:

- world knowledge -> semantic
- agent behavior / config / preferences / policies -> operational
- learned reusable instructions / trigger-action patterns -> procedural
- current conversation / ephemeral task state -> session only

This routing should be deterministic and rule-based for now. Do not add an LLM classifier.

### 3. Backward compatibility

Required:

- `mem_save_fact` must continue to behave as the semantic write path
- existing consumers of semantic facts must keep working

Optional:

- if you add a generalized typed store function internally, `mem_save_fact` can wrap it for semantic writes

### 4. Read path

Add the smallest useful typed read support. One acceptable approach:

- extend `mem_get_facts` with a `kind` filter

Another acceptable approach:

- add a small typed read tool if necessary

Prefer the smaller API surface.

### 5. Provenance / trust behavior

Typed persisted writes should still pass through the trust-aware path for persisted categories.

If you need to namespace provenance keys internally to avoid collisions across semantic / operational / procedural buckets, do so in a clean and explicit way.

### 6. Session behavior

For `session`, do not write to disk. Return a result that makes the boundary clear.

## Tests

Extend the test suite with focused coverage for at least:

- semantic writes still land in semantic storage
- operational writes do not land in semantic storage
- procedural writes do not land in semantic storage
- session writes do not persist
- typed reads can retrieve the right bucket
- backward-compatible `mem_save_fact` behavior still works

Use temporary memory roots and isolated local files.

## Deliverables

At the end, report:

1. Files changed
2. Validations run
3. Residual risks or limitations

## Acceptance Notes

Codex is the acceptance authority.

Optimize for:

- narrow scope
- clear routing boundaries
- minimal API churn
- correctness and testability
