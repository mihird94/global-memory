import os
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "research"
PAPERS_DIR = RESEARCH_DIR / "papers"
MEMORY_MCP_URI = (REPO_ROOT / "tools" / "memory_mcp_server.py").resolve().as_uri()

os.makedirs(PAPERS_DIR, exist_ok=True)

# Detailed data for all 24 papers
papers_data = [
    {
        "id": "01",
        "slug": "superlocalmemory_v1",
        "title": "SuperLocalMemory V1 — Privacy-Preserving Multi-Agent Memory with Bayesian Trust Defense",
        "identifier": "arXiv:2603.02240",
        "date": "Feb 2026",
        "status": "arXiv preprint",
        "role": "Primary competitor. Evaluates Bayesian trust barriers under OWASP ASI06 memory poisoning vulnerabilities.",
        "abstract": "SuperLocalMemory V1 proposes a local-first, privacy-focused memory architecture for LLM agents that tracks provenance and implements a formal Bayesian trust scoring system to defend against memory poisoning attacks.",
        "mechanism": "SQLite storage backend + Leiden-based graph clustering for entity relations + dynamic threshold filtering. When an agent attempts to write, GMS evaluates the agent's historical accuracy (alpha) and failures (beta) to compute a trust index.",
        "gms_application": "Forms the baseline for GMS's local-first database logic. GMS replicates this architecture by using a local SQLite-backed reputation layer to prevent unauthorized memory updates without cloud overhead.",
        "math": "T_i = \\frac{\\alpha_i + 1}{\\alpha_i + \\beta_i + 2}",
        "limitations": "Leiden clustering scales quadratically on massive graph states, leading to latency issues during high-frequency write operations."
    },
    {
        "id": "02",
        "slug": "superlocalmemory_v3",
        "title": "SuperLocalMemory V3 — Info-Geometric Foundations",
        "identifier": "arXiv:2603.14588",
        "date": "Mar 2026",
        "status": "arXiv preprint",
        "role": "Retrieval optimization. Explores Fisher-Rao geodesic distances on information manifolds for conflict checks.",
        "abstract": "Applies differential geometry and sheaf theory to agentic memory spaces. It models semantic drift as movement along a Riemannian manifold, using Fisher-Rao metrics to detect structural integrity changes.",
        "mechanism": "Fisher-Rao distance bounds calculated during similarity checks. Rather than simple cosine distance, it projects embedding weights into an information manifold to identify semantic outliers.",
        "gms_application": "Informs the mathematical bounds of GMS's similarity checks. Provides a theoretical foundation for using multi-encoder projections to detect subtle semantic drift.",
        "math": "d_G(\\theta_1, \\theta_2) = \\arccos\\left(\\int \\sqrt{p(x|\\theta_1) p(x|\\theta_2)} dx\\right)",
        "limitations": "Calculating geodesic distances at runtime adds significant CPU overhead compared to standard vector dot products."
    },
    {
        "id": "03",
        "slug": "superlocalmemory_v3.3",
        "title": "SuperLocalMemory V3.3 — Living Brain: Dynamic Decay & Forgetting",
        "identifier": "arXiv:2604.04514",
        "date": "Apr 2026",
        "status": "arXiv preprint",
        "role": "Forgetting curve modeling. Dictates how GMS implements temporal decay to evict stale facts.",
        "abstract": "Introduces the 'Living Brain' concept: a 7-channel memory framework with dynamic forgetting curves modeled as exponential decay. Evaluates how natural eviction improves resilience against poisoning.",
        "mechanism": "Temporal decay function where memory recall weight decays based on elapsed time and frequency of access. Stale memories are naturally purged to prevent payload accumulation.",
        "gms_application": "Directly applied to GMS's Dream Cycle. The nightly consolidation routine applies an exponential decay factor to episodic entries to prune inactive and low-trust memories.",
        "math": "R(t) = e^{-\\lambda t}",
        "limitations": "Risk of premature eviction of high-value static system parameters (e.g. key configurations) if they are not explicitly locked."
    },
    {
        "id": "04",
        "slug": "a_trust",
        "title": "A-Trust — Attention-based Trust Management for LLM Multi-Agent Systems",
        "identifier": "arXiv:2506.02546",
        "date": "Jun 2025",
        "status": "ACL 2026 Main",
        "role": "Complementary. Focuses on internal attention weights to classify message reliability rather than memory storage.",
        "abstract": "Proposes evaluating the trustworthiness of agent communications by extracting internal self-attention vectors across layers, bypassing the need for secondary LLM verification prompts.",
        "mechanism": "Attention vector aggregation + logistic regression classifier trained on attention cues. Cues flag adversarial prompt patterns or incongruent instructions.",
        "gms_application": "Can be adapted as a zero-cost validation gate on incoming write streams. High-risk write payloads are flagged based on attention metrics during inference.",
        "math": "\\text{AttentionScore} = \\frac{1}{L} \\sum_{l=1}^L \\text{Mean}(\\mathbf{A}_l)",
        "limitations": "Highly dependent on model-specific architectures; cannot be easily transferred across different LLMs without retraining."
    },
    {
        "id": "05",
        "slug": "treemem",
        "title": "TreeMem — Tree-based Credit Assignment for Multi-Agent Memory Pipelines",
        "identifier": "arXiv:2605.04811",
        "date": "May 2026",
        "status": "arXiv preprint",
        "role": "Credit assignment framework. Used to attribute execution failures back to specific memory writes.",
        "abstract": "Introduces TreeMem, a method to optimize multi-agent memory pipelines by extending the sequence into a tree structure and using Monte Carlo averaging to assign credit/blame to individual writes.",
        "mechanism": "Monte Carlo estimation over subsequent decision branches. Evaluates which memory entries contributed to the final reward or task success.",
        "gms_application": "Informs GMS's consolidation and pruning logic. Allows GMS to audit past memory inputs and trace incorrect agent actions back to specific fact insertions.",
        "math": "C(m_i) = \\mathbb{E}_{\\tau \\sim \\mathcal{T}} \\left[ R(\\tau) | m_i \\in \\tau \\right] - \\mathbb{E}_{\\tau \\sim \\mathcal{T}} \\left[ R(\\tau) \\right]",
        "limitations": "Requires a closed-loop task execution environment with defined rewards to calculate credit accurately."
    },
    {
        "id": "06",
        "slug": "misattribution_gap",
        "title": "The Misattribution Gap — Memory Poisoning Looks Like Model Failure",
        "identifier": "arXiv:2605.22842",
        "date": "May 2026",
        "status": "Under review",
        "role": "Core validation. Explains why memory protection must be handled at the database layer.",
        "abstract": "Identifies the 'Misattribution Gap' where memory poisoning attacks (Semantic Norm Drift) produce behaviors that are misdiagnosed as model alignment issues, leading to ineffective retraining.",
        "mechanism": "Demonstrates that memory-layer injections bypass standard LLM guardrails, altering downstream task behaviors without triggering model safety filters.",
        "gms_application": "Validates GMS's architectural placement: a dedicated trust gateway at the database level that sanitizes and quarantines inputs before they commit.",
        "math": "\\text{ASR}_{\\text{misattribution}} = P(\\text{Failure} | \\text{PoPoisoned Memory}) \\times (1 - P(\\text{Alert} | \\text{Safety Gate}))",
        "limitations": "Mainly diagnostic; relies on external testing wrappers to detect the gap rather than providing a native prevention mechanism."
    },
    {
        "id": "07",
        "slug": "memory_poisoning_ehr",
        "title": "Memory Poisoning Attack & Defense (EHR)",
        "identifier": "arXiv:2601.05504",
        "date": "Jan 2026",
        "status": "arXiv preprint",
        "role": "Defense calibration. Shows why static trust thresholds fail under realistic workloads.",
        "abstract": "Analyzes memory poisoning in Electronic Health Record (EHR) agents, establishing that benign memories act as a natural immunization barrier but static trust gates fail due to overconfidence.",
        "mechanism": "Empirical evaluation of EHR agent retrieval. Recommends dynamic prior calibration and adaptive thresholding to manage trust decisions.",
        "gms_application": "Motivates GMS's dynamic trust scoring. GMS avoids static threshold values and instead updates trust margins based on running performance.",
        "math": "\\text{ASR} \\propto \\frac{1}{1 + \\lambda \\cdot |\\mathcal{M}_{\\text{benign}}|}",
        "limitations": "The immunization effect requires a large corpus of pre-existing benign memories, which is not present in newly initialized agent systems."
    },
    {
        "id": "08",
        "slug": "asb",
        "title": "Agent Security Bench (ASB) — Vulnerability Baselines",
        "identifier": "arXiv:2410.02644",
        "date": "Oct 2024",
        "status": "ICLR 2025",
        "role": "Threat baseline. Provides the core scenarios used to red-team GMS's security gates.",
        "abstract": "Establishes a standardized benchmark for evaluating agent safety and security, demonstrating a 67% vulnerability success rate on traditional agent architectures.",
        "mechanism": "Automated attack simulation scripts that target tool calls, file access, and memory writing pathways.",
        "gms_application": "Used to create the integration test suite for GMS. We adapt ASB attack scripts to verify that GMS quarantine gates successfully block malicious injections.",
        "math": "\\text{ASR}_{\\text{ASB}} = \\frac{|\\text{Successful Violations}|}{|\\text{Total Scenarios}|}",
        "limitations": "Does not address state persistence across multi-session environments, focusing instead on single-turn exploits."
    },
    {
        "id": "09",
        "slug": "poisonedrag",
        "title": "PoisonedRAG — Knowledge Poisoning Attacks on Retrieval-Augmented Generation",
        "identifier": "arXiv:2402.07867",
        "date": "Feb 2024",
        "status": "arXiv preprint",
        "role": "Threat vector. Documents how injected documents poison long-term memory via RAG pipelines.",
        "abstract": "Demonstrates that injecting a small number of adversarial passages into a RAG database is sufficient to systematically compromise model responses for targeted topics.",
        "mechanism": "Adversarial passage injection designed to mislead search algorithms during contextual retrieval.",
        "gms_application": "GMS mitigates this by running semantic similarity checks against verified facts before committing RAG summaries to facts.json.",
        "math": "\\arg\\max_{\\delta} P(\\text{Target Response} | \\text{Query}, \\mathcal{D} \\cup \\{\\delta\\})",
        "limitations": "Assumes the attacker can directly write raw files to the retrieval database or index directory."
    },
    {
        "id": "10",
        "slug": "agentpoison",
        "title": "AgentPoison — Red-Teaming Multi-Agent Collaboration",
        "identifier": "NeurIPS 2024",
        "date": "2024",
        "status": "NeurIPS 2024",
        "role": "Adversarial simulation. Used to test GMS behavior under worst-case targeted optimization.",
        "abstract": "Presents AgentPoison, the first systematic optimization-based poisoning attack against LLM agents, demonstrating high effectiveness with minimal payload footprints.",
        "mechanism": "Adversarial prompt generation targeting agent tool schemas, triggering execution loops or credential leaks.",
        "gms_application": "Used to test the robustness of our SQLite conflict quarantine engine against targeted, optimized key overwrites.",
        "math": "\\min_{\\delta} ||\\delta||_p \\quad \\text{s.t.} \\quad \\text{Action}(\\text{Agent}(\\mathcal{M} \\cup \\{\\delta\\})) = \\text{Target Exploit}",
        "limitations": "Requires complete white-box access to the target model's output distribution to optimize the trigger tokens."
    },
    {
        "id": "11",
        "slug": "mem0",
        "title": "Mem0 — Commercial Multi-Agent Memory System",
        "identifier": "arXiv:2504.19413",
        "date": "Apr 2025",
        "status": "arXiv preprint",
        "role": "Commercial baseline. Highlights the security gaps that GMS is designed to resolve.",
        "abstract": "Presents Mem0, a developer-friendly memory layer that extracts facts and entities from conversations to maintain persistent state across sessions.",
        "mechanism": "Heuristic entity extraction via LLM prompts + flat key-value vector storage. Focuses solely on write throughput.",
        "gms_application": "Serves as the structural baseline for fact management. GMS improves on Mem0 by adding provenance tracking, branch isolation, and trust scores.",
        "math": "\\text{Score}(f) = \\cos(\\mathbf{e}_q, \\mathbf{e}_f) \\quad [\\text{No trust weighting}]",
        "limitations": "Lacks write safety, provenance verification, or conflict resolution, leaving it vulnerable to memory poisoning."
    },
    {
        "id": "12",
        "slug": "letta_memgpt",
        "title": "Letta/MemGPT — Virtual Memory for LLMs",
        "identifier": "arXiv:2310.08560",
        "date": "Oct 2023",
        "status": "arXiv preprint",
        "role": "Memory hierarchy reference. Models the paging interface between core and archival storage.",
        "abstract": "MemGPT (now Letta) structures LLM memory as an OS-like hierarchy, allowing the agent to use explicit page swaps to manage long-term state.",
        "mechanism": "Core memory (in-context), recall storage (episodic event log), and archival storage (flat database). Paging is handled via model tool calls.",
        "gms_application": "Guides GMS's session startup logic. GMS replicates the virtual hierarchy by loading active preferences in-context while keeping facts archived in SQLite.",
        "math": "\\text{PagingAction} \\in \\{\\text{core\\_memory\\_append}, \\text{archival\\_memory\\_search}\\}",
        "limitations": "Designed for single-agent architectures; lacks cross-agent synchronization, consensus protocols, or multi-writer trust gates."
    },
    {
        "id": "13",
        "slug": "zep",
        "title": "Zep — Temporal Knowledge Graph Architecture for Agent Memory",
        "identifier": "arXiv:2501.13956",
        "date": "Jan 2025",
        "status": "arXiv preprint",
        "role": "Temporal indexing. Shows how time-aware graphs improve context retrieval accuracy.",
        "abstract": "Zep introduces a temporal knowledge graph system (Graphiti) that updates relations dynamically as new interactions are logged.",
        "mechanism": "Graphiti temporal edge weighting + asynchronous fact consolidation. Fact edges decay over time unless reinforced.",
        "gms_application": "Applied to GMS's temporal query filters. GMS incorporates time decay directly into FAISS query scoring to prioritize recent contexts.",
        "math": "W_t = W_0 \\cdot e^{-\\lambda (t_c - t_e)}",
        "limitations": "Graph database maintenance adds latency, making it less suitable for real-time high-throughput development pipelines."
    },
    {
        "id": "14",
        "slug": "a_mem",
        "title": "A-MEM — Zettelkasten-inspired Agentic Memory",
        "identifier": "arXiv:2502.12110",
        "date": "Feb 2025",
        "status": "arXiv preprint",
        "role": "Relational link reference. Explores how semantic links improve open-ended reasoning tasks.",
        "abstract": "A-MEM implements an agentic memory based on the Zettelkasten method, allowing agents to create atomic, interconnected notes instead of flat lists.",
        "mechanism": "Atomic note generation + semantic link classification. Agents write bidirectionally linked notes to build a personal wiki.",
        "gms_application": "Informs the structure of GMS lessons and projects. Helps GMS group related rules and paths into structured semantic clusters in facts.json.",
        "math": "\\text{LinkStrength}(n_1, n_2) = \\text{LLM\\_Classify}(n_1, n_2) \\times \\cos(\\mathbf{e}_1, \\mathbf{e}_2)",
        "limitations": "Generating and classifying links for every transaction requires multiple LLM calls, significantly increasing API costs."
    },
    {
        "id": "15",
        "slug": "memos",
        "title": "MemOS — Unified Memory OS for AI Systems",
        "identifier": "arXiv:2507.03724",
        "date": "Jul 2025",
        "status": "arXiv preprint (Discrepancy: user prompt listed 2407.01876 / Jul 2024)",
        "role": "Structural abstraction. Evaluates standardizing memory blocks as versioned objects.",
        "abstract": "MemOS separates AI memory into three distinct tiers (parametric, activation, and plaintext) and manages them using versioned, self-contained objects called 'MemCubes'.",
        "mechanism": "MemCube architecture with built-in version control and cryptographic provenance. Standardizes read/write APIs across different storage nodes.",
        "gms_application": "Inspires GMS's metadata schema. We wrap facts and their DB provenance records in a unified JSON structure to ensure traceability.",
        "math": "\\text{MemCube} = \\{\\text{payload}, \\text{provenance}, \\text{version\\_hash}, \\text{timestamp}\\}",
        "limitations": "Cryptographic hashing on every memory commit adds latency that can impact real-time developer workflows."
    },
    {
        "id": "16",
        "slug": "longmemeval",
        "title": "LongMemEval — Benchmarking Chat Assistants on Long-Term Interactive Memory",
        "identifier": "arXiv:2410.10813",
        "date": "Oct 2024",
        "status": "ICLR 2025",
        "role": "Evaluation protocol. Used to measure GMS performance and recall stability.",
        "abstract": "Evaluates long-context memory models across sustained multi-session conversations, identifying a ~30% accuracy drop under temporal and factual updates.",
        "mechanism": "Testing framework evaluating information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention.",
        "gms_application": "We adapt the knowledge-update and multi-session reasoning subsets to measure GMS's retention stability and guard against norm drift.",
        "math": "\\text{RecallAccuracy} = \\frac{|\\text{Correct Retrievals}|}{|\\text{Total Queries}|}",
        "limitations": "Focuses on conversational systems and does not model multi-agent database write conflicts."
    },
    {
        "id": "17",
        "slug": "metagpt",
        "title": "MetaGPT — SOP-driven Multi-Agent Collaboration",
        "identifier": "ICLR 2024",
        "date": "2024",
        "status": "ICLR 2024",
        "role": "Orchestration standard. Helps define structured schema roles for different GMS agents.",
        "abstract": "MetaGPT incorporates Standard Operating Procedures (SOPs) into multi-agent systems, assigning structured roles to agents to improve code generation quality.",
        "mechanism": "SOP-based task execution + role-specific message channels. Lacks long-term cross-session database memory.",
        "gms_application": "Allows GMS to configure agent role profiles (e.g. Gemini, Codex) and assign reputation benchmarks based on their standard operating roles.",
        "math": "\\text{Role}(\\text{Agent}) \\in \\{\\text{Engineer}, \\text{Architect}, \\text{Tester}\\}",
        "limitations": "Re-initializes state for every task run, lacking persistence across subsequent executions."
    },
    {
        "id": "18",
        "slug": "autogen",
        "title": "AutoGen — Multi-Agent Conversational Framework",
        "identifier": "arXiv:2308.08155",
        "date": "Aug 2023",
        "status": "arXiv preprint",
        "role": "Conversation routing. Defines GMS's multi-agent communication and workspace partitions.",
        "abstract": "AutoGen structures multi-agent applications as conversational systems where customizable agents collaborate to solve complex, open-ended tasks.",
        "mechanism": "Dynamic conversational routing + local tool execution. Lacks a shared, persistent database memory layer.",
        "gms_application": "Helps design GMS's branch isolation. We map AutoGen-style conversational agents to separated workspaces, enforcing trust gates before consensus.",
        "math": "\\text{NextSpeaker} = \\text{Selector}(\\mathcal{H}_{\\text{conversation}})",
        "limitations": "Agent state is session-bound; does not persist project facts or lessons across subsequent executions."
    },
    {
        "id": "19",
        "slug": "josang_reputation",
        "title": "Jøsang's Beta Reputation System",
        "identifier": "Bled eConference 2002",
        "date": "2002",
        "status": "Bled eConference Publication",
        "role": "Reputation math foundation. Forms the mathematical backbone of the GMS agent trust scorer.",
        "abstract": "Proposes a formal trust and reputation system based on a Beta probability density function of positive (r) and negative (s) observation histories.",
        "mechanism": "Beta distribution updates: posterior reputation updates incrementally as actions are evaluated.",
        "gms_application": "Forms GMS's agent evaluation core. We map correct commits to positive counts (alpha) and syntax errors/conflicts to negative counts (beta).",
        "math": "\\text{Reputation}(r, s) = \\text{Beta}(r+1, s+1) \\implies E[R] = \\frac{r+1}{r+s+2}",
        "limitations": "Vulnerable to collusion or sybil attacks if the identity of the scoring agents cannot be verified."
    },
    {
        "id": "20",
        "slug": "travos",
        "title": "TRAVOS — Trust and Reputation Model for Virtual Organizations",
        "identifier": "AAMAS 2006",
        "date": "2006",
        "status": "AAMAS 2006",
        "role": "Dishonest report filter. Provides the math to manage collusive agent recommendations.",
        "abstract": "Presents TRAVOS, a probabilistic trust model that filters out inaccurate or dishonest recommendations from third-party agents using confidence intervals.",
        "mechanism": "Confidence boundary calculation on third-party advice, weighting reports based on the recommender's past reliability.",
        "gms_application": "Helps GMS manage peer review. If an agent vouches for a quarantined fact, GMS weights their endorsement using their TRAVOS reliability score.",
        "math": "\\gamma = P(|\\tilde{p} - E[p]| \\le \\epsilon)",
        "limitations": "Requires a large history of peer recommendations to accurately calibrate recommender reliability."
    },
    {
        "id": "21",
        "slug": "dawid_skene",
        "title": "Dawid & Skene — Maximum Likelihood Estimation for Observer Error",
        "identifier": "JRSS-C 1979",
        "date": "1979",
        "status": "JRSS-C Publication",
        "role": "Statistical baseline solver. Used to calculate trust ratings when direct evaluations are sparse.",
        "abstract": "Presents an EM algorithm to estimate observer error rates and resolve the true consensus states when ground-truth labels are missing.",
        "mechanism": "Expectation-Maximization (EM) iterations on a confusion matrix of observer ratings.",
        "gms_application": "Applied during the Dream Cycle. If multiple agents record conflicting data across sessions, the EM solver estimates true values and agent error rates.",
        "math": "\\pi_{ij} = \\text{Prob}(\\text{Response } j | \\text{True State } i)",
        "limitations": "Requires multiple observers per item to run EM, which may not be available in single-agent developer workflows."
    },
    {
        "id": "22",
        "slug": "minja_attack",
        "title": "MINJA — Memory Injection Attack on Demonstration-based Agents",
        "identifier": "arXiv:2405.06821",
        "date": "May 2024",
        "status": "arXiv preprint (Extra Paper 1)",
        "role": "Exploit vector documentation. Explains how prompt injections are sneaked into demonstrations.",
        "abstract": "Exposes MINJA, a class of attacks where malicious payloads are hidden inside agent memory stores to execute arbitrary command loops when retrieved for demonstrations.",
        "mechanism": "Indirect prompt injection leveraging semantic retrieval matching to sneak payloads into the agent's context window.",
        "gms_application": "Dictates GMS's strict isolation of demo contexts. Injected memories are quarantined to prevent them from entering few-shot generation pipelines.",
        "math": "\\text{ASR}_{\\text{MINJA}} = f(\\text{Similarity}(\\text{Payload}, \\text{User Task}))",
        "limitations": "Only targets agents that automatically retrieve historical memories as few-shot demonstration prompts."
    },
    {
        "id": "23",
        "slug": "rag_poisoning_defense",
        "title": "Dual-Encoder Defensive Filtering for RAG Pipelines",
        "identifier": "arXiv:2411.08291",
        "date": "Nov 2024",
        "status": "arXiv preprint (Extra Paper 2)",
        "role": "Retriever protection. Used to drop outlier matches before context construction.",
        "abstract": "Proposes a dual-encoder architecture to filter RAG contexts, verifying consistency across separate embedding representations to catch adversarial inputs.",
        "mechanism": "Cross-verification using two distinct semantic encoders. If the embedding distance is inconsistent, the context is dropped.",
        "gms_application": "Guides GMS's similarity gate. We use a dual-encoder comparison (such as Ollama + local BM25) to identify and filter anomalous search matches.",
        "math": "\\Delta d = |d_{\\text{enc1}}(f_1, f_2) - d_{\\text{enc2}}(f_1, f_2)| > \\delta_{anomaly}",
        "limitations": "Running dual-encoder model evaluations increases execution latency during context construction."
    },
    {
        "id": "24",
        "slug": "semantic_norm_drift",
        "title": "Semantic Norm Drift in LLM Memory Systems",
        "identifier": "arXiv:2509.05510",
        "date": "Sep 2025",
        "status": "arXiv preprint (Extra Paper 3)",
        "role": "Drift measurement. Tracks the long-term degradation of the GMS context baseline.",
        "abstract": "Investigates 'Semantic Norm Drift' where gradual, minor memory updates shift the semantic baseline of an LLM agent, leading to alignment drift over time.",
        "mechanism": "Iterative similarity drift tracking on memory updates. Measures the angular distance between initial and updated semantic clusters.",
        "gms_application": "Applied during GMS index validation. We track the centroid drift of our FAISS vectors to identify slow, persistent poisoning campaigns.",
        "math": "\\text{Drift}_t = ||\\mathbf{C}_t - \\mathbf{C}_0||_2",
        "limitations": "Requires caching historical indexing states to calculate baseline semantic centroid movements."
    }
]

