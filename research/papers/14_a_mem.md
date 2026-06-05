# A-MEM — Zettelkasten-inspired Agentic Memory

## Metadata
*   **Paper ID:** 14
*   **Identifier:** [arXiv:2502.12110](https://arxiv.org/abs/2502.12110)
*   **Date:** Feb 2025
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Relational link reference. Explores how semantic links improve open-ended reasoning tasks.

---

## 1. Abstract / Key Concept
A-MEM implements an agentic memory based on the Zettelkasten method, allowing agents to create atomic, interconnected notes instead of flat lists.

---

## 2. Core Mechanism & Methodology
Atomic note generation + semantic link classification. Agents write bidirectionally linked notes to build a personal wiki.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{LinkStrength}(n_1, n_2) = \text{LLM\_Classify}(n_1, n_2) \times \cos(\mathbf{e}_1, \mathbf{e}_2)$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Informs the structure of GMS lessons and projects. Helps GMS group related rules and paths into structured semantic clusters in facts.json.

---

## 5. Limitations & Vulnerabilities
Generating and classifying links for every transaction requires multiple LLM calls, significantly increasing API costs.
