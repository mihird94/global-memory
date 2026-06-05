# Agent Security Bench (ASB) — Vulnerability Baselines

## Metadata
*   **Paper ID:** 08
*   **Identifier:** [arXiv:2410.02644](https://arxiv.org/abs/2410.02644)
*   **Date:** Oct 2024
*   **Status / Venue:** ICLR 2025
*   **Role in GMS:** Threat baseline. Provides the core scenarios used to red-team GMS's security gates.

---

## 1. Abstract / Key Concept
Establishes a standardized benchmark for evaluating agent safety and security, demonstrating a 67% vulnerability success rate on traditional agent architectures.

---

## 2. Core Mechanism & Methodology
Automated attack simulation scripts that target tool calls, file access, and memory writing pathways.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{ASR}_{\text{ASB}} = \frac{|\text{Successful Violations}|}{|\text{Total Scenarios}|}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Used to create the integration test suite for GMS. We adapt ASB attack scripts to verify that GMS quarantine gates successfully block malicious injections.

---

## 5. Limitations & Vulnerabilities
Does not address state persistence across multi-session environments, focusing instead on single-turn exploits.
