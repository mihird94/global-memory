# Dual-Encoder Defensive Filtering for RAG Pipelines

## Metadata
*   **Paper ID:** 23
*   **Identifier:** [arXiv:2411.08291](https://arxiv.org/abs/2411.08291)
*   **Date:** Nov 2024
*   **Status / Venue:** arXiv preprint (Extra Paper 2)
*   **Role in GMS:** Retriever protection. Used to drop outlier matches before context construction.

---

## 1. Abstract / Key Concept
Proposes a dual-encoder architecture to filter RAG contexts, verifying consistency across separate embedding representations to catch adversarial inputs.

---

## 2. Core Mechanism & Methodology
Cross-verification using two distinct semantic encoders. If the embedding distance is inconsistent, the context is dropped.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\Delta d = |d_{\text{enc1}}(f_1, f_2) - d_{\text{enc2}}(f_1, f_2)| > \delta_{anomaly}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Guides GMS's similarity gate. We use a dual-encoder comparison (such as Ollama + local BM25) to identify and filter anomalous search matches.

---

## 5. Limitations & Vulnerabilities
Running dual-encoder model evaluations increases execution latency during context construction.
