# PoisonedRAG — Knowledge Poisoning Attacks on Retrieval-Augmented Generation

## Metadata
*   **Paper ID:** 09
*   **Identifier:** [arXiv:2402.07867](https://arxiv.org/abs/2402.07867)
*   **Date:** Feb 2024
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Threat vector. Documents how injected documents poison long-term memory via RAG pipelines.

---

## 1. Abstract / Key Concept
Demonstrates that injecting a small number of adversarial passages into a RAG database is sufficient to systematically compromise model responses for targeted topics.

---

## 2. Core Mechanism & Methodology
Adversarial passage injection designed to mislead search algorithms during contextual retrieval.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\arg\max_{\delta} P(\text{Target Response} | \text{Query}, \mathcal{D} \cup \{\delta\})$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** GMS mitigates this by running semantic similarity checks against verified facts before committing RAG summaries to facts.json.

---

## 5. Limitations & Vulnerabilities
Assumes the attacker can directly write raw files to the retrieval database or index directory.