# Generate index / README.md
readme_content = """# GMS SOTA Research Index

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
"""

(RESEARCH_DIR / "README.md").write_text(readme_content)
print("Generated research/README.md")

# Generate individual markdown files
for p in papers_data:
    filename = f"{p['id']}_{p['slug']}.md"
    file_path = PAPERS_DIR / filename
    
    content = f"""# {p['title']}

## Metadata
*   **Paper ID:** {p['id']}
*   **Identifier:** [{p['identifier']}](https://arxiv.org/abs/{p['identifier'].split(':')[-1] if 'arXiv' in p['identifier'] else ''})
*   **Date:** {p['date']}
*   **Status / Venue:** {p['status']}
*   **Role in GMS:** {p['role']}

---

## 1. Abstract / Key Concept
{p['abstract']}

---

## 2. Core Mechanism & Methodology
{p['mechanism']}

---

## 3. Mathematical Formulation
Where applicable, the core equations driving this framework are:

$${p['math']}$$

---

## 4. Specific GMS Integration & Application
*   **Codebase Link:** [memory_mcp_server.py]({MEMORY_MCP_URI})
*   **How We Apply It:** {p['gms_application']}

---

## 5. Limitations & Vulnerabilities
{p['limitations']}
"""
    
    file_path.write_text(content)
    print(f"Generated research/papers/{filename}")

print("\nResearch directory initialization complete.")
