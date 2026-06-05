# AgentPoison — Red-Teaming Multi-Agent Collaboration

## Metadata
*   **Paper ID:** 10
*   **Identifier:** [NeurIPS 2024](https://arxiv.org/abs/)
*   **Date:** 2024
*   **Status / Venue:** NeurIPS 2024
*   **Role in GMS:** Adversarial simulation. Used to test GMS behavior under worst-case targeted optimization.

---

## 1. Abstract / Key Concept
Presents AgentPoison, the first systematic optimization-based poisoning attack against LLM agents, demonstrating high effectiveness with minimal payload footprints.

---

## 2. Core Mechanism & Methodology
Adversarial prompt generation targeting agent tool schemas, triggering execution loops or credential leaks.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\min_{\delta} ||\delta||_p \quad \text{s.t.} \quad \text{Action}(\text{Agent}(\mathcal{M} \cup \{\delta\})) = \text{Target Exploit}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Used to test the robustness of our SQLite conflict quarantine engine against targeted, optimized key overwrites.

---

## 5. Limitations & Vulnerabilities
Requires complete white-box access to the target model's output distribution to optimize the trigger tokens.
