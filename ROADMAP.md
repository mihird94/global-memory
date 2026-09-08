# GMS Product Roadmap

## Scope

This document captures the current state of the Global Memory System (GMS), the independently validated research inputs, the major architectural gaps, and the implementation roadmap for turning GMS into a best-in-class local memory system for multi-agent workflows.

Date: 2026-09-08

## Current State

GMS v2.1.0 provides an enterprise-grade, local-first memory platform for multi-agent systems with:

- **Trust-Gated Writes & Provenance**: All writes route through Bayesian trust scoring, versioned claims, and quarantine tables.
- **Namespaced Schema Contracts**: Pydantic schema validation (`tools/schemas.py`) guarding critical namespaces (`infra`, `trading`, `models`, `policies`, `procedures`) with reputation penalties on violations.
- **Bi-Temporal Knowledge Graph**: SQLite graph substrate (`gms_relationships`) with `valid_from`/`valid_to` validity windows, automatic invalidation of single-valued predicates, and as-of time-travel queries.
- **Unified SQLite Vector Store**: Embeddings stored ACID-compliantly in `gms_trust.sqlite` (`gms_embeddings`), eliminating drift with FAISS sync.
- **FlashRank Cross-Encoder Reranker**: High-precision semantic retrieval using local cross-encoder scoring.
- **Dual-Cadence Consolidation**: Automated Post-Session Harvesting ("Agentic Sleep" via `tools/harvest.py`) and nightly Dream Cycle consolidation with Dawid-Skene calibration and retention pruning.
- **Task Handoffs & Evaluation**: A2A-style task revision leases and 93 deterministic unit tests across Python 3.10 and 3.13.

### Material Gaps Resolved

- [x] Trust gateway bypass in Dream Cycle eliminated (`save_fact_with_trust`)
- [x] Symmetric Dawid-Skene multi-rater calibration implemented
- [x] Weighted reviewer endorsements & TRAVOS-style trust updating
- [x] Semantic drift monitoring and reporting
- [x] Retention and lifecycle pruning with non-destructive claim archival
- [x] Namespaced Pydantic schema validation at the gateway
- [x] Bi-temporal edge tracking with functional predicate invalidation
- [x] Consolidated ACID vector storage in SQLite
- [x] Post-session agent micro-consolidation hook ("Agentic Sleep")
- [x] FlashRank cross-encoder reranking integration

## Independent Research Summary

### GBrain

Best reusable idea:

- Strict separation of `world knowledge` vs `agent operational memory` vs `session context`

Why it matters:

- This is the cleanest boundary discipline missing from current GMS.

### Graphiti / Zep

Best reusable idea:

- Temporal knowledge graph with `entities`, `relationships`, and `episodes` as first-class objects with provenance

Why it matters:

- This is the cleanest upgrade path from flat facts plus logs to durable structured memory.

### Engram

Best reusable ideas:

- Typed memory
- Belief dynamics
- Reinforcement and decay
- Contradiction handling
- Procedural extraction

Why it matters:

- These are strong product concepts, but they should be adopted selectively to avoid unnecessary complexity.

### ENGRAM Paper

Best reusable idea:

- Simple typed routing can outperform more complex memory architectures if schemas and retrieval are clean

Why it matters:

- This is a useful corrective against overengineering.

### G-Memory

Best reusable idea:

- Multi-agent memory should encode cross-trial collaboration structure, not just single-agent memories

Why it matters:

- This is the right future direction for team memory inside GMS.

### E-mem

Best reusable idea:

- Preserve raw episodic context and reconstruct it when needed instead of over-compressing everything into embeddings or flat facts

Why it matters:

- This is highly relevant for debugging, coding, audits, and forensic recall.

### Existing Validated Corpus

Already relevant to GMS direction:

- SuperLocalMemory
- LongMemEval
- Mem0
- MemGPT
- The Misattribution Gap

## Target Product Direction

The target product should combine:

- MCP-first local operation
- Typed memory routing
- Temporal and provenance-aware entity graphs
- Trust-gated fact promotion
- Contradiction handling
- Procedural memory extraction
- Raw episodic preservation
- Benchmark-driven evaluation

### Proposed Memory Layers

#### Layer 1: Operational Memory

Stores:

- Agent preferences
- Tool contracts
- Execution policies
- Environment rules

Notes:

- Closest to the current `facts.json`, but should become typed and trust-gated.

#### Layer 2: World / Knowledge Brain

Stores:

- World knowledge
- Entities
- Pages
- Relationships
- Compiled truth
- Append-only evidence trail

Notes:

- This is the GBrain-style knowledge layer.

#### Layer 3: Episodic Evidence Store

Stores:

- Raw episodes
- Compressed episodes
- Provenance roots

Notes:

- This should support E-mem style reconstruction for deep recall.

