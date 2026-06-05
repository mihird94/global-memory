# Zep — Temporal Knowledge Graph Architecture for Agent Memory

## Metadata
*   **Paper ID:** 13
*   **Identifier:** [arXiv:2501.13956](https://arxiv.org/abs/2501.13956)
*   **Date:** Jan 2025
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Temporal indexing. Shows how time-aware graphs improve context retrieval accuracy.

---

## 1. Abstract / Key Concept
Zep introduces a temporal knowledge graph system (Graphiti) that updates relations dynamically as new interactions are logged.

---

## 2. Core Mechanism & Methodology
Graphiti temporal edge weighting + asynchronous fact consolidation. Fact edges decay over time unless reinforced.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$W_t = W_0 \cdot e^{-\lambda (t_c - t_e)}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Applied to GMS's temporal query filters. GMS incorporates time decay directly into FAISS query scoring to prioritize recent contexts.

---

## 5. Limitations & Vulnerabilities
Graph database maintenance adds latency, making it less suitable for real-time high-throughput development pipelines.
