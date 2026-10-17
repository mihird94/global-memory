# Prior-Art & Claim Boundary: Decision Fidelity in Agent Memory

**Date:** October 17, 2026  
**Document Status:** Exploratory Study Design & Claim Boundary Analysis  
**Location:** `research_harness/decision_fidelity/docs/PRIOR_ART_AND_CLAIM_BOUNDARY.md`

---

## 1. Research Question & Empirical Objective

When an **unchanged, authoritative source** is compressed into memory, does that memory preserve the constraints needed to make correct downstream decisions?

### Core Problem
Autonomous agents increasingly depend on structured memory (key-value records, entity-relationship graphs, or condensed working summaries) to operate across extended horizons within bounded context windows. Existing evaluations often score memory quality by surface text similarity, extraction precision/recall, or conversational question answering. However, in software engineering and systems operations, a memory can be syntactically valid and topically relevant while distorting critical decision-relevant constraints:
- **Scope:** Broadening an internal tool policy to public environments.
- **Exceptions & Negation:** Dropping an explicit exception or inverted conditional.
- **Quantities & Units:** Conflating milliseconds with seconds or MB with GB.
- **Ordering & Error Handling:** Reversing sequential recovery steps or omitting rollbacks.
- **Prerequisites:** Treating an optional diagnostic flag as a mandatory prerequisite.
- **Rationale Attribution:** Fabricating ungrounded reasons or misattributing policy intent.

This study investigates whether binding structured memory fields directly to verifiable source spans improves downstream executable action correctness compared to full-source and extractive baselines, and whether it introduces counter-productive refusals, omissions, or token overhead. A null result—where full source or simple extractive excerpts dominate structured representations—is a valid and informative empirical outcome.

---

## 2. Boundary from CCMP-Bench (Paper 2)

We maintain a strict conceptual and experimental boundary between this study and CCMP-Bench:

| Dimension | Decision Fidelity Study (This Work) | CCMP-Bench (Correction Propagation) |
|---|---|---|
| **Source State** | **Fixed & Authoritative:** The source text $S$ never changes or revokes during the episode. | **Dynamic & Evolving:** An upstream premise transitions from version $V_1$ to $V_2$. |
| **Investigated Phenomenon** | **Compression Distortion:** How initial memory synthesis distorts constraints under fixed source truth. | **Stale Plan Anchoring & Recovery:** How agents recover after an active premise has been revoked. |
| **Core Metric** | Downstream action correctness against the static source contract under 4 representation arms. | Sustained action recovery rate across post-correction opportunities ($H_1, H_2, H_3$). |
| **Corpus & Tasks** | 12 independently authored service families with static minimal pairs. | 8 authored multi-turn recovery episodes across 4 operational families. |

No dynamic source revocations, mid-episode edits, or multi-turn recovery interventions will be introduced into this study. Infrastructure simulators may share technical libraries, but source texts, task definitions, and outcome contracts are strictly independent.

---

## 3. Analysis of Primary Literature

We analyze five primary sources published between November 2025 and October 2026 addressing memory extraction, hallucinations, security boundaries, and revision costs:

### 3.1 HaluMem: Evaluating Hallucinations in Memory Systems (arXiv:2511.03506, Nov 2025)
- **Scope & Method:** HaluMem is an operation-level benchmark evaluating memory hallucinations across three stages: extraction, updating, and question answering. It uses multi-turn dialogue histories (1.5k–2.6k turns) spanning 15k memory points and 3.5k questions.
- **Key Findings:** Memory systems accumulate errors during extraction and updating, which propagate into conversational QA.
- **Boundary & Limitations:** HaluMem evaluates conversational dialogue facts (e.g., user preferences, persona attributes) through text-generation QA scored by LLM judges. It does not evaluate executable action outcomes, simulator state transitions, or specific technical constraints such as unit conversions, ordered execution pipelines, or prerequisite checking.

### 3.2 Memory Provenance Laundering in LLM Agents (arXiv:2607.29167, July 2026)
- **Scope & Method:** Investigates security vulnerabilities where untrusted or adversarial observations are consolidated into agent memory, stripping their low-trust origin and conferring unintended execution authority. Proposes the Provenance-Preserving Memory Firewall (PPMF).
- **Key Findings:** Consolidated memories without provenance tracking allow malicious action triggers to reach up to 1.000 Attack Success Rate (ASR); matching action risk to memory authority eliminates unauthorized high-risk calls.
- **Boundary & Limitations:** PPMF focuses on adversarial prompt injections and security risk tiers (high-risk vs. low-risk tool access). It does not address benign compression errors, syntactic/unit mutations, or execution failures arising from honest LLM summarization of legitimate operational source text.

### 3.3 Endogenous Authorization Laundering (EAL-Bench, arXiv:2609.01836, Sept 2026)
- **Scope & Method:** Cerruti et al. formalize *endogenous authorization laundering*, where an agent's own memory misrepresents evolving permissions, restrictions, or revocations across procurement, cybersecurity, and finance tasks, leading to unauthorized actions without external adversaries.
- **Key Findings:** Memory writers create false authority in up to 50.2% of unauthorized requests; executors act on spurious permissions in 98.6% of trials. Enforcing source-event backing reduces laundering but increases false refusals.
- **Boundary & Limitations:** EAL-Bench focuses specifically on dynamic authorization state and access-control decisions over time. It does not measure non-security operational constraints (e.g., exact parameter units, procedural step ordering, exception routing) under static documentation.