#### Layer 4: Team Memory

Stores:

- Cross-agent traces
- Cross-run collaboration patterns
- Reusable insights
- Interaction summaries

Notes:

- This is the G-Memory style multi-agent layer.

### Cross-Cutting Controls

- Trust gateway on all writes
- Contradiction detection and quarantine
- Confidence and belief updates
- Temporal validity and supersession
- Benchmark and red-team evaluation

## Phased Roadmap

### Phase 1: Stabilize the Trust Boundary

Goals:

- Route Dream Cycle through `mem_judge` and `mem_save_fact`
- Remove direct writes to `facts.json`
- Stop calling the nightly heuristic "EM" unless it becomes real Dawid-Skene
- Add write-path tests for overwrite, quarantine, promotion, and replay

Why first:

- This is the highest-value correctness fix and closes the most serious architectural hole.

### Phase 2: Introduce Typed Memory Routing

Goals:

- Split writes into `semantic`, `episodic`, `procedural`, and `operational`
- Adopt a GBrain-style routing rule:
  - World facts go to the brain
  - Agent behavior and config go to operational memory
  - Current task state remains session-local
- Keep the MCP surface small

Why second:

- It reduces category confusion before deeper structural work begins.

### Phase 3: Replace Flat Provenance with Versioned Claims

Goals:

- Move to claim records with fields like:
  - `claim_id`
  - `subject`
  - `predicate`
  - `object` or `value`
  - `agent`
  - `timestamp`
  - `confidence`
  - `status`
  - `supersedes`

Why third:

- This unlocks temporal truth, conflicts, witness scoring, and durable traceability.

### Phase 4: Add Temporal and Entity Graph Support

Goals:

- Add entity and relationship tables
- Keep episodes as provenance roots
- Start with lightweight local storage instead of a heavyweight graph stack

Why fourth:

- The graph should sit on top of typed claims, not replace them prematurely.

### Phase 5: Add Contradiction Handling and Belief Dynamics

Goals:

- Implement:
  - Exact conflict
  - Temporal invalidation
  - Contextual coexistence
- Add confidence updates on reinforcement and contradiction

Why fifth:

- This is where Engram-style memory evolution becomes genuinely useful.

### Phase 6: Add Procedural Memory

Goals:

- Extract stable trigger-action policies from successful episodes
- Store explicit procedures and playbooks rather than implicit heuristics

Why sixth:

- This is critical for multi-agent coding and operations workflows.

### Phase 7: Add Raw Episodic Reconstruction

Goals:

- Preserve enough raw context for difficult reasoning tasks
- Support:
  - Fast summary path
  - Deep reconstruction path

Why seventh:

- It provides both speed and fidelity.

### Phase 8: Build the Evaluation Harness

Goals:

- LongMemEval-style tests for:
  - Knowledge updates
  - Temporal reasoning
  - Multi-session recall
  - Abstention
- Poisoning tests for overwrite attacks and malicious retrieval
- Drift tests across repeated consolidations

Why eighth:

- This is required to make product and research claims defensible.

### Phase 9: Productize

Goals:

- Memory inspector or TUI
- Graph explorer
- Claim provenance UI
- Quarantine review UI
- Branch, project, and agent scope controls
- One-command local setup

Why ninth:

- This turns the system from infrastructure into a usable product.

## What to Reuse

- GBrain's memory-boundary discipline
- Graphiti/Zep's temporal entity-edge-episode model
- ENGRAM's typed routing simplicity
- Engram's contradiction and confidence concepts
- E-mem's reconstruction path
- G-Memory's multi-agent hierarchy for later phases

## What to Avoid

- Turning GMS into a heavyweight managed platform clone
- Premature graph complexity before typed claims exist
- LLM-only consolidation without a trust boundary
- Claiming advanced trust or drift features before they are implemented

## Execution Milestones

1. [x] Trust-gate all writes (Phase 1)
2. [x] Typed memory routing (Phase 2)
3. [x] Versioned claim model (Phase 3)
4. [x] Temporal graph plus contradiction handling (Phase 4 & 5)
5. [x] Namespaced Pydantic schema validation at gateway
6. [x] Consolidated ACID vector storage in SQLite (`gms_embeddings`)
7. [x] Cross-encoder reranking (FlashRank)
8. [x] Post-session agent harvesting ("Agentic Sleep")
9. [x] Evaluation harness (93 tests across Python 3.10 and 3.13)
10. [ ] TUI graph visualization and interactive temporal time-travel slider
11. [ ] Continuous online calibration and auto-discovery of contract schemas

## Immediate Next Step

The highest-priority refinement tasks:

- Interactive graph navigation and time-travel query slider in `gms_tui.py`
- Distributed multi-node sync protocol between Mac (M4) and MiniPC (Linux x86_64) using lightweight SQLite changeset streams or replication hooks
