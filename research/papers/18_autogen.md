# AutoGen — Multi-Agent Conversational Framework

## Metadata
*   **Paper ID:** 18
*   **Identifier:** [arXiv:2308.08155](https://arxiv.org/abs/2308.08155)
*   **Date:** Aug 2023
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Conversation routing. Defines GMS's multi-agent communication and workspace partitions.

---

## 1. Abstract / Key Concept
AutoGen structures multi-agent applications as conversational systems where customizable agents collaborate to solve complex, open-ended tasks.

---

## 2. Core Mechanism & Methodology
Dynamic conversational routing + local tool execution. Lacks a shared, persistent database memory layer.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{NextSpeaker} = \text{Selector}(\mathcal{H}_{\text{conversation}})$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Helps design GMS's branch isolation. We map AutoGen-style conversational agents to separated workspaces, enforcing trust gates before consensus.

---

## 5. Limitations & Vulnerabilities
Agent state is session-bound; does not persist project facts or lessons across subsequent executions.
