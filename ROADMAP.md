# GMS Product Roadmap

## Scope

This document captures the current state of the Global Memory System (GMS), the independently validated research inputs, the major architectural gaps, and the implementation roadmap for turning GMS into a best-in-class local memory system for multi-agent workflows.

Date: 2026-06-04

## Current State

GMS already has strong foundations in the following areas:

- Local-first operation
- MCP-first access pattern
- Semantic facts plus episodic logs
- Provenance tagging
- Quarantine tables
- Jøsang-style trust scoring
- Hybrid retrieval with temporal decay and branch boost

Current material gaps:

- `dream_cycle.py` bypasses the trust gateway and writes extracted facts directly
- The nightly "EM" calibration is not actually Dawid-Skene
- No TRAVOS-style witness or recommender weighting
- No semantic drift monitoring
- No lifecycle forgetting or pruning
- No serious benchmark harness for poisoning or long-memory evaluation
- Provenance is too flat and non-versioned for multi-claim truth resolution

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

## Recommended Execution Order

1. Trust-gate all writes
2. Typed memory routing
3. Versioned claim model
4. Temporal graph plus contradiction handling
5. Evaluation harness
6. Procedural memory plus reconstruction
7. UI and product polish

## Immediate Next Step

The highest-priority implementation task is:

- Route Dream Cycle fact promotion through the trust and quarantine gateway instead of writing LLM-extracted facts directly into `facts.json`
