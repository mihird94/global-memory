# The Misattribution Gap — Memory Poisoning Looks Like Model Failure

## Metadata
*   **Paper ID:** 06
*   **Identifier:** [arXiv:2605.22842](https://arxiv.org/abs/2605.22842)
*   **Date:** May 2026
*   **Status / Venue:** Under review
*   **Role in GMS:** Core validation. Explains why memory protection must be handled at the database layer.

---

## 1. Abstract / Key Concept
Identifies the 'Misattribution Gap' where memory poisoning attacks (Semantic Norm Drift) produce behaviors that are misdiagnosed as model alignment issues, leading to ineffective retraining.

---

## 2. Core Mechanism & Methodology
Demonstrates that memory-layer injections bypass standard LLM guardrails, altering downstream task behaviors without triggering model safety filters.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{ASR}_{\text{misattribution}} = P(\text{Failure} | \text{PoPoisoned Memory}) \times (1 - P(\text{Alert} | \text{Safety Gate}))$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Validates GMS's architectural placement: a dedicated trust gateway at the database level that sanitizes and quarantines inputs before they commit.

---

## 5. Limitations & Vulnerabilities
Mainly diagnostic; relies on external testing wrappers to detect the gap rather than providing a native prevention mechanism.