### 3.4 MemTxn: Transaction Boundary for Source-Supported Updates (arXiv:2607.27834, July 2026)
- **Scope & Method:** Cui et al. propose MemTxn, a middleware transaction boundary outside the generation model that validates memory writes using Ordered PatchTest, resolves conflicting versions with a Temporal Resolver, and restores state via snapshot journaling.
- **Key Findings:** Accepts 60 supported memory writes and rejects 179 hard negatives on an item-disjoint audit; restores active state under multi-key faults; improves FactConsolidation F1 on MemoryAgentBench.
- **Boundary & Limitations:** MemTxn evaluates transactional integrity, version consistency, and state recovery over key-value records. It evaluates write-time support rather than reader-side decision fidelity across structured versus extractive representations in executable environments.

### 3.5 When Evidence Changes: Memory Repair vs. Re-reading (arXiv:2610.03902, Oct 2026)
- **Scope & Method:** Chu et al. compare memory repair, memory rebuilding, and full/filtered source re-reading on clinical ICU records when supporting documents are replaced or revoked. They track full-pipeline token costs across an extensive length sweep (up to 20 uses).
- **Key Findings:** For short records, source-filtered re-reading is $3.5\text{--}4.3\times$ cheaper than memory repair; graph repair only amortizes over long static contexts after repeated queries. In replacement experiments, paired confirmatory tests failed to reach statistical significance.
- **Boundary & Limitations:** Focuses on pipeline token costs and evidence revision economics in medical QA. It does not formalize a fine-grained taxonomy of constraint distortions (scope, negation, units, ordering) or evaluate simulated execution outcomes.

---

## 4. Prior-Art Comparison Matrix

| Evaluation Dimension | HaluMem (2025) | Memory Prov. Laundering (2026) | EAL-Bench (2026) | MemTxn (2026) | When Evidence Changes (2026) | Decision Fidelity (This Study) |
|---|---|---|---|---|---|---|
| **Primary Focus** | Dialogue memory hallucination stages | Adversarial memory poisoning & privilege escalation | Endogenous permission drift & unauthorized tool calls | Transactional update integrity & snapshot fault recovery | Token cost of memory repair vs. source re-reading | Semantic constraint preservation during fixed-source compression |
| **Source Grounding** | Text conversation history (1M tokens) | Untrusted web/email observation streams | Incremental permission policy updates | Structured KV claims with source doc pointers | ICU medical admission documents | Immutable technical service documentation with byte spans |
| **Source Dynamics** | Accumulating multi-turn dialogues | Streaming external observations | Evolving permissions & revocations | Multi-key mutations & rollbacks | Document replacement & revocation events | **Strictly Static:** Source truth remains fixed and invariant |
| **Evaluated Endpoint** | Conversational QA (LLM-as-a-judge) | Security tool gate bypass (ASR) | Unauthorized API action rate in procurement/finance | Key-value state restoration & FactConsolidation F1 | Clinical list extraction & full-pipeline token cost | **Deterministic Action-Effect Transitions ($E_0 \to E_1$)** |
| **Constraint Granularity** | General factual entities | Risk level of target API call | Permission grants & scope restrictions | Atomic fact updates | Document-level relevance | **6 Concrete Types:** Scope, Negation, Units, Order, Prereqs, Rationale |
| **Evaluated Memory Arms** | Native agent memory (Mem0, etc.) | Raw memory vs. PPMF middleware | Baseline vs. Event-Sourced vs. Source-Backed | Standard KV vs. MemTxn transaction manager | Re-reading vs. Rebuild vs. Graph Repair | **4 Arms:** Full Source (A), Excerpts (B), Structured (C), Source-Bound (D) |

---

## 5. Precise Distinction of the Proposed Endpoint

Existing literature evaluates memory extraction either via:
1. **Surface String / Token Metrics:** Token F1, ROUGE, or BLEU matching against reference facts.
2. **Conversational Question Answering:** Prompting an LLM judge to determine if an answer aligns with context.
3. **Binary Authorization Gating:** Checking whether a high-privilege tool was executed without permission.

In contrast, our proposed **Executable Decision Endpoint**:
- Evaluates reader agent tool dispatches against a **hermetic domain simulator** that updates an explicit environment state ($E_0 \to E_1$).
- Distinguishes **unsafe over-action** (executing with wrong scope, inverted negation, wrong units, or incorrect sequence) from **costly under-action** (excessive refusals, unneeded confirmation requests, or missing required actions).
- Disentangles **span existence** from **semantic support**: verifying that citing a literal source span does not guarantee that the span logically entails the asserted constraint.
- Evaluates **rationale attribution** strictly when downstream decisions depend on it, avoiding false penalties for benign paraphrases.

---

## 6. Unresolved Novelty Questions & Honest Scope Limitations

1. **Does Structured Memory Provide Any Net Decision Benefit Over Simple Excerpts?**  
   If extractive sentence filtering (Arm B) preserves decision constraints with lower token cost and zero extraction hallucination, structured memory (Arms C and D) may represent unnecessary complexity for static sources.
2. **Is Source-Bound Citation Feasible Locally?**  
   Local consumer models (e.g., 7B–9B parameters) may struggle to produce exact span offsets or valid JSON under strict completion budgets.
3. **Safety-Utility Tradeoff:**  
   As observed by Cerruti et al. (2026), strict source-grounding checks can increase false refusals. The study must measure whether Arm D reduces wrong actions only at the cost of excessive abstention.
4. **Generalization Scope:**  
   The initial 12-family corpus represents a development benchmark, not a blinded held-out evaluation. Results cannot be claimed as general agent capabilities without an independently partitioned test set.
