# GMS & Research Harness — Comprehensive Experiment Log

**Date:** 2026-10-17  
**Repository:** `mihird94/global-memory`  
**Git Branch:** `master`  
**Author / Operators:** Antigravity (Pair Programming with Mihir Deshpande)  
**Status:** All offline scaffolds, audit ledgers, reproduction suites, and test suites passing. Zero unverified claims.

---

## 1. System State & Core Architecture

### Global Memory System (GMS) v2.2.0
The central persistent memory layer across all local agents (Codex, Antigravity, background daemons).
- **Storage & Ingestion:**
  - Fast transactional SQLite trust store (`~/memories/gms_trust.sqlite`) and semantic fact store (`~/memories/semantic/facts.json`).
  - Pre-edit risk guards (`tools/context_retrieval_planner.py`), drift detection, and quarantine staging for ungrounded or contradictory claims.
  - Automatic error learning (`tools/dream_cycle.py`) and nocturnal consolidation.
- **Retrieval Engine:**
  - 10-lane hybrid retrieval fusing BM25 keyword search, semantic dense vector search (in-process FastEmbed ONNX fallback + FAISS), knowledge graph Personalized PageRank, and recency decay.
- **Test Health:**
  - **318 passed, 1 skipped** across the repository test suite (`pytest tests/`).

---

## 2. Research Stream 1: Two-Speed Agent Memory & Frontier Benchmarking (Paper 1)

