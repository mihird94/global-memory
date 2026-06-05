# MINJA — Memory Injection Attack on Demonstration-based Agents

## Metadata
*   **Paper ID:** 22
*   **Identifier:** [arXiv:2405.06821](https://arxiv.org/abs/2405.06821)
*   **Date:** May 2024
*   **Status / Venue:** arXiv preprint (Extra Paper 1)
*   **Role in GMS:** Exploit vector documentation. Explains how prompt injections are sneaked into demonstrations.

---

## 1. Abstract / Key Concept
Exposes MINJA, a class of attacks where malicious payloads are hidden inside agent memory stores to execute arbitrary command loops when retrieved for demonstrations.

---

## 2. Core Mechanism & Methodology
Indirect prompt injection leveraging semantic retrieval matching to sneak payloads into the agent's context window.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{ASR}_{\text{MINJA}} = f(\text{Similarity}(\text{Payload}, \text{User Task}))$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Dictates GMS's strict isolation of demo contexts. Injected memories are quarantined to prevent them from entering few-shot generation pipelines.

---

## 5. Limitations & Vulnerabilities
Only targets agents that automatically retrieve historical memories as few-shot demonstration prompts.
