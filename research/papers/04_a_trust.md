# A-Trust — Attention-based Trust Management for LLM Multi-Agent Systems

## Metadata
*   **Paper ID:** 04
*   **Identifier:** [arXiv:2506.02546](https://arxiv.org/abs/2506.02546)
*   **Date:** Jun 2025
*   **Status / Venue:** ACL 2026 Main
*   **Role in GMS:** Complementary. Focuses on internal attention weights to classify message reliability rather than memory storage.

---

## 1. Abstract / Key Concept
Proposes evaluating the trustworthiness of agent communications by extracting internal self-attention vectors across layers, bypassing the need for secondary LLM verification prompts.

---

## 2. Core Mechanism & Methodology
Attention vector aggregation + logistic regression classifier trained on attention cues. Cues flag adversarial prompt patterns or incongruent instructions.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{AttentionScore} = \frac{1}{L} \sum_{l=1}^L \text{Mean}(\mathbf{A}_l)$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Can be adapted as a zero-cost validation gate on incoming write streams. High-risk write payloads are flagged based on attention metrics during inference.

---

## 5. Limitations & Vulnerabilities
Highly dependent on model-specific architectures; cannot be easily transferred across different LLMs without retraining.
