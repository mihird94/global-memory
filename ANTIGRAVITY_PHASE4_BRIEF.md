# Antigravity Phase 4 Brief

## Objective

Implement only the Phase 4 foundation of the GMS roadmap:

- Add lightweight local entity and relationship graph storage
- Keep episodes and claims as provenance roots
- Expose a minimal MCP surface for explicit entity and relationship management
- Do not add heavy graph retrieval or automatic extraction yet

## Repository in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/memory_mcp_server.py`
- `tests/test_memory.py`
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond the Phase 4 foundation
- Do not add automatic entity extraction from free text yet
- Do not add graph databases or external dependencies
- Do not replace the current typed bucket or claim-ledger model
- Preserve local-first and MCP-first architecture
- Avoid unrelated refactors

## Required Design

### 1. Local graph tables

Add lightweight SQLite tables for at least:

- entities
- relationships

A reasonable minimum entity shape:

- `entity_id`
- `name`
- `entity_type`
- `summary`
- timestamps

A reasonable minimum relationship shape:

- `relationship_id`
- `subject_entity_id`
- `predicate`
- `object_entity_id` and/or `object_literal`
- `source_claim_id`
- `valid_from`
- `valid_to`
- timestamps

### 2. Provenance linkage

Relationships should be able to reference a claim from the Phase 3 claim ledger via `source_claim_id`.

This is the key Phase 4 principle:

- graph sits on top of typed claims
- graph does not replace claims

### 3. MCP surface

Keep the API small. A reasonable minimal set is:

- `mem_upsert_entity`
- `mem_link_entities`
- `mem_get_entity_graph`

You may choose different names if they are clearer, but keep the surface narrow.

### 4. Temporal support

Relationships should support lightweight temporal validity fields:

- `valid_from`
- `valid_to`

No advanced temporal reasoning is required yet.

### 5. No automatic extraction

Do not try to infer entities or relations from arbitrary fact keys or values in this slice.

Phase 4 is explicit graph substrate only.

## Tests

Extend the test suite with focused coverage for at least:

- entity upsert is idempotent
- relationships can be created between entities
- relationship temporal fields are stored
- relationship can reference a valid claim id
- entity graph read returns linked relationships

Use temporary memory roots and isolated SQLite state.

## Deliverables

At the end, report:

1. Files changed
2. Validations run
3. Residual risks or limitations

## Acceptance Notes

Codex is the acceptance authority.

Optimize for:

- narrow scope
- clean substrate for later graph work
- explicit provenance linkage
- minimal migration risk
