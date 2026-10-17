# Local Agent Memory Under Resource Constraints: Retrieval Sufficiency and Safe Consolidation

**Track:** Empirical Systems & Applied AI Engineering  
**Status:** Development & Pilot Empirical Study v1.2 (Frozen `.venv` Retrieval Ablations, Deduplicated Surrogate Storage Audit, Deterministic Graph-Boundary Controls, and Durable Single-Fixture `qwen3:8b` Thinking-Mode Intervention Bundle)

---

## Abstract

Deploying persistent memory for multi-agent software engineering workflows locally on consumer hardware (Apple Silicon unified memory) introduces operational constraints that differ from cloud-hosted retrieval systems: (1) retrieved fragments that match query keywords may still be stale, conflicted, or uncorroborated for high-privilege execution; (2) background LLM consolidation must operate within fixed token and resident-memory budgets without starving structured JSON generation; (3) unguarded local LLM harvesting extracts sensitive tokens and conversational noise from work journals; and (4) multi-agent shared memory can act as a vector for *endogenous authorization laundering* (Cerruti et al., 2026), where low-trust background harvesters inject unverified procedural rules into high-privilege coding harnesses.

We present a development and pilot empirical systems study of the **Global Memory System (GMS)**, evaluating its daytime multi-lane retrieval pipeline and nighttime local consolidation workflow under resource constraints. Across a 142-case local regression and abstention suite (31 canonical scenarios and 111 correlated variants), GMS's four-state sufficiency heuristic (`supported`, `conflicted`, `stale`, `insufficient`) achieves **142/142 (100.0%)** pass rate with median retrieval latency of **2.43 ms** (mean = 3.94 ms). In a frozen 5-method retrieval ablation over 45 evaluated queries per strategy (`ablation_run_20261017_102439.json`), multi-lane fusion achieves median latency of **2.38 ms** (`hybrid_rrf`, P95 = 3.17 ms) and **8.22 ms** (`hybrid_reranked` in `.venv`, P95 = 18.81 ms). We formalize the **Two-Channel Decoding Starvation Inequality** for hybrid reasoning models under consumer completion ceilings ($B = \texttt{num\_predict}$). In one `qwen3:8b` fixture under a 1,536-token completion cap, thinking-enabled generation exhausted the budget without a visible response (`7,183` thinking chars, `0` response chars, `done_reason="length"`), whereas suppressing internal reasoning (`think=False`) produced complete JSON extraction (`564` tokens, `2,054` response chars, `2` valid candidates in `55.06s`); this is a configuration-specific observation, not a universal necessity or sufficiency result. In a surrogate isolated temporary persistence and readback audit (`facts.json` + SQLite), deterministic schema and secret-pattern admission gates block 100% of raw credential leaks (`sk-live-...`) and reduce total prohibited candidate matches from **`6/13` raw LLM candidates to `1/7` unique admitted/persisted candidate records**. Finally, we formalize GMS's **Cross-Harness Trust Boundary** (`requires_corroboration=True`): for operational resume and procedure intents, the heuristic withholds actionability when every relevant focus item requires corroboration. Mixed verified/unverified packets remain a limitation; this is an intent-scoped heuristic, not a claim-level authorization reference monitor or demonstrated end-to-end defense against authorization laundering.

---

## 1. Introduction & Positioning

Developer agents operating across IDE sessions, CLI workflows, and background tasks benefit from a shared local memory layer that preserves architectural decisions, operational procedures, and project state. Prior work established the foundations of tiered agent memory—most notably **MemGPT** (Packer et al., 2023, `arXiv:2310.08560`), which manages virtual context paging between active and archival tiers, and offline sleep-style consolidation such as **SCM** (`arXiv:2604.20943`) and **Mem0**.

Recent breakthroughs in late 2026 have brought renewed scrutiny to the safety, consistency, and resource bounds of agent memory:
* **Cascading Invalidation & Validity Lattices:** **PACMI** (Wang et al., Oct 2026, `arXiv:2610.05732`) introduced a 4-state validity lattice and typed dependency edges for long-term agent memory. PACMI demonstrated a statistically significant improvement on primary final-answer accuracy against its strongest baseline, while its cascading-removal ablation did not reach statistical significance on paired text QA. GMS targets a complementary focus: deterministic sub-millisecond retrieval sufficiency and executable action recovery.
* **Endogenous Authorization Laundering:** Cerruti et al. (Sept 2026, `arXiv:2609.01836`) demonstrated that shared agent memory surfaces enable *endogenous authorization laundering*, where low-trust or untrusted inputs are promoted into trusted agent memory, conferring unintended execution privileges across sessions. This directly motivates GMS's multi-agent trust boundary and corroboration gating.
* **Transaction Boundaries for Updates:** Cui et al. (July 2026, `arXiv:2607.27834`, *MemTxn*) formalized transactional boundaries for source-supported memory updates, reinforcing the need for atomic persistence invariants.
* **Reasoning-Channel Termination in Coding Agents:** Recent audits of coding agent memory (**VibeMemBench**, Sept 2026, `arXiv:2609.23570`; *Coding-Agent Memory After a Reset*, OpenReview 2026) have independently identified that reasoning-channel starvation (`think` token exhaustion) and output truncation severely impair coding harnesses operating under bounded context limits.

