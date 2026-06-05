# Dawid & Skene — Maximum Likelihood Estimation for Observer Error

## Metadata
*   **Paper ID:** 21
*   **Identifier:** [JRSS-C 1979](https://arxiv.org/abs/)
*   **Date:** 1979
*   **Status / Venue:** JRSS-C Publication
*   **Role in GMS:** Statistical baseline solver. Used to calculate trust ratings when direct evaluations are sparse.

---

## 1. Abstract / Key Concept
Presents an EM algorithm to estimate observer error rates and resolve the true consensus states when ground-truth labels are missing.

---

## 2. Core Mechanism & Methodology
Expectation-Maximization (EM) iterations on a confusion matrix of observer ratings.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\pi_{ij} = \text{Prob}(\text{Response } j | \text{True State } i)$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Applied during the Dream Cycle. If multiple agents record conflicting data across sessions, the EM solver estimates true values and agent error rates.

---

## 5. Limitations & Vulnerabilities
Requires multiple observers per item to run EM, which may not be available in single-agent developer workflows.
