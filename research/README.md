# GMS SOTA Research Index

This directory contains comprehensive literature reviews, key mechanisms, and integration details for the 21 core papers (and 3 additional SOTA papers) relevant to the **Global Memory System (GMS)** security and trust architecture.

## Literature Taxonomy Table

| # | Paper / Project | Identifier | Date | Status | GMS Focus / Role |
|---|---|---|---|---|---|
| 1 | [SuperLocalMemory V1](papers/01_superlocalmemory_v1.md) | arXiv:2603.02240 | Feb 2026 | arXiv | Primary competitor. Bayesian trust. |
| 2 | [SuperLocalMemory V3](papers/02_superlocalmemory_v3.md) | arXiv:2603.14588 | Mar 2026 | arXiv | Info-geometric manifolds & metrics. |
| 3 | [SuperLocalMemory V3.3](papers/03_superlocalmemory_v3.3.md) | arXiv:2604.04514 | Apr 2026 | arXiv | 7-channel memory & decay. |
| 4 | [A-Trust](papers/04_a_trust.md) | arXiv:2506.02546 | Jun 2025 | ACL 2026 | Attention-based message trust. |
| 5 | [TreeMem](papers/05_treemem.md) | arXiv:2605.04811 | May 2026 | arXiv | Credit assignment & Monte Carlo. |
| 6 | [Misattribution Gap](papers/06_misattribution_gap.md) | arXiv:2605.22842 | May 2026 | Review | Memory vs model misalignment. |
| 7 | [Memory Poisoning EHR](papers/07_memory_poisoning_ehr.md) | arXiv:2601.05504 | Jan 2026 | arXiv | Dynamic prior & EHR agents. |
| 8 | [Agent Security Bench](papers/08_asb.md) | arXiv:2410.02644 | Oct 2024 | ICLR 2025 | Standard exploit scenarios. |
| 9 | [PoisonedRAG](papers/09_poisonedrag.md) | arXiv:2402.07867 | Feb 2024 | arXiv | Injected document RAG exploit. |
| 10 | [AgentPoison](papers/10_agentpoison.md) | NeurIPS 2024 | 2024 | NeurIPS 2024 | Adversarial memory optimization. |
| 11 | [Mem0](papers/11_mem0.md) | arXiv:2504.19413 | Apr 2025 | arXiv | Commercial flat memory benchmark. |
| 12 | [Letta/MemGPT](papers/12_letta_memgpt.md) | arXiv:2310.08560 | Oct 2023 | arXiv | virtual memory & context paging. |
| 13 | [Zep](papers/13_zep.md) | arXiv:2501.13956 | Jan 2025 | arXiv | Temporal Graphiti index. |
| 14 | [A-MEM](papers/14_a_mem.md) | arXiv:2502.12110 | Feb 2025 | arXiv | Zettelkasten atomic link memory. |
| 15 | [MemOS](papers/15_memos.md) | arXiv:2507.03724 | Jul 2025 | arXiv | MemCube metadata structure. |
| 16 | [LongMemEval](papers/16_longmemeval.md) | arXiv:2410.10813 | Oct 2024 | ICLR 2025 | Recall stability benchmark. |
| 17 | [MetaGPT](papers/17_metagpt.md) | ICLR 2024 | 2024 | ICLR 2024 | SOP-driven agent schemas. |
| 18 | [AutoGen](papers/18_autogen.md) | arXiv:2308.08155 | Aug 2023 | arXiv | Multi-agent workspaces. |
| 19 | [Jøsang Beta Reputation](papers/19_josang_reputation.md) | 2002 | 2002 | Bled Conf | Mathematical reputation foundations. |
| 20 | [TRAVOS](papers/20_travos.md) | 2006 | 2006 | AAMAS | Inaccurate witness weighting. |
| 21 | [Dawid & Skene](papers/21_dawid_skene.md) | 1979 | 1979 | JRSS-C | EM solver for sparse ratings. |
| 22 | [MINJA Attack](papers/22_minja_attack.md) | arXiv:2405.06821 | May 2024 | arXiv | Prompt injection in demonstrations. |
| 23 | [RAG Defenses](papers/23_rag_poisoning_defense.md) | arXiv:2411.08291 | Nov 2024 | arXiv | Dual-encoder similarity filtering. |
| 24 | [Semantic Norm Drift](papers/24_semantic_norm_drift.md) | arXiv:2509.05510 | Sep 2025 | arXiv | Centroid drift tracking in FAISS. |

---

## Strategic GMS Application

The Global Memory System (GMS) builds upon this literature to construct a **runtime trust boundary at the database level**. By combining **Jøsang's Beta reputation updates** with **provenance logging**, GMS provides a robust defense against memory poisoning that is fully local-first.

Refer to the individual markdown files in the `papers/` directory for detailed mathematical formulations, summaries, and exact GMS codebase mapping.
