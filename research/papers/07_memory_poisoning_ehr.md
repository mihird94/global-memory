# Memory Poisoning Attack & Defense (EHR)

## Metadata
*   **Paper ID:** 07
*   **Identifier:** [arXiv:2601.05504](https://arxiv.org/abs/2601.05504)
*   **Date:** Jan 2026
*   **Status / Venue:** arXiv preprint
*   **Role in GMS:** Defense calibration. Shows why static trust thresholds fail under realistic workloads.

---

## 1. Abstract / Key Concept
Analyzes memory poisoning in Electronic Health Record (EHR) agents, establishing that benign memories act as a natural immunization barrier but static trust gates fail due to overconfidence.

---

## 2. Core Mechanism & Methodology
Empirical evaluation of EHR agent retrieval. Recommends dynamic prior calibration and adaptive thresholding to manage trust decisions.

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$$\text{ASR} \propto \frac{1}{1 + \lambda \cdot |\mathcal{M}_{\text{benign}}|}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py](file:///home/mihir/projects/global-memory/tools/memory_mcp_server.py)
*   **How We Apply It:** Motivates GMS's dynamic trust scoring. GMS avoids static threshold values and instead updates trust margins based on running performance.

---

## 5. Limitations & Vulnerabilities
The immunization effect requires a large corpus of pre-existing benign memories, which is not present in newly initialized agent systems.
