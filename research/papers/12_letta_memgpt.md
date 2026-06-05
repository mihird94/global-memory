# Letta/MemGPT — Virtual Memory for LLMs

## Metadata
*   **Paper ID:** 12
*   **Identifier:** [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
*   **Date:** Oct 2023
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Memory hierarchy reference. Models the paging interface between core and archival storage.

---

## 1. Abstract / Key Concept
MemGPT (now Letta) structures LLM memory as an OS-like hierarchy, allowing the agent to use explicit page swaps to manage long-term state.

---

## 2. Core Mechanism & Methodology
Core memory (in-context), recall storage (episodic event log), and archival storage (flat database). Paging is handled via model tool calls.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{PagingAction} \in \{\text{core\_memory\_append}, \text{archival\_memory\_search}\}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Guides GMS's session startup logic. GMS replicates the virtual hierarchy by loading active preferences in-context while keeping facts archived in SQLite.

---

## 5. Limitations & Vulnerabilities
Designed for single-agent architectures; lacks cross-agent synchronization, consensus protocols, or multi-writer trust gates.
