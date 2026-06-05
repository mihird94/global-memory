# Antigravity Phase 1 Brief

## Objective

Implement only Phase 1 of the GMS roadmap:

- Route Dream Cycle fact promotion through the trust and quarantine gateway instead of writing LLM-extracted facts directly into `facts.json`
- Remove direct Dream Cycle fact writes that bypass trust checks
- Rename or refactor the nightly "EM" trust calibration so it no longer falsely claims to be Dawid-Skene EM unless it is upgraded to a real EM implementation
- Add a minimal automated test surface for the trust-gated write path and Dream Cycle promotion path

## Repositories in Scope

- `/home/mihir/projects/global-memory`

Do not touch any other repository or global config.

## Files Expected to Be Relevant

- `tools/dream_cycle.py`
- `tools/memory_mcp_server.py`
- `tools/memoryctl.py`
- new test files if needed
- minimal docs updates only if required by the change

## Hard Constraints

- Do not implement roadmap phases beyond Phase 1
- Do not add graph, entity, or claim-model work yet
- Do not change external behavior outside trust-gating, calibration naming/logic clarity, and tests
- Preserve local-first and MCP-first architecture
- Keep changes tightly scoped and reviewable
- Avoid unrelated refactors
- If you add tests, keep them focused and fast
- If the repo has no existing test harness, add the smallest viable one

## Specific Requirements

### 1. Dream Cycle write path

Current problem:

- `dream_cycle.py` merges extracted facts directly into `facts.json`, bypassing `mem_judge` / `mem_save_fact`

Required behavior:

- Dream Cycle must promote facts through the same trust-aware write path used by the MCP memory layer
- If a fact conflicts and trust is insufficient, it must be quarantined rather than silently overwriting
- Provenance for promoted Dream Cycle facts must still be recorded

### 2. Calibration naming / logic

Current problem:

- The function currently called EM calibration is not Dawid-Skene EM

Required behavior:

- Either rename it to something accurate, or replace it with a more honest heuristic name and log messaging
- Do not claim Dawid-Skene EM if the implementation is still a count-based heuristic

### 3. Tests

Add targeted tests covering at least:

- conflicting fact writes go through quarantine behavior
- non-conflicting Dream Cycle promotions use the trust-aware path
- the calibration routine naming or behavior is no longer misleading

Use temporary directories and isolated memory roots if possible.

## Deliverables

At the end, report:

1. Files changed
2. Validations run
3. Residual risks or limitations

## Acceptance Notes

Codex is the acceptance authority.

Your output should optimize for:

- high signal
- narrow scope
- minimal unrelated churn
- correctness over breadth