Rather than claiming architectural priority on tiered retrieval or claiming broad generalization from development fixtures, this paper investigates **concrete engineering failure modes and measurement pitfalls when running local agent memory under consumer hardware constraints**:

1. **Retrieval Similarity vs. Deterministic Evidence Sufficiency:** High BM25 or vector similarity does not guarantee that retrieved records are current, unconflicted, or sufficiently overlapping with material query terms. We formalize and evaluate the exact four-state deterministic sufficiency heuristic (`supported`, `conflicted`, `stale`, `insufficient`) implemented in GMS, including a content-preserving token partition repair for queries where framing terms (`snapshot`, `retrieval`) are the sole subject.
2. **Thinking-Token Starvation Under Fixed Consolidation Budgets:** When running local hybrid reasoning models via Ollama (`/api/generate`) with bounded completion budgets (`num_predict=1536`), models that emit extended reasoning in the separate `thinking` field (`https://docs.ollama.com/capabilities/thinking`) can exhaust `num_predict` before writing JSON to `response`. We formalize the **Two-Channel Decoding Starvation Inequality** and isolate this mechanism using durable empirical bundles on `qwen3:8b` ([`thinking_intervention_qwen3_8b_20261017.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json)).
3. **Cross-Harness Trust Boundaries Against Authorization Laundering:** For operational resume and procedure intents, GMS evaluates an intent-scoped heuristic that withholds actionability when every relevant focus item requires corroboration (`requires_corroboration=True`). We document its structural limitation on mixed-authority candidate packets, distinguishing this heuristic gate from a claim-level authorization reference monitor.
4. **Surrogate Storage-Boundary Auditing & Graph Boundary Controls:** Counting prohibited strings only in in-memory candidate dictionaries overstates safety, while conflating JSON and SQLite copies inflates record denominators. We implement a surrogate isolated persistence and readback audit ([`verify_isolated_storage_boundary`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py#L420-L545)) with deduplicated record denominators (`7` unique candidate records vs. `14` JSON+SQLite representation rows) alongside deterministic positive and negative graph-boundary controls ([`evaluate_graph_boundary_controls`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py#L548-L639)).

```mermaid
flowchart LR
    subgraph FastPath["Daytime Retrieval Pipeline (tools/context_retrieval_planner.py)"]
        Q["Agent Query"] --> L["10 Retrieval Lanes (Exact, BM25, Vector, Graph, Decisions, Tasks...)"]
        L --> RRF["Weighted RRF + Stage 1 Scope/Temporal/Lifecycle Filter"]
        RRF --> BOOST["Stage 2 Bounded Intent-Gated Recency Boost (<= 1.25x)"]
        BOOST --> GATE{"4-State Sufficiency Heuristic (_classify_evidence)"}
        GATE -->|supported| AUTH{"Cross-Harness Trust Check (requires_corroboration)"}
        AUTH -->|Corroborated| PKT["Actionable Context Packet"]
        AUTH -->|Uncorroborated & Action Intent| ABS["Abstain: Requires Corroboration"]
        GATE -->|conflicted / stale / insufficient| ABS
    end

    subgraph Consolidation["Offline Consolidation Pilot (tools/eval_model_harvesting.py)"]
        J["Episodic Excerpt"] --> ROUTE{"Proposed Tiered Routing: Modal Regex vs. LLM"}
        ROUTE -->|Explicit Modal (0.4ms)| REG["Deterministic Regex Parser (F1=0.889)"]
        ROUTE -->|Implicit Transition| OLL["Local Ollama Harvester (think=False, num_predict=1536)"]
        REG & OLL --> VAL{"Schema + Secret-Pattern Admission Gate"}
        VAL -->|Admitted| TMP[("Surrogate Isolated Store: facts.json + SQLite")]
        TMP --> READ["Deduplicated Disk Readback & Surrogate Projection Audit"]
        OLL --> UNL["Explicit Unload (keep_alive: 0 + Reachable /api/ps Check)"]
    end
```

---

## 2. Implemented Retrieval & Sufficiency Architecture

To avoid any divergence between mathematical notation and executable code, we formalize the exact behavior implemented in [`tools/context_retrieval_planner.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py) and [`tools/schemas.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/schemas.py).

### 2.1 Dual-Timestamp Record Representation (Valid Time vs. Transaction Time)

Each structured context record $v_i$ validated by [`validate_context_candidate`](file:///Users/mihirdeshpande/projects/global-memory/tools/schemas.py) distinguishes two temporal dimensions:
* **Transaction / Ingestion Time ($t_{\text{ext}}$):** Recorded in `provenance.extracted_at` (with SHA-256 source integrity hashes `provenance.source_hashes` verifying that the source text has not been mutated since extraction). Note that SHA-256 hashing establishes *record integrity and provenance binding*, not factual truth of the underlying statement.
* **Valid / Effective Time ($[t_{\text{eff}}, t_{\text{exp}})$):** Recorded in `effective_at` and `expires_at` (alongside explicit supersession pointers `freshness.supersedes` and `lifecycle_status` $\in \{\texttt{active}, \texttt{accepted}, \texttt{archived}, \texttt{superseded}, \texttt{quarantined}, \texttt{contested}, \texttt{discarded}, \texttt{expired}\}$). Point-in-time historical queries (`as_of`) filter records where `effective_at > as_of` in Stage 1 ([`context_retrieval_planner.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py#L1796-L1800)).

### 2.2 Weighted RRF & Bounded Stage-2 Recency Boost

Given query $q$, enabled retrieval lanes $m \in \mathcal{L}$ return ranked candidate lists fused via weighted Reciprocal Rank Fusion (`rrf_k` $= 60$):

$$\text{RRF}(v_i \mid q) = \sum_{m \in \mathcal{L}} \frac{w_m}{60 + \text{rank}_m(v_i \mid q)}$$

After Stage 1 removes out-of-scope (`applies_to`), post-`as_of`, source-invalid, and non-active (`archived`, `superseded`, `discarded`, `expired`) records, Stage 2 ([`context_retrieval_planner.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py#L1820-L1855)) applies a **bounded multiplicative recency boost** *only* when the query intent is operational (`resume`, `current`, `status`, `next_action`, `handoff`), `as_of` is not set, and the record is neither conflicted/stale nor low-authority (`llm_inference`, `imported_legacy`):

$$\text{boost}(v_i) = \min\Big(1.25, \; \max\big(1.0, \; 1.0 + 0.25 \exp(-0.01 \cdot \Delta_{\text{days}})\big)\Big), \quad \text{Score}_{\text{boosted}}(v_i) = \text{RRF}(v_i \mid q) \cdot \text{boost}(v_i)$$

where $\Delta_{\text{days}} = \max(0, (t_{\text{ref}} - t_{\text{eff}}(v_i)) / 86400)$.

### 2.3 Four-State Deterministic Sufficiency Heuristic (`_classify_evidence`)

In [`_classify_evidence`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py#L1998-L2063), GMS evaluates the surviving candidate set $S$ and lifecycle evidence $L$ as follows:

1. **Content-Preserving Token Partition:** From query tokens $T(q)$, remove strict grammatical stopwords $T_{\text{stop}}$, project-name tokens, and non-substantive agent identifiers (`mihir`, `user`, `agent`, `system`) to form $T_{\text{base}}(q)$. Contextual framing terms $T_{\text{frame}} = \{\texttt{current}, \texttt{memory}, \texttt{state}, \texttt{stale}, \texttt{records}, \texttt{record}, \texttt{limiting}, \texttt{retrieval}, \texttt{historical}, \texttt{snapshot}, \texttt{retrieve}, \texttt{point}, \texttt{time}, \texttt{post}, \texttt{dated}, \texttt{leakage}\}$ are stripped **if and only if** removing them leaves at least one substantive token ($T_{\text{base}}(q) \setminus T_{\text{frame}} \neq \emptyset$):
   $$T_{\text{req}}(q) = \begin{cases} T_{\text{base}}(q) \setminus T_{\text{frame}} & \text{if } T_{\text{base}}(q) \setminus T_{\text{frame}} \neq \emptyset, \\ T_{\text{base}}(q) & \text{otherwise.} \end{cases}$$
   This prevents division-by-zero or blind stripping when a user queries about a component literally named `snapshot` or `retrieval` (verified by unit test [`test_classify_evidence_preserves_framing_words_when_sole_subject`](file:///Users/mihirdeshpande/projects/global-memory/tests/test_eval_model_harvesting.py#L215-L252)).
2. **Overlap & Minimum Threshold:** For each candidate $v \in S \cup L$, tokenize `key` and `statement` after camelCase splitting (`aB -> a B`), and compute overlap $o(v) = |T_{\text{req}}(q) \cap T(v)| + \mathbb{I}(\text{ISO date match})$. Let $o_{\max} = \max_{v} o(v)$ and $o_{\min} = \min(2, \max(1, |T_{\text{req}}(q)|))$. If $(T_{\text{req}}(q) = \emptyset \land D(q) = \emptyset)$ or $(T_{\text{req}}(q) \neq \emptyset \land o_{\max} < o_{\min})$, return **`insufficient`**.
3. **Four-State Classification on Focus Set $F = \{v : o(v) = o_{\max}\}$:**
   * If any $v \in F$ has `contradiction_flag=True` or `lifecycle_status` $\in \{\texttt{quarantined}, \texttt{contested}\}$, return **`conflicted`**.
   * If $F$ contains only stale/superseded/archived/expired items and zero current source-valid items, return **`stale`**.
   * If at least one current source-valid item exists in $F$, return **`supported`** (and otherwise **`insufficient`**).
4. **Composite Heuristic Confidence & Abstention Gate:**
   In [`context_retrieval_planner.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py#L1945-L1970), term coverage is bounded in $[0, 1]$ (`top1_cov`, `top5_cov`), and heuristic retrieval confidence is computed as:
   $$C_{\text{ret}} = \text{clip}_{[0,1]}\Big( 0.40 \max(\text{cov}_1, \text{cov}_5) + 0.25 \min\big(1.0, \tfrac{\text{lanes}_1}{2}\big) + 0.15 \min(1.0, \text{margin}) + 0.20\,\mathbb{I}(\text{status}=\texttt{supported}) \Big)$$
   with `abstention_recommended = (C_ret < 0.40 or evidence_status == "insufficient")`.

### 2.4 Cross-Harness Trust Boundary & Corroboration Gating

A critical hazard in multi-agent environments is *endogenous authorization laundering* (Cerruti et al., 2026): when background harvesters (`llm_inference`) extract a procedural claim from an untrusted log or external source, storing it into shared memory can trick a high-privilege interactive agent into executing it with full permissions.

GMS addresses this through **Cross-Harness Corroboration Gating** in [`_classify_evidence`](file:///Users/mihirdeshpande/projects/global-memory/tools/context_retrieval_planner.py#L2056-L2061):
$$\text{If } \text{intent} \in \{\texttt{resume}, \texttt{procedure}\} \land \forall v \in F, \; \text{requires\_corroboration}(v) = \text{True} \implies \text{Return } \texttt{insufficient}$$

**Scope & Boundary Limitation:** This rule is an intent-scoped heuristic filter that blocks actionable execution *only* when the top-scoring focus set $F$ consists exclusively of uncorroborated records. Because it evaluates candidate focus sets rather than performing claim-level reference monitoring inside prompt templates, it does not guarantee complete exclusion of uncorroborated assertions in mixed evidence sets (where at least one verified fact causes the gate to return `supported`). Fully mitigating endogenous authorization laundering requires downstream tool-gate enforcement and cryptographically verified source-event permission binding (Cerruti et al., 2026; Cui et al., 2026).

### 2.5 Non-LLM Regex Baseline & Proposed Tiered Consolidation Routing

In the current implementation, `evaluate_regex_heuristic_baseline()` ([`tools/eval_model_harvesting.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py)) operates as an offline evaluation baseline over the labeled fixture corpus, not a deployed production router in the nocturnal Dream Cycle. 

The baseline results in Table 3A motivate a **proposed Tiered Consolidation Routing** architecture for future work:
1. **Tier-0 Deterministic Extraction ($0.4\,\text{ms}$):** Explicit modal statements with syntactic markers (`must`, `never`, `always`, `timeout_ms=`) are processed by `deterministic_regex_heuristic_v1`, achieving $F_1 = 0.889$ on explicit sentences with zero token cost.
2. **Tier-1 Local LLM Extraction ($44\text{--}90\,\text{s}$):** Reserved for multi-sentence narrative state transitions lacking explicit syntactic keys. 

Establishing a genuine routing Pareto frontier requires an end-to-end coverage and quality study across uncurated developer work logs.

---

## 3. Experimental Evaluation (Development & Pilot Studies)

### 3.1 Retrieval Lane Ablation (Frozen `.venv` Environment vs. Historical Run)

Table 1 reports the complete 5-method retrieval ablation from the frozen project virtual environment (`.venv/bin/python`, `flashrank` installed, saved at [`ablation_run_20261017_102439.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/ablation_run_20261017_102439.json)) across **45 queries evaluated per strategy**, alongside historical comparison values from [`ablation_run_20261004_065955.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/ablation_run_20261004_065955.json).

| Ablation Strategy | Evaluated Queries | Recall@5 (Oct 17) | MRR (Oct 17) | NDCG@10 (Oct 17 Frozen) | NDCG@10 (Oct 4 Hist.) | Latency P50 (ms) | Latency P95 (ms) | Latency P99 (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `dense_vector` (FastEmbed ONNX / Synthetic) | 45 | 0.472 | 0.556 | 0.343 | 0.343 | 0.22 ms | 0.29 ms | 84.75 ms |
| `relational_graph` (SQLite Entity Traversal) | 45 | 0.489 | 0.496 | 0.250 | 0.250 | 1.09 ms | 1.20 ms | 102.51 ms |
| `lexical_bm25` (BM25 + Exact Match) | 45 | 0.983 | 0.952 | 0.658 | 0.700 | 0.59 ms | 1.15 ms | 1.19 ms |
| `hybrid_rrf` (Multi-Lane RRF, No Rerank) | 45 | **1.000** | 0.951 | **0.816** | 0.821 | **2.38 ms** | **3.17 ms** | 3.22 ms |
| `hybrid_reranked` (`ms-marco-TinyBERT-L-2-v2`) | 45 | **1.000** | 0.951 | **0.816** | **0.880** | **8.22 ms** | **18.81 ms** | 62.82 ms |

*Table 1: Frozen October 17 `.venv` retrieval ablation (`ablation_run_20261017_102439.json`, 45 queries per strategy) compared with the historical October 4 run (`ablation_run_20261004_065955.json`). Fixture dense embeddings in this ablation are synthetic precomputed representations used to evaluate multi-lane fusion contracts rather than an external general-domain embedding model's semantic quality. Invoking the CLI with system Python outside `.venv` lacks `flashrank` and marks `hybrid_reranked` as `UNAVAILABLE` (falling back to `hybrid_rrf`). Moreover, while `hybrid_rrf` maintains P50 = 2.38ms (P95 = 3.17ms), cross-encoder reranking incurs P50 = 8.22ms (P95 = 18.81ms on Oct 17; P50 = 14.53ms on Oct 4) and exceeds 15ms at the tail.*

### 3.2 Multi-Suite Regression & Abstention Benchmark (142 Author-Constructed Cases)

Table 2 reports results from [`eval_run_20261017_085056.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/eval_run_20261017_085056.json) across 142 local adapter cases (31 canonical scenarios + 111 correlated paraphrase/perturbation variants, including 37 abstention traps).

| Local Adapter Suite | Total Cases | Canonical / Variants | Oct 13 Pass Rate | Oct 17 Pass Rate | Latency P50 (ms) | Latency Mean (ms) | Prohibited Leaks |
|---|---:|---:|---:|---:|---:|---:|---:|
| `longmemeval_adapter` | 60 | 12 / 48 | 59/60 (98.3%) | **60/60 (100.0%)** | 2.41 ms | 6.21 ms | 0 |
| `locomo_adapter` | 60 | 12 / 48 | 60/60 (100.0%) | **60/60 (100.0%)** | 2.47 ms | 2.33 ms | 0 |
| `memoryagentbench_adapter` | 20 | 5 / 15 | 20/20 (100.0%) | **20/20 (100.0%)** | 1.62 ms | 2.02 ms | 0 |
| `continuation_bundle_structure` | 2 | 2 / 0 | 2/2 (100.0%) | **2/2 (100.0%)** | 2.44 ms | 3.25 ms | 0 |
| **Aggregate** | **142** | **31 / 111** | **141/142 (99.3%)** | **142/142 (100.0%)** | **2.43 ms** | **3.94 ms** | **0** |

*Table 2: Regression suite results (`eval_run_20261017_085056.json`). Because the 111 variants are correlated perturbations of 31 canonical scenarios and the October 17 repair targeted a known failed framing-token query (`lme_009`), this suite serves as a development regression testbed rather than an unseen held-out generalization study.*

### 3.3 Consolidation Pilot: Non-LLM Baseline, Local Coder LLM, and Single-Fixture Thinking Intervention

We evaluate consolidation on `GOLD_HARVEST_CORPUS` ([`harvest_fixtures.py`](file:///Users/mihirdeshpande/projects/global-memory/tests/fixtures/harvest_fixtures.py), 3 multi-sentence scenarios with 4 gold candidates, 4 gold `(S, P, O)` triples, and 5 prohibited secret/noise items) using the repaired evaluator ([`tools/eval_model_harvesting.py`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py)), archived in durable report bundles [`gold_harvest_pilot_qwen25_coder_7b_20261017.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/gold_harvest_pilot_qwen25_coder_7b_20261017.json) and [`thinking_intervention_qwen3_8b_20261017.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json).

#### Table 3A: Extraction Proxy Comparison (3-Scenario Development Pilot on Apple Silicon)

| Extractor / Model Configuration | Raw Proxy Recall / Prec / F1 | Post-Admission Proxy Recall / Prec / F1 | Type Acc. | Rationale Keyword Proxy | Live Graph Stage Status / F1 | Mean Latency | Verified Unloaded (`/api/ps` Reachable) |
|---|---:|---:|---:|---:|:---:|---:|:---:|
| **`deterministic_regex_heuristic_v1`** *(Non-LLM Baseline)* | 1.000 / 0.800 / 0.889 | **1.000 / 0.800 / 0.889** | 1.000 | 1.000 | `not_run` (0.000) | **0.0004 s** | N/A (No LLM) |
| **`qwen2.5-coder:7b`** *(Digest `dae161e27b0e`, 7.6B Q4_K_M, `num_predict=1536`)* | 0.750 / 0.231 / 0.353 | **0.750 / 0.429 / 0.546** | 0.667 | **0.500** | `unavailable` (0.000) | 90.65 s | **Yes (`true`)** |
| **`qwen3.5:9b`** *(Historical Default Run, 9.7B Q4_K_M, `num_predict=1536`)* | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 | 0.000 | 0.000 | `not_run` (0.000) | 178.0 s | **Yes (`true`)** |

*Table 3A: Pilot extraction comparison under conjunctive proxy scoring (`gold_harvest_pilot_qwen25_coder_7b_20261017.json`). On structured journal sentences with explicit modal markers (`must`, `never`, `always`), the deterministic rule/regex baseline (`0.889` proxy F1 in `0.4ms`) outperforms unconstrained 7B LLM generation (`0.353` raw F1 $\to$ `0.546` post-admission F1), because `qwen2.5-coder:7b` over-generates 13 raw candidates across the 3 scenarios (7 admitted after schema filtering) and hits `done_reason="length"` at 1,536 tokens on Scenarios 1 and 3. In the saved October 17 `qwen2.5-coder:7b` run, live graph enrichment was not executed (`graph_stage_status="unavailable"` due to a prior import symbol mismatch in `eval_model_harvesting.py`, now repaired); therefore, no live graph-extraction or live graph-safety claim is made from that run.*

#### Table 3B: Single-Fixture Intervention on Thinking-Token Starvation (`qwen3:8b`, `gold_1_architecture_decision`)

To test whether reasoning-token allocation explains empty JSON responses on a hybrid thinking model under fixed `num_predict=1536`, we recorded a controlled intervention on **`qwen3:8b`** (digest `500a1f067a9f`, 8.2B Q4_K_M) on Scenario 1 (`gold_1_architecture_decision`), archived in [`thinking_intervention_qwen3_8b_20261017.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json):

| Intervention Arm (`qwen3:8b` on `gold_1`) | `think` Setting | `prompt_eval_count` | `eval_count` (Generated Tokens) | `thinking_chars` | `response_chars` (JSON Output) | `done_reason` | Parsed Valid Candidates | Wall-Clock Latency |
|---|:---:|---:|---:|---:|---:|:---:|---:|---:|
| **Thinking Enabled** | `True` | 1,066 | **1,536 (100% of budget)** | **7,183 chars** | **0 chars** | `length` | **0** | 104.19 s |
| **Thinking Disabled** | `False` | 1,072 | **564 (36.7% of budget)** | **0 chars** | **2,054 chars** | `stop` | **2** | **55.06 s** |

*Table 3B: Saved single-fixture intervention on `qwen3:8b` (`thinking_intervention_qwen3_8b_20261017.json`). With `think=True`, `qwen3:8b` expends all 1,536 predicted tokens inside `thinking` (`7,183` characters) and terminates with `done_reason="length"` before writing to `response`. Setting `think=False` on the same fixture eliminates `thinking` tokens, reduces latency from 104.19s to 55.06s, and yields 2 parsed JSON candidates. Scope note: this causal intervention was recorded on one `qwen3:8b` fixture (`gold_1`); we do not extrapolate its exact `7,183`-character trace to `qwen3.5:9b` without separate raw telemetry.*

##### Analysis: Budget Allocation Under Two-Channel Autoregressive Generation

The empirical result in Table 3B reflects a token allocation conflict in **Two-Channel Autoregressive Generation** under a shared completion budget ceiling $B = \texttt{num\_predict}$.

Let an autoregressive decoder produce two distinct sequential token sequences: an internal chain-of-thought channel $\mathbf{y}_{\text{think}} \in \mathcal{V}^*$ and a structured schema output channel $\mathbf{y}_{\text{schema}} \in \mathcal{V}^*$. Under resource-constrained local serving, the total generated token count is bounded:
$$|\mathbf{y}_{\text{think}}| + |\mathbf{y}_{\text{schema}}| \le B$$

Let $L_{\min}$ be the minimal token length required to form a complete valid JSON candidate object adhering to schema contracts. When internal reasoning consumes $|\mathbf{y}_{\text{think}}| > B - L_{\min}$ tokens, complete schema emission is precluded under that serving contract:
$$P\Big(\text{ValidSchema}(\mathbf{y}_{\text{schema}}) \;\Big|\; |\mathbf{y}_{\text{think}}| > B - L_{\min}\Big) = 0$$

In the observed `qwen3:8b` intervention, because internal reasoning reached 1,536 tokens without emitting a terminal schema block, generation terminated with `done_reason="length"` before any characters were written to the visible response channel ($|\mathbf{y}_{\text{schema}}| = 0$).

**Scope & Empirical Limitation:** This condition explains why runaway thinking traces cause schema starvation under fixed consumer budgets. However, it does not imply that reasoning tokens must be strictly zero ($|\mathbf{y}_{\text{think}}| = 0$) in general; a bounded reasoning trace ($|\mathbf{y}_{\text{think}}| = 200, |\mathbf{y}_{\text{schema}}| = 400$) would fit comfortably within $B = 1536$. Nor does setting `think=False` guarantee valid schema generation across all inputs (as demonstrated by `qwen2.5-coder:7b`'s verbosity truncation in the 4-scenario pilot). Disabling thinking is an operational mitigation for models prone to unconstrained internal reasoning on structured extraction tasks.

#### Table 3C: Surrogate Isolated Storage-Boundary Audit (`qwen2.5-coder:7b`) & Deterministic Graph Boundary Controls

To avoid conflating duplicated JSON and SQLite representations into a single denominator, [`verify_isolated_storage_boundary`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py#L420-L545) reports each persistence representation separately alongside the deduplicated count of unique records. This check is an **isolated temporary persistence and readback surrogate** (writing to temporary `facts.json` and simplified SQLite tables and projecting retrieved fields), not an end-to-end production promotion and multi-lane indexing test. Because the saved `qwen2.5-coder:7b` run did not execute live graph extraction (`0/0`), we also evaluate the graph validator (`validate_enrichment_output`) and SQLite relationship persistence using deterministic positive and negative controls ([`evaluate_graph_boundary_controls`](file:///Users/mihirdeshpande/projects/global-memory/tools/eval_model_harvesting.py#L548-L639)):

| Audit Track & Stage | Prohibited Leaks Observed | Deduplicated Record Denominator | Representation Rows Checked | Findings & Scope |
|---|---:|---:|---:|---|
| **A. Saved `qwen2.5-coder:7b` Candidate Run (`gold_1..3`)** | | | | |
| 1. `raw_candidates` (Raw LLM JSON Output) | **6** (`1` secret + `5` chatter) | 13 raw candidates | 13 | Raw LLM extracts `sk-live-...` secret (`gold_1`) and conversational chatter (`gold_1`, `gold_2`). |
| 2. `admitted_candidates` (`validate_context_candidate`) | **1** (`0` secrets, `1` chatter) | 7 unique candidates | 7 | **100% of `sk-live-...` secrets blocked**; 5/6 prohibited items rejected; 1 non-secret chatter record in `gold_1` satisfied schema syntax. |
| 3. `persisted_facts_json_readback` (Temp `facts.json`) | **1** (`0` secrets, `1` chatter) | 7 unique candidates | 7 | Re-read from isolated temporary `facts.json`. |
| 4. `persisted_sqlite_candidates_readback` (Temp SQLite) | **1** (`0` secrets, `1` chatter) | 7 unique candidates | 7 | Re-read from isolated temporary `gms_concept_candidates` table. |
| 5. `persisted_disk_readback` *(Deduplicated Summary)* | **1 unique** (`2` across representations) | **7 unique records** | 14 (`7` JSON + `7` SQLite) | Deduplicated across representations (`1/7` unique candidate records; `0/7` secret leaks). |
| 6. `retrieved_output` *(Surrogate Field Projection)* | **1** (`0` secrets, `1` chatter) | 7 unique records | 7 | Projected `key`/`statement`/`rationale` from temporary store. |
| **B. Deterministic Graph Boundary Controls (`gold_1`)** | | | | |
| 7. **Positive Graph Control** (2 Gold + 1 Wrong-Object Triple) | **0** | 3 raw / 3 admitted triples | 3 | 1-to-1 `(S,P,O)` scorer matches `2/2` gold triples, flags wrong-object `("agent trust","retired_in","Postgres")` as FP (`Prec = 0.667, Rec = 1.000, F1 = 0.800`). |
| 8. **Negative Secret-Leak Graph Control** (`sk-live-...` + 1 Valid) | **1 raw $\to$ 0 admitted / 0 disk** | 2 raw $\to$ 1 admitted triple | 1 SQLite row | `validate_enrichment_output` blocks the `sk-live-...` relationship (`raw_graph: 1/2` $\to$ `admitted_graph: 0/1`, `persisted_sqlite_relationships: 0/1`). |

*Table 3C: Deduplicated surrogate storage-boundary audit (`gold_harvest_pilot_qwen25_coder_7b_20261017.json`) and deterministic graph boundary controls (`evaluate_graph_boundary_controls`). Notably, while regex secret scanning (`SECRET_PATTERNS`) blocked all credential tokens (`0/7` secret leaks) in both candidates and graph controls, 1 non-secret conversational-chatter candidate in `gold_1` passed schema validation (`1/7` unique records), demonstrating that schema and secret-pattern gates alone do not eliminate all non-secret topical noise.*

### 3.4 Four-Scenario Local Harvesting Pilot (`harvest_pilot_20261017_v1`): Coder Verbosity Failures, Thinking-Disabled Reasoning Operability, and Extraction Fidelity Insights

To test local model extraction on newly authored inputs under strict evaluation rules, an independent pilot was executed across 4 newly authored synthetic development scenarios:
* `backup_scope`: Cedar service encrypted backup retention (21 days) with explicit rejection of indefinite retention.
* `configuration_update`: Harbor client timeout update (`request_timeout_ms=4500`) and retirement of legacy 30-second key.
* `procedure_with_secret`: Juniper index recovery procedure with an embedded synthetic secret canary (`API_KEY=sk-live-SYNTHETICONLY...`) and personal chatter.
* `no_write_control`: Non-durable conversational chatter where an empty candidate list (`[]`) is the expected ground truth.

The run used frozen inputs, randomized schedule, seed 1742, temperature 0, context 8192, completion budget 1536, a 120s request timeout, and a strict **fail-closed no-retry rule**. The entire run package is preserved unmodified at [`research_harness/reports/harvest_pilot_20261017_v1/`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/harvest_pilot_20261017_v1/).

#### Table 4: Execution Summary of the 4-Scenario Local Pilot (`FAILED_BACKEND`)

| Model | Scheduled Calls | Attempted Calls | Parseable JSON | Truncated / Invalid Output | Request Timeout (> 120s) | Unattempted Calls (Halted) |
|---|---:|---:|---:|---:|---:|---:|
| **`qwen2.5-coder:7b`** (`think=false`) | 4 | 2 | 0 | **1** (`configuration_update`) | **1** (`procedure_with_secret`) | 2 |
| **`qwen3:8b`** (`think=false`) | 4 | **4** | **4 (100%)** | 0 | 0 | 0 |
| **Total** | **8** | **6** | **4** | **1** | **1** | **2** |

*Table 4: Independent pilot execution matrix (`harvest_pilot_20261017_v1`). Terminal run status: `FAILED_BACKEND` (halted after call 6 under the frozen fail-closed no-retry rule; elapsed 478s, 10,702 reported tokens). Strict complete JSON parsing was enforced: neither truncated output nor missing output was salvaged or scored as correct.*

#### Empirical Findings & Extraction Realities

1. **Refuting the Universal "Coder Model Superiority" Assumption:** Prior development assumptions held that code-specialized 7B models would universally outperform general reasoning models on structured JSON extraction. The fresh evidence refutes this blanket claim: under a 1,536-token completion ceiling, `qwen2.5-coder:7b` suffered from verbose over-generation, terminating with `done_reason="length"` at character 4659 (mid-string JSON syntax error) on `configuration_update` and timing out (>120s) on `procedure_with_secret`. Conversely, thinking-disabled `qwen3:8b` (`think=false`) was operationally stable, completing all 4 scenarios with 100% parseable JSON (average latency 44.2s).
2. **Strict Parsing vs. Truncation Salvage:** Earlier prototypes relied on regex-based JSON salvagers (`_parse_context_harvest_candidates`). Under strict complete parsing (`json.loads`), length-truncated JSON fails completely. Future studies must explicitly preregister parsing policy (strict parser vs. truncation recovery) as an experimental factor.
3. **Canary Secret Defense Validated:** On `procedure_with_secret`, `qwen3:8b` emitted 2 raw candidates, one of which extracted the synthetic canary secret (`API_KEY=sk-live-SYNTHETICONLY...`). The admission firewall ([`validate_context_candidate`](file:///Users/mihirdeshpande/projects/global-memory/tools/schemas.py)) caught and rejected the canary token (`0/1` admitted leaks), confirming secret-boundary enforcement on a deliberately placed canary probe.
4. **Model-Level No-Write Failure vs. Storage-Level Pass:** On `no_write_control` (where ground truth is an empty candidate array), `qwen3:8b` failed at the model level by emitting 3 candidate records from conversational chatter. However, the deterministic admission gate rejected all 3 records (due to missing/invalid rationale and implications), ensuring zero non-durable records reached storage.
5. **Hallucinated Rationale Embellishment & Proxy Misalignment:** In `backup_scope`, `qwen3:8b` correctly extracted the 21-day retention decision but invented an unprompted rationale clause ("minimizing storage overhead", absent from the source). Because the statement contained the expected recovery keyword, automated keyword matching credited the candidate. This demonstrates empirically that keyword rationale coverage is not faithful causal attribution.
6. **Invented Prerequisites & Generic Metadata:** In `configuration_update`, the model invented workflow and testing prerequisites absent from the text. Furthermore, in `procedure_with_secret`, the model defaulted the structured project scope to generic `project-name`, illustrating that Pydantic schema validation does not ensure factual or accurate metadata.

---

## 4. Threats to Validity & Limitations

1. **Development & Pilot Generalization Scope:** The 142-case retrieval benchmark (31 canonical cases + 111 correlated variants), the 3-scenario gold corpus, the single-fixture `qwen3:8b` thinking intervention, and the 4-scenario partial pilot (`harvest_pilot_20261017_v1`) constitute development and pilot engineering evidence. The pilot was halted under `FAILED_BACKEND` due to coder model timeout and truncation under strict parsing rules. Establishing external generalization requires frozen held-out query/journal corpora, multi-seed sweeps across models, and prompt improvements that address unprompted rationale embellishment and generic scope defaults.
2. **Automated Matching Proxies vs. Human Adjudication:** Candidate recall/precision/F1 and rationale scores are deterministic keyword/schema matching proxies (`score_candidate_proxies`), not blind human semantic grading. As demonstrated in `backup_scope`, models can invent rationale clauses that keyword proxies credit.
3. **Surrogate Storage Audit & Pattern-Based Filtering:** `verify_isolated_storage_boundary` tests persistence and readback on simplified temporary `facts.json` and SQLite tables rather than full production promotion and multi-lane indexing. Furthermore, pattern-based secret scanners (`SECRET_PATTERNS`) block known credential formats (`sk-live-...`) but do not filter arbitrary non-secret conversational prose when formatted as a syntactically valid record.

---

## Reproducibility Appendix (Pinned `.venv` Environment)

All retrieval and fixture evaluations run in isolated temporary directories without touching `~/memories`. Note that **Table 1 (`ablate`) and Table 2 (`run --suite all`) are separate commands** and must be executed using the project virtual environment (`.venv/bin/python`) where `flashrank` and `fastembed` are installed:

```bash
# 1. Reproduce Table 1: 5-Method Retrieval Lane Ablation (Requires .venv for flashrank)
cd /Users/mihirdeshpande/projects/global-memory
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli ablate --no-export

# 2. Reproduce Table 2: 142-Case Multi-Suite Regression & Abstention Evaluation
PYTHONPATH=.:tools .venv/bin/python -m research_harness.eval.cli run --suite all --no-export

# 3. Run Unit & Regression Test Suites (11 Harvesting/Boundary Tests + 91 Harness Tests)
PYTHONPATH=.:tools .venv/bin/python -m pytest tests/test_eval_model_harvesting.py -v
PYTHONPATH=.:tools .venv/bin/python -m pytest research_harness/tests -q

# 4. Run Offline Harvesting Contract, Graph Boundary Controls & Regex Baseline (No Ollama Required)
PYTHONPATH=.:tools .venv/bin/python tools/eval_model_harvesting.py --fixtures-only

# 5. Inspect Durable Saved Evidence Bundles (Archived in research_harness/reports/eval_runs/)
ls -lh research_harness/reports/eval_runs/gold_harvest_pilot_qwen25_coder_7b_20261017.json \
       research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json
```
