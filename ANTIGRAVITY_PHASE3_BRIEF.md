# Antigravity Phase 3 Brief

## Objective

Implement only the Phase 3 foundation of the GMS roadmap:

- Add a versioned claim ledger beneath the current fact system
- Preserve the current fact read path and current typed bucket behavior
- Record accepted and quarantined persisted writes as claims with explicit status
- Expose a minimal MCP read surface for inspecting claims

## Repository in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/memory_mcp_server.py`
- `tests/test_memory.py`
- `tools/memoryctl.py` only if needed for minimal compatibility or testability
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond the Phase 3 foundation
- Do not add graph, entity, relationship, ontology, or retrieval-graph work yet
- Do not replace the existing `facts.json` / typed bucket current-state model yet
- Do not break existing Phase 1 or Phase 2 behavior
- Preserve local-first and MCP-first architecture
- Avoid unrelated refactors
- Keep the claim model simple and testable

## Required Design

### 1. Add a claim ledger

Add a new SQLite-backed claim table for persisted memory writes.

It should be explicit enough to support later supersession and trust workflows. A reasonable minimum schema includes:

- `claim_id`
- `memory_kind`
- `memory_key`
- `value`
- `agent_id`
- `branch`
- `status`
- `supersedes_claim_id`
- `created_at`

You may add small additional fields if justified, but keep it minimal.

### 2. Claim statuses

Support at least these statuses:

- `active`
- `superseded`
- `quarantined`

Session-only writes should not create claims.

### 3. Write-path behavior

For persisted writes:

- A new accepted write should create an `active` claim
- If it replaces an existing accepted value for the same typed bucket and key, the previous active claim should become `superseded`
- A quarantined write should create a `quarantined` claim

Backward compatibility is required:

- typed bucket JSON files remain the current-state read model
- `mem_save_fact` and `mem_save_typed` must keep working

### 4. Read surface

Add the smallest useful MCP read surface for claims.

One acceptable approach:

- add `mem_get_claims` with optional filters like `kind`, `key`, and `status`

Prefer a narrow API.

### 5. Quarantine resolution integration

If practical within scope:

- when a quarantined entry is promoted, its claim status should become `active` and supersede the prior active claim if applicable
- when discarded, its claim status may remain quarantined or become discarded only if that is easy and clean

If full discard-state modeling is not worth it for this slice, keep it simple and document the limitation.

## Tests

Extend the test suite with focused coverage for at least:

- accepted persisted writes create active claims
- overwrites supersede prior active claims
- quarantined writes create quarantined claims
- session writes do not create claims
- claim reads can filter by kind/key/status

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
- preserving current behavior
- creating a strong substrate for later phases
- minimal migration risk
