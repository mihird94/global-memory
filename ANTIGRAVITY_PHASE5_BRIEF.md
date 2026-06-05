# Antigravity Phase 5 Brief

## Objective

Implement only the Phase 5 foundation of the GMS roadmap:

- Add explicit contradiction classification
- Add lightweight confidence / belief dynamics to claims
- Preserve the current typed bucket, claim-ledger, and graph substrate behavior

## Repository in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/memory_mcp_server.py`
- `tests/test_memory.py`
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond the Phase 5 foundation
- Do not add LLM-based contradiction analysis
- Do not add graph reasoning engines or external dependencies
- Do not break existing Phase 1-4 behavior
- Preserve local-first and MCP-first architecture
- Avoid unrelated refactors

## Required Design

### 1. Contradiction classification

Support explicit contradiction categories for persisted memory conflicts:

- `exact_conflict`
- `temporal_invalidation`
- `contextual_coexistence`

This can be deterministic and rule-based for now.

Examples of acceptable heuristics:

- same kind + same key + different value -> `exact_conflict`
- relation or claim with a new time window superseding older validity -> `temporal_invalidation`
- coexistence allowed when values are scoped/context-tagged rather than mutually exclusive -> `contextual_coexistence`

Keep it simple and explicit.

### 2. Confidence / belief dynamics

Add a lightweight confidence signal to claims.

Minimum acceptable approach:

- store a numeric confidence field on claims
- initialize from a deterministic rule using agent trust and write outcome
- reinforce on repeated consistent writes
- lower or keep low for quarantined / contradicted writes

Keep it local and rule-based. Do not attempt probabilistic inference beyond what is needed for a small confidence substrate.

### 3. Read surface

Expose the smallest useful inspection surface for contradiction and confidence data.

One acceptable approach:

- extend `mem_get_claims` to include confidence and contradiction_type metadata

Another acceptable approach:

- add one narrow inspection tool if necessary

Prefer minimal API churn.

### 4. Compatibility

Required:

- existing tests from Phases 1-4 must keep passing
- current-state typed storage remains unchanged
- claim and graph substrate remain usable

## Tests

Extend the test suite with focused coverage for at least:

- repeated same-value writes reinforce confidence
- quarantined conflicting writes produce low-confidence quarantined claims
- exact conflict classification is recorded
- temporal invalidation can be represented for a relationship or claim transition
- contextual coexistence can be represented without overwriting current state

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
- explicit deterministic behavior
- preserving current foundations
- building a clean substrate for later evaluation work
