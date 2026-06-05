# MemOS — Unified Memory OS for AI Systems

## Metadata
*   **Paper ID:** 15
*   **Identifier:** [arXiv:2507.03724](https://arxiv.org/abs/2507.03724)
*   **Date:** Jul 2025
*   **Status / Venue:** arXiv preprint (Discrepancy: user prompt listed 2407.01876 / Jul 2024)
*   **Role in GMS:** Structural abstraction. Evaluates standardizing memory blocks as versioned objects.

---

## 1. Abstract / Key Concept
MemOS separates AI memory into three distinct tiers (parametric, activation, and plaintext) and manages them using versioned, self-contained objects called 'MemCubes'.

---

## 2. Core Mechanism & Methodology
MemCube architecture with built-in version control and cryptographic provenance. Standardizes read/write APIs across different storage nodes.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{MemCube} = \{\text{payload}, \text{provenance}, \text{version\_hash}, \text{timestamp}\}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Inspires GMS's metadata schema. We wrap facts and their DB provenance records in a unified JSON structure to ensure traceability.

---

## 5. Limitations & Vulnerabilities
Cryptographic hashing on every memory commit adds latency that can impact real-time developer workflows.