### Manuscript & Artifacts
- **Manuscript:** [`docs/manuscripts/paper_1_gms_two_speed_memory_manuscript.md`](file:///Users/mihirdeshpande/projects/global-memory/docs/manuscripts/paper_1_gms_two_speed_memory_manuscript.md)
- **Comprehensive Technical Report:** [`docs/manuscripts/GMS_SYSTEM_AND_BENCHMARKS_REPORT_2026.md`](file:///Users/mihirdeshpande/projects/global-memory/docs/manuscripts/GMS_SYSTEM_AND_BENCHMARKS_REPORT_2026.md)
- **Reproduction Runner:** [`docs/manuscripts/reproduce_papers.py`](file:///Users/mihirdeshpande/projects/global-memory/docs/manuscripts/reproduce_papers.py)
- **Verified Offline Outputs:** [`docs/manuscripts/reproduction_results.json`](file:///Users/mihirdeshpande/projects/global-memory/docs/manuscripts/reproduction_results.json)

### Core Contribution & Findings
- Explores the duality of **Fast Working Memory** (low-latency episodic cache, tool receipts, execution continuations) and **Slow Consolidated Memory** (nocturnal dreaming, semantic crystallization, schema-validated facts).
- Integrates lessons across 34 literature baselines (MemGPT/Letta, Mem0, HippoRAG, GraphRAG, Reflexion, CoALA).
- Demonstrates how pre-commit risk guards and decay scheduling eliminate hallucinated overwrites and stale plan anchoring.

---

## 3. Research Stream 2: Continual Correction Memory Propagation (CCMP-Bench / Paper 2)

### Manuscript & Audit Records
- **Manuscript:** [`docs/manuscripts/paper_2_ccmp_correction_propagation_manuscript.md`](file:///Users/mihirdeshpande/projects/global-memory/docs/manuscripts/paper_2_ccmp_correction_propagation_manuscript.md)
- **Audit Ledger:** [`research_harness/docs/MANUSCRIPT_CLAIM_LEDGER_2026_10_17.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/docs/MANUSCRIPT_CLAIM_LEDGER_2026_10_17.md)
- **Reconciliation Audit:** [`research_harness/docs/MANUSCRIPT_RECONCILIATION_CHECK_2026_10_17.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/docs/MANUSCRIPT_RECONCILIATION_CHECK_2026_10_17.md)
- **Independent Review:** [`research_harness/docs/TWO_PAPER_INDEPENDENT_REVIEW_2026_10_17.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/docs/TWO_PAPER_INDEPENDENT_REVIEW_2026_10_17.md)

### Core Contribution & Findings
- Evaluates the **Belief Trapping** phenomenon: when an authoritative source transitions from $V_1 \to V_2$, how reliably do agents propagate corrections across downstream task steps ($H_1, H_2, H_3$)?
- Measures sustained recovery rates across 8 authored operational episodes across 4 families.
- All empirical claims reconciled: historical simulation results, deterministic replay numbers, and theoretical boundaries strictly classified to eliminate overstatement.

---

## 4. Research Stream 3: Local Harvesting & Model Behavioral Pilot (2026-10-17)

### Pilot Reports & Execution Runs
- **Run Directory:** [`research_harness/reports/harvest_pilot_20261017_v1/`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/harvest_pilot_20261017_v1/)
- **Thinking Intervention Evaluation:** [`research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/reports/eval_runs/thinking_intervention_qwen3_8b_20261017.json)
- **Protocol Definition:** [`research_harness/docs/FROZEN_HARVEST_PILOT_2026_10_17.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/docs/FROZEN_HARVEST_PILOT_2026_10_17.md)

### Empirical Findings
1. **Qwen 3 Thinking Intervention:**
   - Under `think=true`, Qwen 3 (8B) exhausted a 1536 token completion cap entirely on 7,183 reasoning characters, producing 0 output response characters before truncation (`done_reason=length`).
   - Under `think=false`, Qwen 3 completed 4 generation calls in 44.2 seconds (11.0s/call) with 100% parseable, valid JSON responses.
2. **Qwen 2.5 Coder Latency & Truncation:**
   - `qwen2.5-coder:7b` experienced excessive latency (>120s timeout on 1 call) and output truncation on procedural extraction. Halted cleanly under the frozen no-retry rule.
3. **Synthetic Secret Canary Rejection:**
   - Evaluated admission gating on synthetic candidate emissions. Candidates reproducing canary patterns were rejected by deterministic post-processing.

---

## 5. Research Stream 4: Decision Fidelity of Agent Memory

### Research Question
> When an unchanged authoritative source is compressed into memory, does that memory preserve the constraints needed to make correct downstream decisions?

### Experimental Design
- **Four Representation Arms:**
  - **Arm A (Full Source):** Uncompressed raw source text (information upper bound, maximum token consumption).
  - **Arm B (Extractive Excerpts):** BM25 sentence-ranked excerpts (lexical baseline).
  - **Arm C (Ordinary Structured Memory):** Standard key-value extraction without span binding.
  - **Arm D (Source-Bound Constraint Memory):** Typed constraint records bound to verified verbatim source span citations.
- **Six Constraint Categories:**
  1. *Applicability Scope:* Resource boundaries and tenant isolation.
  2. *Exceptions & Negation:* Negative guards and protocol downgrade restrictions.
  3. *Quantities & Units:* Exact numeric parameters and measurement unit mappings.
  4. *Ordering & Procedures:* Sequential execution ordering and rollback handlers.
  5. *Required vs. Optional Prerequisites:* Mandatory blocking gates vs. non-blocking telemetry.
  6. *Rationale Attribution:* Statutory compliance justification vs. cost optimization.

### Auditor Remediation & Hardening (October 17, 2026)
Following an independent audit verdict (`OFFLINE_SCAFFOLD_PRESENT — NOT_READY_FOR_MODEL_PILOT`), all six identified vulnerabilities were resolved:

| Probe / Gap | Identified Vulnerability | Architectural Remediation | Offline Test & Metric |
|---|---|---|---|
| **Probe 1: Hidden Annotations** | Arms C & D read hidden `source.constraints` and `support_span_ids`. | Introduced `PublicSourceInput` carrying strictly public text/metadata. Diagnostic oracles isolated in separate classes (`DiagnosticOracleArmC`, `DiagnosticOracleArmD`). | `test_probe_1`: Corrupting hidden annotations leaves public representation payloads 100% identical. |
| **Probe 2: Semantic Validator** | Validator checked only substring presence; missed widened scope and substring numbers (`4` matching `4096`). | Built `validate_record()` with restrictive keyword detection, word-boundary numeric parsing, canonical unit normalization, and monotonic step ordering. Built formal admission gate. | `test_probe_2`: Auditor probe (`"only to Cedar"` asserting `"Every project including Harbor"`) and substring numbers strictly rejected. |
| **Probe 3: Action Matcher Bypass** | Conjunction bug (`!= step and != action`) allowed nested overrides and wrong operations. | Replaced with strict recursive typed matching and 6 hermetic domain state effect simulators ($E_0 \to E_1$). | `test_probe_3`: Nested overrides (`timeout_ms: 999999` vs `50`) and wrong steps (`delete_database` vs `drain_traffic`) evaluate to `WRONG_ACTION`. |
| **Probe 4: Memory-to-Action Fidelity** | Evaluator tested hardcoded actions rather than actions derived by reader agents. | Implemented `ScriptedReaderAgent` and `evaluate_end_to_end()` tracing the complete provenance chain. | `test_probe_4`: Mutated memory alters reader action and triggers simulator rejection; admission rejection causes explicit reader abstention. |
| **Probe 5: Statistical Rigor** | Proposal claimed $p > 0.05$ proved dominance/equivalence. | Preregistered Two One-Sided Tests (TOST) with non-inferiority margin $\delta = 0.05$ and bootstrap CIs; treated $p > 0.05$ as inconclusive. Separated scientific rules from engineering viability heuristics. | Formally codified in [`FROZEN_PILOT_PROPOSAL.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/docs/FROZEN_PILOT_PROPOSAL.md). |
| **Probe 6: Execution Budget & Prior Art** | 72 calls at 11s/call was unrealistic; prior-art citations needed refinement. | Re-budgeted at 18–25s/call (25–36 min allocated window). Generated machine-readable [`frozen_schedule.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/docs/frozen_schedule.json). Refined HaluMem and MemTxn descriptions in [`PRIOR_ART_AND_CLAIM_BOUNDARY.md`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/docs/PRIOR_ART_AND_CLAIM_BOUNDARY.md). | Machine-readable manifest validated for 72 calls across 12 scenarios. |

### Quantitative Offline Verification Results
- **Span Integrity:** 24 source variants across 12 families: 0 slice mismatches (**PASS**).
- **Gold Action Replay:** 12 canonical + 12 minimal pair gold actions: 24/24 correct (**PASS**).
- **Valid Alternatives:** 13 alternative action serializations: 13/13 correct (**PASS**).
- **Counterexample Rejection:** 24 wrong actions + 12 excessive refusals + 13 omissions: 49/49 rejected, 0 false passes (**PASS**).
- **Representation Payloads:** 4 arms across 12 families: 48/48 non-empty public payloads (**PASS**).
- **Offline Decision Fidelity Tests:** **96 / 96 passed in 0.10s** (`test_decision_fidelity_offline.py`).
- **Cryptographic Manifest:** All source texts digests frozen in [`offline_audit_manifest.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/reports/offline_audit_manifest.json).
- **Summary Report:** [`offline_audit_summary.json`](file:///Users/mihirdeshpande/projects/global-memory/research_harness/decision_fidelity/reports/offline_audit_summary.json) (`overall_pass: true`).

---

## 6. Execution Safety & Reproducibility Guarantees

1. **Zero Unverified Claims:** All assertions in manuscripts and reports are verified against runnable test scripts or explicitly marked as development prototypes / hypotheses.
2. **Deterministic Seed & Temperatures:** Local runs use seed 1742 and temperature 0.0.
3. **Private Memory Isolation:** Zero reads or writes to private user memory at `~/memories/`. All evaluation text is synthetic.
4. **Hermetic Test Suite:** All 96 decision fidelity tests run completely offline without model inference or internet access.
