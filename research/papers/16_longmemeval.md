# LongMemEval — Benchmarking Chat Assistants on Long-Term Interactive Memory

## Metadata
*   **Paper ID:** 16
*   **Identifier:** [arXiv:2410.10813](https://arxiv.org/abs/2410.10813)
*   **Date:** Oct 2024
*   **Status / Venue:** ICLR 2025
*   **Role in GMS:** Evaluation protocol. Used to measure GMS performance and recall stability.

---

## 1. Abstract / Key Concept
Evaluates long-context memory models across sustained multi-session conversations, identifying a ~30% accuracy drop under temporal and factual updates.

---

## 2. Core Mechanism & Methodology
Testing framework evaluating information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{RecallAccuracy} = \frac{|\text{Correct Retrievals}|}{|\text{Total Queries}|}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** We adapt the knowledge-update and multi-session reasoning subsets to measure GMS's retention stability and guard against norm drift.

---

## 5. Limitations & Vulnerabilities
Focuses on conversational systems and does not model multi-agent database write conflicts.
