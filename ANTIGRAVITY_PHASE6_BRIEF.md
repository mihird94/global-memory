# Antigravity Phase 6 Brief

## Objective

Implement only the Phase 6 foundation of the GMS roadmap:

- Add explicit procedural memory primitives on top of the existing typed bucket and claim system
- Support reusable trigger-action playbooks as first-class procedural records
- Keep the scope deterministic and local

## Repository in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/memory_mcp_server.py`
- `tests/test_memory.py`
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond the Phase 6 foundation
- Do not add LLM-based automatic procedural extraction yet
- Do not add workflow execution or orchestration engines
- Do not break existing Phase 1-5 behavior
- Preserve local-first and MCP-first architecture
- Avoid unrelated refactors

## Required Design

### 1. Procedural record model

Add explicit procedural memory records for reusable playbooks.

A minimal acceptable shape includes:

- `procedure_id`
- `name`
- `trigger`
- `action`
- `context`
- `status`
- `source_claim_id`
- timestamps

SQLite-backed storage is fine.

### 2. MCP surface

Keep the API small. A reasonable minimum set is:

- `mem_upsert_procedure`
- `mem_get_procedures`

Optional:

- a small status toggle/update path if needed

### 3. Relationship to existing procedural bucket

Procedural records should not replace the current procedural typed bucket.

Instead:

- the procedural bucket remains simple key/value procedural memory
- the new procedural table stores richer trigger-action playbooks

### 4. Provenance linkage

If `source_claim_id` is provided, validate that it exists in the claim ledger.

### 5. Status model

Support a minimal status model such as:

- `active`
- `archived`

Keep it simple.

## Tests

Extend the test suite with focused coverage for at least:

- upsert is idempotent by name
- trigger/action/context fields persist correctly
- claim linkage validation works
- status updates persist
- read path can filter active vs archived procedures

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
- explicit procedural substrate
- preserving current typed/claim foundations
- clean path toward later automated extraction
