# MetaGPT — SOP-driven Multi-Agent Collaboration

## Metadata
*   **Paper ID:** 17
*   **Identifier:** [ICLR 2024](https://arxiv.org/abs/)
*   **Date:** 2024
*   **Status / Venue:** ICLR 2024
*   **Role in GMS:** Orchestration standard. Helps define structured schema roles for different GMS agents.

---

## 1. Abstract / Key Concept
MetaGPT incorporates Standard Operating Procedures (SOPs) into multi-agent systems, assigning structured roles to agents to improve code generation quality.

---

## 2. Core Mechanism & Methodology
SOP-based task execution + role-specific message channels. Lacks long-term cross-session database memory.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{Role}(\text{Agent}) \in \{\text{Engineer}, \text{Architect}, \text{Tester}\}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Allows GMS to configure agent role profiles (e.g. Gemini, Codex) and assign reputation benchmarks based on their standard operating roles.

---

## 5. Limitations & Vulnerabilities
Re-initializes state for every task run, lacking persistence across subsequent executions.
